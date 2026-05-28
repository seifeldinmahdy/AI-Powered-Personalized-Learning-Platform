"""
Local file persistence for the evidence ledger.

Each student accumulates behavioral observations and validation records
into a single JSON file under ``ai_service/data/evidence_ledger/{student_id}/``.
This mirrors the lightweight persistence approach used by problem_set_store
and lab_store.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "evidence_ledger"


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
        """Returns path to the student's ledger JSON file."""
        return self._student_dir(student_id) / "ledger.json"

    # ── Load / Save ─────────────────────────────────────────────

    def load(self, student_id: str) -> dict:
        """
        Load the full ledger for a student.
        Returns empty ledger structure if file does not exist.
        """
        path = self.get_ledger_path(student_id)
        if not path.exists():
            return {
                "student_id": student_id,
                "last_updated": "",
                "evidence": [],
                "pending_observations": [],
                "validated_updates": [],
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw
        except Exception as exc:
            logger.error(
                "evidence_ledger_load_failed student_id=%s error=%s",
                student_id, exc,
            )
            return {
                "student_id": student_id,
                "last_updated": "",
                "evidence": [],
                "pending_observations": [],
                "validated_updates": [],
            }

    def save(self, student_id: str, ledger: dict) -> None:
        """Save the full ledger dict to disk. Sets last_updated to now."""
        ledger["last_updated"] = datetime.utcnow().isoformat() + "Z"
        path = self.get_ledger_path(student_id)
        path.write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("evidence_ledger_saved student_id=%s path=%s", student_id, path)

    # ── Evidence ────────────────────────────────────────────────

    def append_evidence(
        self,
        student_id: str,
        items: list[dict],
    ) -> None:
        """
        Append new evidence items to the ledger.
        Each item shape:
        {
            "id": str,
            "session_id": str,
            "session_type": str,
            "source": str,
            "timestamp": str,
            "raw_observation": str,
            "supports_labels": list[str],
            "confidence": str,
            "used_in_profile_update": False
        }
        """
        if not items:
            return
        ledger = self.load(student_id)
        ledger["evidence"].extend(items)
        self.save(student_id, ledger)
        logger.info(
            "evidence_appended student_id=%s count=%d total=%d",
            student_id, len(items), len(ledger["evidence"]),
        )

    # ── Pending observations ────────────────────────────────────

    def add_pending_observation(
        self,
        student_id: str,
        pending: dict,
    ) -> None:
        """
        Add a rejected proposed update to pending_observations.
        If a pending item with the same proposed_label already exists,
        merge: extend its evidence_ids, increment sessions_observed.
        """
        ledger = self.load(student_id)

        # Check for existing pending with same proposed_label
        existing = None
        for p in ledger["pending_observations"]:
            if p.get("proposed_label") == pending.get("proposed_label"):
                existing = p
                break

        if existing is not None:
            # Merge: extend evidence_ids (deduplicate), bump sessions_observed
            existing_ids = set(existing.get("evidence_ids", []))
            new_ids = pending.get("evidence_ids", [])
            for eid in new_ids:
                if eid not in existing_ids:
                    existing["evidence_ids"].append(eid)
            existing["sessions_observed"] = existing.get("sessions_observed", 1) + 1
            # Keep the latest validator_reasoning
            existing["validator_reasoning"] = pending.get(
                "validator_reasoning", existing.get("validator_reasoning", "")
            )
        else:
            ledger["pending_observations"].append(pending)

        self.save(student_id, ledger)

    # ── Validated updates ───────────────────────────────────────

    def add_validated_update(
        self,
        student_id: str,
        update: dict,
    ) -> None:
        """
        Record a validated update that was written to the profile.
        Also mark the referenced evidence_ids as used_in_profile_update=True.
        """
        ledger = self.load(student_id)
        ledger["validated_updates"].append(update)

        # Mark evidence items as used
        used_ids = set(update.get("evidence_ids", []))
        if used_ids:
            for ev in ledger["evidence"]:
                if ev.get("id") in used_ids:
                    ev["used_in_profile_update"] = True

        self.save(student_id, ledger)

    # ── Queries ─────────────────────────────────────────────────

    def get_pending_ready_for_validation(
        self,
        student_id: str,
        thresholds: dict[str, int],
    ) -> list[dict]:
        """
        Return pending observations whose evidence_ids count has reached
        or exceeded the threshold for their proposed_field.
        Uses confidence-weighted counting.
        """
        from services.profiler_service import _evidence_weight

        ledger = self.load(student_id)
        evidence_by_id = {ev["id"]: ev for ev in ledger.get("evidence", [])}
        ready = []

        for pending in ledger.get("pending_observations", []):
            field_base = pending.get("proposed_field", "").split(".")[0]
            threshold = thresholds.get(field_base, 2)

            # Gather evidence items for this pending observation
            evidence_items = [
                evidence_by_id[eid]
                for eid in pending.get("evidence_ids", [])
                if eid in evidence_by_id
            ]
            weight = _evidence_weight(evidence_items)

            if weight >= threshold:
                ready.append(pending)

        return ready

    def get_evidence_for_labels(
        self,
        student_id: str,
        labels: list[str],
    ) -> list[dict]:
        """
        Return all evidence items where supports_labels intersects with
        the given labels list.
        """
        ledger = self.load(student_id)
        labels_set = set(labels)
        results = []

        for ev in ledger.get("evidence", []):
            ev_labels = set(ev.get("supports_labels", []))
            if ev_labels & labels_set:
                results.append(ev)

        return results

    def remove_pending_by_label(
        self,
        student_id: str,
        proposed_label: str,
    ) -> None:
        """Remove a pending observation after it has been validated."""
        ledger = self.load(student_id)
        ledger["pending_observations"] = [
            p for p in ledger["pending_observations"]
            if p.get("proposed_label") != proposed_label
        ]
        self.save(student_id, ledger)


# ── Module-level singleton ──────────────────────────────────────

_store: EvidenceLedgerStore | None = None


def get_evidence_ledger_store() -> EvidenceLedgerStore:
    global _store
    if _store is None:
        _store = EvidenceLedgerStore()
    return _store
