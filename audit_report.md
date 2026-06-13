# Pre-Testing Audit Report — Batches 1–3

> **Methodology**: Every check traces actual data flow file-by-file with line citations. Claims without code citations are not accepted.

---

## CHECK 1 — Mastery Loop (Problem-Set → EMA → Profile)

**Verdict: `PASS` with one `FRAGILE` note**

### Trace

1. **Problem-set generation attaches `concept_id` to rubric criteria.**
   - [problem_set.py:76](file:///d:/Grad%20proj%20(my%20module)/ai_service/schemas/problem_set.py#L76): `concept_id: Optional[str] = None`
   - [problem_set_service.py:266](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/problem_set_service.py#L266): The system prompt tells the LLM `concept_id: (optional) set to the concept ID string from AVAILABLE CONCEPTS if one matches`
   - [problem_set_service.py:379–406](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/problem_set_service.py#L379-L406): Fetches course concepts via `fetch_course_concepts()` and passes `AVAILABLE CONCEPTS FOR TAGGING` block into the prompt

2. **Submit endpoint calls `update_concept_mastery_from_eval` fire-and-forget.**
   - [problem_set router:71–80](file:///d:/Grad%20proj%20(my%20module)/ai_service/routers/problem_set.py#L71-L80):
     ```python
     asyncio.create_task(
         update_concept_mastery_from_eval(
             student_id=request.student_id,
             evaluated_rubric=[c.model_dump() for c in result.evaluated_rubric],
         )
     )
     ```

3. **`mastery.py` updates are deterministic — LLM never touches scores.**
   - [mastery.py:29–33](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/mastery.py#L29-L33): Pure EMA: `old + alpha * (outcome - old)`
   - [mastery.py:95–141](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/mastery.py#L95-L141): `compute_mastery_updates()` aggregates binary check outcomes per concept, then calls `build_entry()`. All pure.
   - [mastery.py:204–222](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/mastery.py#L204-L222): `update_concept_mastery_from_eval()` fetches → computes → PATCHes

4. **Django PATCH endpoint correctly merges (not overwrites).**
   - [progress/views.py:194–200](file:///d:/Grad%20proj%20(my%20module)/backend/apps/progress/views.py#L194-L200):
     ```python
     incoming_cm = request.data.get("concept_mastery")
     if incoming_cm and isinstance(incoming_cm, dict):
         existing_cm = profile.concept_mastery or {}
         existing_cm.update(incoming_cm)
         profile.concept_mastery = existing_cm
         profile.save(update_fields=["concept_mastery"])
     ```

5. **Auth for internal calls works.**
   - [authentication.py:28–67](file:///d:/Grad%20proj%20(my%20module)/backend/apps/core/authentication.py#L28-L67): `InternalServiceAuthentication` validates `X-Service-Key` + `X-Student-ID`
   - [settings.py:121–124](file:///d:/Grad%20proj%20(my%20module)/backend/config/settings.py#L121-L124): Registered in `DEFAULT_AUTHENTICATION_CLASSES`

6. **Profiler does NOT overwrite `concept_mastery`.**
   - grep for `concept_mastery` in `profiler_service.py` returns **zero results**. ✅
   - [progress/models.py:157–158](file:///d:/Grad%20proj%20(my%20module)/backend/apps/progress/models.py#L157-L158): Comment: `"Concept-mastery is a SEPARATE field — the profiler LLM never writes here."`

### FRAGILE

> **`concept_id` tagging depends on the LLM obeying the prompt.** If the LLM omits `concept_id` from rubric criteria, the mastery loop silently no-ops ([mastery.py:113–115](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/mastery.py#L113-L115): `if not concept_id: continue`). There's no post-generation validation that at least N criteria got a concept_id. This is acceptable for now but means mastery data will be sparse if the model is lazy.

---

## CHECK 2 — Capstone Evaluation Scoring Invariant

**Verdict: `PASS`**

### Trace

1. **AI service returns binary pass/fail only — never a numeric score.**
   - [capstone_rubric_service.py:270–352](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L270-L352): System prompt: `"Do NOT compute totals, percentages, scores, or grades."` LLM response is `{results: {item_id: {passed: bool, evidence: str}}, feedback: str}`.
   - [capstone schemas:66–73](file:///d:/Grad%20proj%20(my%20module)/ai_service/schemas/capstone.py#L66-L73): `RubricItemResult` has only `passed: bool` and `evidence: str`. `CapstoneEvalResult` has no score field.

2. **Score computed deterministically in Django.**
   - [capstone/views.py:59–72](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L59-L72):
     ```python
     def _compute_score(rubric_items, results):
         total_weight = sum(item.weight for item in rubric_items)
         earned = sum(item.weight for item in rubric_items
                      if results.get(str(item.id), {}).get("passed", False))
         return round(earned / total_weight * 100, 2)
     ```
   - [capstone/views.py:509–510](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L509-L510): `score = _compute_score(rubric_items, results)` — called after normalizing AI results

3. **Capstone mastery update is also deterministic.**
   - [capstone/views.py:92–134](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L92-L134): `_update_concept_mastery_sync()` uses EMA directly on `item.concept_id` FK, no LLM involved.

---

## CHECK 3 — GitHub Provisioning & Branch Safety

**Verdict: `PASS`**

### Trace

1. **Token never leaves the server.**
   - [github_app.py:103–109](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/github_app.py#L103-L109): `github_headers()` adds `Authorization: Bearer <token>` to outgoing requests only. Return value to client is `{repo_url, repo_name, branch}` only ([views.py:652](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L652)).

2. **Repo is public (free CI on GitHub Actions).**
   - [views.py:593](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L593): `"private": False` in template generate
   - [views.py:600](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L600): `"private": False` in blank create

3. **Main branch is protected; students work on `work` branch.**
   - [views.py:612–622](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L612-L622): Branch protection on `main` with required status check `ci`
   - [views.py:633–638](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L633-L638): `branch = "work"`; `ensure_branch()` called

4. **`ensure_branch` and `commit` both guard against main.**
   - [capstone_git.py:97–98](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L97-L98): `if branch == "main": raise GitError("Refusing to use 'main' as a feature branch.")`
   - [capstone_git.py:198–199](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L198-L199): Same guard on commit

5. **Path validation prevents traversal.**
   - [capstone_git.py:56–63](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L56-L63): Rejects `..`, absolute paths, backslashes, and chars outside `[A-Za-z0-9._\-/]`

---

## CHECK 4 — Webhook HMAC Signature Verification

**Verdict: `BROKEN`** 🔴

### Evidence

[views.py:674](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L674):
```python
expected = "sha256=" + hmac.new(
    secret.encode(), body, hashlib.sha256
).hexdigest()
```

**Bug**: `hmac.new()` exists in Python stdlib, **but the webhook view has `permission_classes=[]`** at [line 660](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L660). Combined with the global `DEFAULT_PERMISSION_CLASSES: [IsAuthenticated]`, an empty list means **no permissions at all** — the endpoint is fully public. This is correct and intentional for a webhook.

**However**, the webhook only handles `check_suite` events ([line 686](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L686)). The `push` event is silently ignored — there's no handler for it. This means when a student pushes to the `work` branch, the webhook receives the push event but does nothing with it. The `check_suite` handler only fires on CI completion.

**Actual real bug**: The `submit_from_repo` path at [views.py:705–748](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L705-L748) records the submission intent but **never triggers AI evaluation**. The only evaluation path is:
1. `submit_archive` (direct code bundle) → calls `_call_ai_evaluate` synchronously ✅
2. `submit_from_repo` → records `status="evaluating"` → waits for `github_webhook` `check_suite` to flip status → **but CI check_suite only updates status, it never calls `_call_ai_evaluate`** ❌

> **Result**: The `submit_from_repo` + webhook pipeline records CI pass/fail but **never runs the AI rubric evaluation**. The `results` dict stays empty, `score` stays `None`, and `feedback` stays empty. Only `submit_archive` actually evaluates.

### Priority: **HIGH** — The entire repo-based submission pipeline is non-functional for grading.

---

## CHECK 5 — CI Verdict Pipeline (commit → check runs → verdict)

**Verdict: `PASS` (read path only)**

### Trace

1. **Commit pipeline is correct.**
   - [capstone_git.py:183–283](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L183-L283): Atomic blobs → tree → commit → fast-forward ref update with 3 retries on stale ref.

2. **Check runs read is correct.**
   - [capstone_git.py:290–327](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L290-L327): Reads `check_runs` for SHA, aggregates completion status + conclusion.

3. **`commit_status` view works.**
   - [views.py:888–914](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L888-L914): Reads submission by SHA or capstone fallback.

> **Note**: CI verdict is display-only. It never triggers evaluation (see CHECK 4).

---

## CHECK 6 — AI Assist (Socratic guard, code cap, quota)

**Verdict: `PASS`**

### Trace

1. **Socratic guard reused from tutor.**
   - [capstone_rubric_service.py:367–375](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L367-L375): Tries to import `TUTOR_SKILLS.SOCRATIC_GUARD` / `SOCRATIC_SCAFFOLD`; falls back to built-in `_SOCRATIC_FALLBACK`.

2. **System prompt explicitly forbids implementing graded features.**
   - [capstone_rubric_service.py:408–421](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L408-L421): Lists all rubric criteria as "GRADED — do not implement any of them."

3. **Code block cap enforced post-LLM.**
   - [capstone_rubric_service.py:378–398](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L378-L398): `_cap_code_blocks()` regex-trims any fenced code block to `ASSIST_MAX_CODE_LINES=10` lines.
   - [capstone_rubric_service.py:444](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L444): Applied to every response.

4. **Quota checked and decremented in Django.**
   - [views.py:1033–1038](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L1033-L1038): `if quota.remaining <= 0` → 429
   - [views.py:1069–1070](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L1069-L1070): `quota.used += 1; quota.save()`

5. **Mastery penalty applied per assist call.**
   - [views.py:975–1003](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L975-L1003): `_apply_assist_mastery_penalty()` uses gentle EMA (`ALPHA=0.1`) toward outcome `0.3`
   - [views.py:1080–1084](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L1080-L1084): Fired in background thread

6. **Uses `client.chat()` (not `chat_json()`) — correct since assist returns prose.**
   - [capstone_rubric_service.py:433](file:///d:/Grad%20proj%20(my%20module)/ai_service/services/capstone_rubric_service.py#L433): `raw = client.chat(messages=..., temperature=0.4)`

---

## CHECK 7 — Team Matchmaking

**Verdict: `PASS`**

### Trace

1. **Scoring is pure math, no LLM.**
   - [matchmaking.py:80–136](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/matchmaking.py#L80-L136): `pair_score()` = weighted blend of complementarity, interest similarity, cohort fit, minus redundancy.

2. **Queue never deadlocks.**
   - [matchmaking.py:221–276](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/matchmaking.py#L221-L276): `process_queue()` checks for `any_expired` fill windows or admin `force=True`. If expired, forms teams from whoever is waiting, even a team of one.
   - [matchmaking.py:257–258](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/matchmaking.py#L257-L258): Without forcing, drops under-sized trailing groups so students keep waiting.

3. **Rubric scales with team size.**
   - [views.py:54–56](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/views.py#L54-L56): `_get_effective_rubric(capstone, team_size)` filters by `min_team_size__lte=team_size`.

4. **Contribution summary from commit authorship.**
   - [capstone_git.py:359–382](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/capstone_git.py#L359-L382): `summarize_contributions()` counts commits per member login/name.

---

## CHECK 8 — Survey Pipeline (Feedback App)

**Verdict: `PASS`**

### Trace

1. **Survey gated on 100% course completion.**
   - [feedback/views.py:41](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/views.py#L41): `if float(enrollment.progress_percentage) < 100: return Response({"pending": False})`

2. **One response per enrollment enforced by DB.**
   - [feedback/models.py:53](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/models.py#L53): `enrollment = models.OneToOneField("courses.Enrollment", ...)`
   - [feedback/views.py:109–110](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/views.py#L109-L110): `except IntegrityError: return Response(..., status=409)`

3. **Auto-refresh every 5 new responses.**
   - [feedback/views.py:118–125](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/views.py#L118-L125): `if total - summary.response_count >= 5: threading.Thread(target=_refresh_summary_sync, ...).start()`

4. **AI summarization endpoint exists.**
   - [surveys router:16](file:///d:/Grad%20proj%20(my%20module)/ai_service/routers/surveys.py#L16): `POST /surveys/summarize`
   - [feedback/views.py:211–222](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/views.py#L211-L222): Calls `AI_SERVICE_URL/surveys/summarize` with `text_answers`, `likert_distributions`, `clo_labels`

5. **CLO labels included in the summary request.**
   - [feedback/views.py:206–208](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/views.py#L206-L208): Fetches `CourseLearningOutcome` texts and passes as `clo_labels`

---

## CHECK 9 — CLO Integration

**Verdict: `PASS`**

### Trace

1. **CLO model exists with concept M2M.**
   - [courses/models.py:258](file:///d:/Grad%20proj%20(my%20module)/backend/apps/courses/models.py#L258): `class CourseLearningOutcome(models.Model)`
   - Capstone rubric items have FK to CLO: [capstone/models.py:59–65](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/models.py#L59-L65)
   - Survey questions have FK to CLO: [feedback/models.py:35–38](file:///d:/Grad%20proj%20(my%20module)/backend/apps/feedback/models.py#L35-L38)

2. **AI CLO suggestion endpoint exists.**
   - [clos router:16](file:///d:/Grad%20proj%20(my%20module)/ai_service/routers/clos.py#L16): `POST /clos/suggest`

---

## CHECK 10 — Frontend Wiring

**Verdict: `PASS` with one `FRAGILE` note**

### Trace

1. **Capstone API client matches backend URLs.**
   - [capstone.ts:75–408](file:///d:/Grad%20proj%20(my%20module)/frontend/src/services/capstone.ts#L75-L408): All endpoints use `/capstone/capstones/<id>/...` pattern matching [urls.py](file:///d:/Grad%20proj%20(my%20module)/backend/apps/capstone/urls.py)

2. **ConceptMasteryChart renders correctly.**
   - [ConceptMasteryChart.tsx:14–71](file:///d:/Grad%20proj%20(my%20module)/frontend/src/components/ConceptMasteryChart.tsx#L14-L71): Renders bar chart with trend-colored bars and percentage tooltip.

3. **Pages exist for student capstone flow.**
   - `CapstonePage.tsx` and `CapstoneWorkspace.tsx` exist in `pages/student/`
   - `AdminCapstoneEditor.tsx` exists in `pages/admin/`

### FRAGILE

> **Frontend capstone routes not found in `routes.tsx`.** Grep for "Capstone" in routes.tsx returned zero results. The pages exist but may not be wired into the React Router. This needs manual verification — if the routes are missing, the pages are unreachable.

---

## BONUS — Additional Issues Found

### ISSUE A: Duplicate Router Registration
**Verdict: `BROKEN`** 🟡

[main.py:112](file:///d:/Grad%20proj%20(my%20module)/ai_service/main.py#L112) and [main.py:120](file:///d:/Grad%20proj%20(my%20module)/ai_service/main.py#L120):
```python
app.include_router(pathway_router)   # line 112
...
app.include_router(pathway_router)   # line 120 — DUPLICATE
```
FastAPI will register all routes from `pathway_router` **twice**, doubling them in `/docs`. This causes ambiguous routing and potential issues.

**Priority**: LOW — functional but pollutes the API.

### ISSUE B: `submit_from_repo` Never Evaluates (restated from CHECK 4)
**Verdict: `BROKEN`** 🔴

The GitHub-based submission flow records intent and CI status, but the binary rubric evaluation is **never triggered** for repo-based submissions. The webhook flips `status` from `evaluating` to `completed`/`failed` based on CI conclusion, but `_call_ai_evaluate()` is only called in `submit_archive()`.

**Priority**: **CRITICAL** — Repo-based submission is the primary flow for Batch 3's in-platform IDE.

---

## Priority-Ranked Fix List

| # | Priority | Check | Issue | Fix |
|---|----------|-------|-------|-----|
| 1 | 🔴 **CRITICAL** | 4 | `submit_from_repo` pipeline never calls AI evaluation | Add AI evaluation call when `check_suite` webhook fires with `conclusion=success`, or add a separate "evaluate now" endpoint |
| 2 | 🟡 **LOW** | Bonus A | `pathway_router` registered twice in `main.py` | Remove duplicate `app.include_router(pathway_router)` at line 120 |
| 3 | 🟡 **LOW** | 10 | Capstone pages may not be wired into React Router | Verify `routes.tsx` includes capstone routes; add them if missing |
| 4 | ⚪ **INFO** | 1 | LLM may omit `concept_id` from rubric criteria → mastery no-ops silently | Add post-generation validation/warning if zero criteria have concept_id |
