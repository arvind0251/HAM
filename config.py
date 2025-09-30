import os

API_ID = int(os.getenv("API_ID", "12345"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

COOKIES_PATH = os.getenv("COOKIES_PATH", "cookies.txt")
DOWNLOADS_DIR = "downloads"

# Optional YouTube API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", None)

# Logging group ka ID (yaha apna group ka -100 se start hone wala ID daalna)
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "-1001234567890"))
