"""Fetch a course's CLO concept set from Django (for coverage-guaranteed gen).

Returns one row per (CLO, concept): ``[{concept_id, label, clo_code}]``. This is
the set the pathway generator must guarantee coverage of. Lives under
``pathway/`` (like ``corpus_resolver``) so both the in-process placement trigger
and the pathway router share one implementation without a course_pathway →
ai_service import.
"""

from __future__ import annotations

import os

import httpx
import structlog

logger = structlog.get_logger(__name__)

_DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")
_TIMEOUT = float(os.getenv("CLO_FETCH_TIMEOUT", "15"))


def fetch_clo_concepts(course_id: str) -> list[dict]:
    """Return ``[{concept_id, label, clo_code}]`` for *course_id* (empty on error)."""
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    headers = {"X-Service-Key": service_key} if service_key else {}
    base = _DJANGO_API_URL.rstrip("/")
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            clo_resp = client.get(f"{base}/courses/courses/{course_id}/clos/", headers=headers)
            con_resp = client.get(f"{base}/courses/courses/{course_id}/concepts/", headers=headers)
    except Exception as exc:
        logger.warning("clo_fetch_failed", course_id=course_id, error=str(exc))
        return []

    if clo_resp.status_code != 200 or con_resp.status_code != 200:
        logger.warning("clo_fetch_bad_status", course_id=course_id,
                       clos=clo_resp.status_code, concepts=con_resp.status_code)
        return []

    def _rows(payload):
        return payload.get("results", payload) if isinstance(payload, dict) else payload

    label_map = {str(c["id"]): c["label"] for c in _rows(con_resp.json())}
    rows: list[dict] = []
    for clo in _rows(clo_resp.json()):
        for cid in clo.get("concepts", []):
            cid = str(cid)
            rows.append({"concept_id": cid, "label": label_map.get(cid, cid),
                         "clo_code": clo.get("code", "")})
    return rows
