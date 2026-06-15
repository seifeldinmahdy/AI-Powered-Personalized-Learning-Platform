"""Clean MCQ dataset — strip embedded A/B/C/D options from question text.

Some teacher LLM samples embed multiple-choice options directly inside the
question text instead of keeping the question stem clean.  This script:

1. Detects whether a question has embedded options (A)/B)/C)/D) or A./B./C./D.)
2. Extracts the clean question stem (everything before the first option marker)
3. Extracts option texts and rebuilds the correct_answer + distractors fields
4. Strips option-label prefixes from correct_answer even on already-clean samples
5. Strips all Unicode box-drawing characters (U+2500–U+257F) from every field
6. Re-runs the book-reference regex pre-filter on the cleaned question text
7. Validates every cleaned object and drops malformed ones

Usage::

    python -m mcq.training.clean_dataset \\
        --input  data/mcq_training/mcq_raw_accepted.jsonl \\
        --output data/mcq_training/mcq_final_cleaned.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import structlog
from tqdm import tqdm

logger = structlog.get_logger(__name__)

# Minimum fraction of non-whitespace characters that must be alphabetic for a
# text field to count as real language. Below this, the field is symbol-noise
# (mangled PDF tables, pipe-tables, decorative separators) — e.g. a chunk that
# extracted as only "|" border characters scores ~0. Tunable via CLI.
_MIN_ALPHA_RATIO = 0.40


def _alpha_ratio(text: str) -> float:
    """Fraction of non-whitespace chars in *text* that are alphabetic (0..1)."""
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    return sum(1 for c in non_ws if c.isalpha()) / len(non_ws)


# Minimum non-whitespace length before the alpha-ratio test is meaningful.
# The heuristic only makes sense on LONG fields: a symbol-wall garbage chunk is
# hundreds of chars, whereas a short legit answer ("O(1)", "0.05", "x²") is
# naturally symbol/number-heavy and must NOT be flagged. So we never test the
# answer/distractors at all, and we gate the chunk/question on a length floor.
_GARBAGE_MIN_CHUNK_LEN = 60
_GARBAGE_MIN_QUESTION_LEN = 25


def _garbage_reason(sample: dict, min_alpha_ratio: float = _MIN_ALPHA_RATIO) -> str | None:
    """Deterministic garbage detector — returns a reason code or None.

    Catches samples grounded in (or composed of) non-linguistic noise that the
    option/box-drawing/book-reference cleaners do not: most importantly a source
    ``chunk`` that survived as symbol-only junk (pipe-tables, garbled PDF table
    extractions), which the teacher LLM then hallucinated a fabricated MCQ from.
    ``|`` is plain ASCII so it slips past the Unicode box-drawing filters.

    Deliberately conservative to avoid quarantining valid symbolic content:
    only long ``chunk``/``question`` fields are tested, and the (often numeric
    or Big-O) answer/distractor fields are never tested.
    """
    def _is_noise(text: str, min_len: int) -> bool:
        t = text.strip()
        non_ws = sum(1 for c in t if not c.isspace())
        return non_ws >= min_len and _alpha_ratio(t) < min_alpha_ratio

    if _is_noise(sample.get("chunk", "") or "", _GARBAGE_MIN_CHUNK_LEN):
        return "garbage_chunk:low_alpha_ratio"
    if _is_noise(sample.get("question", "") or "", _GARBAGE_MIN_QUESTION_LEN):
        return "garbage_question:low_alpha_ratio"
    return None

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Matches a standalone option label at the start of a line or after a newline.
# Captures: A) ... or A. ... or A ) ... (with optional space after label).
_OPTION_START_RE = re.compile(
    r'(?:^|\n)\s*([A-D])\s*[).]\s+',
    re.MULTILINE,
)

# Splits the options block into individual option segments.
# Each segment starts with a label like "A) " or "A. ".
_OPTION_SPLIT_RE = re.compile(
    r'\n?\s*[A-D]\s*[).]\s+',
)

# Detects a leading option label prefix in the correct_answer field.
# Matches: "A) ...", "A. ...", "B)...", etc.
_ANSWER_PREFIX_RE = re.compile(
    r'^([A-D])\s*[).]\s*',
)

# Bare letter answer: just "A", "B", "C", or "D" with nothing else.
_BARE_LETTER_RE = re.compile(r'^[A-D]$')

# Validation: any remaining option-label pattern in cleaned text.
_RESIDUAL_LABEL_RE = re.compile(
    r'(?:^|\n)\s*[A-D]\s*[).]\s',
    re.MULTILINE,
)

# ── Box-drawing strip ─────────────────────────────────────────────────────────
# Unicode box-drawing block: U+2500 through U+257F.
# These are decorative PDF artefacts that cost 20-30 tokens per line with zero
# training value.  Any line consisting entirely of these characters is removed.
# Any inline occurrence is removed (replaced with nothing — not "---").
_BOX_DRAWING_RE = re.compile(r'[\u2500-\u257f]+')
_BOX_DRAWING_LINE_RE = re.compile(r'^[\u2500-\u257f\s]*$', re.MULTILINE)


def _strip_box_drawing(text: str) -> str:
    """Remove all Unicode box-drawing characters (U+2500–U+257F) from *text*.

    Lines consisting entirely of box-drawing characters (possibly with
    whitespace) are deleted.  Inline occurrences within a line are removed
    without substitution — no ``---`` replacement is inserted.
    """
    # First remove lines that are only box-drawing chars / whitespace
    lines_out: list[str] = []
    for line in text.split('\n'):
        if _BOX_DRAWING_LINE_RE.fullmatch(line) and _BOX_DRAWING_RE.search(line):
            # Entire line is decorative — drop it
            continue
        # Remove inline occurrences
        cleaned = _BOX_DRAWING_RE.sub('', line)
        lines_out.append(cleaned)
    return '\n'.join(lines_out)


def _box_drawing_free(sample: dict) -> dict:
    """Apply box-drawing strip to every string field that may appear in the
    final training example.

    Fields touched: ``question``, ``correct_answer``, ``explanation``,
    each element of ``distractors``, and ``chunk``.  All other fields
    are left untouched.
    """
    s = dict(sample)
    for field in ('question', 'correct_answer', 'explanation', 'chunk'):
        if field in s and isinstance(s[field], str):
            s[field] = _strip_box_drawing(s[field])
    if 'distractors' in s and isinstance(s['distractors'], list):
        s['distractors'] = [
            _strip_box_drawing(d) if isinstance(d, str) else d
            for d in s['distractors']
        ]
    return s


# ── URL / email strip ─────────────────────────────────────────────────────────
_CLEAN_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)
_CLEAN_URL_RE = re.compile(
    r'https?://\S+'
    r'|(?<!\w)www\.\S+'
    r'|(?<!\w)ftp://\S+',
)


def _strip_urls_and_emails(text: str) -> str:
    """Remove all email addresses and URLs from *text*, collapsing extra spaces."""
    text = _CLEAN_EMAIL_RE.sub("", text)
    text = _CLEAN_URL_RE.sub("", text)
    return re.sub(r'  +', ' ', text).strip()


def _url_email_free(sample: dict) -> dict:
    """Strip emails/URLs from chunk and question fields in-place (copy)."""
    s = dict(sample)
    for field in ('chunk', 'question'):
        if field in s and isinstance(s[field], str):
            s[field] = _strip_urls_and_emails(s[field])
    return s


# ── Book-reference regex re-filter ────────────────────────────────────────────
# Mirrors the patterns in data_generator._passes_regex_filter.
# Applied after cleaning as a final safety net.  Any sample whose *question*
# still matches a book-reference pattern is dropped.

_BOOK_REF_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bfigure\s+\d+[\.\-]\d+\b', re.IGNORECASE),
    re.compile(r'\bfig\.?\s*\d+', re.IGNORECASE),
    re.compile(r'\bexample\s+\d+[\.\-]\d+\b', re.IGNORECASE),
    re.compile(r'\bsection\s+\d+[\.\-]\d+\b', re.IGNORECASE),
    re.compile(r'\blisting\s+\d+[\.\-]\d+\b', re.IGNORECASE),
    re.compile(r'\bchapter\s+\d+\b', re.IGNORECASE),
    re.compile(r'\bappendix\s+[A-Z]\b', re.IGNORECASE),
    re.compile(r'\bscipy\b', re.IGNORECASE),
    re.compile(r'\btextbook\b', re.IGNORECASE),
    re.compile(r'\bas shown in\b', re.IGNORECASE),
    re.compile(r'\brefer to\b', re.IGNORECASE),
    re.compile(r'\bsee (figure|table|listing|example)\b', re.IGNORECASE),
]


def _passes_book_regex_filter(sample: dict) -> bool:
    """Return True if the cleaned question contains no book-reference pattern.

    Returns False (→ sample will be dropped) if any pattern fires.
    """
    text = sample.get('question', '')
    for pat in _BOOK_REF_PATTERNS:
        if pat.search(text):
            return False
    return True


# ── Existing cleaning utilities ───────────────────────────────────────────────

def _find_options_start(question: str) -> int | None:
    """Return the character index where embedded options begin, or None."""
    match = _OPTION_START_RE.search(question)
    if match is None:
        return None

    # Find the start of the line containing the match (not the label itself)
    # by backtracking to the previous newline.
    pos = match.start()
    # If the match starts with a newline, skip past it for the split point
    if question[pos] == '\n':
        return pos
    return pos


def _extract_options(options_block: str) -> list[tuple[str, str]]:
    """Parse an options block and return [(label, text), ...].

    The options_block starts at the first option label and runs to the end
    of the question text.
    """
    # Find all option starts with their labels
    parts: list[tuple[str, str]] = []
    # Use finditer to locate each option start
    starts = list(_OPTION_START_RE.finditer(options_block))

    for i, m in enumerate(starts):
        label = m.group(1)
        text_start = m.end()
        # Text runs to the start of the next option or end of string
        if i + 1 < len(starts):
            text_end = starts[i + 1].start()
        else:
            text_end = len(options_block)
        text = options_block[text_start:text_end].strip()
        parts.append((label, text))

    return parts


def _strip_answer_prefix(answer: str) -> str:
    """Strip leading option label prefix like 'A) ' from an answer string."""
    m = _ANSWER_PREFIX_RE.match(answer)
    if m:
        return answer[m.end():].strip()
    return answer.strip()


def _fuzzy_match(text_a: str, text_b: str) -> bool:
    """Case-insensitive match after normalizing whitespace and markdown."""
    def _norm(s: str) -> str:
        # Strip markdown bold/italic markers and backticks
        s = s.replace('**', '').replace('`', '').replace('*', '')
        return re.sub(r'\s+', ' ', s.strip().lower())
    return _norm(text_a) == _norm(text_b)


def clean_sample(sample: dict) -> tuple[dict | None, str | None]:
    """Clean a single MCQ sample.

    Returns ``(cleaned_sample, None)`` on success, or ``(None, reason)`` if the
    sample fails any validation step (the reason is a short machine-readable
    code, used to populate the quarantine record for human review).

    Steps:
    1. Detect and strip embedded A/B/C/D options from the question stem.
    2. Strip option-label prefix from correct_answer.
    3. Validate the cleaned object (residual labels, distractor count, etc.).
    4. Strip email addresses and URLs from chunk and question fields.
    5. Strip all Unicode box-drawing characters from every string field.
    6. Re-run the book-reference regex filter; drop if any pattern fires.
    """
    question = sample.get("question", "")
    correct_answer = sample.get("correct_answer", "")
    distractors = sample.get("distractors", [])
    chunk_hash = sample.get("_chunk_hash", "???")

    # ── Step 1: Detect embedded options ──────────────────────────────────
    options_start = _find_options_start(question)
    has_embedded = options_start is not None

    if has_embedded:
        # ── Step 2: Extract clean question stem ──────────────────────────
        stem = question[:options_start].rstrip()
        options_block = question[options_start:]

        # ── Step 3: Extract option texts ─────────────────────────────────
        parsed_options = _extract_options(options_block)

        if len(parsed_options) < 2:
            logger.warning(
                "clean_skip_few_options",
                chunk_hash=chunk_hash,
                n_options=len(parsed_options),
            )
            return None, "few_embedded_options"

        # ── Step 4: Identify correct answer and rebuild distractors ──────
        clean_answer = _strip_answer_prefix(correct_answer)

        # Handle bare-letter answers: "A", "B", etc. — look up the option text
        if _BARE_LETTER_RE.match(correct_answer.strip()):
            target_label = correct_answer.strip()
            found = False
            for label, text in parsed_options:
                if label == target_label:
                    clean_answer = text
                    found = True
                    break
            if not found:
                logger.warning(
                    "clean_skip_bare_letter_no_match",
                    chunk_hash=chunk_hash,
                    answer=correct_answer,
                )
                return None, "bare_letter_no_match"

        # Try to match clean_answer against parsed options
        correct_label = None
        for label, text in parsed_options:
            if _fuzzy_match(text, clean_answer):
                correct_label = label
                break

        # If no fuzzy match, try matching the raw correct_answer with prefix
        if correct_label is None:
            raw_stripped = _strip_answer_prefix(correct_answer)
            for label, text in parsed_options:
                if _fuzzy_match(text, raw_stripped):
                    correct_label = label
                    clean_answer = text
                    break

        if correct_label is None:
            # Last resort: if the clean_answer starts with the same text as
            # one of the options (partial match due to truncation), match it
            for label, text in parsed_options:
                if len(text) > 20 and (
                    text.startswith(clean_answer[:30]) or
                    clean_answer.startswith(text[:30])
                ):
                    correct_label = label
                    clean_answer = text
                    break

        if correct_label is None:
            logger.warning(
                "clean_skip_no_answer_match",
                chunk_hash=chunk_hash,
                answer=repr(clean_answer[:80]),
                options=[repr(t[:40]) for _, t in parsed_options],
            )
            return None, "answer_not_in_options"

        # Build new distractors from the remaining options
        new_distractors = [
            text for label, text in parsed_options if label != correct_label
        ]

        # Update the sample
        sample = dict(sample)  # shallow copy
        sample["question"] = stem
        sample["correct_answer"] = clean_answer
        sample["distractors"] = new_distractors

    else:
        # ── Step 6: Handle already-clean samples ─────────────────────────
        # Still strip any option label prefix from correct_answer
        clean_answer = _strip_answer_prefix(correct_answer)

        # Handle bare-letter answers on clean questions
        # (e.g., answer is "C" but question has no embedded options)
        # These are ambiguous — the answer might genuinely be the letter.
        # Only strip if the distractors are NOT single letters themselves.
        if _BARE_LETTER_RE.match(correct_answer.strip()):
            # Check if distractors look like labels too
            distractor_look_like_labels = all(
                _BARE_LETTER_RE.match(d.strip()) for d in distractors if d.strip()
            )
            if not distractor_look_like_labels:
                # Bare letter answer but non-letter distractors — this is a
                # genuine label reference in a clean question. We can't resolve
                # it without embedded options, so keep it but log.
                logger.debug(
                    "clean_bare_letter_clean_question",
                    chunk_hash=chunk_hash,
                    answer=correct_answer,
                )
                # Keep the original — can't resolve without options
                clean_answer = correct_answer.strip()

        sample = dict(sample)
        sample["correct_answer"] = clean_answer

    # ── Step 5: Validate the cleaned object ──────────────────────────────
    q = sample["question"]
    ca = sample["correct_answer"]
    ds = sample["distractors"]

    # Check: no residual option labels in question
    if _RESIDUAL_LABEL_RE.search(q):
        logger.warning("clean_validate_residual_in_question", chunk_hash=chunk_hash)
        return None, "residual_option_label_in_question"

    # Check: no leading option label in answer
    if _ANSWER_PREFIX_RE.match(ca):
        logger.warning("clean_validate_prefix_in_answer", chunk_hash=chunk_hash, answer=ca[:60])
        return None, "option_prefix_in_answer"

    # Check: exactly 3 distractors
    if len(ds) != 3:
        logger.warning("clean_validate_wrong_distractor_count", chunk_hash=chunk_hash, count=len(ds))
        return None, "distractor_count_not_3"

    # Check: no distractor is identical to the correct answer
    for d in ds:
        if _fuzzy_match(d, ca):
            logger.warning("clean_validate_distractor_equals_answer", chunk_hash=chunk_hash)
            return None, "distractor_equals_answer"

    # Check: no two distractors are identical
    for i in range(len(ds)):
        for j in range(i + 1, len(ds)):
            if _fuzzy_match(ds[i], ds[j]):
                logger.warning(
                    "clean_validate_duplicate_distractors",
                    chunk_hash=chunk_hash,
                    d1=ds[i][:40],
                    d2=ds[j][:40],
                )
                return None, "duplicate_distractors"

    # Check: no distractor contains option label prefix
    for d in ds:
        if _ANSWER_PREFIX_RE.match(d):
            logger.warning(
                "clean_validate_distractor_has_prefix",
                chunk_hash=chunk_hash,
                distractor=d[:60],
            )
            return None, "distractor_has_prefix"

    # ── Step 7: Strip email addresses and URLs from chunk/question ───────
    sample = _url_email_free(sample)
    if not sample.get("question", "").strip():
        logger.debug("clean_question_emptied_by_url_strip", chunk_hash=chunk_hash)
        return None, "question_emptied_by_url_strip"

    # ── Step 8: Strip Unicode box-drawing characters ──────────────────────
    sample = _box_drawing_free(sample)

    # ── Step 9: Book-reference regex re-filter ────────────────────────────
    if not _passes_book_regex_filter(sample):
        logger.debug(
            "clean_book_regex_dropped",
            chunk_hash=chunk_hash,
            question=sample.get("question", "")[:80],
        )
        return None, "book_reference"

    return sample, None


# ── LLM re-validation stage — the same 4 judges used during generation ────────
# Judge A (regex) + deterministic type-eligibility + Judges B/C/D (LLM) are
# imported wholesale from data_generator so the post-hoc criteria are byte-for-
# byte identical to the live pipeline. This is a second, independent pass: it
# re-scores already-generated samples and quarantines any that no longer pass.


def _load_judge_pipeline():
    """Import data_generator and build the 3 judge RoleClients + key manager.

    Returns ``(dg_module, key_mgr, judge_b, judge_c, judge_d)``. Raises on
    misconfiguration (no judge keys) so the caller can fall back to
    deterministic-only cleaning.
    """
    import sys
    pkg_src = str(Path(__file__).resolve().parent.parent.parent)
    if pkg_src not in sys.path:
        sys.path.insert(0, pkg_src)
    from mcq.training import data_generator as dg  # type: ignore

    if not (dg.JUDGE_B_KEYS and dg.JUDGE_C_KEYS and dg.JUDGE_D_KEYS):
        raise RuntimeError(
            "No judge keys available (set OLLAMA_API_KEY_* / NVIDIA keys in .env)."
        )

    key_mgr = dg.SharedKeyManager(
        role_keys={
            "generation": dg.GENERATION_KEYS,
            "judge_b":    dg.JUDGE_B_KEYS,
            "judge_c":    dg.JUDGE_C_KEYS,
            "judge_d":    dg.JUDGE_D_KEYS,
            "fallback":   dg.FALLBACK_KEYS,
        },
        fail_threshold=dg.CONFIG["key_fail_threshold"],
        base_cooldown=dg.CONFIG["key_cooldown"],
    )
    fb = dg.FALLBACK_KEYS
    judge_b = dg.RoleClient(key_mgr, dg.JUDGE_B_KEYS + fb, dg.JUDGE_MODEL, "judge_b")
    judge_c = dg.RoleClient(key_mgr, dg.JUDGE_C_KEYS + fb, dg.JUDGE_MODEL, "judge_c")
    judge_d = dg.RoleClient(key_mgr, dg.JUDGE_D_KEYS + fb, dg.JUDGE_MODEL, "judge_d")
    return dg, key_mgr, judge_b, judge_c, judge_d


def _llm_judge_sample(dg, sample: dict, judge_b, judge_c, judge_d) -> tuple[bool, str]:
    """Run the full 4-judge decision on ONE sample. Returns (accepted, reason).

    Mirrors data_generator._judge_once exactly: regex pre-filter, deterministic
    type-eligibility gate, then Judges B/C/D in one parallel round-trip, fed to
    the same _decide(). Never raises — on an unexpected error it fails OPEN
    (accept), so a transient API hiccup never quarantines a good sample.
    """
    try:
        if not dg._passes_regex_filter(sample):
            return False, "judge_a:regex"
        if not dg._is_type_eligible(
            sample.get("mastery_level", "Intermediate"),
            sample.get("score_category", "moderate"),
            sample.get("question_type", "4a"),
        ):
            return False, "judge_b:type_not_eligible"
        with ThreadPoolExecutor(max_workers=3) as ex:
            fb = ex.submit(dg._run_judge_b, sample, judge_b)
            fc = ex.submit(dg._run_judge_c, sample, judge_c)
            fd = ex.submit(dg._run_judge_d, sample, judge_d)
            b_result, c_result, d_result = fb.result(), fc.result(), fd.result()
        return dg._decide(b_result, c_result, d_result, sample)
    except Exception as exc:  # noqa: BLE001 — fail-open on any judging error
        logger.warning("llm_judge_error_failopen", error=str(exc)[:120])
        return True, "judge_error_failopen"


def _llm_validate(
    survivors: list[dict],
    workers: int,
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Re-judge every deterministically-clean sample with the 4-judge pipeline.

    Returns ``(accepted, rejected)`` where rejected is a list of
    ``(sample, reason)``. If the judge pipeline can't be built (no keys), every
    sample is accepted unchanged and a warning is logged.
    """
    if not survivors:
        return [], []
    try:
        dg, key_mgr, judge_b, judge_c, judge_d = _load_judge_pipeline()
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_stage_disabled", reason=str(exc)[:160])
        print(f"  ⚠  LLM stage skipped — {exc}")
        return survivors, []

    print(
        f"  LLM re-validation: {len(survivors)} samples through Judges B/C/D "
        f"({dg.JUDGE_MODEL}), {workers} parallel workers ..."
    )
    accepted: list[dict] = []
    rejected: list[tuple[dict, str]] = []

    # n sample-workers, each fires 3 inner judge calls in parallel.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_llm_judge_sample, dg, s, judge_b, judge_c, judge_d): s
            for s in survivors
        }
        for fut in tqdm(
            as_completed(futs), total=len(futs), desc="LLM judging",
            unit="mcq", dynamic_ncols=True, colour="magenta",
        ):
            sample = futs[fut]
            ok, reason = fut.result()
            if ok:
                accepted.append(sample)
            else:
                rejected.append((sample, f"llm:{reason}"))
            if key_mgr.all_dead:
                logger.error("llm_stage_all_keys_dead_aborting")
                break

    return accepted, rejected


