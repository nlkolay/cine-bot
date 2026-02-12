import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PHONE = os.environ.get("PHONE", "")
TG_PASSWORD = os.environ.get("TG_PASSWORD", "")
TMDB_API_KEY = os.environ["TMDB_API_KEY"]
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_target = os.environ["TARGET_CHANNEL"]
TARGET_CHANNEL: int | str = int(_target) if _target.lstrip("-").isdigit() else _target
SOURCE_CHANNELS = [ch.strip() for ch in os.environ["SOURCE_CHANNELS"].split(",") if ch.strip()]

RADARR_URL = os.environ.get("RADARR_URL", "")
RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
SONARR_URL = os.environ.get("SONARR_URL", "")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")

_allowed = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {int(uid.strip()) for uid in _allowed.split(",") if uid.strip()}
