"""Signal Scout – local HTTP server for the digest view + feedback API."""

import json
import logging
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import TOPIC_NAME, FEEDS, LLM_API_KEY, LLM_MODEL, KEYWORDS

logger = logging.getLogger(__name__)

# Module-level DB reference, set by start_digest_server()
_db = None


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    """Handles GET / (digest page) and POST /api/feedback."""

    def log_message(self, fmt, *args):
        pass  # silence default stderr logging

    def do_GET(self):
        if self.path in ("/", ""):
            self._serve_digest()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/feedback":
            self._handle_feedback()
        else:
            self.send_error(404)

    def _serve_digest(self):
        items = _db.get_digest_items(limit=15)
        stats = {
            "total_items": _db.get_item_count(),
            "feed_count": len(FEEDS),
            "feed_names": [f["name"] for f in FEEDS],
            "has_llm_key": bool(LLM_API_KEY),
            "llm_model": LLM_MODEL,
            "keywords": KEYWORDS,
        }
        html = _build_html(items, stats)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _handle_feedback(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            item_id = int(body["item_id"])
            vote = int(body["vote"])
            if vote not in (1, -1):
                raise ValueError("vote must be 1 or -1")
            _db.record_feedback(item_id, vote)
            from ranking import recalculate_scores
            recalculate_scores(_db)
            self._json_response(200, {"ok": True})
        except Exception as exc:
            self._json_response(400, {"error": str(exc)})

    def _json_response(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())


# ── Server lifecycle ─────────────────────────────────────────────────────────

def start_digest_server(db, port):
    global _db
    _db = db

    def _run():
        try:
            srv = _ReusableHTTPServer(("127.0.0.1", port), _Handler)
            logger.info("Digest server at http://127.0.0.1:%s", port)
            srv.serve_forever()
        except OSError as exc:
            logger.error("Cannot start digest server on port %s: %s", port, exc)

    threading.Thread(target=_run, daemon=True).start()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _relative_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.utcnow() - dt
        if delta.days > 0:
            return f"{delta.days}d ago"
        hrs = delta.seconds // 3600
        if hrs > 0:
            return f"{hrs}h ago"
        mins = delta.seconds // 60
        return f"{mins}m ago" if mins else "just now"
    except Exception:
        return ""


def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── HTML rendering ───────────────────────────────────────────────────────────

def _build_html(items, stats):
    now = datetime.now().strftime("%B %d, %Y at %H:%M")
    total = stats["total_items"]
    feed_count = stats["feed_count"]
    feed_names_js = json.dumps(stats["feed_names"])
    has_key = stats["has_llm_key"]
    llm_model = _esc(stats["llm_model"])
    keywords_js = json.dumps(stats["keywords"])
    mode_label = f"AI-powered ({llm_model})" if has_key else "Keyword matching (no API key)"

    # ── Build cards ──────────────────────────────────────────────────────
    if not items:
        cards = (
            '<div class="empty">'
            "No items yet. Click <strong>Refresh Now</strong> in the menu bar."
            "</div>"
        )
    else:
        parts = []
        for idx, it in enumerate(items):
            tags = json.loads(it.get("tags", "[]"))
            tags_html = "".join(
                f'<span class="tag">{_esc(t)}</span>' for t in tags
            )
            score = it.get("final_score", 0)
            if score >= 70:
                score_color = "#22c55e"
            elif score >= 40:
                score_color = "#eab308"
            else:
                score_color = "#94a3b8"

            uv = it.get("user_vote")
            up_cls = " voted" if uv == 1 else ""
            dn_cls = " voted" if uv == -1 else ""
            source = _esc(it.get("source", ""))
            pub = _relative_time(it.get("published_at", ""))

            # First card gets an id for the tour to target
            extra_cls = ' data-tour="first-card"' if idx == 0 else ""

            parts.append(f"""
            <div class="card" id="card-{it['id']}"{extra_cls}>
              <div class="card-head">
                <a class="title" href="{_esc(it['url'])}" target="_blank">{_esc(it['title'])}</a>
                <span class="score" style="color:{score_color}">{score:.0f}</span>
              </div>
              <div class="meta">{source} &middot; {pub}</div>
              <p class="summary">{_esc(it.get('summary', ''))}</p>
              <p class="why"><strong>Why it matters:</strong> {_esc(it.get('why_it_matters', 'N/A'))}</p>
              <div class="tags">{tags_html}</div>
              <div class="feedback">
                <button class="vote up{up_cls}" onclick="vote({it['id']},1,this)">&#x1F44D;</button>
                <button class="vote down{dn_cls}" onclick="vote({it['id']},-1,this)">&#x1F44E;</button>
              </div>
            </div>""")
        cards = "\n".join(parts)

    # ── Full page ────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal Scout – Digest</title>
<style>
/* ── Base ─────────────────────────────────────────────────── */
:root {{
  --bg: #f5f5f7; --card: #fff; --border: #e5e7eb;
  --text: #1d1d1f; --muted: #6e6e73; --accent: #0071e3;
}}
*{{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg); color:var(--text); line-height:1.5;
  padding:2rem; max-width:720px; margin:0 auto;
}}
header {{ margin-bottom:2rem; text-align:center; }}
header h1 {{ font-size:1.6rem; font-weight:700; margin-bottom:.25rem; }}
header .topic {{ color:var(--muted); font-size:.95rem; }}
header .updated {{ color:var(--muted); font-size:.8rem; margin-top:.25rem; }}
.card {{
  background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:1.25rem; margin-bottom:1rem;
  transition:box-shadow .15s;
}}
.card:hover {{ box-shadow:0 2px 12px rgba(0,0,0,.06); }}
.card.tour-highlight {{
  box-shadow:0 0 0 3px var(--accent), 0 4px 24px rgba(0,113,227,.18);
  position:relative; z-index:1001;
}}
.card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:.75rem; }}
.title {{ font-weight:600; font-size:1rem; color:var(--accent); text-decoration:none; line-height:1.35; }}
.title:hover {{ text-decoration:underline; }}
.score {{
  font-weight:700; font-size:.85rem; flex-shrink:0;
  padding:2px 8px; background:#f0f0f0; border-radius:6px;
}}
.meta {{ font-size:.8rem; color:var(--muted); margin:.35rem 0 .6rem; }}
.summary {{ font-size:.9rem; margin-bottom:.4rem; }}
.why {{ font-size:.85rem; color:#444; margin-bottom:.6rem; }}
.tags {{ display:flex; flex-wrap:wrap; gap:.35rem; margin-bottom:.6rem; }}
.tag {{ font-size:.72rem; background:#eef2ff; color:#4338ca; padding:2px 8px; border-radius:999px; }}
.feedback {{ display:flex; gap:.5rem; }}
.vote {{
  border:1px solid var(--border); background:var(--card); border-radius:8px;
  padding:4px 12px; cursor:pointer; font-size:1.05rem;
  transition:background .15s,transform .1s;
}}
.vote:hover {{ background:#f3f4f6; }}
.vote:active {{ transform:scale(.95); }}
.vote.up.voted {{ background:#dcfce7; border-color:#86efac; }}
.vote.down.voted {{ background:#fee2e2; border-color:#fca5a5; }}
.empty {{ text-align:center; padding:4rem 1rem; color:var(--muted); font-size:1.05rem; }}

/* ── Tour button ──────────────────────────────────────────── */
.tour-launch {{
  display:inline-flex; align-items:center; gap:6px;
  margin-top:.75rem; padding:8px 20px;
  background:var(--accent); color:#fff; border:none; border-radius:999px;
  font-size:.85rem; font-weight:600; cursor:pointer;
  transition:background .15s,transform .1s;
}}
.tour-launch:hover {{ background:#005bb5; }}
.tour-launch:active {{ transform:scale(.97); }}

/* ── Tour overlay ─────────────────────────────────────────── */
.tour-overlay {{
  position:fixed; inset:0; z-index:9999;
  background:rgba(0,0,0,.55); backdrop-filter:blur(4px);
  display:flex; align-items:center; justify-content:center;
  opacity:0; pointer-events:none;
  transition:opacity .25s;
}}
.tour-overlay.active {{ opacity:1; pointer-events:auto; }}
.tour-modal {{
  background:#fff; border-radius:20px; width:600px; max-width:92vw;
  max-height:88vh; overflow-y:auto;
  box-shadow:0 25px 60px rgba(0,0,0,.3);
  animation:tourSlideUp .3s ease;
}}
@keyframes tourSlideUp {{
  from {{ transform:translateY(30px); opacity:0; }}
  to {{ transform:translateY(0); opacity:1; }}
}}
.tour-top {{
  display:flex; justify-content:space-between; align-items:center;
  padding:1.25rem 1.5rem .75rem; border-bottom:1px solid #f0f0f0;
}}
.tour-step-label {{ font-size:.75rem; color:var(--muted); font-weight:600; letter-spacing:.04em; text-transform:uppercase; }}
.tour-close {{
  background:none; border:none; font-size:1.4rem; color:var(--muted);
  cursor:pointer; padding:0 4px; line-height:1;
}}
.tour-close:hover {{ color:var(--text); }}
.tour-content {{ padding:1.5rem; }}
.tour-content h2 {{ font-size:1.3rem; margin-bottom:.75rem; }}
.tour-content h3 {{ font-size:1rem; margin:1rem 0 .5rem; color:#333; }}
.tour-content p {{ font-size:.9rem; color:#444; margin-bottom:.75rem; line-height:1.6; }}
.tour-content .highlight {{ color:var(--accent); font-weight:600; }}
.tour-content .subtle {{ color:var(--muted); font-size:.82rem; }}
.tour-nav {{
  display:flex; justify-content:space-between; align-items:center;
  padding:.75rem 1.5rem 1.25rem; border-top:1px solid #f0f0f0;
}}
.tour-dots {{ display:flex; gap:6px; }}
.tour-dot {{
  width:8px; height:8px; border-radius:50%;
  background:#ddd; transition:background .2s;
}}
.tour-dot.active {{ background:var(--accent); }}
.tour-btn {{
  padding:8px 20px; border-radius:10px; font-size:.85rem; font-weight:600;
  cursor:pointer; transition:all .15s; border:none;
}}
.tour-btn.secondary {{ background:#f0f0f0; color:#333; }}
.tour-btn.secondary:hover {{ background:#e5e5e5; }}
.tour-btn.primary {{ background:var(--accent); color:#fff; }}
.tour-btn.primary:hover {{ background:#005bb5; }}
.tour-btn:disabled {{ opacity:.3; cursor:default; }}

/* ── Pipeline diagram ─────────────────────────────────────── */
.pipeline {{ display:flex; align-items:center; gap:0; margin:1.25rem 0; flex-wrap:wrap; justify-content:center; }}
.pipe-node {{
  display:flex; flex-direction:column; align-items:center; padding:12px 10px;
  background:#f8f9ff; border:1px solid #e0e4f0; border-radius:12px;
  min-width:85px; text-align:center;
  opacity:0; transform:translateY(10px);
  animation:pipeIn .4s ease forwards;
}}
.pipe-node .pipe-icon {{ font-size:1.5rem; margin-bottom:4px; }}
.pipe-node .pipe-label {{ font-size:.7rem; font-weight:600; color:#333; }}
.pipe-node .pipe-detail {{ font-size:.65rem; color:var(--muted); margin-top:2px; }}
.pipe-arrow {{
  font-size:1.1rem; color:var(--accent); margin:0 4px; font-weight:700;
  opacity:0; animation:pipeIn .3s ease forwards;
}}
@keyframes pipeIn {{
  to {{ opacity:1; transform:translateY(0); }}
}}
.pipe-node:nth-child(1){{ animation-delay:.1s }}
.pipe-arrow:nth-child(2){{ animation-delay:.2s }}
.pipe-node:nth-child(3){{ animation-delay:.3s }}
.pipe-arrow:nth-child(4){{ animation-delay:.4s }}
.pipe-node:nth-child(5){{ animation-delay:.5s }}
.pipe-arrow:nth-child(6){{ animation-delay:.6s }}
.pipe-node:nth-child(7){{ animation-delay:.7s }}
.pipe-arrow:nth-child(8){{ animation-delay:.8s }}
.pipe-node:nth-child(9){{ animation-delay:.9s }}
.pipe-arrow:nth-child(10){{ animation-delay:1s }}
.pipe-node:nth-child(11){{ animation-delay:1.1s }}

/* ── Anatomy card ─────────────────────────────────────────── */
.anatomy {{
  background:#fff; border:1px solid var(--border); border-radius:12px;
  padding:1rem; margin:1rem 0; position:relative;
}}
.anatomy .apart {{ position:relative; margin-bottom:.5rem; }}
.anatomy .alabel {{
  display:inline-block; background:var(--accent); color:#fff;
  font-size:.65rem; font-weight:700; padding:1px 8px; border-radius:999px;
  margin-right:6px; vertical-align:middle;
}}
.anatomy .apart.atitle {{ font-weight:600; color:var(--accent); font-size:.95rem; }}
.anatomy .apart.ascore {{
  position:absolute; top:1rem; right:1rem;
  background:#f0f0f0; padding:2px 10px; border-radius:6px;
  font-weight:700; font-size:.85rem; color:#22c55e;
}}
.anatomy .apart.ameta {{ font-size:.78rem; color:var(--muted); }}
.anatomy .apart.asummary {{ font-size:.85rem; }}
.anatomy .apart.awhy {{ font-size:.82rem; color:#444; }}
.anatomy .atags {{ display:flex; gap:4px; flex-wrap:wrap; margin-bottom:.5rem; }}
.anatomy .atag {{ font-size:.68rem; background:#eef2ff; color:#4338ca; padding:1px 8px; border-radius:999px; }}
.anatomy .afeedback {{ display:flex; gap:6px; }}
.anatomy .avote {{
  border:1px solid var(--border); background:#fff; border-radius:8px;
  padding:3px 10px; font-size:.95rem;
}}

/* ── Demo card ────────────────────────────────────────────── */
.demo-card {{
  background:#fff; border:1px solid var(--border); border-radius:12px;
  padding:1.25rem; margin:1rem 0;
}}
.demo-card .demo-title {{ font-weight:600; color:var(--accent); margin-bottom:.25rem; }}
.demo-card .demo-meta {{ font-size:.78rem; color:var(--muted); margin-bottom:.5rem; }}
.demo-card .demo-tags {{ display:flex; gap:4px; flex-wrap:wrap; margin-bottom:.6rem; }}
.demo-card .demo-tag {{ font-size:.68rem; background:#eef2ff; color:#4338ca; padding:2px 8px; border-radius:999px; }}
.demo-score-row {{
  display:flex; align-items:center; gap:12px; margin-bottom:.75rem;
}}
.demo-score-display {{
  font-weight:700; font-size:1.3rem;
  transition:color .3s;
}}
.demo-score-bar {{
  flex:1; height:8px; background:#f0f0f0; border-radius:99px; overflow:hidden;
}}
.demo-score-fill {{
  height:100%; border-radius:99px; transition:width .5s ease, background .5s;
}}
.demo-btns {{ display:flex; gap:.5rem; margin-bottom:.75rem; }}
.demo-vote {{
  border:1px solid var(--border); background:#fff; border-radius:10px;
  padding:6px 18px; cursor:pointer; font-size:1rem;
  transition:all .15s; font-weight:500;
}}
.demo-vote:hover {{ background:#f3f4f6; transform:scale(1.04); }}
.demo-vote.picked {{ transform:scale(1.08); }}
.demo-vote.picked.up {{ background:#dcfce7; border-color:#86efac; }}
.demo-vote.picked.down {{ background:#fee2e2; border-color:#fca5a5; }}
.demo-log {{
  background:#f8f9fa; border-radius:10px; padding:.75rem 1rem;
  font-family:'SF Mono',SFMono-Regular,Menlo,monospace;
  font-size:.75rem; line-height:1.8; color:#555;
  max-height:0; overflow:hidden; transition:max-height .4s ease;
}}
.demo-log.open {{ max-height:300px; }}
.demo-log .log-line {{
  opacity:0; transform:translateX(-8px);
  animation:logIn .3s ease forwards;
}}
@keyframes logIn {{
  to {{ opacity:1; transform:translateX(0); }}
}}
.demo-log .log-ok {{ color:#16a34a; }}
.demo-log .log-calc {{ color:var(--accent); }}

/* ── Feed list ────────────────────────────────────────────── */
.feed-list {{
  display:grid; grid-template-columns:1fr 1fr; gap:6px;
  margin:.75rem 0;
}}
.feed-pill {{
  font-size:.75rem; background:#f0fdf4; color:#166534;
  padding:4px 10px; border-radius:8px; border:1px solid #bbf7d0;
}}
.kw-list {{ display:flex; flex-wrap:wrap; gap:4px; margin:.5rem 0; }}
.kw {{ font-size:.72rem; background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:999px; }}

/* ── Formula ──────────────────────────────────────────────── */
.formula {{
  background:#1d1d1f; color:#e5e5e5; padding:1rem 1.25rem;
  border-radius:12px; font-family:'SF Mono',SFMono-Regular,Menlo,monospace;
  font-size:.82rem; margin:.75rem 0; line-height:1.8;
}}
.formula .fvar {{ color:#7dd3fc; }}
.formula .fop {{ color:#fbbf24; }}
.formula .fcomment {{ color:#6b7280; }}
</style>
</head>
<body>

<header>
  <h1>&#x1F4E1; Signal Scout</h1>
  <p class="topic">{_esc(TOPIC_NAME)}</p>
  <p class="updated">{now} &middot; {len(items)} items shown &middot; {total} in database</p>
  <button class="tour-launch" onclick="startTour()">&#x1F9ED; Take a Tour – See How It Works</button>
</header>

<main id="digest-list">
{cards}
</main>

<!-- ═══════ TOUR OVERLAY ═══════ -->
<div class="tour-overlay" id="tour-overlay">
  <div class="tour-modal">
    <div class="tour-top">
      <span class="tour-step-label" id="tour-step-label">Step 1 of 7</span>
      <button class="tour-close" onclick="closeTour()">&times;</button>
    </div>
    <div class="tour-content" id="tour-content"></div>
    <div class="tour-nav">
      <button class="tour-btn secondary" id="tour-prev" onclick="tourNav(-1)">&larr; Back</button>
      <div class="tour-dots" id="tour-dots"></div>
      <button class="tour-btn primary" id="tour-next" onclick="tourNav(1)">Next &rarr;</button>
    </div>
  </div>
</div>

<script>
/* ── Voting (real) ────────────────────────────────────────── */
async function vote(itemId, v, btn) {{
  try {{
    const res = await fetch('/api/feedback', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{item_id:itemId,vote:v}})
    }});
    if (!res.ok) throw new Error('fail');
    const card = btn.closest('.card');
    card.querySelectorAll('.vote').forEach(b => b.classList.remove('voted'));
    btn.classList.add('voted');
  }} catch(e) {{ console.error('Vote failed',e); }}
}}

/* ── Tour engine ──────────────────────────────────────────── */
const FEEDS = {feed_names_js};
const KEYWORDS = {keywords_js};
const TOTAL = {total};
const FEED_COUNT = {feed_count};
const MODE = "{mode_label}";

let tourStep = 0;
const steps = [
  // 0 – Welcome
  () => `
    <h2>Welcome to Signal Scout</h2>
    <p>Everything you see on this page is <span class="highlight">100% real, live data</span> pulled from the internet just minutes ago.</p>
    <p>Signal Scout is a tiny macOS menu bar app that:</p>
    <ol style="margin:.5rem 0 .75rem 1.25rem;font-size:.9rem;color:#444;line-height:1.8">
      <li>Pulls articles from <strong>${{FEED_COUNT}} RSS feeds</strong> across the web</li>
      <li>Stores them in a <strong>local SQLite database</strong> (currently <strong>${{TOTAL}} items</strong>)</li>
      <li>Scores each item for relevance to your topic</li>
      <li>Shows you this ranked digest — the best stuff on top</li>
      <li>Learns from your <strong>thumbs up / thumbs down</strong> feedback</li>
    </ol>
    <p class="subtle">No cloud. No accounts. Everything stays on your Mac in ~/.signal_scout/</p>
  `,
  // 1 – Data pipeline
  () => `
    <h2>The Data Pipeline</h2>
    <p>Here's what happens every time Signal Scout refreshes (auto every 60 min, or on demand):</p>
    <div class="pipeline">
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F4E1;</span>
        <span class="pipe-label">RSS Feeds</span>
        <span class="pipe-detail">${{FEED_COUNT}} sources</span>
      </div>
      <span class="pipe-arrow">&rarr;</span>
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F50D;</span>
        <span class="pipe-label">Collector</span>
        <span class="pipe-detail">feedparser</span>
      </div>
      <span class="pipe-arrow">&rarr;</span>
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F4BE;</span>
        <span class="pipe-label">Database</span>
        <span class="pipe-detail">${{TOTAL}} items</span>
      </div>
      <span class="pipe-arrow">&rarr;</span>
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F9E0;</span>
        <span class="pipe-label">Summarizer</span>
        <span class="pipe-detail">${{MODE}}</span>
      </div>
      <span class="pipe-arrow">&rarr;</span>
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F3AF;</span>
        <span class="pipe-label">Ranker</span>
        <span class="pipe-detail">score + weights</span>
      </div>
      <span class="pipe-arrow">&rarr;</span>
      <div class="pipe-node">
        <span class="pipe-icon">&#x1F4F0;</span>
        <span class="pipe-label">This Page</span>
        <span class="pipe-detail">top items</span>
      </div>
    </div>
    <h3>Your live feeds</h3>
    <div class="feed-list">
      ${{FEEDS.map(f=>'<span class="feed-pill">'+f+'</span>').join('')}}
    </div>
    <p class="subtle">These are real RSS/Atom feeds. Every item you see was published on the actual web.</p>
  `,
  // 2 – Anatomy of a card
  () => `
    <h2>Anatomy of a Digest Card</h2>
    <p>Each card represents one real article. Here's what each part means:</p>
    <div class="anatomy">
      <span class="apart ascore">
        <span class="alabel">E</span> 72
      </span>
      <div class="apart atitle">
        <span class="alabel">A</span>
        How We Shipped 10x Faster with LLM Ops
      </div>
      <div class="apart ameta">
        <span class="alabel">B</span>
        Hacker News (Popular) &middot; 3h ago
      </div>
      <div class="apart asummary">
        <span class="alabel">C</span>
        A team at Stripe describes how they restructured their engineering process around LLM-assisted workflows, cutting planning overhead by 60%.
      </div>
      <div class="apart awhy">
        <span class="alabel">D</span>
        <strong>Why it matters:</strong> Directly relevant to LLM ops and shipping cadence.
      </div>
      <div class="atags">
        <span class="alabel">F</span>
        <span class="atag">LLM ops</span>
        <span class="atag">shipping cadence</span>
        <span class="atag">dev workflow</span>
      </div>
      <div class="afeedback">
        <span class="alabel">G</span>
        <span class="avote">&#x1F44D;</span>
        <span class="avote">&#x1F44E;</span>
      </div>
    </div>
    <div style="font-size:.82rem;color:#444;line-height:1.9">
      <strong style="color:var(--accent)">A</strong> Title – click to open the real article in a new tab<br>
      <strong style="color:var(--accent)">B</strong> Source feed + time since published<br>
      <strong style="color:var(--accent)">C</strong> AI summary (or snippet in no-key mode)<br>
      <strong style="color:var(--accent)">D</strong> Why this matters for your topic<br>
      <strong style="color:var(--accent)">E</strong> Relevance score (green &ge; 70, yellow &ge; 40, gray &lt; 40)<br>
      <strong style="color:var(--accent)">F</strong> Tags – used for learning your preferences<br>
      <strong style="color:var(--accent)">G</strong> Feedback buttons – this is how the app learns
    </div>
  `,
  // 3 – Scoring formula
  () => `
    <h2>How Scoring Works</h2>
    <p>Every item gets a <strong>relevance score</strong> from the summarizer, then feedback adjusts it:</p>
    <div class="formula">
      <span class="fvar">final_score</span> <span class="fop">=</span> <span class="fvar">relevance_score</span> <span class="fcomment">// 0–100 from LLM or keywords</span><br>
      &nbsp;&nbsp;&nbsp;&nbsp;<span class="fop">+</span> <span class="fvar">sum</span>(tag_weights) <span class="fcomment">// each tag: -10 to +10</span><br>
      &nbsp;&nbsp;&nbsp;&nbsp;<span class="fop">+</span> <span class="fvar">source_weight</span> <span class="fcomment">// per-source: -10 to +10</span>
    </div>
    <p>When you thumbs-up an article:</p>
    <ul style="margin:.4rem 0 .75rem 1.25rem;font-size:.88rem;color:#444;line-height:1.8">
      <li>Each of its <strong>tags</strong> gets <strong>+1</strong> weight</li>
      <li>Its <strong>source feed</strong> gets <strong>+1</strong> weight</li>
      <li>All scores recalculate instantly</li>
    </ul>
    <p>Thumbs-down does the opposite (-1). Weights clamp at &pm;10 so no single preference dominates.</p>
    <p>Over time, articles matching your preferred tags and sources <span class="highlight">automatically rise to the top</span>.</p>
    <h3>Your tracked keywords</h3>
    <div class="kw-list">
      ${{KEYWORDS.map(k=>'<span class="kw">'+k+'</span>').join('')}}
    </div>
  `,
  // 4 – Interactive demo
  () => {{
    return `
    <h2>Try It – Interactive Demo</h2>
    <p>This simulated card shows exactly what happens when you vote. <strong>Click a thumb to see the feedback loop in action:</strong></p>
    <div class="demo-card">
      <div class="demo-title">How We Shipped 10x Faster with LLM Ops</div>
      <div class="demo-meta">Hacker News (Popular) &middot; 3h ago</div>
      <div class="demo-tags">
        <span class="demo-tag">LLM ops</span>
        <span class="demo-tag">shipping cadence</span>
        <span class="demo-tag">dev workflow</span>
      </div>
      <div class="demo-score-row">
        <span>Score:</span>
        <span class="demo-score-display" id="demo-score">70</span>
        <div class="demo-score-bar">
          <div class="demo-score-fill" id="demo-fill" style="width:70%;background:#eab308"></div>
        </div>
      </div>
      <div class="demo-btns">
        <button class="demo-vote up" id="demo-up" onclick="demoVote(1)">&#x1F44D; Thumbs Up</button>
        <button class="demo-vote down" id="demo-down" onclick="demoVote(-1)">&#x1F44E; Thumbs Down</button>
        <button class="demo-vote" onclick="demoReset()" style="font-size:.8rem;color:var(--muted)">Reset</button>
      </div>
      <div class="demo-log" id="demo-log"></div>
    </div>
    <p class="subtle">This is a simulation – your real digest cards below work the same way, but with live data.</p>
    `;
  }},
  // 5 – Menu bar
  () => `
    <h2>The Menu Bar</h2>
    <p>Signal Scout lives in your macOS menu bar as <strong>"SS"</strong>. Click it anytime to see:</p>
    <div style="background:#1d1d1f;border-radius:12px;padding:1rem 1.25rem;margin:.75rem 0;color:#e5e5e5;font-size:.9rem;line-height:2.2">
      <div style="color:#888;font-size:.75rem;margin-bottom:.25rem">&#x25BC; SS menu</div>
      <div>&#x1F7E2; <strong>Updated 17:10 &middot; 113 items</strong> <span style="color:#888">← live status</span></div>
      <div style="border-top:1px solid #333;margin:4px 0"></div>
      <div>&#x1F504; <strong>Refresh Now</strong> <span style="color:#888">← fetch new articles</span></div>
      <div>&#x1F4F0; <strong>Open Digest</strong> <span style="color:#888">← opens this page</span></div>
      <div style="border-top:1px solid #333;margin:4px 0"></div>
      <div>&#x2705; <strong>Auto-refresh (60 min)</strong> <span style="color:#888">← toggle on/off</span></div>
      <div>&#x2699;&#xFE0F; <strong>Settings…</strong> <span style="color:#888">← view current config</span></div>
      <div style="border-top:1px solid #333;margin:4px 0"></div>
      <div>&#x1F6D1; <strong>Quit Signal Scout</strong></div>
    </div>
    <p>Auto-refresh runs every 60 minutes in the background. You can toggle it off if you prefer manual refreshes only.</p>
  `,
  // 6 – Architecture & next steps
  () => `
    <h2>Under the Hood</h2>
    <p>Signal Scout is built with Python and runs entirely on your Mac:</p>
    <div style="font-size:.85rem;line-height:1.9;margin:.75rem 0">
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">app.py</code> &rarr; Menu bar app (rumps/PyObjC)</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">collector.py</code> &rarr; RSS fetcher (feedparser)</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">summarizer.py</code> &rarr; LLM summaries or keyword fallback</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">ranking.py</code> &rarr; Score calculation with feedback weights</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">database.py</code> &rarr; SQLite (~/.signal_scout/)</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">digest_server.py</code> &rarr; This page (localhost:19847)</div>
      <div><code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">config.py</code> &rarr; Feeds, topic, keywords, settings</div>
    </div>
    <h3>Level up</h3>
    <ul style="margin:.4rem 0 .5rem 1.25rem;font-size:.88rem;color:#444;line-height:1.9">
      <li>Set <code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">SIGNAL_SCOUT_LLM_KEY</code> for AI-powered summaries</li>
      <li>Edit <code style="background:#f0f0f0;padding:1px 6px;border-radius:4px">config.py</code> to add your own RSS feeds</li>
      <li>Vote on articles to train the ranker to your taste</li>
    </ul>
    <p style="margin-top:1rem;font-size:1rem"><strong>That's it! Close this tour and start exploring your digest. &#x1F680;</strong></p>
  `,
];

function startTour() {{
  tourStep = 0;
  renderTourStep();
  document.getElementById('tour-overlay').classList.add('active');
  document.querySelectorAll('.card').forEach(c => c.classList.remove('tour-highlight'));
}}
function closeTour() {{
  document.getElementById('tour-overlay').classList.remove('active');
  document.querySelectorAll('.card').forEach(c => c.classList.remove('tour-highlight'));
}}
function tourNav(dir) {{
  tourStep = Math.max(0, Math.min(steps.length - 1, tourStep + dir));
  renderTourStep();
}}
function renderTourStep() {{
  const content = typeof steps[tourStep] === 'function' ? steps[tourStep]() : steps[tourStep];
  document.getElementById('tour-content').innerHTML = content;
  document.getElementById('tour-step-label').textContent = `Step ${{tourStep+1}} of ${{steps.length}}`;
  document.getElementById('tour-prev').disabled = tourStep === 0;
  const nextBtn = document.getElementById('tour-next');
  if (tourStep === steps.length - 1) {{
    nextBtn.textContent = 'Finish';
    nextBtn.onclick = closeTour;
  }} else {{
    nextBtn.textContent = 'Next \\u2192';
    nextBtn.onclick = () => tourNav(1);
  }}
  // Dots
  const dots = document.getElementById('tour-dots');
  dots.innerHTML = steps.map((_,i) =>
    `<div class="tour-dot${{i===tourStep?' active':''}}"></div>`
  ).join('');
  // Highlight first card on card-anatomy step
  document.querySelectorAll('.card').forEach(c => c.classList.remove('tour-highlight'));
}}

/* ── Demo voting simulation ───────────────────────────────── */
let demoScore = 70;
let demoTagWeights = {{ 'LLM ops':0, 'shipping cadence':0, 'dev workflow':0 }};
let demoSourceWeight = 0;

function demoVote(v) {{
  const log = document.getElementById('demo-log');
  const scoreEl = document.getElementById('demo-score');
  const fillEl = document.getElementById('demo-fill');
  const upBtn = document.getElementById('demo-up');
  const downBtn = document.getElementById('demo-down');

  // Reset button states
  upBtn.classList.remove('picked');
  downBtn.classList.remove('picked');
  if (v === 1) upBtn.classList.add('picked');
  else downBtn.classList.add('picked');

  const emoji = v === 1 ? '\\ud83d\\udc4d' : '\\ud83d\\udc4e';
  const lines = [];
  lines.push(`<span class="log-ok">\\u2713 Vote recorded: ${{emoji}}</span>`);

  const tags = Object.keys(demoTagWeights);
  tags.forEach(t => {{
    const old = demoTagWeights[t];
    demoTagWeights[t] = Math.max(-10, Math.min(10, old + v));
    lines.push(`\\u2192 tag "${{t}}": weight ${{old}} \\u2192 ${{demoTagWeights[t]}}`);
  }});

  const oldSrc = demoSourceWeight;
  demoSourceWeight = Math.max(-10, Math.min(10, demoSourceWeight + v));
  lines.push(`\\u2192 source "Hacker News": weight ${{oldSrc}} \\u2192 ${{demoSourceWeight}}`);

  const baseScore = 70;
  const tagSum = Object.values(demoTagWeights).reduce((a,b)=>a+b,0);
  const oldScore = demoScore;
  demoScore = baseScore + tagSum + demoSourceWeight;
  lines.push(`<span class="log-calc">\\u2192 Score recalculated: ${{oldScore}} \\u2192 ${{demoScore}}</span>`);

  // Animate log
  log.innerHTML = lines.map((l,i) =>
    `<div class="log-line" style="animation-delay:${{i*0.15}}s">${{l}}</div>`
  ).join('');
  log.classList.add('open');

  // Animate score
  scoreEl.textContent = demoScore;
  const pct = Math.max(0, Math.min(100, demoScore));
  fillEl.style.width = pct + '%';
  if (demoScore >= 70) {{ fillEl.style.background = '#22c55e'; scoreEl.style.color = '#22c55e'; }}
  else if (demoScore >= 40) {{ fillEl.style.background = '#eab308'; scoreEl.style.color = '#eab308'; }}
  else {{ fillEl.style.background = '#94a3b8'; scoreEl.style.color = '#94a3b8'; }}
}}

function demoReset() {{
  demoScore = 70;
  demoTagWeights = {{ 'LLM ops':0, 'shipping cadence':0, 'dev workflow':0 }};
  demoSourceWeight = 0;
  document.getElementById('demo-score').textContent = '70';
  document.getElementById('demo-score').style.color = '#eab308';
  document.getElementById('demo-fill').style.width = '70%';
  document.getElementById('demo-fill').style.background = '#eab308';
  document.getElementById('demo-log').classList.remove('open');
  document.getElementById('demo-log').innerHTML = '';
  document.getElementById('demo-up').classList.remove('picked');
  document.getElementById('demo-down').classList.remove('picked');
}}
</script>

</body>
</html>"""
