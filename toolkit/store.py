"""SQLite log of notifications sent to the phone (backs the notifications://sent resource)."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from toolkit.models import SentNotification

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title    TEXT NOT NULL,
    message  TEXT NOT NULL,
    links    TEXT NOT NULL,
    topic    TEXT NOT NULL,
    sent_at  TEXT NOT NULL
)
"""


class NotificationLog:
    def __init__(self, path: Path):
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute(SCHEMA)
        return conn

    def add(self, *, title: str, message: str, links: dict[str, str], topic: str) -> SentNotification:
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notifications (title, message, links, topic, sent_at) VALUES (?, ?, ?, ?, ?)",
                (title, message, json.dumps(links), topic, sent_at),
            )
        conn.close()
        return SentNotification(
            id=cur.lastrowid, title=title, message=message, links=links, topic=topic, sent_at=sent_at
        )

    def recent(self, limit: int = 50) -> list[SentNotification]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        conn.close()
        return [SentNotification(**{**dict(row), "links": json.loads(row["links"])}) for row in rows]
