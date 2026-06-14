"""Durable, append-only session-event log (survives tab-close / AI-service restart).

Live-session signal (slide views, time-per-slide, tutor events, fused emotions)
is streamed here AS IT IS PRODUCED, instead of living only in the volatile
SharedSessionStore. The session profiler consolidates from this log, so an
ABANDONED session still yields a partial profile update.

Idempotency: consolidation reads UNCONSUMED events and then marks them consumed.
The explicit session-end call and the background sweeper therefore never
double-apply — a re-run over an already-consumed session reads nothing.

SQLite (local file) keeps high-frequency emotion writes off the Django HTTP path.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "session_events.db"

_DDL = """
CREATE TABLE IF NOT EXISTS session_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    student_id  TEXT NOT NULL DEFAULT '',
    course_id   TEXT NOT NULL DEFAULT '',
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    consumed    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_events_sid ON session_events (session_id, consumed, id);
"""


class SessionEventLog:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Path | None = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init(db_path or _DB_PATH)
        return cls._instance

    def _init(self, db_path: Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_DDL)
            conn.commit()
        logger.info("session_event_log_ready", path=self._db_path)

    def append(self, session_id: str, event_type: str, payload: dict,
               student_id: str = "", course_id: str = "") -> None:
        if not session_id:
            return
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO session_events (session_id, student_id, course_id, event_type, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, str(student_id), str(course_id), event_type,
                     json.dumps(payload, ensure_ascii=False),
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except Exception as exc:  # never let logging break the live session
            logger.warning("session_event_append_failed", session_id=session_id, error=str(exc))

    def read_unconsumed(self, session_id: str) -> list[dict]:
        """Return this session's unconsumed events, oldest first."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, student_id, course_id, event_type, payload, created_at "
                "FROM session_events WHERE session_id=? AND consumed=0 ORDER BY id",
                (session_id,),
            ).fetchall()
        out = []
        for _id, sid, cid, etype, payload, created in rows:
            try:
                data = json.loads(payload)
            except Exception:
                data = {}
            out.append({"id": _id, "student_id": sid, "course_id": cid,
                        "event_type": etype, "payload": data, "created_at": created})
        return out

    def mark_consumed(self, session_id: str, up_to_id: int) -> None:
        """Mark this session's events (id ≤ up_to_id) consumed — the idempotency
        marker. A re-run then reads nothing → no double-apply."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE session_events SET consumed=1 WHERE session_id=? AND id<=? AND consumed=0",
                (session_id, up_to_id),
            )
            conn.commit()

    def sessions_with_unconsumed(self, older_than_iso: str | None = None) -> list[str]:
        """Distinct session_ids that still have unconsumed events (for the sweeper)."""
        q = "SELECT DISTINCT session_id FROM session_events WHERE consumed=0"
        params: tuple = ()
        if older_than_iso:
            q += " AND created_at < ?"
            params = (older_than_iso,)
        with sqlite3.connect(self._db_path) as conn:
            return [r[0] for r in conn.execute(q, params).fetchall()]


def get_session_event_log() -> SessionEventLog:
    return SessionEventLog()
