from .claude import check as check_claude
from .netflix import check as check_netflix
from .spotify import check as check_spotify
from .primevideo import check as check_primevideo
from .chatgpt import check as check_chatgpt

PLATFORMS = {
    "claude":      {"name": "Claude AI",     "fn": check_claude},
    "netflix":     {"name": "Netflix",       "fn": check_netflix},
    "spotify":     {"name": "Spotify",       "fn": check_spotify},
    "primevideo":  {"name": "Prime Video",   "fn": check_primevideo},
    "chatgpt":     {"name": "ChatGPT",       "fn": check_chatgpt},
}
