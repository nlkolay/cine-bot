import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
TMDB_API_KEY = os.environ["TMDB_API_KEY"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL"]
SOURCE_CHANNELS = [ch.strip() for ch in os.environ["SOURCE_CHANNELS"].split(",") if ch.strip()]
