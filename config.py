"""Signal Scout – configuration."""

import os

# ── App identity ──────────────────────────────────────────────────────────────
APP_VERSION = "0.1.0"
GITHUB_REPO = "psalt21/signal-scout"  # owner/repo for update checks

# ── Topic ────────────────────────────────────────────────────────────────────
TOPIC_NAME = "AI process + productivity systems"
KEYWORDS = [
    "scrum", "team structure", "engineering process", "shipping cadence",
    "planning", "execution", "LLM ops", "dev workflow", "productivity",
    "developer experience", "agile", "kanban", "CI/CD", "devops",
]

# ── RSS Feeds ────────────────────────────────────────────────────────────────
# Each entry: {"name": "<display name>", "url": "<RSS/Atom URL>"}
# Add or remove feeds here. Most blogs expose /feed or /rss – check the site.
FEEDS = [
    {"name": "Hacker News (Popular)",   "url": "https://hnrss.org/newest?points=100"},
    {"name": "Lobsters",                "url": "https://lobste.rs/rss"},
    {"name": "Simon Willison",          "url": "https://simonwillison.net/atom/everything/"},
    {"name": "The New Stack",           "url": "https://thenewstack.io/blog/feed/"},
    {"name": "GitHub Blog",             "url": "https://github.blog/feed/"},
    {"name": "Stack Overflow Blog",     "url": "https://stackoverflow.blog/feed/"},
    {"name": "Changelog",               "url": "https://changelog.com/feed"},
    {"name": "MIT Tech Review",         "url": "https://www.technologyreview.com/feed/"},
]

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_API_KEY = os.environ.get("SIGNAL_SCOUT_LLM_KEY", "")
LLM_API_URL = os.environ.get(
    "SIGNAL_SCOUT_LLM_URL", "https://api.openai.com/v1/chat/completions"
)
LLM_MODEL = os.environ.get("SIGNAL_SCOUT_LLM_MODEL", "gpt-4o-mini")

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.expanduser("~/.signal_scout")
DB_PATH = os.path.join(DATA_DIR, "signal_scout.db")

# ── Server / Scheduling ─────────────────────────────────────────────────────
DIGEST_PORT = 19847
REFRESH_INTERVAL_SECONDS = 60 * 60          # 60 minutes
MAX_NEW_ITEMS_PER_REFRESH = 30
ITEM_MAX_AGE_DAYS = 7
