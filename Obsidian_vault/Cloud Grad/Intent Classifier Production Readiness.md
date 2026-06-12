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

## Training Pipeline Status

- `data/real_utterances.csv` is present (293 samples, all 6 classes represented).
- `train.py` evaluates on the real-utterance split, records the checkpoint path, and sets `promotion_ready` when real-utterance F1 ≥ 0.75.
- `kaggle_train.ipynb` was updated to verify `real_utterances.csv`, write the same JSON keys, export `prod_model.onnx`, and report the promotion gate.
- Pre-flight / post-run checks and promotion are handled **inside existing files** (no extra scripts). Use the notebook’s final cell and the existing `/intent/reload` endpoint with `X-Service-Key`.

## Code Cleanup

Recent cleanup removed dead/unused code from the classifier:

- `TinyBert.py`: removed unused `train_step`, `evaluate`, `predict_with_confidence`, `export_onnx`, `predict_onnx`; simplified dead Arabic branch in compound splitter.
- `auto_trainer.py`: fixed stale metric-key reads (`accuracy`/`f1_score`/`f1_score`) and model-path mismatch (`best_model.pt`); removed unused logger.
- `feedback_trainer.py`: fixed corrected-intent labels being overwritten; removed unused import and no-op rename.
- `test_suite.py`: fixed misplaced `__main__` guard that was silently skipping ~40% of tests; removed unused `json` import.
- `dataset_generator.py`: removed unused `generate_session_context`, unused logger, dead Groq LLM augmentation block, and verbose `MOVED`/`REMOVED` comment noise.
- `train.py` / `generate_real_utterances.py`: removed unused imports and placeholder f-strings.

## Dependencies

- `structlog` is installed (required by `rag_pipeline`).
- `USE_TF=0` is set before the RAG engine import to avoid pulling TensorFlow/Keras into the import chain.

## Key Artifacts

- Design doc: [[Intent Feedback Loop Design]]
- Runbook: [[Intent Feedback Loop Runbook]]
- Claude conversation change log: [[Claude Intent Classifier Change Log]]

## Remaining Recommendations

- Run a full end-to-end retraining test on a GPU machine once at least 50 real feedback samples exist.
- Monitor the feedback F1 gate (`>=0.75`) and adjust based on real-world performance.
- Consider adding Celery + Redis for async retraining instead of cron-based polling.
- Add monitoring/alerting when `retraining_recommended` is true but no retrain has occurred for >24h.
- Periodically review thumbs-down entries in the admin buffer and relabel them.

## Known Issues

- Local RAG fetch still fails with a ChromaDB Rust panic (`range start index 10 out of range for slice of length 9`). This appears to be a `chromadb` version/DB-format mismatch, not a code bug. The existing `real_utterances.csv` is unaffected; the Kaggle notebook does not use RAG.
