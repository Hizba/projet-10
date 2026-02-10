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
    allow_origins=["*"],   # 🔒 Ajuste en prod si besoin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# GOOGLE CLOUD LOGGING (PRODUCTION SAFE)
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

    # ⛔ évite doublons de handlers
    if not any(isinstance(h, type(gcloud_handler)) for h in root_logger.handlers):
        root_logger.addHandler(gcloud_handler)

    logging.info("✅ Google Cloud Logging connected (HTTP Sync mode)")

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
# SESSION STORAGE (IN-MEMORY)
# ============================================================

sessions: Dict[str, FlyMeAgent] = {}

# ============================================================
# MODELS
# ============================================================

class ChatMessage(BaseModel):
    session_id: str
    text: str

# ============================================================
# STARTUP EVENT (EXECUTED ONCE)
# ============================================================

@app.on_event("startup")
async def startup_event():
    print("\n" + "=" * 60)
    print("🚀 FLYME CHATBOT SERVER STARTED (PROD)")
    print(f"📁 BASE_DIR   : {BASE_DIR}")
    print(f"📁 PUBLIC_DIR : {PUBLIC_DIR}")
    print(f"📄 index.html : {(PUBLIC_DIR / 'index.html').exists()}")
    print("=" * 60 + "\n")

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

    logger.info(
        "User message received",
        extra={
            "json_fields": {
                "event_type": "user_message",
                "session_id": msg.session_id,
                "message_length": len(msg.text),
                "message_preview": msg.text[:100]
            }
        }
    )

    try:
        # Create session if needed
        if msg.session_id not in sessions:
            sessions[msg.session_id] = FlyMeAgent()

            logger.info(
                "Session created",
                extra={
                    "json_fields": {
                        "event_type": "session_created",
                        "session_id": msg.session_id,
                        "active_sessions": len(sessions)
                    }
                }
            )

        agent = sessions[msg.session_id]
        response = agent.process_message(msg.text)

        is_fallback = (
            "sorry" in response["text"].lower()
            or "don't understand" in response["text"].lower()
            or not response["complete"]
        )

        logger.info(
            "Bot response generated",
            extra={
                "json_fields": {
                    "event_type": "bot_response",
                    "session_id": msg.session_id,
                    "is_fallback": is_fallback,
                    "is_complete": response["complete"],
                    "missing_info_count": len(response["missing_info"]),
                    "response_length": len(response["text"]),
                    "booking_created": response.get("booking_id") is not None
                }
            }
        )

        if is_fallback:
            logger.warning(
                "Fallback triggered",
                extra={
                    "json_fields": {
                        "event_type": "fallback",
                        "session_id": msg.session_id,
                        "user_input": msg.text[:300],
                        "bot_response": response["text"][:300]
                    }
                }
            )

        return {
            "session_id": msg.session_id,
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
# STATIC FILES (LAST)
# ============================================================

app.mount("/", StaticFiles(directory=str(PUBLIC_DIR)), name="static")
