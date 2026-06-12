# Claude Intent Classifier Change Log

> Source: [Claude shared conversation](https://claude.ai/share/14ccc0af-5c0b-4c33-bd02-e3e3a01ed1db)  
> Topic: Intent classifier architecture, data generation, training pipeline, and tutor integration for AI-powered programming tutor  
> Logged by: Kimi on 2026-06-12

---

## 0. Goal

Build an intent classifier that is the best possible fit for a **programming education environment**, then wire it into the conversational tutor agent so the tutor's output quality matches the classifier's routing decisions.

---

## 1. Initial Six Fixes (Round 1)

The first analysis identified that **Emotional-State was a "gravity well"** — On-Topic, Off-Topic, and Pace-Related utterances were all bleeding into it.

| # | File | Change | Impact |
|---|------|--------|--------|
| 1 | `dataset_generator.py` | Remove ambiguous templates from `ON_TOPIC_TEMPLATES` (`"{topic} is confusing"`, `"I'm stuck..."`, `"I don't get..."`, `"Help me with {topic}"`) or move them to Emotional-State. | Stops On-Topic from leaking into Emotional-State. |
| 2 | `dataset_generator.py` | Reduce context dropout from 50% to **15–20%**. | Preserves `emotion:` and `pace:` supervisory signals. |
| 3 | `TinyBert.py` | Concatenate `[CLS]` token with CNN output; update `cnn_out_dim = len(filter_sizes) * num_filters + bert_hidden_size`. | Helps short utterances like "I'm bored". |
| 4 | `tutor_service.py` | Remove `check_relevance()`; use classifier result directly for Off-Topic routing at confidence > 0.65. | Removes redundant LLM call and conflicting logic. |
| 5 | Inference path | Add OOS confidence fallback; raise threshold from 0.55 to **0.65**. | Reduces false positives in the 0.55–0.70 band. |
| 6 | Test set | Expand `real_utterance_metrics` from 15 to **at least 200** samples. | Makes acceptance decisions statistically valid. |

**Apply order:** Fix 1 & 2 (data) → regenerate dataset → Fix 3 (model) → retrain from scratch. Fixes 1, 2, 4, 5 can be A/B tested independently.

---

## 2. Conversational Agent Improvements

Claude rewrote `tutor_service.py` to fix subpar tutor output. Key changes:

| Area | Change |
|------|--------|
| `_call_ollama` | Accepts `temperature` and `num_predict` parameters; injects optional `conversation_history`. |
| `_update_summary` | Uses `temperature=0.2`, `num_predict=400` for deterministic compression. |
| `TutorSession` | Added `socratic_attempt_count`, `last_intent`, `last_intent_confidence`, `awaiting_student_response`, `awaiting_response_type`. |
| New skills | `EMOTIONAL_ACKNOWLEDGEMENT`, `PACE_ACKNOWLEDGEMENT`, `PROBE_RESPONSE_HANDLER`, `SOCRATIC_SCAFFOLD`. |
| `_build_profile_context` | Centralizes engagement profile injection on every prompt (was only on first chunk). |
| `_build_conversation_history` | Converts last 3 transcript exchanges into Ollama messages format. |
| `answer_question` | Fully intent-aware: Emotional → `handle_emotional_state()`, Pace → `handle_pace_change()`, Off-Topic > 0.65 → redirect. Only On-Topic goes through Socratic path. |
| New handlers | `handle_emotional_state()` and `handle_pace_change()` were added; `pace_modifier` was previously unused. |

---

## 3. TTS/ASR Benchmark

A separate benchmark project (`tts_asr_benchmark/`) was created to compare TTS and ASR providers.

### TTS Candidates

| Provider | Notes |
|----------|-------|
| Edge TTS (baseline) | Free, but MP3 output requires ffmpeg → WAV conversion; limited emotion control. |
| ElevenLabs Flash v2.5 | `pcm_16000` output (no ffmpeg), ~75ms latency, emotion via `voice_settings`. |
| Cartesia Sonic-3 | Sub-200ms latency, expressive, `pcm_s16le` output, supports emotion tags. |

### ASR Candidates

| Provider | Notes |
|----------|-------|
| Whisper tiny (baseline) | ~10.6% WER, slow on CPU, no streaming. |
| Faster-Whisper | 4× faster, lower memory, same accuracy. |
| Deepgram Nova-3 | <300ms, 5.26–6.84% WER, streaming. |

### Outputs

- `results/<timestamp>/results.json` — per-run structured logs.
- `results/<timestamp>/summary.csv` — provider averages + P95 latency.
- `results/<timestamp>/report.md` — formatted comparison + recommendations.

**Note:** User later required **open-source, zero-cost models** for production. The benchmark was initially API-based; this requirement shifted the design toward local/offline options.

---

## 4. Data Generation Analysis (Key Decisions)

### Confirmed Wins

- **Emotional-State F1 jumped from 0.74 → 0.94** after removing ambiguous templates.
- **On-Topic → Emotional-State leak (54 errors) eliminated.**

### New Problems Identified

| Severity | Problem | Root Cause |
|----------|---------|------------|
| Critical | `generate_real_utterances.py` saved to `real_utterances_test.csv` but `train.py` looked for `real_utterances.csv`. | Path mismatch. |
| Critical | Training set shrank 73% because `--augment-llm` was not run. | Overfitting; val loss divergence. |
| High | Three Off-Topic templates belonged in On-Topic or Pace-Related. | Taxonomy misalignment. |
| High | Pace ↔ Repeat overlap on tokens like "hold on", "wait", "pause". | Shared temporal vocabulary. |
| Medium | Repeat templates with `{topic}` slots fired On-Topic detectors. | CNN saw topic name, not "again" signal. |

### Label Change Decisions

| Decision | Evidence | Action |
|----------|----------|--------|
| Add `Debugging/Code-Sharing` class | Strong evidence | New label for utterances with code snippets, error messages, tracebacks. |
| Relabel curriculum-curiosity templates | Moderate evidence | Move "Are we going to learn about {topic} soon?" etc. from Off-Topic → On-Topic. |
| Add `Social/Procedural` class | Moderate evidence | Conditional: only if Off-Topic recall stays < 75% after Tier 1. |
| Do NOT split On-Topic into sub-intents | Inconclusive | On-Topic recall already 95.67%; splitting risks redistributing errors. |

### Code-Snippet Templates Added to On-Topic

Examples:
- `"why does \`def {topic}():\` give me a SyntaxError?"`
- `"my code keeps throwing IndexError on line 3"`
- `"what does self mean inside a class method"`
- `"TypeError: unsupported operand — what is that"`

---

## 5. RAG Integration

Two wires connected the RAG pipeline to the tutor:

| Wire | Description |
|------|-------------|
| Runtime | `answer_question()` queries ChromaDB using `slide_title` + `current_subtopic` as filter, injects grounded textbook passage into Ollama prompt before Socratic questioning. |
| Training | `generate_real_utterances.py` fetches 3–5 real passages per Python topic and injects them into the Groq generation prompt so utterances reference actual book content. |

Files touched: `rag.py`, `generate_real_utterances.py`, `tutor_service_rag_patch.py`.

---

## 6. Model Architecture Analysis

### Key Corrections

- "Underfitting" was the wrong diagnosis. Val loss oscillated (−50.9% to +32.9%); root cause was **BatchNorm instability at batch_size=16**.
- Recommended fix: **replace BatchNorm with GroupNorm**.
- Error concentration was **52%** (102/196), not 60%.
- Off-Topic fails in three directions: 56 → On-Topic, 21 → Pace, 14 → Repeat, 8 → Emotional.

### Training Run 4 Results

- Test accuracy: **92.22%**
- Off-Topic F1: **87.9%** (best ever)
- Emotional→Pace regression: 6 → 47 errors (template surgery required)
- Train accuracy pattern: 0.8 → 0.4 → 0.2 → 0.1 across three LR phases (expected behavior of early-stopping continuation)

---

## 7. Early Stopping Continuation Plan

When early stopping triggers:

1. Load best checkpoint.
2. Apply temperature calibration via `fit_temperature()`.
3. Halve both learning rates.
4. Reduce label smoothing from 0.1 → 0.05.
5. Reset early-stopping counter.
6. Continue training (no extra epochs; keep `EPOCHS=20`).
7. `MAX_RESTARTS=2`.

**Decision:** Use `WarmupCosineScheduler` on restart (not `get_linear_schedule_with_warmup`). Recreate criterion for label smoothing change (don't mutate internal PyTorch attribute).

---

## 8. AntiGravity Implementation Prompts

Multiple prompts were generated for AntiGravity. The final prompt is structured into **6 parts**:

1. **TinyBert.py** — fix `save_model()` crash, lower Off-Topic threshold 0.70 → 0.60, add ONNX export.
2. **train.py** — 7 changes including scheduler fix, label smoothing fix, train accuracy tracking.
3. **dataset_generator.py** — correlated context generation, programming-specific augmentation, template cleanup.
4. **generate_real_utterances.py** — add Repeat as adjacent class to Off-Topic and On-Topic.
5. **auto_trainer.py** — full restore of session counter, retrain threshold, quality gate, staleness check, model promotion.
6. **test_suite.py** — docstring fix `[0,4] → [0,5]`.

---

## 9. Acceptance Criteria

After retraining, targets are:

| Metric | Target |
|--------|--------|
| Off-Topic recall | ≥ 75% |
| Pace-Related F1 | ≥ 87% |
| Repeat/Clarification F1 | ≥ 90% |
| Emotional-State F1 | ≥ 94% |
| Debugging/Code-Sharing F1 | ≥ 80% |
| Overall accuracy | ≥ 88% |

---

## 10. Pipeline Cleanup (No New Files)

Refactored to keep functionality inside existing files and remove bloat:

| File | What changed |
|------|--------------|
| Removed | `verify_training_ready.py`, `kaggle_post_run_check.py`, `promote_model.py`, `requirements.txt` — redundant; checks belong in existing scripts/endpoint. |
| `TinyBert.py` | Removed dead methods (`train_step`, `evaluate`, `predict_with_confidence`, `export_onnx`, `predict_onnx`); simplified dead Arabic branch in compound splitter. |
| `auto_trainer.py` | Fixed stale metric-key reads (`accuracy`/`f1_score`/`f1_score`); fixed model path mismatch (`best_model.pt`); removed unused logger. |
| `feedback_trainer.py` | Fixed corrected-intent labels being overwritten by `label_id`; removed unused import and no-op rename. |
| `test_suite.py` | Fixed misplaced `__main__` guard that silently skipped classes 8–11; removed unused `json` import. |
| `dataset_generator.py` | Removed dead `generate_session_context`, unused logger, dead Groq LLM augmentation block, and verbose `MOVED`/`REMOVED` comment noise. |
| `train.py` | Removed unused `shutil`/`get_linear_schedule_with_warmup` imports and placeholder f-strings. |
| `generate_real_utterances.py` | Removed placeholder f-strings; added `USE_TF=0` guard for RAG import. |
| Environment | Installed `structlog`; RAG import chain now works, but local ChromaDB Rust panic remains. |

## 11. Open Questions / TODO

- [ ] Verify GroupNorm is actually applied (print `named_modules()` before training).
- [ ] Verify expanded CNN filter sizes are in place.
- [ ] Run end-to-end retraining on GPU with the updated notebook and verify `promotion_ready`.
- [ ] Collect 200+ real session utterances for acceptance gate.
- [ ] Re-evaluate `Social/Procedural` class if Off-Topic recall remains < 75%.
- [ ] Finalize open-source TTS/ASR selection for production.
- [ ] Resolve ChromaDB Rust panic if local RAG-grounded regeneration is needed.

---

## Related Notes

- [[Intent Classifier Production Readiness]]
- [[Intent Feedback Loop Design]]
- [[Intent Feedback Loop Runbook]]
