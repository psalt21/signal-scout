"""Signal Scout – macOS menu bar application.

Launch:
    python app.py
"""

import logging
import threading
import webbrowser
from datetime import datetime

import rumps

from collector import fetch_feeds
from config import (
    DB_PATH,
    DIGEST_PORT,
    FEEDS,
    ITEM_MAX_AGE_DAYS,
    KEYWORDS,
    LLM_API_KEY,
    LLM_API_URL,
    LLM_MODEL,
    MAX_NEW_ITEMS_PER_REFRESH,
    REFRESH_INTERVAL_SECONDS,
    TOPIC_NAME,
)
from database import Database
from digest_server import start_digest_server
from ranking import recalculate_scores
from summarizer import summarize_items

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("signal_scout")


class SignalScoutApp(rumps.App):
    def __init__(self):
        super().__init__("Signal Scout", quit_button=None)
        self.title = "SS"  # short text shown in the menu bar

        self.db = Database(DB_PATH)
        self.last_refresh = None
        self.auto_refresh_on = True
        self._refreshing = False  # guard against overlapping refreshes

        # Thread-safe status: background threads write here,
        # a main-thread timer reads it and updates the menu item.
        self._pending_status = None
        self._status_lock = threading.Lock()

        # Menu items
        self.status_item = rumps.MenuItem("Not yet refreshed")
        self.auto_toggle = rumps.MenuItem("Auto-refresh (60 min)")
        self.auto_toggle.state = True

        self.menu = [
            self.status_item,
            None,
            "Refresh Now",
            "Open Digest",
            None,
            self.auto_toggle,
            "Set API Key…",
            "Settings…",
            None,
            "Quit Signal Scout",
        ]

        # Start local digest server
        start_digest_server(self.db, DIGEST_PORT)

        # Fast timer that syncs status text on the main thread (every 2s)
        self._status_timer = rumps.Timer(self._sync_status, 2)
        self._status_timer.start()

        # Periodic refresh timer
        self.timer = rumps.Timer(self._timer_fire, REFRESH_INTERVAL_SECONDS)
        self.timer.start()

        # Kick off first refresh immediately
        threading.Thread(target=self._do_refresh, daemon=True).start()

    # ── LLM key resolution ───────────────────────────────────────────────

    def _get_llm_key(self):
        """Return the LLM API key: env var first, then DB-stored value."""
        if LLM_API_KEY:
            return LLM_API_KEY
        return self.db.get_setting("llm_api_key", "")

    # ── Main-thread status sync ──────────────────────────────────────────

    def _set_status(self, text):
        """Thread-safe: queue a status update for the main thread."""
        with self._status_lock:
            self._pending_status = text

    def _sync_status(self, _sender):
        """Runs on the main thread via rumps.Timer – applies pending status."""
        with self._status_lock:
            if self._pending_status is not None:
                self.status_item.title = self._pending_status
                self._pending_status = None

    # ── Timer callback ───────────────────────────────────────────────────

    def _timer_fire(self, _sender):
        if self.auto_refresh_on:
            threading.Thread(target=self._do_refresh, daemon=True).start()

    # ── Core refresh logic ───────────────────────────────────────────────

    def _do_refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._set_status("Refreshing…")
            logger.info("Refresh started")

            # 1. Collect
            items = fetch_feeds(FEEDS, max_age_days=ITEM_MAX_AGE_DAYS)
            new = 0
            for it in items:
                if self.db.insert_item(
                    it["url"], it["title"], it["source"],
                    it["published_at"], it["snippet"],
                ):
                    new += 1
            logger.info("Fetched %d items (%d new)", len(items), new)

            # 2. Summarize (use dynamic key lookup)
            api_key = self._get_llm_key()
            unsummarized = self.db.get_unsummarized_items(
                limit=MAX_NEW_ITEMS_PER_REFRESH
            )
            if unsummarized:
                results = summarize_items(
                    unsummarized, TOPIC_NAME, KEYWORDS,
                    api_key, LLM_API_URL, LLM_MODEL,
                )
                for r in results:
                    self.db.update_summary(
                        r["id"], r["summary"], r["why_it_matters"],
                        r["tags"], r["relevance_score"],
                    )
                logger.info("Summarized %d items", len(results))

            # 3. Rank
            recalculate_scores(self.db)

            # 4. Update status
            self.last_refresh = datetime.now()
            total = self.db.get_item_count()
            key_note = " · no-key mode" if not api_key else ""
            self._set_status(
                f"Updated {self.last_refresh.strftime('%H:%M')}"
                f" · {total} items{key_note}"
            )
            logger.info("Refresh complete (%d total items)", total)

        except Exception as exc:
            logger.error("Refresh failed: %s", exc, exc_info=True)
            self._set_status(f"Refresh failed – {str(exc)[:45]}")
        finally:
            self._refreshing = False

    # ── Menu actions ─────────────────────────────────────────────────────

    @rumps.clicked("Refresh Now")
    def on_refresh(self, _sender):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    @rumps.clicked("Open Digest")
    def on_open_digest(self, _sender):
        webbrowser.open(f"http://127.0.0.1:{DIGEST_PORT}")

    @rumps.clicked("Auto-refresh (60 min)")
    def on_toggle_auto(self, sender):
        self.auto_refresh_on = not self.auto_refresh_on
        sender.state = self.auto_refresh_on

    @rumps.clicked("Set API Key…")
    def on_set_api_key(self, _sender):
        current = self._get_llm_key()
        masked = (current[:8] + "…" + current[-4:]) if len(current) > 16 else current

        win = rumps.Window(
            title="Set OpenAI API Key",
            message=(
                "Paste your OpenAI-compatible API key below.\n"
                "This enables AI-powered summaries.\n"
                "Leave blank to use keyword-only mode."
            ),
            default_text=masked,
            ok="Save",
            cancel="Cancel",
            dimensions=(380, 24),
        )
        response = win.run()
        if response.clicked:
            new_key = response.text.strip()
            # Don't save the masked version back
            if new_key == masked:
                return
            self.db.set_setting("llm_api_key", new_key)
            status = "saved" if new_key else "cleared"
            logger.info("API key %s via GUI", status)
            rumps.alert(
                title="API Key Updated",
                message=f"Key {status}. New articles will use "
                + ("AI summaries." if new_key else "keyword-only mode."),
            )

    @rumps.clicked("Settings…")
    def on_settings(self, _sender):
        api_key = self._get_llm_key()
        key_status = "Configured" if api_key else "Not set (keyword-only mode)"
        key_source = "env var" if LLM_API_KEY else ("GUI" if api_key else "—")
        rumps.alert(
            title="Signal Scout – Settings",
            message=(
                f"Topic: {TOPIC_NAME}\n"
                f"Feeds: {len(FEEDS)} configured\n"
                f"LLM API key: {key_status} (via {key_source})\n"
                f"LLM model: {LLM_MODEL}\n"
                f"Database: {DB_PATH}\n"
                f"Digest URL: http://127.0.0.1:{DIGEST_PORT}\n\n"
                "Use 'Set API Key…' to add or change your key.\n"
                "Edit config.py to change feeds or topic."
            ),
        )

    @rumps.clicked("Quit Signal Scout")
    def on_quit(self, _sender):
        self.db.close()
        rumps.quit_application()


if __name__ == "__main__":
    SignalScoutApp().run()
