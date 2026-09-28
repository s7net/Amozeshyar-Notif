import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "session.json"
ENV_FILE = BASE_DIR / ".env"

# iGap WebSocket Endpoint
IGAP_WS_URL = os.getenv("IGAP_WS_URL", "wss://secure.igap.net/hybrid/")

# Server public key for secondary encryption (embedded in iGap client protocol)
EMBEDDED_PUBLIC_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAo+inlAfd8Qior8IMKaJ+
BREJcEc9J9RhHgh6g/LvHKsnMaiEbAL70jQBQTLpCRu5Cnpj20+isOi++Wtf/pIP
FdJbD/1H+5jS+ja0RA6unp93DnBuYZ2JjV60vF3Ynj6F4Vr1ts5Xg5dJlEaOcOO2
YzOU97ZGP0ozrXIT5S+Y0BC4M9ieQmlGREzt3UZlTBbyUYPS4mMFh88YcT3QTiTA
k897qlJLxkYxVyAgwAD/0ihmWEkBQe9IxwVT/x5/QbixGSl4Zvd+5d+9sTZcSZQS
iJInT4E6DcmgAVYu5jFMWJDTEuurOQZ1W4nbmGyoY1bZXaFoiMPfzy72VIddkoHg
mwIDAQAB
-----END PUBLIC KEY-----"""

# Common iGap protocol Action IDs
ACTION_ERROR = 0
ACTION_CONNECTION_SECURING = 30001
ACTION_CONNECTION_SYMMETRIC_KEY = 2
ACTION_CONNECTION_SYMMETRIC_KEY_RESPONSE = 30002
ACTION_HEARTBEAT = 3
ACTION_HEARTBEAT_RESPONSE = 30003

ACTION_USER_REGISTER = 100
ACTION_USER_REGISTER_RESPONSE = 30100
ACTION_USER_VERIFY = 101
ACTION_USER_VERIFY_RESPONSE = 30101
ACTION_USER_LOGIN = 102
ACTION_USER_LOGIN_RESPONSE = 30102

ACTION_CHAT_SEND_MESSAGE_RESPONSE = 30201
ACTION_GROUP_SEND_MESSAGE_RESPONSE = 30310
ACTION_CHANNEL_SEND_MESSAGE_RESPONSE = 30410

ACTION_CLIENT_RESOLVE_USERNAME = 606
ACTION_CLIENT_RESOLVE_USERNAME_RESPONSE = 30606

# Telegram Bot configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Target Amoozeshyar bot username in iGap
AMOOZESH_BOT_USERNAME = os.getenv("AMOOZESH_BOT_USERNAME", "amoozeshbot").strip().lstrip("@")


def load_session() -> dict:
    """Load stored session from session.json or environment variable."""
    token = os.getenv("IGAP_TOKEN", "").strip()
    session_data = {}
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception:
            session_data = {}

    if token and not session_data.get("token"):
        session_data["token"] = token

    return session_data


def save_session(data: dict) -> None:
    """Save user session data into session.json."""
    existing = load_session()
    existing.update(data)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=4, ensure_ascii=False)
