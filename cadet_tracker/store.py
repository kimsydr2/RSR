"""SQLite state: last snapshot, miss history, change log, sent-keys, outbox."""
from __future__ import annotations
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (week TEXT, cadet TEXT, col TEXT, status TEXT, raw TEXT,
  updated_at TEXT, PRIMARY KEY (week, cadet, col));
CREATE TABLE IF NOT EXISTS changes (week TEXT, cadet TEXT, col TEXT, old TEXT, new TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS misses (week TEXT, cadet TEXT, kind TEXT, at TEXT,
  PRIMARY KEY (week, cadet, kind));
CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, at TEXT);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT,
  subject TEXT, body TEXT, due_at TEXT, sent_at TEXT, created_at TEXT,
  attempts INTEGER DEFAULT 0, last_error TEXT);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(outbox)")}
        for name, decl in (("attempts", "INTEGER DEFAULT 0"), ("last_error", "TEXT")):
            if name not in cols:                       # upgrade an older database
                self.db.execute(f"ALTER TABLE outbox ADD COLUMN {name} {decl}")
        self.db.commit()

    # --- idempotency: each logical notification fires once ---
    def once(self, key: str, now: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO sent VALUES (?, ?)", (key, now))
        self.db.commit()
        return cur.rowcount == 1

    # --- snapshots / change detection ---
    def previous(self, week: str) -> dict:
        rows = self.db.execute("SELECT cadet, col, raw FROM snapshot WHERE week=?", (week,))
        return {(c, col): raw for c, col, raw in rows}

    def save_cell(self, week, cadet, col, status, raw, now):
        self.db.execute("INSERT OR REPLACE INTO snapshot VALUES (?,?,?,?,?,?)",
                        (week, cadet, col, status, raw, now))

    def log_change(self, week, cadet, col, old, new, now):
        self.db.execute("INSERT INTO changes VALUES (?,?,?,?,?,?)", (week, cadet, col, old, new, now))

    def commit(self):
        self.db.commit()

    # --- history ---
    def record_miss(self, week, cadet, kind, now) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO misses VALUES (?,?,?,?)", (week, cadet, kind, now))
        self.db.commit()
        return cur.rowcount == 1

    def miss_count(self, cadet: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM misses WHERE cadet=?", (cadet,)).fetchone()[0]

    def miss_table(self):
        return self.db.execute(
            "SELECT cadet, COUNT(*), SUM(kind='deadline'), SUM(kind LIKE 'event:%'), MAX(at) "
            "FROM misses GROUP BY cadet ORDER BY COUNT(*) DESC, cadet").fetchall()

    def change_count(self, cadet: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM changes WHERE cadet=?", (cadet,)).fetchone()[0]

    # --- outbox (supports digest timing) ---
    def enqueue(self, recipient, subject, body, due_at, now):
        self.db.execute("INSERT INTO outbox (recipient, subject, body, due_at, created_at) "
                        "VALUES (?,?,?,?,?)", (recipient, subject, body, due_at, now))
        self.db.commit()

    def due(self, now: str):
        return self.db.execute("SELECT id, recipient, subject, body FROM outbox "
                               "WHERE sent_at IS NULL AND due_at <= ? ORDER BY id", (now,)).fetchall()

    def recent_sent(self, limit: int = 50):
        return self.db.execute("SELECT sent_at, recipient, subject, body FROM outbox "
                               "WHERE sent_at IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def pending(self):
        return self.db.execute(
            "SELECT due_at, recipient, subject, COALESCE(attempts, 0), last_error FROM outbox "
            "WHERE sent_at IS NULL ORDER BY due_at").fetchall()

    def record_failure(self, ids, error: str, now: str):
        self.db.executemany(
            "UPDATE outbox SET attempts = COALESCE(attempts, 0) + 1, last_error = ? WHERE id = ?",
            [(error, i) for i in ids])
        self.db.commit()

    def failures(self):
        return self.db.execute("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL "
                               "AND COALESCE(attempts, 0) > 0").fetchone()[0]

    def mark_sent(self, ids, now):
        self.db.executemany("UPDATE outbox SET sent_at=? WHERE id=?", [(now, i) for i in ids])
        self.db.commit()
