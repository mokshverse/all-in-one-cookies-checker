import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MAX_THREADS = int(os.getenv("MAX_THREADS", "30"))
TIMEOUT     = int(os.getenv("TIMEOUT", "18"))
