# agent.py
import json
from typing import Dict
import ollama


class FlyMeAgent:
    def __init__(self):
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
        self.confirmation_attempts = 0

    def _missing_slots(self):
        """Return list of slot keys that are still None"""
        return [k for k, v in self.slots.items() if v is None]


    def _build_prompt(self, user_message: str) -> str:
        """Build the LLM prompt for slot extraction"""
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
    4. Keep already filled slots UNCHANGED (copy them as-is).
    5. Next priority: or_city→dst_city→dep_date→ret_date→budget.

    EXAMPLES (format only):
    Input: "Paris to Djerba" → Extract or_city="Paris", dst_city="Djerba"
    Input: "15th February" → Extract dep_date="2026-02-15"
    Input: "hi" or "ok" → Extract nothing, all null

    OUTPUT STRICT JSON (no other text):
    {{
    "updated_slots": {{
        "or_city": <keep existing or new value or null>,
        "dst_city": <keep existing or new value or null>,
        "dep_date": <keep existing or new value or null>,
        "ret_date": <keep existing or new value or null>,
        "budget": <keep existing or new value or null>
    }},
    "next_missing": "<first missing slot name or 'none'>",
    "next_question": "<natural question for next slot or empty string>"
    }}
    """
        return prompt



    def _call_ollama(self, prompt: str) -> dict:
        """Call Ollama LLM with error handling and JSON repair"""
        try:
            print (prompt)
            response = ollama.Client(host='http://127.0.0.1:11434').chat(
                model="llama3.1",
                messages=[
                    {
                        "role": "system", 
                        "content": "Output ONLY complete valid JSON ending with }}. No text before or after JSON."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                format="json",  # Force JSON mode
                options={
                    "temperature": 0.0,  # Deterministic
                    "num_predict": 500   # Allow complete response
                }
            )
            
            # Extract content correctly
            raw_text = response['message']['content'].strip()
            print("DEBUG Full LLM Response:", raw_text)
            
            # Repair truncated JSON if needed
            if not raw_text.endswith('}'):
                print("⚠️ JSON truncated, repairing...")
                # Count braces to close properly
                open_braces = raw_text.count('{')
                close_braces = raw_text.count('}')
                raw_text += '}' * (open_braces - close_braces)
            
            parsed = json.loads(raw_text)
            
            # Validate required keys exist
            if "updated_slots" not in parsed:
                raise ValueError("Missing 'updated_slots' key")
            if "next_missing" not in parsed:
                parsed["next_missing"] = self._missing_slots()[0] if self._missing_slots() else "none"
            if "next_question" not in parsed:
                parsed["next_question"] = ""
            
            return parsed
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Parse Error: {e}")
            print(f"Raw text: {raw_text[:300]}")
            return self._fallback_response()
        except Exception as e:
            print(f"❌ LLM Call Error: {e}")
            return self._fallback_response()


    def _fallback_response(self) -> dict:
        """Safe fallback if LLM fails"""
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


    def process_message(self, user_message: str) -> Dict:
        print("\n" + "="*50)
        print("--- BEFORE PROCESSING ---")
        print(f"Current Slots: {self.slots}")
        print(f"User Message: {user_message}")
        print(f"Last Question: {self.last_question}")
        print(f"Awaiting Confirmation: {self.awaiting_confirmation}")
        print(f"Confirmation Attempts: {self.confirmation_attempts}")

        # ============================
        # 1️⃣ HANDLE CONFIRMATION STATE
        # ============================
        if self.awaiting_confirmation:
            confirmed = self._llm_detect_confirmation(user_message)

            if confirmed:
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

            # Not confirmed
            self.confirmation_attempts += 1

            if self.confirmation_attempts >= 3:
                self.awaiting_confirmation = False

                return {
                    "text": (
                        "⚠️ We couldn't get your confirmation.\n"
                        "If you want to modify anything, please tell me what to change."
                    ),
                    "slots": self.slots,
                    "booking_context": self.slots,
                    "missing_info": [],
                    "complete": False,
                    "confirmation_failed": True
                }

            # Ask again
            return {
                "text": self._confirmation_message(),
                "slots": self.slots,
                "booking_context": self.slots,
                "missing_info": [],
                "complete": False
            }

        # ============================
        # 2️⃣ NORMAL SLOT COLLECTION
        # ============================
        prompt = self._build_prompt(user_message)
        llm_result = self._call_ollama(prompt)

        # Update slots safely
        for k, v in llm_result["updated_slots"].items():
            if v is not None:
                self.slots[k] = v

        missing = self._missing_slots()
        complete = len(missing) == 0

        # ============================
        # 3️⃣ ALL SLOTS FILLED → ASK CONFIRMATION
        # ============================
        if complete:
            self.awaiting_confirmation = True
            self.confirmation_attempts = 1
            self.status = "WAITING_CONFIRMATION"

            confirmation_text = self._confirmation_message()
            self.last_question = confirmation_text

            return {
                "text": confirmation_text,
                "slots": self.slots,
                "booking_context": self.slots,
                "missing_info": [],
                "complete": False
            }

        # ============================
        # 4️⃣ ASK NEXT SLOT
        # ============================
        next_slot = missing[0]
        questions = {
            "or_city": "What is your departure city?",
            "dst_city": "What is your destination city?",
            "dep_date": "When do you want to depart? (e.g., 2026-07-10)",
            "ret_date": "When do you want to return? (e.g., 2026-07-15)",
            "budget": "What is your maximum budget? (e.g., 500 EUR)"
        }

        next_question = questions[next_slot]
        self.last_question = next_question

        return {
            "text": next_question,
            "slots": self.slots,
            "booking_context": self.slots,
            "missing_info": missing,
            "complete": False
        }


    def _confirmation_message(self) -> str:
        """Generate final confirmation message when all slots filled"""
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
        """
        Use LLM to detect if user is confirming booking details
        """
        prompt = f"""
    You are a confirmation intent classifier.

    User message:
    "{user_message}"

    Question previously asked:
    "{self.last_question}"

    TASK:
    Decide if the user CONFIRMS the booking details.

    Rules:
    - Confirmation can be explicit or implicit
    - Accept natural language confirmations
    - Accept short answers
    - Reject questions, modifications, hesitation, or silence

    OUTPUT STRICT JSON ONLY:
    {{
    "confirmed": true | false
    }}
    """

        try:
            response = ollama.Client(host="http://127.0.0.1:11434").chat(
                model="llama3.1",
                messages=[
                    {"role": "system", "content": "Output ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                format="json",
                options={
                    "temperature": 0.0,
                    "num_predict": 50
                }
            )

            raw = response["message"]["content"].strip()
            parsed = json.loads(raw)
            return bool(parsed.get("confirmed", False))

        except Exception as e:
            print(f"⚠️ Confirmation LLM error: {e}")
            return False