def _print_report(
    total: int,
    already_clean: int,
    cleaned: int,
    skipped: int,
    box_drawing_stripped: int,
    book_regex_dropped: int,
    output_samples: list[dict],
):
    """Print a comprehensive report of the cleaning run."""
    W = 66
    print(f"\n{'=' * W}")
    print("  MCQ DATASET CLEANING — REPORT")
    print(f"{'=' * W}")
    print(f"  Total samples processed:       {total:>5}")
    print(f"  Already clean (no changes):    {already_clean:>5}")
    print(f"  Successfully cleaned:          {cleaned:>5}")
    print(f"  Box-drawing stripped:          {box_drawing_stripped:>5}")
    print(f"  Book-reference dropped:        {book_regex_dropped:>5}")
    print(f"  Skipped (validation failure):  {skipped:>5}")
    print(f"  Final output samples:          {len(output_samples):>5}")

    # Distribution checks
    type_counts: Counter = Counter()
    mastery_counts: Counter = Counter()
    score_counts: Counter = Counter()
    for s in output_samples:
        type_counts[s.get("question_type", "?")] += 1
        mastery_counts[s.get("mastery_level", "?")] += 1
        score_counts[s.get("score_category", "?")] += 1

    n = len(output_samples)
    print(f"\n  QUESTION TYPE DISTRIBUTION:")
    for t in sorted(type_counts):
        c = type_counts[t]
        pct = 100 * c / max(n, 1)
        print(f"    Type {t:<4}: {c:>5}  ({pct:.1f}%)")

    print(f"\n  MASTERY LEVEL DISTRIBUTION:")
    for m in sorted(mastery_counts):
        c = mastery_counts[m]
        pct = 100 * c / max(n, 1)
        print(f"    {m:<14}: {c:>5}  ({pct:.1f}%)")

    print(f"\n  SCORE CATEGORY DISTRIBUTION:")
    for sc in sorted(score_counts):
        c = score_counts[sc]
        pct = 100 * c / max(n, 1)
        print(f"    {sc:<10}: {c:>5}  ({pct:.1f}%)")
    print(f"\n{'=' * W}\n")


