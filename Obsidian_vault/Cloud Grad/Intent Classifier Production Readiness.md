# Intent Classifier Production Readiness

## Current Status (2026-06-12)
- Most `issues/` folder items are resolved.
- Remaining future task: **Make Intent Classifier Model production-ready**.
- Lecture 9 MLOps introduces a drift-avoidance mechanic using 👍/👎 reinforcement learning feedback.

## Goal
Build a closed-loop system that:
1. Collects user feedback (👍 / 👎) on tutor answers.
2. Stores reviewed utterances in a dedicated database (`IntentFeedbackBuffer`).
3. Retrains the intent classifier after a configurable number of reviews.

## Implementation Status: ✅ Implemented

| Component | Status |
|-----------|--------|
| Backend DB schema + API | ✅ Done |
| Frontend 👍/👎 buttons + prediction capture | ✅ Done |
| Feedback buffer export management command | ✅ Done |
| Feedback-aware retraining script | ✅ Done |
| Model reload endpoint | ✅ Done |
| Migrations | ✅ Generated & tested on SQLite |
| Admin views | ✅ Done |

## Key Artifacts

- Design doc: [[Intent Feedback Loop Design]]
- Runbook: [[Intent Feedback Loop Runbook]]

## Remaining Recommendations

- Run a full end-to-end retraining test on a GPU machine once at least 50 real feedback samples exist.
- Monitor the feedback F1 gate (`>=0.75`) and adjust based on real-world performance.
- Consider adding Celery + Redis for async retraining instead of cron-based polling.
- Add monitoring/alerting when `retraining_recommended` is true but no retrain has occurred for >24h.
- Periodically review thumbs-down entries in the admin buffer and relabel them.
