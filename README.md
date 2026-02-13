# 📡 Signal Scout

A tiny macOS menu bar app that tracks **one topic** ("AI engineering processes + productivity systems"), collects fresh links from RSS feeds, summarizes them with an LLM, and shows a rolling daily digest with thumbs-up/thumbs-down feedback.

---

## Install (macOS app – recommended)

1. Download **Signal Scout.app.zip** from the [latest GitHub release](https://github.com/psalt21/signal-scout/releases/latest).
2. Unzip it. You'll see `Signal Scout.app`.
3. Drag it to your **Applications** folder (or just double-click from Downloads).
4. **First launch:** Right-click the app → **Open** (macOS Gatekeeper will ask you to confirm once since the app isn't notarized).
5. **"SS"** appears in your menu bar. Click it to refresh feeds, open the digest, or set your API key.

> **No API key?** The app works out of the box in keyword-only mode. To enable AI summaries, click **SS → Set API Key…** and paste an OpenAI key.

---

## Install (from source – for developers)

```bash
# 1. Create & activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Set your OpenAI-compatible API key for AI summaries
export SIGNAL_SCOUT_LLM_KEY="sk-..."

# 4. Launch
python app.py
```

The **SS** icon will appear in your menu bar. Click it to refresh, open the digest, or adjust settings.

### Build the .app yourself

```bash
pip install py2app
python setup.py py2app
# Output: dist/Signal Scout.app
```

---

## Architecture

```
signal-scout/
├── app.py              # Menu bar app (rumps). Entry point.
├── config.py           # Topic, feeds, LLM settings, paths.
├── database.py         # Thread-safe SQLite wrapper.
├── collector.py        # RSS/Atom feed fetcher (feedparser).
├── summarizer.py       # LLM summarization + no-key fallback.
├── ranking.py          # Score recalculation from feedback weights.
├── digest_server.py    # Local HTTP server for the digest HTML + feedback API.
├── requirements.txt
├── LICENSE
└── README.md
```

### Data flow

1. **Collect** – `collector.py` pulls items from RSS feeds listed in `config.py`.
2. **Store** – New items are inserted into a local SQLite database (`~/.signal_scout/signal_scout.db`).
3. **Summarize** – `summarizer.py` sends each new item to an LLM (or uses keyword fallback) to get a summary, relevance score, and tags.
4. **Rank** – `ranking.py` computes `final_score = relevance_score + Σ(tag_weights) + source_weight`.
5. **Display** – `digest_server.py` serves an HTML digest page at `http://127.0.0.1:19847`.
6. **Feedback** – Thumbs-up/down buttons adjust `tag_weights` and `source_weights` (clamped to ±10) so future rankings reflect your preferences.

---

## How Sources Are Defined

Edit the `FEEDS` list in `config.py`:

```python
FEEDS = [
    {"name": "Hacker News (Popular)", "url": "https://hnrss.org/newest?points=100"},
    {"name": "Simon Willison",        "url": "https://simonwillison.net/atom/everything/"},
    # Add more feeds here ...
]
```

Any standard RSS or Atom feed URL works.

---

## How Ranking Works

| Component | Source | Range |
|-----------|--------|-------|
| `relevance_score` | LLM (or keyword heuristic) | 0–100 |
| `tag_weights` | Updated by 👍/👎 per tag | −10 to +10 each |
| `source_weight` | Updated by 👍/👎 per source | −10 to +10 |

**Formula:** `final_score = relevance_score + sum(tag_weights for item's tags) + source_weight`

- **👍** → +1 to each of the item's tag weights, +1 to source weight
- **👎** → −1 to each of the item's tag weights, −1 to source weight
- Weights are clamped to [−10, +10]

---

## Configuration

| Env Variable | Default | Purpose |
|---|---|---|
| `SIGNAL_SCOUT_LLM_KEY` | *(empty – no-key mode)* | OpenAI-compatible API key |
| `SIGNAL_SCOUT_LLM_URL` | `https://api.openai.com/v1/chat/completions` | LLM endpoint |
| `SIGNAL_SCOUT_LLM_MODEL` | `gpt-4o-mini` | Model name |

All other settings (topic, keywords, feeds, refresh interval) live in `config.py`.

---

## License

MIT
