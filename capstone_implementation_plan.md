# Implementation Plan — Profiler Upgrade, CLOs, Survey & Capstone Projects

> Scope note: you are near submission. Every recommendation below is chosen to **reuse what you already built** (the problem-set HD-eval engine, the LLM-as-judge pattern, the profiler's patch loop, the OllamaClient, your sandboxed execution) rather than build new infrastructure. Where a feature has a "fancy" and a "safe" version, the safe version is marked so you can cut scope without breaking the story.

---

## 0. The big picture: how these five things actually connect

Right now your personalization is **descriptive** (the profile is mostly prose the generators read) and your course has **no terminal artifact** (sessions → labs → problem sets, then nothing).

The five additions form one coherent loop if you build them in the right order:

```
CLOs  ──────────────►  Concept graph  ◄────── Profiler (mastery per concept)
  │                          │                        │
  │                          ▼                        ▼
  │                 Labs & Problem Sets  ──evidence──►  closes the loop
  │                  (target weak concepts)            (mastery updates)
  │                          │
  ▼                          ▼
Capstone rubric  ◄──────  Matchmaking (complementary mastery)
  │
  ▼
Survey (did we hit the CLOs?) + CLO attainment report
```

The single highest-leverage change is **giving the profiler a structured, per-concept mastery layer.** It is the foundation that makes targeted labs/problem-sets *actually* targeted, makes matchmaking *smart*, and makes CLO attainment *measurable*. Build it first; everything else plugs into it.

### Recommended build order (also a good defense narrative)

1. **Profiler → concept-mastery layer** (foundation; biggest impact, lowest external risk)
2. **CLOs** (small; anchors rubrics + survey + attainment)
3. **Survey** (small; mostly reuses your summarization pattern)
4. **Capstone — solo, single-rubric, no GitHub yet** (prove the evaluation pipeline by reusing problem-set HD-eval)
5. **Capstone — GitHub integration** (template repos + free public-repo Actions)
6. **Capstone — team mode + matchmaking** (depends on #1)

If you run out of time, you can stop after step 4 and still have a complete, demonstrable capstone feature. Steps 5–6 are "look good" upgrades, not prerequisites.

---

## 1. Profiler upgrade — a structured concept-mastery layer

### The problem with the current profiler
Your `profile_data` is rich but **unstructured for downstream consumers**. A generator can't reliably answer "what is this student's single weakest concept in this lesson, and what's the evidence?" from prose. So personalization is soft. Matchmaking would have nothing crisp to match on.

### The fix: add a concept-mastery vector (do *not* rip out what you have)
Keep `profile_summary` and the qualitative `profile_data` exactly as they are. **Add one new structured field** that the generators and matchmaker can query deterministically.

**New structure inside `profile_data` (or a new column on `StudentLearningProfile`):**

```jsonc
"concept_mastery": {
  "py.loops.for":        { "score": 0.42, "evidence": 7, "trend": "up",   "last_updated": "...", "linked_mistakes": ["off_by_one"] },
  "py.data.dict":        { "score": 0.81, "evidence": 5, "trend": "flat", "last_updated": "..." },
  "py.func.scope":       { "score": 0.30, "evidence": 3, "trend": "down", "last_updated": "..." }
}
```

- `score` ∈ [0,1]. Update with a simple **exponentially-weighted rule**, not full Bayesian Knowledge Tracing (BKT is overkill for your timeline and harder to defend if questioned):
  `new = old + α * (outcome − old)` where `outcome` ∈ {0,1} per rubric-criterion result, `α ≈ 0.3`. Decay slightly over time so stale strengths fade.
- `evidence` = count of observations (use it to mark "low-confidence" concepts the tutor should probe).
- `linked_mistakes` connects your existing `recurrent_mistakes` to a concept so remediation is targeted.

### Where concepts come from
You need a **concept catalog per course**. Two options:

- **Safe:** derive concepts from your existing lesson/topic hierarchy — each lesson maps to 1–3 concept IDs. Admin-light. Defensible.
- **Fancy:** an AI pass over course content emits a concept list; admin approves (same "AI drafts, admin approves" pattern as CLOs below). Concepts then link to CLOs.

Either way, store a `Concept` table (id, course FK, label, optional parent for a shallow tree) and let lessons/problem-set-questions/rubric-items reference `concept_id`.

### Closing the loop (this is the part that makes it "actually enhance" generation)
1. **Problem-set evaluator** already returns binary per-criterion results. Tag each question/criterion with a `concept_id`. On submit, feed each result into the mastery update rule. *Now the profile is evidence-driven, not vibes-driven.*
2. **Lab generator**: before generating, query the student's **3 weakest concepts relevant to the current lesson** plus their `recurrent_mistakes`. Inject an explicit instruction: "include one remediation cell that targets `{weak_concept}` and avoids/surfaces `{mistake}`." You already do profile-aware personalization — this just makes the input precise instead of prose.
3. **Problem-set generator**: weight question selection toward weak/low-evidence concepts so the assessment both *teaches to the gap* and *gathers evidence* where you're uncertain.
4. **Tutor**: your `DIFFICULTY_TOPIC` / `RECURRENT_MISTAKE` / `SURFACE_UNRESOLVED` skills already exist. Feed them the structured weak-concept list for the current topic instead of having the LLM infer weakness from the summary. More reliable activation, same architecture.

### Implementation steps
1. **Backend**: add `Concept` model + `concept_id` FKs on problem-set questions and (later) rubric items. Add `concept_mastery` to the profile (JSON field is fine; no migration pain).
2. **AI service**: write a tiny `mastery.py` helper (the EW update + decay). Call it from the problem-set submit handler and lab-completion handler.
3. **Profiler service**: when it rewrites the profile, have it (a) leave `concept_mastery` numeric updates to the deterministic helper, (b) only write the *qualitative* fields. **Do not let the LLM hallucinate mastery numbers** — keep scoring deterministic, exactly like your "deterministic scoring + LLM judgment" pattern for problem sets. This is a strong design-consistency point for your defense.
4. **Generators**: change the prompt-builders for lab + problem set to accept a `weak_concepts` list and inject it.
5. **Expose** a `GET /progress/concept-mastery/?course=` endpoint for the frontend (radar chart on the dashboard = cheap, great-looking thesis screenshot) and for the matchmaker.

**Effort:** medium. **Risk:** low (additive). **Payoff:** unlocks 3 other features.

---

## 2. Course Learning Outcomes (CLOs)

### Design
CLOs are small but they anchor the capstone rubric, the survey, and per-student attainment reporting — so do them before the capstone.

**Model (`courses` app):**
```python
class CourseLearningOutcome(models.Model):
    course      = FK(Course, related_name="clos")
    code        = CharField   # "CLO1"
    text        = TextField   # "Implement and trace recursive functions."
    bloom_level = CharField(choices=...)   # optional: Remember..Create
    concepts    = M2M(Concept, blank=True) # links CLO → concepts (enables attainment)
    order       = IntegerField
```

### AI-assisted authoring (the "AI drafts, admin approves" pattern — reuse it everywhere)
- Endpoint: `POST /courses/{id}/clos/suggest` → AI service reads course title + module/lesson outline → returns 4–8 draft CLOs using **action verbs / Bloom's taxonomy**, each pre-linked to likely concepts.
- Frontend (AdminCourseEditor): render drafts as editable rows with "Approve / Edit / Delete / Add". Nothing is saved until the admin confirms. This exact UI pattern is reused for concepts and capstone rubrics, so build one reusable `<AIDraftReviewTable>` component.

### Attainment (the payoff)
Because problem-set questions and capstone rubric items carry `concept_id`, and CLOs link to concepts, you can compute **per-student CLO attainment** = aggregate pass-rate of evidence mapped to that CLO's concepts. One endpoint + one bar chart = a very strong "measurable outcomes" slide.

**Effort:** small. **Risk:** low.

---

## 3. Post-course survey with AI summary

### Models (`courses` or a new `feedback` app)
```python
class SurveyTemplate(models.Model):       # one per course, or a global default
    course = FK(Course, null=True)        # null = global template

class SurveyQuestion(models.Model):
    template = FK(SurveyTemplate, related_name="questions")
    kind     = CharField(choices=["likert", "text", "single", "multi"])
    prompt   = TextField
    clo      = FK(CourseLearningOutcome, null=True)  # optional: ties feedback to CLOs
    order    = IntegerField

class SurveyResponse(models.Model):
    enrollment   = FK(Enrollment)         # ensures one response per student/course
    answers      = JSONField              # {question_id: value}
    submitted_at = DateTimeField

class SurveySummary(models.Model):        # cached AI summary per course
    course        = FK(Course)
    summary_json  = JSONField             # themes, sentiment, quant rollup
    response_count= IntegerField          # so you know when to regenerate
    generated_at  = DateTimeField
```

### Flow
1. **Trigger:** when `Enrollment.progress == 100%` (or on a "Finish course" action), surface the survey once. Gate it so it can't be spammed.
2. **AI summary:** reuse your OllamaClient + the profiler's summarization style. Input = all text answers + Likert distributions for a course. Output = JSON: `recurring_themes` (with frequency), `sentiment`, `top_praise`, `top_complaints`, `per_CLO_perception`. **Aggregate, never quote a single student** (privacy + cleaner output).
3. **Regeneration:** don't summarize on every page load. Cache `SurveySummary`; regenerate when `response_count` grew by ≥ N (e.g. 5) since last run, or on an admin "Refresh" button. Cheap and avoids LLM spam.
4. **Display:** Admin view — themes with counts, a Likert bar chart, sentiment. Tie 1–2 Likert items to "This course achieved {CLO}" so the survey reinforces the CLO story.

**Effort:** small. **Risk:** low.

---

## 4. Capstone projects — the unified design

This is the big one. The trick that makes it tractable before submission: **every mode reduces to "produce a rubric, then judge against it,"** which is *exactly your existing problem-set HD-eval pattern* (LLM-as-judge, binary criteria, deterministic scoring). You are not building a new evaluator — you are feeding a bigger artifact (a repo) into the one you have.

### 4.1 Don't think in 3 project "types" — think in 2 axes

You described admin-predefined, student-defined, and team-based. Those aren't three parallel systems; they're **two independent axes**:

| | **Solo** | **Team** |
|---|---|---|
| **Admin-defined spec** | rubric extracted from uploaded brief | same + per-member contribution checks |
| **Student-proposed spec** | rubric = core ∪ AI-generated idea criteria | same + matchmaking |

One pipeline handles all four. The only moving parts that differ are *where the rubric comes from* and *how many people are on the repo*.

### 4.2 The rubric is the universal currency (solves "fair judging of different ideas")

Define a **`CapstoneRubric` = list of binary criteria**, each with:
```jsonc
{
  "id": "...",
  "text": "Program persists data to a file or DB and reloads it on restart",
  "category": "core" | "stretch",
  "clo_id": "CLO3",
  "concept_id": "py.io.files",
  "weight": 1,
  "min_team_size": 1            // criterion only applies if team >= this
}
```

- **Core criteria** = the unified baseline *every* student's project must meet, regardless of idea. This is precisely what makes different student ideas comparable and fair. The admin defines core criteria **once per course capstone** — or AI drafts them from the course's CLOs + concepts and the admin approves (same pattern again).
- **Project-specific criteria** come from one of two sources:
  - **Admin-predefined project:** admin uploads a brief/spec → AI **extracts** binary criteria from it (your HD-eval extraction idea). Admin approves.
  - **Student-proposed project:** student submits a short proposal (title, description, planned features) → AI **maps the core onto their idea** and adds idea-specific checks → admin (or auto, with a confidence gate) approves. This guarantees a student making a "library system" and one making a "to-do app" are both judged against the same core, plus fair idea-specific extras.

**Final rubric = core ∪ project-specific, filtered by team size (see 4.4).** Judge with your existing binary-check evaluator. Map results → concepts (mastery update) → CLOs (attainment) → grade + XP. The capstone is then *fully consistent* with how you already grade problem sets — a clean defense point.

### 4.3 Matchmaking (where the profiler upgrade pays off)

When a student opts into a team capstone for a course, they enter a **matchmaking queue** for that course's capstone.

**Score for pairing/grouping candidates A and B:**
```
match = w1 * complementarity(A,B)      # A weak where B strong, per concept_mastery
      + w2 * interest_similarity(A,B)  # shared interests/tags from profile
      + w3 * cohort_fit(A,B)           # similar age band / pace / availability
      − w4 * redundancy(A,B)           # both weak in the same critical concept = penalty
```
- `complementarity` is a dot-product-style measure over the **concept-mastery vectors** from §1: reward pairs where one covers the other's gaps. This is the concrete answer to your "user 1 lacks X, user 2 excels at X" example — and it only works because §1 made mastery structured.
- Greedy grouping is fine: form teams up to the cap (default 4) by repeatedly taking the highest-scoring compatible addition. Don't over-engineer with optimal clustering.
- Surface **recommendations**, not forced assignments: show each student their top suggested teammates with a one-line "why" ("complements your weak spots in recursion; shares your interest in games"). They confirm. Better UX and a better demo.

### 4.4 The "not enough teammates" problem — solved by rubric scaling

This is your sharpest worry, and your own instinct (scale requirements by team size) is the right answer. Make it a **first-class rule, not a hack:**

- Every criterion has `min_team_size`. **Effective rubric = criteria where `min_team_size ≤ actual_team_size`.**
- Matchmaking queue has a **timeout / fill window** (e.g., 48h or "when the cohort closes"). When it expires, you form the best team available *right now* — even if that's 1 person.
- Team of 1 → only `min_team_size:1` (core) criteria apply → a fair, completable solo project. **No deadlock, ever, even if they're the only student enrolled.**
- Team of 4 → all stretch criteria apply → more is expected, scored fairly because everyone at that size faces the same bar.
- Scoring is always **passed ÷ applicable**, so a solo student isn't punished for criteria that never applied.

This also gives you a tidy table for the thesis ("requirement scaling by team size") and demos cleanly: show the same project idea with a 1-person vs 4-person rubric.

> Optional refinement for teams: a few criteria can be **per-member** ("each member authored ≥ N meaningful commits to a distinct module"), checked from commit history (§4.6). Keeps freeloading in check and is a nice talking point.

### 4.5 GitHub integration without paying and without storing code

Here is the architecture that satisfies all three constraints (no cost, no codebase storage, works for any project):

**Use one platform-owned GitHub Organization + one GitHub App (both free).**

- A **GitHub App** (not a personal token) is the right primitive. It can: create repos in the org, add collaborators, receive **webhooks** (push, PR), post **commit statuses / checks**, and comment on PRs. Free.
- **Make every capstone repo PUBLIC.** This is the key cost decision: **standard GitHub-hosted Actions runners are free and unlimited on public repositories** (confirmed against current GitHub docs/changelog — the March 2026 pricing change only touches self-hosted runner accounting; public-repo standard runners stay free). So your "I don't want to pay for each user's Actions" problem disappears entirely: the compile/test Action lives in the repo and runs free because the repo is public.
  - *Tradeoff:* public = visible to anyone. For student coursework that's usually fine (it doubles as a portfolio). If you need privacy, the fallback is private repos + **no Actions**, doing the compile/test step yourself inside your existing sandbox at evaluation time. Note both in the thesis; recommend public.
- **No codebase storage on your side.** Your DB stores only: `repo_url`, `template_used`, branch/PR metadata, latest `commit_sha`, and the evaluation JSON. The code lives on GitHub. For evaluation, the App **shallow-clones at submit time** into an ephemeral sandbox (you already sandbox code execution for labs/problem sets), runs the judge, then **discards the clone.** Nothing persistent.

**Starter files → template repository.** For each course capstone, the admin uploads starter files + the `.github/workflows/ci.yml` compile/test workflow into a **template repo**. The App instantiates the template per student/team (`generateFromTemplate`). Every project therefore ships with the free compile-check Action by default — answering "there has to be an Action that checks if it compiles."

**"AI owns the repo and allows/denies each push" → PR-gating (the realistic version).** You can't literally veto a push (a push is already written once it lands on a branch). The correct, equivalent mechanism:
1. Students push to **feature branches**; `main` is **protected**.
2. A push/PR fires a **webhook** to your service.
3. The free **CI Action** runs (does it compile / do smoke tests pass?) and reports a required **status check**.
4. Optionally your AI posts a **review comment** on the PR (style, obvious bugs, "this doesn't address criterion X yet") via the App.
5. Merge to `main` is blocked until the check passes. **Merge = "accepted."** That *is* your "AI allows or denies."

**Final evaluation.** When the team marks the capstone "submitted" (and required PRs are merged), the App clones `main`, runs the **binary-rubric judge** (your problem-set evaluator, pointed at a repo instead of a snippet), maps results → concepts → CLOs → grade, updates profiles, awards XP. Identical mental model to problem-set grading.

**Inviting students.** The App invites each member as a collaborator by GitHub username (collect it on opt-in). They accept once. Because repos are public, a lighter alternative is fork + PR, but collaborator invites are cleaner for monitored team repos.

> Academic freebie worth 10 minutes: apply for **GitHub Education / Campus** benefits for your org — not required (public repos already cover you), but it's free and looks good.

### 4.6 Anti-gaming / monitoring notes (cheap, strong defense points)
- The judge reads the **actual repo**, so "it doesn't really work" is caught by CI + rubric.
- **Commit-history checks**: real iteration vs one giant dump; per-member contribution for teams.
- Keep the rubric's binary criteria **observable** (a behavior you can test or a file that must exist), not subjective — same discipline as your problem-set rubrics.

### 4.7 Capstone — phased implementation steps

**Phase A — Solo, manual rubric, no GitHub (prove the pipeline):**
1. Models: `Capstone` (course FK, mode, team cap, status), `CapstoneRubricItem` (the schema in §4.2), `CapstoneSubmission` (enrollment/team FK, repo_url, commit_sha, results JSON, score).
2. Admin: define core criteria (AI-draft + approve UI you already built for CLOs).
3. Student: submit a **zip or a pasted repo** → run through the existing binary-rubric evaluator → score + concept/CLO mapping + XP. *This validates the whole judge path with zero GitHub risk.*

**Phase B — Rubric sources:**
4. Admin-predefined: upload brief → AI extracts criteria → approve.
5. Student-proposed: proposal form → AI maps core + adds idea criteria → approve gate.

**Phase C — GitHub:**
6. Create the org + GitHub App; store the App credentials in your backend (server-side only).
7. Build template repos (starter + `ci.yml`).
8. Repo provisioning endpoint: instantiate template, set branch protection, invite collaborator(s).
9. Webhook receiver: on PR, record status; optional AI review comment.
10. Submit endpoint: shallow-clone `main` → judge → discard clone → persist results only.

**Phase D — Teams + matchmaking (needs §1):**
11. `Team` model + matchmaking queue per capstone.
12. Matchmaking scorer over concept-mastery vectors (§4.3); recommendation UI.
13. Team-size rubric filtering (§4.4) + per-member contribution checks (§4.6).

**Cut lines if time is short:** ship A + B + (C without the AI PR-comment, just the CI check) and you have a complete, defensible capstone. D is the "wow" layer.

### 4.8 In-platform coding: write, run, commit, and scoped AI help

Goal: the student never leaves your platform. They edit files, run them, click **Commit**, type a message, and see **approved / rejected + reason** — all in your UI, while the code still lives on GitHub and you store none of it.

**The one non-negotiable rule: all Git operations happen server-side.** The GitHub App token never touches the browser (same discipline as your existing `X-Service-Key` internal auth). The frontend talks to your Django/FastAPI backend; the backend talks to GitHub. This is what keeps it secure *and* keeps you from storing code.

#### a) Loading the repo into the editor (no clone, no storage)
On opening the capstone workspace:
1. Backend calls the **Git Trees API** (`GET /repos/{o}/{r}/git/trees/{branch}?recursive=1`) via the App → returns the full file tree.
2. Frontend renders a file tree. When the student opens a file, backend lazily fetches that blob (**Contents API**) and returns its text.
3. Edits live in **frontend state only** until commit. Nothing is persisted server-side. Use **Monaco** (the VS Code editor — gives you the real-IDE look you want; you likely already have an editor in `CodingLab.tsx` you can promote to multi-file).

#### b) The commit pipeline (real commits via the Git Data API)
When the student clicks **Commit** → types a message → frontend POSTs `{ changed_files: [{path, content}], message }` to the backend. The backend creates **one real, atomic, multi-file commit** using the Git Data API:

```
1. GET ref          → current HEAD SHA of the student's branch
2. GET commit/tree  → base tree SHA
3. POST blobs        → one blob per changed file
4. POST tree         → new tree = base tree + changed blobs
5. POST commit       → parent = HEAD SHA, tree = new tree, message, author = student
6. PATCH ref         → move branch to the new commit   ← this is the "push"
```

- **Authorship matters for team grading.** Set the commit `author` to the student's GitHub identity (collect their GitHub username + a no-reply email at opt-in), or add a `Co-authored-by:` trailer. Otherwise every commit looks like it came from the bot, and your per-member contribution checks (§4.6) break.
- Students commit to **their feature branch**, never directly to protected `main` (keeps the §4.5 PR-gate intact).
- Don't use the single-file Contents API for this — it makes one commit per file. The Git Data API sequence above commits everything in one clean commit.

#### c) "Approved or rejected + reason" (this is just the CI result, surfaced)
The `PATCH ref` in step 6 *is* a push, so it triggers the free CI Action (free because the repo is public — §4.5). Then:
1. Backend returns the new commit SHA; frontend shows **"Pushed — checks running…"**
2. Frontend polls `GET /capstone/commit-status/{sha}`; backend reads the **Check Runs API** for that SHA.
3. When CI finishes: **✅ Approved** (checks green) or **❌ Rejected** + reason.
4. **Make the reason readable:** have your `ci.yml` write a concise verdict to the **GitHub Step Summary** (or emit annotations) — e.g. "Build failed: `main.py` line 42, NameError" — and parse that, instead of dumping raw logs. Optionally append the AI review note (below) to the reason.

So "approved/rejected per commit" = continuous CI feedback on each push; the **PR-to-`main` merge** (§4.5) remains the final acceptance gate. Same check infrastructure, two purposes — continuous feedback vs. final gate.

#### d) Running code *before* committing (reuse your sandbox)
Give them two distinct buttons:
- **Run** → backend writes the current (even uncommitted) files into your **existing sandboxed executor** (the one you already use for labs/problem sets, scaled to multi-file), runs the entry command, streams stdout/stderr back. Fast local feedback, nothing committed.
- **Commit** → the pipeline in (b), whose official verdict comes from CI.

MVP cut: if multi-file sandbox execution is too much before submission, skip **Run** and let CI be the only feedback. It's slower but free and zero extra infra.

#### e) AI assist with quota — help without writing their project for them
This is the delicate part, and you already own every piece needed to do it well.

**Quota (anti-spam):** `CapstoneAssistQuota(student/team, period, used, limit)`. Decrement per request, block at zero, reset daily or weekly. Show remaining credits in the UI so it feels fair, not punitive.

**Scope so it can't ghost-write the project (anti-abuse):** make the assistant a **Socratic helper, not a code generator** — reuse your existing `SOCRATIC_GUARD` / `SOCRATIC_SCAFFOLD` tutor skills, which already enforce hint-based guidance. Concretely:
- Make the assistant **rubric-aware**: pass it the capstone's rubric criteria and instruct it *not* to implement any rubric-bearing functionality directly. It may explain the concept, locate the bug, ask leading questions, and review code the student wrote — but it scaffolds *around* graded functionality, not through it.
- **Cap returned code** (e.g. ≤ ~10 lines, illustrative/analogous only — never the exact graded function). Enforce in the prompt *and* with a post-check that trims oversized code blocks.
- **Log every assist call** and feed reliance back into the profile/score, exactly like your **problem-set hint-penalty scoring**: heavy hinting on concept X lowers demonstrated mastery of X (§1) and can lightly affect the capstone score. This both deters abuse and keeps you consistent with how problem sets already work — a clean defense point.

**The framing for your thesis:** the capstone AI assistant is the same Socratic, hint-penalized, rubric-aware philosophy as your problem sets and tutor — not a new "write my code" tool. That consistency is worth stating explicitly.

#### f) Security & limits (cheap, important)
- Token stays server-side; validate file paths (no `../` traversal); cap file size, file count, and commit frequency per student.
- Rate-limit commits (protects against CI spam and accidental loops — public CI is free, but it's good hygiene and avoids GitHub abuse flags).

#### g) Implementation steps
1. Promote your existing editor to a **multi-file Monaco workspace** with a file tree (frontend).
2. Backend endpoints: `GET /capstone/{id}/tree`, `GET /capstone/{id}/file?path=`, `POST /capstone/{id}/commit`, `GET /capstone/commit-status/{sha}`.
3. Implement the **Git Data API commit sequence** (b) in a backend service module using the App installation token.
4. Add the **commit-status poller** reading the Check Runs API; make `ci.yml` emit a readable Step Summary.
5. (Optional) **Run** endpoint reusing the sandbox executor for uncommitted files.
6. **AI assist**: quota model + a rubric-aware Socratic prompt (reuse `SOCRATIC_GUARD`), length-capped output, logged usage feeding mastery/hint-penalty.

---

## 5. Risk & scope summary (near-submission reality check)

| Feature | Effort | External risk | Cut-down version if needed |
|---|---|---|---|
| Profiler concept-mastery (§1) | Medium | Low (additive) | Skip decay; derive concepts from lessons, not AI |
| CLOs (§2) | Small | Low | Manual entry only, skip AI draft |
| Survey (§3) | Small | Low | Likert-only, summarize on-demand button |
| Capstone solo + rubric (§4 A/B) | Medium | Low | Zip upload instead of GitHub |
| Capstone GitHub (§4 C) | Medium | **Medium** (App setup, webhooks) | Public repo + CI check; skip AI PR comments |
| In-platform editor + commit (§4.8 a–c) | Medium | Medium (Git Data API) | Monaco + commit-via-API + poll CI status |
| In-platform Run (§4.8 d) | Medium | Low | Skip it; let CI be the only feedback |
| Scoped AI assist + quota (§4.8 e) | Small | Low | Reuse SOCRATIC_GUARD + a quota counter |
| Capstone teams + matchmaking (§4 D) | Medium-High | Medium | Recommend-only, manual confirm; greedy grouping |

**Three things to get right because they're load-bearing:**
1. **Keep scoring deterministic, LLM for judgment only** — across mastery, problem sets, and capstone. It's your most coherent design principle; don't break it for the capstone.
2. **Make every rubric criterion observable/binary** so the LLM-as-judge stays reliable and fair across different student ideas.
3. **Public GitHub repos** so Actions are free and you store no code — this single choice resolves your two biggest capstone constraints at once.
