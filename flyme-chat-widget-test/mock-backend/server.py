from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from typing import Dict
import uuid
import logging

from agent import FlyMeAgent

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Fly Me Flight Booking API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# GOOGLE CLOUD LOGGING
# ============================================================

try:
    import google.cloud.logging
    from google.cloud.logging_v2.handlers.transports import SyncTransport

    log_client = google.cloud.logging.Client()
    gcloud_handler = log_client.get_default_handler()
    gcloud_handler.transport = SyncTransport(
        log_client,
        name="flyme-chatbot-server"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(isinstance(h, type(gcloud_handler)) for h in root_logger.handlers):
        root_logger.addHandler(gcloud_handler)

    logging.info("✅ Google Cloud Logging connected")

except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logging.warning(f"⚠️ Google Cloud Logging disabled: {e}")

logger = logging.getLogger("flyme-chatbot-server")

# ============================================================
# PATH CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = (BASE_DIR.parent / "public").resolve()

# ============================================================
# SESSION STORAGE (IN MEMORY)
# ============================================================

sessions: Dict[str, FlyMeAgent] = {}

# ============================================================
# MODELS
# ============================================================

class ChatMessage(BaseModel):
    session_id: str | None = None
    text: str

# ============================================================
# STARTUP EVENT
# ============================================================

@app.on_event("startup")
async def startup_event():

    logger.info(
        "Server startup",
        extra={
            "json_fields": {
                "event_type": "server_startup",
                "base_dir": str(BASE_DIR),
                "public_dir": str(PUBLIC_DIR)
            }
        }
    )

# ============================================================
# ROUTES
# ============================================================

@app.get("/")
async def serve_index():
    return FileResponse(PUBLIC_DIR / "index.html")

@app.get("/index.html")
async def serve_index_file():
    return FileResponse(PUBLIC_DIR / "index.html")


@app.post("/v1/chat/message")
async def chat_message(msg: ChatMessage):

    try:
        # ===================================================
        # SESSION ID SAFETY
        # ===================================================
        session_id = msg.session_id

        if not session_id or session_id == "unknown":
            session_id = str(uuid.uuid4())

            logger.info(
                "Session auto-generated",
                extra={
                    "json_fields": {
                        "event_type": "session_auto_created",
                        "session_id": session_id
                    }
                }
            )

        # ===================================================
        # USER MESSAGE LOG
        # ===================================================
        logger.info(
            "User message received",
            extra={
                "json_fields": {
                    "event_type": "user_message",
                    "session_id": session_id,
                    "message_length": len(msg.text),
                    "message_preview": msg.text[:100]
                }
            }
        )

        # ===================================================
        # SESSION CREATION
        # ===================================================
        if session_id not in sessions:
            sessions[session_id] = FlyMeAgent()

            logger.info(
                "Session created",
                extra={
                    "json_fields": {
                        "event_type": "session_created",
                        "session_id": session_id,
                        "active_sessions": len(sessions)
                    }
                }
            )

        agent = sessions[session_id]

        # ===================================================
        # PROCESS MESSAGE
        # ===================================================
        response = agent.process_message(msg.text)

        # ===================================================
        # BUSINESS EVENTS
        # ===================================================
        if response.get("confirmation_refused"):
            logger.warning(
                "Booking confirmation refused",
                extra={
                    "json_fields": {
                        "event_type": "confirmation_refused",
                        "session_id": session_id
                    }
                }
            )

        # ===================================================
        # FALLBACK DETECTION
        # ===================================================
        is_fallback = (
            "sorry" in response["text"].lower()
            or "don't understand" in response["text"].lower()
        )

        if is_fallback:
            logger.warning(
                "Fallback triggered",
                extra={
                    "json_fields": {
                        "event_type": "fallback",
                        "session_id": session_id,
                        "user_input": msg.text[:300],
                        "bot_response": response["text"][:300]
                    }
                }
            )

        # ===================================================
        # BOT RESPONSE LOG
        # ===================================================
        logger.info(
            "Bot response generated",
            extra={
                "json_fields": {
                    "event_type": "bot_response",
                    "session_id": session_id,
                    "is_fallback": is_fallback,
                    "is_complete": response["complete"],
                    "missing_info_count": len(response["missing_info"]),
                    "response_length": len(response["text"]),
                }
            }
        )

        # ===================================================
        # RETURN API RESPONSE
        # ===================================================
        return {
            "session_id": session_id,
            "reply_id": str(uuid.uuid4()),
            "text": response["text"],
            "slots": response["slots"],
            "missing_info": response["missing_info"],
            "complete": response["complete"],
            "booking_id": response.get("booking_id")
        }

    except Exception as e:
        logger.error(
            "Chat processing error",
            exc_info=True,
            extra={
                "json_fields": {
                    "event_type": "processing_error",
                    "session_id": msg.session_id,
                    "error": str(e)
                }
            }
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/v1/health")
async def health():
    return {
        "status": "healthy",
        "active_sessions": len(sessions)
    }

# ============================================================
# STATIC FILES
# ============================================================

app.mount("/", StaticFiles(directory=str(PUBLIC_DIR)), name="static")
