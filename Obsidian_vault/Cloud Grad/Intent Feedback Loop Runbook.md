# Intent Feedback Loop Runbook

## What Changed

### Backend (`backend/apps/progress/`)
- Extended `AIChatLog` model with intent prediction metadata and feedback fields.
- Added `IntentFeedbackBuffer` model as the dedicated reviewed-utterance store.
- Added `IntentRetrainingCounter` singleton to count reviews since last retrain.
- New API endpoints:
  - `POST /api/progress/chat-logs/` — create chat log (now accepts prediction metadata).
  - `PATCH /api/progress/chat-logs/<id>/feedback/` — submit 👍/👎 feedback.
  - `GET /api/progress/intent-feedback-buffer/` — admin review queue.
  - `PATCH /api/progress/intent-feedback-buffer/<id>/` — relabel thumbs-down entries.
  - `GET /api/progress/intent-retraining-counter/` — view counter.
  - `PATCH /api/progress/intent-retraining-counter/` — staff-only threshold update.
- Management command: `python manage.py check_intent_retraining [--force] [--dry-run]`.

### Frontend (`frontend/src/`)
- `CompactTutor.tsx` now captures the full intent prediction before answering.
- `persistChatLog` stores prediction + context + session id.
- Tutor response bubbles show 👍/👎 buttons.
- `submitFeedback()` sends feedback to backend.

### AI Service (`ai_service/`)
- `POST /intent/reload` endpoint reloads the production checkpoint without restart.
- `intent_service.py` exposes `reload_intent_service()`.

### Intent Classifier Model (`Intent_Classifier_Model/`)
- `train.py` accepts `--train-csv`, `--val-csv`, `--test-csv`, `--best-model-path`, `--results-path`, `--feedback-test-csv` via CLI/env overrides.
- `feedback_trainer.py` orchestrates mixing feedback utterances into synthetic data, training, quality gate, and promotion to `prod_tinybert.pt`.

## Migration

```bash
cd backend
venv/Scripts/python.exe manage.py migrate
```

New migration: `0007_intentretrainingcounter_aichatlog_confidence_and_more.py`

## Configuration

Threshold default is 50 reviews. Staff can update via:

```bash
curl -X PATCH -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"threshold": 100}' \
  http://localhost:8000/api/progress/intent-retraining-counter/
```

## Operational Workflow

1. Student asks a question; frontend classifies intent and persists chat log.
2. Tutor answers; student clicks 👍 or 👎.
3. Backend stores feedback and increments `IntentRetrainingCounter`.
4. When counter >= threshold:
   - Cron (or manual API call) runs `check_intent_retraining`.
   - Pending buffer rows are exported to `Intent_Classifier_Model/data/feedback_utterances.csv`.
   - `feedback_trainer.py` retrains the model.
   - If quality gate passes, model is promoted to `prod_tinybert.pt`.
   - Backend notifies AI service via `POST /intent/reload`.
   - Buffer rows marked `used`, counter reset.

## Cron Example

```cron
*/15 * * * * cd /path/to/backend && venv/bin/python manage.py check_intent_retraining
```

## Manual Trigger

```bash
cd backend
venv/Scripts/python.exe manage.py check_intent_retraining --force --dry-run
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Feedback buttons not appearing | Ensure `lessonId` prop is passed to `CompactTutor`. |
| Retraining never triggers | Verify cron is running and threshold is set. Check `IntentRetrainingCounter` in admin. |
| Model not reloading after retrain | Check AI service logs for `POST /intent/reload` and that `prod_tinybert.pt` exists. |
| Thumbs-down rows not useful | Admin must relabel via `/intent-feedback-buffer/<id>/` with `corrected_intent`. |

## Files Modified

- `backend/apps/progress/models.py`
- `backend/apps/progress/serializers.py`
- `backend/apps/progress/views.py`
- `backend/apps/progress/urls.py`
- `backend/apps/progress/admin.py`
- `backend/apps/progress/management/commands/check_intent_retraining.py`
- `backend/apps/progress/migrations/0007_intentretrainingcounter_aichatlog_confidence_and_more.py`
- `backend/config/test_settings.py`
- `ai_service/services/intent_service.py`
- `ai_service/routers/intent.py`
- `Intent_Classifier_Model/train.py`
- `Intent_Classifier_Model/feedback_trainer.py`
- `frontend/src/services/tutor.ts`
- `frontend/src/components/CompactTutor.tsx`
