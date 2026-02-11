import json
import logging
from typing import Dict
import ollama

logger = logging.getLogger("flyme-chatbot-server")


class FlyMeAgent:
    def __init__(self, session_id: str = "unknown"):
        self.session_id = session_id
        self.slots = {
            "or_city": None,
            "dst_city": None,
            "dep_date": None,
            "ret_date": None,
            "budget": None
        }
        self.status = "COLLECTING"
        self.last_question = "Hi! I'm the Fly Me assistant. Tell me your departure city, destination, dates, and max budget."
        self.awaiting_confirmation = False

    # --------------------------
    # Slot Helpers
    # --------------------------
    def _missing_slots(self):
        return [k for k, v in self.slots.items() if v is None]

    def _build_prompt(self, user_message: str) -> str:
        prompt = f"""
You are a Fly Me slot extractor. Year is 2026. Current date: January 27, 2026.

SLOTS DEFINITION:
- "or_city" = origin/departure city
- "dst_city" = destination city  
- "dep_date" = departure date (YYYY-MM-DD)
- "ret_date" = return date (YYYY-MM-DD)
- "budget" = max budget with currency

CURRENT STATE:
Already filled: {json.dumps(self.slots, indent=2)}
Question asked: "{self.last_question}"
User just said: "{user_message}"

INSTRUCTIONS:
1. Extract ONLY from user's message what answers the missing slots.
2. NO guesses, NO defaults - only explicit values from user.
3. Parse dates to YYYY-MM-DD (e.g., "15 Feb" → "2026-02-15").
4. Keep already filled slots UNCHANGED.
5. Next priority: or_city→dst_city→dep_date→ret_date→budget.

OUTPUT STRICT JSON:
{{
"updated_slots": {{"or_city": <value or null>, "dst_city": <value or null>, "dep_date": <value or null>, "ret_date": <value or null>, "budget": <value or null>}},
"next_missing": "<first missing slot or 'none'>",
"next_question": "<natural question for next slot or empty string>"
}}
"""
        return prompt

    def _call_ollama(self, prompt: str) -> dict:
        """Call Ollama LLM safely"""
        try:
            response = ollama.Client(host="http://127.0.0.1:11434").chat(
                model="llama3.1",
                messages=[
                    {"role": "system", "content": "Output ONLY complete valid JSON ending with }}."},
                    {"role": "user", "content": prompt}
                ],
                format="json",
                options={"temperature": 0.0, "num_predict": 500}
            )
            raw_text = response["message"]["content"].strip()
            # Repair truncated JSON
            if not raw_text.endswith('}'):
                raw_text += '}' * (raw_text.count('{') - raw_text.count('}'))
            parsed = json.loads(raw_text)
            if "updated_slots" not in parsed:
                raise ValueError("Missing 'updated_slots' key")
            if "next_missing" not in parsed:
                parsed["next_missing"] = self._missing_slots()[0] if self._missing_slots() else "none"
            if "next_question" not in parsed:
                parsed["next_question"] = ""
            return parsed
        except Exception as e:
            print(f"❌ LLM Call Error: {e}")
            return self._fallback_response()

    def _fallback_response(self) -> dict:
        missing = self._missing_slots()
        next_slot = missing[0] if missing else "none"
        questions = {
            "or_city": "What is your departure city?",
            "dst_city": "What is your destination city?",
            "dep_date": "When do you want to depart? (YYYY-MM-DD format)",
            "ret_date": "When do you want to return? (YYYY-MM-DD format)",
            "budget": "What is your maximum budget?"
        }
        return {
            "updated_slots": self.slots.copy(),
            "next_missing": next_slot,
            "next_question": questions.get(next_slot, "")
        }

    # --------------------------
    # 1️⃣ Collect Booking Details
    # --------------------------
    def collect_booking_details(self, user_message: str) -> dict:
        llm_result = self._call_ollama(self._build_prompt(user_message))
        for k, v in llm_result["updated_slots"].items():
            if v is not None:
                self.slots[k] = v

        missing = self._missing_slots()
        complete = len(missing) == 0

        if complete:
            self.status = "WAITING_CONFIRMATION"
            self.awaiting_confirmation = True
            return self.booking_confirmation()
        else:
            next_slot = missing[0]
            questions = {
                "or_city": "What is your departure city?",
                "dst_city": "What is your destination city?",
                "dep_date": "When do you want to depart? (e.g., 2026-07-10)",
                "ret_date": "When do you want to return? (e.g., 2026-07-15)",
                "budget": "What is your maximum budget? (e.g., 500 EUR)"
            }
            self.last_question = questions[next_slot]
            return {
                "text": self.last_question,
                "slots": self.slots,
                "missing_info": missing,
                "complete": False
            }

    # --------------------------
    # 2️⃣ Booking Confirmation
    # --------------------------
    def booking_confirmation(self) -> dict:
        """Ask user to confirm booking details"""
        self.last_question = self._confirmation_message()
        return {
            "text": self.last_question,
            "slots": self.slots,
            "booking_context": self.slots,
            "missing_info": [],
            "complete": False
        }

    # --------------------------
    # 3️⃣ Booking Confirmed
    # --------------------------
    def booking_confirmed(self) -> dict:
        """Booking confirmed by user"""
        self.awaiting_confirmation = False
        self.status = "CONFIRMED"
        return {
            "text": "✅ Booking details confirmed. Your request is being processed.",
            "slots": self.slots,
            "booking_context": self.slots,
            "missing_info": [],
            "complete": True,
            "confirmed": True
        }

    # --------------------------
    # Main entry
    # --------------------------
    def process_message(self, user_message: str) -> dict:
        if self.awaiting_confirmation:
            if self._llm_detect_confirmation(user_message):
                return self.booking_confirmed()
            else:
                # Log refusal
                logger.warning(
                    "Booking confirmation refused",
                    extra={
                        "json_fields": {
                            "event_type": "confirmation_refused",
                            "session_id": self.session_id
                        }
                    }
                )
                # Repose les détails
                return self.booking_confirmation()
        else:
            return self.collect_booking_details(user_message)

    # --------------------------
    # Confirmation & Helpers
    # --------------------------
    def _confirmation_message(self) -> str:
        return (
            f"Thank you! Here are your flight details:\n\n"
            f"✈️ From: {self.slots['or_city']}\n"
            f"✈️ To: {self.slots['dst_city']}\n"
            f"📅 Departure: {self.slots['dep_date']}\n"
            f"📅 Return: {self.slots['ret_date']}\n"
            f"💰 Budget: {self.slots['budget']}\n\n"
            f"Please confirm if everything is correct by replying 'yes' or 'confirm'."
        )

    def _llm_detect_confirmation(self, user_message: str) -> bool:
        prompt = f"""
You are a confirmation intent classifier.

User message:
"{user_message}"

Question previously asked:
"{self.last_question}"

TASK:
Decide if the user CONFIRMS the booking details.

Rules:
- Accept natural language confirmations
- Reject questions, modifications, hesitation, or silence

OUTPUT STRICT JSON ONLY:
{{"confirmed": true | false}}
"""
        try:
            response = ollama.Client(host="http://127.0.0.1:11434").chat(
                model="llama3.1",
                messages=[
                    {"role": "system", "content": "Output ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                format="json",
                options={"temperature": 0.0, "num_predict": 50}
            )
            parsed = json.loads(response["message"]["content"].strip())
            return bool(parsed.get("confirmed", False))
        except Exception as e:
            print(f"⚠️ Confirmation LLM error: {e}")
            return False
