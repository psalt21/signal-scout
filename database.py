"""Signal Scout – SQLite storage layer (thread-safe)."""

import json
import os
import sqlite3
import threading


class Database:
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._create_tables()

    # ── Schema ───────────────────────────────────────────────────────────
    def _create_tables(self):
        with self.lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS items (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT UNIQUE,
                    title         TEXT,
                    source        TEXT,
                    published_at  TEXT,
                    snippet       TEXT,
                    summary       TEXT,
                    why_it_matters TEXT,
                    tags          TEXT DEFAULT '[]',
                    relevance_score INTEGER DEFAULT 50,
                    final_score   REAL DEFAULT 50.0,
                    summarized    INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id    INTEGER,
                    vote       INTEGER,
                    note       TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (item_id) REFERENCES items(id)
                );

                CREATE TABLE IF NOT EXISTS tag_weights (
                    tag    TEXT PRIMARY KEY,
                    weight REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS source_weights (
                    source TEXT PRIMARY KEY,
                    weight REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            self.conn.commit()

    # ── Items ────────────────────────────────────────────────────────────
    def insert_item(self, url, title, source, published_at, snippet):
        """Insert a feed item.  Returns True if new, False if duplicate."""
        with self.lock:
            try:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO items "
                    "(url, title, source, published_at, snippet) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (url, title, source, published_at, snippet),
                )
                self.conn.commit()
                return cur.rowcount > 0
            except sqlite3.Error:
                return False

    def get_unsummarized_items(self, limit=30):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM items WHERE summarized = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_summary(self, item_id, summary, why_it_matters, tags, relevance_score):
        with self.lock:
            self.conn.execute(
                "UPDATE items SET summary=?, why_it_matters=?, tags=?, "
                "relevance_score=?, summarized=1 WHERE id=?",
                (summary, why_it_matters, json.dumps(tags), relevance_score, item_id),
            )
            self.conn.commit()

    def get_digest_items(self, limit=15):
        with self.lock:
            rows = self.conn.execute(
                """SELECT i.*,
                    (SELECT vote FROM feedback
                     WHERE item_id = i.id
                     ORDER BY created_at DESC LIMIT 1) AS user_vote
                   FROM items i
                   WHERE i.summarized = 1
                   ORDER BY i.final_score DESC, i.created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_summarized_items(self):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM items WHERE summarized = 1"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_final_score(self, item_id, final_score):
        with self.lock:
            self.conn.execute(
                "UPDATE items SET final_score=? WHERE id=?",
                (final_score, item_id),
            )
            self.conn.commit()

    # ── Feedback & weights ───────────────────────────────────────────────
    def record_feedback(self, item_id, vote):
        """Record a vote (+1/−1) and adjust tag/source weights."""
        with self.lock:
            self.conn.execute(
                "INSERT INTO feedback (item_id, vote) VALUES (?, ?)",
                (item_id, vote),
            )
            item = self.conn.execute(
                "SELECT * FROM items WHERE id=?", (item_id,)
            ).fetchone()
            if item:
                item = dict(item)
                for tag in json.loads(item.get("tags", "[]")):
                    self._adjust_tag_weight(tag, vote)
                self._adjust_source_weight(item.get("source", ""), vote)
            self.conn.commit()

    def _adjust_tag_weight(self, tag, delta):
        row = self.conn.execute(
            "SELECT weight FROM tag_weights WHERE tag=?", (tag,)
        ).fetchone()
        new = max(-10, min(10, (row["weight"] if row else 0) + delta))
        self.conn.execute(
            "INSERT OR REPLACE INTO tag_weights (tag, weight) VALUES (?, ?)",
            (tag, new),
        )

    def _adjust_source_weight(self, source, delta):
        row = self.conn.execute(
            "SELECT weight FROM source_weights WHERE source=?", (source,)
        ).fetchone()
        new = max(-10, min(10, (row["weight"] if row else 0) + delta))
        self.conn.execute(
            "INSERT OR REPLACE INTO source_weights (source, weight) VALUES (?, ?)",
            (source, new),
        )

    def get_tag_weight(self, tag):
        with self.lock:
            row = self.conn.execute(
                "SELECT weight FROM tag_weights WHERE tag=?", (tag,)
            ).fetchone()
            return row["weight"] if row else 0.0

    def get_source_weight(self, source):
        with self.lock:
            row = self.conn.execute(
                "SELECT weight FROM source_weights WHERE source=?", (source,)
            ).fetchone()
            return row["weight"] if row else 0.0

    # ── Settings ─────────────────────────────────────────────────────────
    def get_setting(self, key, default=None):
        with self.lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key, value):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            self.conn.commit()

    # ── Misc ─────────────────────────────────────────────────────────────
    def get_item_count(self):
        with self.lock:
            return self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM items"
            ).fetchone()["cnt"]

    def close(self):
        self.conn.close()
