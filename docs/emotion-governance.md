# Emotion Governance & Validity (Batch 11b)

This document specifies how the platform captures, uses, retains, and constrains
webcam/microphone **emotion** signals. It is written to be cited directly in the
thesis and to answer a committee question on biometric-data ethics.

## Governing principle

Emotion is a **low-confidence, contested, OPTIONAL auxiliary signal**. The entire
learning cycle — slides, tutoring, labs, problem sets, mastery, completion,
grading, certification — works **fully with emotion disabled**. Nothing required
for learning or assessment depends on emotion existing.

Two recognizers feed one fused label: **FER** (facial-expression recognition,
webcam, ~every 25 s) and **SER** (speech-emotion recognition, microphone). They
are fused into a single coarse label (e.g. *engaged / confused / bored*). The
label `uncertain` is treated as **missing data**, never as a competence signal.

---

## 1. Consent (opt-in, off by default)

Emotion capture is **OFF by default** and requires **explicit, informed opt-in**
before the webcam is ever accessed. We do **not** use on-by-default-with-opt-out;
for biometric capture, off-by-default is the defensible posture.

**What the student is shown** (consent modal, before any `getUserMedia`):
- *What is captured*: facial-expression-derived **emotion labels** about every
  25 seconds. **No video or images are stored** — only short-lived labels.
- *What it's used for*: **tutor delivery/adaptation only**.
- *What it never does*: it **never affects grades, scores, mastery, completion,
  or the certificate**.
- *Control*: they can **withdraw any time**, and withdrawal **deletes** their
  retained emotion data.

**Storage & revocation.** Consent is stored server-side per student
(`EmotionConsent`: `granted`, `granted_at`, `withdrawn_at`, `policy_version`),
authoritative in Django. It is revocable; withdrawal stops capture immediately
and going forward.

**With consent absent or withdrawn** (the default state):
- the frontend never calls `getUserMedia` and makes no FER calls;
- the AI fusion endpoint **fails closed** — see below — and returns `uncertain`
  (the existing "missing emotion" fallback) without persisting anything;
- the tutor runs its **non-emotion path**; the full learning cycle is unaffected.

**Server-side enforcement — fail closed.** `/profiler/fuse-emotions` checks the
student's consent (Django, the system of record) *before* fusing or persisting
any emotion. If consent is absent **or the lookup errors/times out**, the signal
is **dropped and treated as missing** — for biometric data, an ambiguous state
means *don't capture*. Successful lookups are cached briefly (60 s) to keep the
capture loop off the HTTP path; failures are **not** cached, so a transient error
fails closed for exactly one call rather than locking a consented student out.
This is defense-in-depth: even a misbehaving client cannot push emotion into the
record without a valid, current consent.

---

## 2. Retention policy

Raw per-event emotion signals are **short-lived**. They exist only as long as
needed for in-session fusion and the session profiler's consolidation, then are
**purged**. Only the **derived, low-confidence profile claim** persists — and
that is **qualitative** (e.g. "appeared disengaged on loops"), source- and
confidence-tagged per Batch 7, never raw biometric history.

Concretely, raw emotion rows in the durable session log are purged:
1. **After consolidation** — the session profiler writes the derived claim, then
   immediately deletes that session's raw emotion rows.
2. **TTL backstop for abandoned sessions** — a retention sweep first
   **consolidates** sessions older than the TTL (so an abandoned session never
   loses its partial profile to the purge), then deletes raw emotion older than
   the TTL. The age-based purge only ever touches **consumed** rows, so it can
   never race the profiler.
3. **On consent withdrawal** — the student's retained raw emotion is deleted
   immediately (Django withdrawal → AI `/emotion/purge`).

The retention window is a **setting**, not a literal: `EMOTION_RAW_RETENTION_TTL`
(seconds; default 24 h).

**One-time backlog purge.** Emotion rows written before student attribution
existed carry an empty `student_id` and cannot be honoured against a withdrawal.
That unattributable biometric backlog is purged once, idempotently, when the log
initializes — we do not keep a record we cannot attribute or delete on request.

---

## 3. Grade-adjacency guarantee

**Emotion never influences anything grade-adjacent**: not `concept_mastery`, not
problem-set/rubric scoring, not lesson completion, not capstone grading, not
certificate/CLO attainment. It may **only** affect tutor delivery and skill
selection, as a low-confidence auxiliary hint.

**How it is enforced (structural, not just convention):**
- **Separate data path.** Emotion flows `FER/SER → fuse → durable session log →
  session profiler → low-confidence, qualitative profile claim + tutor delivery`.
  Grade writers read `concept_mastery` / rubric outcomes — never the session log
  or any `fused_emotion`.
- **Claim-type firewall (Batch 7).** Emotion-derived profile claims are confined
  to *how the student learns* fields (pace, engagement, emotional_tendencies)
  and are **low-confidence**. The single profile writer **rejects competence
  claims**, so an emotion signal can never become a mastery/competence claim.
- **A guard test.** A source-scan test asserts the complete grade-path module
  list contains **no** emotion reference (matching `fused_emotion`,
  `student_emotion`, etc. but not look-alikes like `demotion`). It fails CI if
  anyone later wires emotion into a grade path.
- **A behavioral test.** Grade outputs (mastery, score, completion, certificate)
  are identical whether or not emotion data is present.

---

## 4. Validity statement

FER/SER emotion recognition is a **scientifically contested** signal: inferred
affect from facial expression or voice is noisy, culturally and individually
variable, and does not reliably map to internal emotional or cognitive states.
We therefore treat it as a **low-confidence auxiliary signal only**. It is used
solely to *soften or adapt how the tutor delivers content* (pacing, encouragement,
re-explanation) and is explicitly excluded — structurally and by test — from any
assessment, mastery, or certification decision. `uncertain` is treated as missing
data, capture is opt-in and revocable, raw signals are short-lived, and only a
qualitative, low-confidence summary is retained. In short: emotion may change
*how* the student is taught, never *what they are judged to know*.

---

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `EMOTION_CONSENT_REQUIRED` | `True` | Capture requires explicit opt-in (off by default). |
| `EMOTION_CONSENT_POLICY_VERSION` | dated | Consent-text version recorded on grant (audit). |
| `EMOTION_RAW_RETENTION_TTL` | `86400` (s) | Raw-emotion TTL backstop for abandoned sessions. |

## Endpoints

- `GET /api/progress/emotion-consent/` — consent state (also the AI's consent check, service-key).
- `POST /api/progress/emotion-consent/grant/` — record opt-in.
- `POST /api/progress/emotion-consent/withdraw/` — revoke + purge raw emotion.
- `POST /emotion/purge` (AI, service-key) — delete a student's raw emotion.
- `POST /emotion/retention-sweep` (AI, service-key) — consolidate-then-TTL-purge (cron).
