"""
Local file persistence for the evidence ledger.

Each student has a ledger JSON file under
``ai_service/data/evidence_ledger/{student_id}/ledger.json``
that records **outcomes only** — validated profile writes and pending
observation counts.  Raw observations are never persisted.

Ledger JSON structure::

    {
      "student_id": "16",
      "last_updated": "2026-05-28T21:45:55Z",
      "validated_updates": [ ... ],
      "pending": [ ... ]
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "evidence_ledger"

# Maximum validated_updates entries before oldest are pruned.
_MAX_VALIDATED = 200


class EvidenceLedgerStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("EvidenceLedgerStore initialised (dir=%s)", self._dir)

    # ── Path helpers ────────────────────────────────────────────

    def _student_dir(self, student_id: str) -> Path:
        safe = student_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        d = self._dir / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_ledger_path(self, student_id: str) -> Path:
        """Returns ``./data/evidence_ledger/{student_id}/ledger.json``."""
        return self._student_dir(student_id) / "ledger.json"

    # ── Load / Save ─────────────────────────────────────────────

    def load(self, student_id: str) -> dict:
        """Load ledger or return empty structure."""
        path = self.get_ledger_path(student_id)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return data
            except Exception as e:
                logger.warning("Failed to load ledger for %s: %s", student_id, e)
        return {
            "student_id": student_id,
            "last_updated": "",
            "validated_updates": [],
            "pending": [],
        }

    def save(self, student_id: str, ledger: dict) -> None:
        """Save ledger dict.  Sets ``last_updated`` to ``utcnow().isoformat()``."""
        ledger["last_updated"] = datetime.utcnow().isoformat() + "Z"
        path = self.get_ledger_path(student_id)
        path.write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("evidence_ledger_saved student_id=%s path=%s", student_id, path)

    # ── Validated updates ───────────────────────────────────────

    def record_validated_update(
        self,
        student_id: str,
        field: str,
        value: str,
        session_id: str,
        session_type: str,
        justification: str,
        evidence_summary: str,
    ) -> None:
        """
        Record a change that passed validation and was written to Django.

        Appends to ``validated_updates``.  Caps at ``_MAX_VALIDATED`` —
        removes oldest entries if over the limit.
        """
        ledger = self.load(student_id)
        ledger["validated_updates"].append({
            "field": field,
            "value": value,
            "written_at": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "session_type": session_type,
            "justification": justification,
            "evidence_summary": evidence_summary,
        })
        # Cap at _MAX_VALIDATED — remove oldest
        if len(ledger["validated_updates"]) > _MAX_VALIDATED:
            ledger["validated_updates"] = ledger["validated_updates"][-_MAX_VALIDATED:]
        self.save(student_id, ledger)

    # ── Pending observations ────────────────────────────────────

    def increment_pending(
        self,
        student_id: str,
        field: str,
        value: str,
        threshold: int,
        session_id: str,
        justification: str,
    ) -> dict:
        """
        Increment the counter for a pending observation.

        If an entry with this exact ``(field, value)`` already exists,
        increment ``times_seen`` and update ``last_session_id`` /
        ``last_justification``.  Otherwise create it with
        ``times_seen=1``.

        Returns the updated pending entry.
        """
        ledger = self.load(student_id)
        existing = None
        for p in ledger["pending"]:
            if p.get("field") == field and p.get("value") == value:
                existing = p
                break

        if existing is not None:
            existing["times_seen"] = existing.get("times_seen", 1) + 1
            existing["last_session_id"] = session_id
            existing["last_justification"] = justification
            entry = existing
        else:
            entry = {
                "field": field,
                "value": value,
                "first_seen": datetime.utcnow().isoformat() + "Z",
                "times_seen": 1,
                "threshold": threshold,
                "last_session_id": session_id,
                "last_justification": justification,
            }
            ledger["pending"].append(entry)

        self.save(student_id, ledger)
        return entry

    def get_pending_ready(self, student_id: str) -> list[dict]:
        """Return all pending entries where ``times_seen >= threshold``."""
        ledger = self.load(student_id)
        return [
            p for p in ledger.get("pending", [])
            if p.get("times_seen", 0) >= p.get("threshold", 2)
        ]

    def remove_pending(
        self,
        student_id: str,
        field: str,
        value: str,
    ) -> None:
        """
        Remove a pending entry by ``(field, value)`` after it has been
        processed by the validator (whether approved or rejected).
        """
        ledger = self.load(student_id)
        ledger["pending"] = [
            p for p in ledger["pending"]
            if not (p.get("field") == field and p.get("value") == value)
        ]
        self.save(student_id, ledger)

    # ── Queries ─────────────────────────────────────────────────

    def get_recent_validated(
        self,
        student_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Return the most recent *N* ``validated_updates`` for audit/debug."""
        ledger = self.load(student_id)
        return ledger.get("validated_updates", [])[-limit:]




# ── Module-level singleton ──────────────────────────────────────

_store: EvidenceLedgerStore | None = None


def get_evidence_ledger_store() -> EvidenceLedgerStore:
    global _store
    if _store is None:
        _store = EvidenceLedgerStore()
    return _store
