# Intent Classifier Feedback Loop Design

## Overview
Production-ready improvement for the Intent Classifier using user 👍/👎 feedback on tutor answers to detect drift and trigger retraining.

## Data Flow

```
┌─────────────────┐     ask/continue      ┌──────────────────┐
│   Frontend      │ ────────────────────> │   ai_service     │
│  CompactTutor   │                       │  /tutor/*        │
└─────────────────┘                       └──────────────────┘
         │                                         │
         │ classify intent + prediction details    │
         │ <───────────────────────────────────────┘
         │
         │ persistChatLog({transcript, response, intent, confidence, probs})
         ▼
┌──────────────────────────────────────────────────────────────┐
│              backend /api/progress/chat-logs/                │
│                     AIChatLog (extended)                     │
└──────────────────────────────────────────────────────────────┘
         │
         │ User clicks 👍 or 👎 on tutor response
         ▼
┌──────────────────────────────────────────────────────────────┐
│        PATCH /api/progress/chat-logs/<id>/feedback/          │
│     Saves feedback, adds row to IntentFeedbackBuffer         │
│        increments IntentRetrainingCounter                    │
└──────────────────────────────────────────────────────────────┘
         │
         │ counter >= INTENT_RETRAIN_REVIEW_THRESHOLD
         ▼
┌──────────────────────────────────────────────────────────────┐
│  check_intent_retraining management command / cron / API     │
│    1. Export buffer to Intent_Classifier_Model/data/         │
│    2. Run dataset_generator.py + train.py with feedback mix  │
│    3. Evaluate on held-out real + feedback test split        │
│    4. Promote model if quality gate passes                   │
│    5. Mark buffer rows as used                               │
└──────────────────────────────────────────────────────────────┘
```

## Backend Models

### AIChatLog (extended)
| Field | Type | Notes |
|-------|------|-------|
| session_id | CharField(max_length=64, blank=True) | ai_service session id |
| predicted_intent | CharField(choices=INTENT_CHOICES, blank=True) | model prediction |
| confidence | FloatField(null=True, blank=True) | top softmax probability |
| intent_probabilities | JSONField(default=dict) | full probability dict |
| session_context | TextField(blank=True) | context string passed to model |
| feedback | CharField(choices=[thumbs_up, thumbs_down], null=True, blank=True) | user feedback |
| feedback_at | DateTimeField(null=True, blank=True) | when feedback was given |
| used_for_retraining | BooleanField(default=False) | whether row consumed |

### IntentFeedbackBuffer (new)
| Field | Type | Notes |
|-------|------|-------|
| chat_log | OneToOneField(AIChatLog) | source row |
| student_input | TextField | utterance text |
| session_context | TextField | model context |
| predicted_intent | CharField | provisional label |
| confidence | FloatField | model confidence |
| feedback | CharField | thumbs_up / thumbs_down |
| corrected_intent | CharField(null=True, blank=True) | admin relabel for thumbs_down |
| status | CharField(choices=[pending, used, relabeled], default=pending) | lifecycle |

### IntentRetrainingCounter (new)
| Field | Type | Notes |
|-------|------|-------|
| reviews_since_last_train | PositiveIntegerField(default=0) | count of feedback events |
| last_trained_at | DateTimeField(null=True, blank=True) | last retrain timestamp |
| threshold | PositiveIntegerField(default=50) | configurable trigger |

## Frontend Changes
- `CompactTutor.tsx`: add 👍/👎 buttons to tutor message bubbles.
- `tutor.ts`: add `submitFeedback`, update `persistChatLog` to capture prediction details.
- Capture full prediction from `classifyIntent` before acting on it.

## Retraining Pipeline
- `feedback_trainer.py` in `Intent_Classifier_Model/`.
- Reads `IntentFeedbackBuffer` (or exported CSV).
- Mixes feedback utterances into synthetic dataset.
- Splits feedback into train/val/test (e.g., 70/15/15).
- Uses corrected_intent if available, otherwise predicted_intent.
- Runs existing `train.py` pipeline.
- Quality gate: same as `auto_trainer.py` plus real-utterance + feedback F1.
- Promotes `best_tinybert.pt` → `prod_tinybert.pt` on success.

## Operational Notes
- No Celery/RQ currently configured; use cron calling management command or manual API trigger.
- Initial threshold: 50 reviews.
- Only 👍 feedback and relabeled 👎 feedback are used as labeled training data.
- Raw 👎 feedback enters review queue for admin correction.