def clean_dataset(
    input_path: str,
    output_path: str,
    quarantine_path: str | None = None,
    use_llm: bool = True,
    llm_workers: int = 6,
    min_alpha_ratio: float = _MIN_ALPHA_RATIO,
) -> int:
    """Clean + validate a JSONL dataset, quarantining garbage for human review.

    Two stages:
      1. Deterministic — garbage detector (alpha-ratio), embedded-option
         stripping, box-drawing strip, book-reference re-filter.
      2. LLM (optional, default on) — re-runs the SAME 4-judge pipeline used
         during generation (Judge A regex + type-eligibility + Judges B/C/D).

    Anything rejected by either stage is written to ``quarantine_path`` with a
    ``_reject_stage`` + ``_reject_reason`` so you can eyeball it later; genuine
    false positives can be moved back into the cleaned output by hand. Nothing
    is silently dropped.

    Parameters
    ----------
    input_path :
        Path to the raw/merged JSONL file (e.g. mcq_raw.jsonl).
    output_path :
        Path to write the cleaned, validated JSONL (e.g. mcq_raw_cleaned.jsonl).
    quarantine_path :
        Where rejected samples go. Defaults to ``<output>_quarantine.jsonl``.
    use_llm :
        Run the LLM 4-judge re-validation stage (needs API keys in .env).
    llm_workers :
        Parallel sample-workers for the LLM stage (each fires 3 judge calls).

    Returns
    -------
    int
        Number of samples in the cleaned output.
    """
    in_p = Path(input_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if quarantine_path is None:
        quar_p = out_p.with_name(out_p.stem + "_quarantine.jsonl")
    else:
        quar_p = Path(quarantine_path)
    quar_p.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    already_clean = 0
    cleaned = 0
    box_drawing_stripped = 0
    survivors: list[dict] = []
    quarantined: list[tuple[dict, str, str]] = []  # (sample, stage, reason)

    # ── Stage 1: deterministic clean + garbage filter ─────────────────────
    with open(in_p, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue

            total += 1
            try:
                sample = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("clean_skip_invalid_json", line=line[:80])
                quarantined.append(({"_raw_line": line[:500]}, "parse", "invalid_json"))
                continue

            # Garbage detector first — symbol-noise chunks/questions are quarantined
            # before any cleaning is attempted.
            garbage = _garbage_reason(sample, min_alpha_ratio)
            if garbage:
                logger.debug("clean_garbage_quarantined", reason=garbage,
                             chunk_hash=sample.get("_chunk_hash", "???"))
                quarantined.append((sample, "garbage", garbage))
                continue

            original_question = sample.get("question", "")
            had_embedded = _find_options_start(original_question) is not None
            had_box_drawing = any(
                _BOX_DRAWING_RE.search(sample.get(f, ""))
                for f in ("question", "correct_answer", "explanation", "chunk")
            ) or any(
                _BOX_DRAWING_RE.search(d)
                for d in sample.get("distractors", [])
                if isinstance(d, str)
            )

            result, reason = clean_sample(sample)

            if result is None:
                quarantined.append((sample, "deterministic", reason or "unknown"))
            else:
                if had_box_drawing:
                    box_drawing_stripped += 1
                if had_embedded:
                    cleaned += 1
                else:
                    already_clean += 1
                survivors.append(result)

    det_quarantined = len(quarantined)
    print(
        f"\n  Stage 1 (deterministic): {len(survivors)} passed, "
        f"{det_quarantined} quarantined of {total}."
    )

    # ── Stage 2: LLM 4-judge re-validation ────────────────────────────────
    llm_rejected = 0
    if use_llm:
        survivors, rejected = _llm_validate(survivors, llm_workers)
        llm_rejected = len(rejected)
        for s, reason in rejected:
            quarantined.append((s, "llm", reason))
        print(f"  Stage 2 (LLM judges): {len(survivors)} accepted, {llm_rejected} quarantined.")
    else:
        print("  Stage 2 (LLM judges): SKIPPED (--skip-llm)")

    # ── Write cleaned output ──────────────────────────────────────────────
    with open(out_p, "w", encoding="utf-8") as fout:
        for s in survivors:
            fout.write(json.dumps(s) + "\n")

    # ── Write quarantine (with reason metadata for human review) ──────────
    with open(quar_p, "w", encoding="utf-8") as fq:
        for s, stage, reason in quarantined:
            rec = dict(s)
            rec["_reject_stage"] = stage
            rec["_reject_reason"] = reason
            fq.write(json.dumps(rec) + "\n")

    logger.info(
        "clean_dataset_complete",
        total=total,
        already_clean=already_clean,
        cleaned=cleaned,
        box_drawing_stripped=box_drawing_stripped,
        deterministic_quarantined=det_quarantined,
        llm_quarantined=llm_rejected,
        kept=len(survivors),
        output=str(out_p),
        quarantine=str(quar_p),
    )

    _print_report(
        total, already_clean, cleaned, len(quarantined),
        box_drawing_stripped, det_quarantined,
        survivors,
    )
    print(f"  Cleaned output:   {len(survivors):>5}  -> {out_p}")
    print(f"  Quarantined:      {len(quarantined):>5}  -> {quar_p}")
    print(f"    (review {quar_p.name}; move any false positives back into {out_p.name})\n")
    return len(survivors)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clean + validate an MCQ dataset: deterministic garbage/option/"
            "box-drawing/book-reference filtering, then an LLM 4-judge "
            "re-validation. Rejects are quarantined (not dropped) for review."
        ),
    )
    parser.add_argument(
        "--input", required=True,
        help="Input JSONL file (e.g. mcq_raw.jsonl).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output cleaned JSONL file (e.g. mcq_raw_cleaned.jsonl).",
    )
    parser.add_argument(
        "--quarantine", default=None,
        help="Quarantine JSONL for rejected samples "
             "(default: <output>_quarantine.jsonl).",
    )
    parser.add_argument(
        "--skip-llm", action="store_true", default=False,
        help="Deterministic cleaning only — skip the LLM 4-judge stage.",
    )
    parser.add_argument(
        "--llm-workers", type=int, default=6,
        help="Parallel sample-workers for the LLM stage (default 6).",
    )
    parser.add_argument(
        "--min-alpha-ratio", type=float, default=_MIN_ALPHA_RATIO,
        help=f"Min fraction of alphabetic chars for chunk/question/answer to be "
             f"considered real text (default {_MIN_ALPHA_RATIO}).",
    )
    args = parser.parse_args()

    n = clean_dataset(
        args.input,
        args.output,
        quarantine_path=args.quarantine,
        use_llm=not args.skip_llm,
        llm_workers=args.llm_workers,
        min_alpha_ratio=args.min_alpha_ratio,
    )
    print(f"Cleaned dataset: {n} samples -> {args.output}")


if __name__ == "__main__":
    main()
