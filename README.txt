╔══════════════════════════════════════════════════════════╗
║      Multi-Platform Cookie Checker — Telegram Bot        ║
║   Claude AI | Netflix | Spotify | Prime Video | ChatGPT  ║
╚══════════════════════════════════════════════════════════╝

SETUP:
──────
1. Python 3.10+ → https://python.org/downloads

2. pip install -r requirements.txt

3. .env banao (.env.example copy karke):
   BOT_TOKEN=apna_token_yahan

4. Bot token: Telegram → @BotFather → /newbot

5. python bot.py


USE KARNA:
──────────
1. /start bhejo
2. Cookie .zip file bhejo
3. Bot puchega: konsa platform?
   → Button click karo (Claude/Netflix/Spotify/Prime/ChatGPT)
4. Bot check karta hai (20 threads parallel)
5. Result + working_<platform>_cookies.zip milega


COOKIE FILE FORMAT (Netscape tab-separated):
─────────────────────────────────────────────
Har .txt file = ek account ki cookies.

.netflix.com  TRUE  /  TRUE  1800000000  NetflixId   abc123...
.netflix.com  TRUE  /  TRUE  1800000000  SecureNetflixId  xyz...

EditThisCookie (Chrome extension) se export karo aise hi.


REQUIRED COOKIES PER PLATFORM:
────────────────────────────────
Claude AI    → sessionKey (sk-ant-sid02-...)
Netflix      → NetflixId + SecureNetflixId
Spotify      → sp_dc
Prime Video  → at-main + sess-at-main
ChatGPT      → __Secure-next-auth.session-token


SPEED SETTINGS (config.py / .env):
────────────────────────────────────
MAX_THREADS=20   (default, safe)
MAX_THREADS=30   (faster, may get rate limited)
