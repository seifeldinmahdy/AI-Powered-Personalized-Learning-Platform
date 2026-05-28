"""Question Type Taxonomy — single source of truth for the MCQ classification system.

Every other module in the mcq package imports from here.  Nothing is duplicated.
The QUESTION_TYPE_TAXONOMY constant is injected verbatim into LLM prompts and
T5 model inputs to ensure deterministic type selection.
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════════════════════════
# QUESTION TYPE TAXONOMY
# ═══════════════════════════════════════════════════════════════════════════════
#
# Injected into every QG and DG prompt as-is.  Write with the precision of a
# published taxonomy — an LLM or fine-tuned T5 model reading this constant as
# part of a prompt must be able to reliably distinguish all eight types with
# no additional context.
# ═══════════════════════════════════════════════════════════════════════════════

QUESTION_TYPE_TAXONOMY: str = """\
────────────────────────────────────────────────────────────────────────
QUESTION TYPE TAXONOMY — 8 Types
────────────────────────────────────────────────────────────────────────

Type 1 — Method/API Knowledge
  Cognitive skill: Recall of exact syntax, method names, parameter orders,
    and return types for language-level APIs and library functions.
  Trigger: The source chunk contains method calls, function signatures,
    API reference documentation, or library usage examples.
  Signal words: method name patterns with parentheses (e.g. `.append()`,
    `len()`, `str.split()`), parameter syntax (`def foo(x, y=0)`),
    return value descriptions ("returns a list of …"), import statements.
  Example:
    Q: Which method removes and returns the last element of a Python list?
    A: .pop()

Type 2 — Code Output
  Cognitive skill: Mental execution — the student must trace through code
    in their head and predict the exact output or final state.
  Trigger: The source chunk contains a runnable code snippet with a
    deterministic, non-trivial output that can be predicted by reading.
  Signal words: `print()` statements, explicit `return` values, loop
    iteration patterns, sequential variable assignments, counter
    increments, string concatenation in loops, list comprehension results.
  Example:
    Q: What is printed by this code?
       x = [1, 2, 3]
       x.append(x.pop(0))
       print(x)
    A: [2, 3, 1]

Type 3 — Code Completion
  Cognitive skill: Constructive syntax knowledge — the student fills in
    a missing piece of code that makes a program correct.
  Trigger: The source chunk describes how to accomplish a task in code
    or contains a code pattern with a step that can be blanked out.
  Signal words: "to do X in Python, use …", "the syntax for …",
    "use the following to …", incomplete code descriptions, "fill in
    the blank", partially written functions.
  Example:
    Q: Complete the function so it returns the square of n:
       def square(n):
           ___________
    A: return n ** 2

Type 4a — Definition/Recall
  Cognitive skill: Basic factual understanding — the student identifies
    what a concept *is* and can distinguish it from unrelated concepts.
  Trigger: The source chunk defines or introduces a single concept.
  Signal words: "is a", "is defined as", "refers to", "consists of",
    "is used for", single-concept explanation, glossary entries,
    introductory "what is …" paragraphs.
  Example:
    Q: What is a Python dictionary?
    A: An unordered collection of key-value pairs accessed by unique keys.

Type 4b — Distinction
  Cognitive skill: Comparative understanding — the student articulates
    how two related but different concepts relate and where they diverge.
  Trigger: The source chunk contrasts two concepts, methods, or approaches.
  Signal words: "unlike", "whereas", "compared to", "the difference
    between", "in contrast", two named subjects discussed side-by-side,
    comparison tables, "on the other hand", "while X does …, Y does …".
  Example:
    Q: What is the key difference between a list and a tuple in Python?
    A: Lists are mutable (can be changed after creation) while tuples
       are immutable (cannot be changed).

Type 4c — Application
  Cognitive skill: Transfer — the student selects the correct concept,
    data structure, or algorithm to solve a novel scenario they have
    not seen before.
  Trigger: The source chunk describes use cases, best practices, or
    decision criteria for choosing between options.
  Signal words: "which would you use", "best approach for", "most
    appropriate", "in this scenario", real-world situations, "given
    that you need to …", design decision language.
  Example:
    Q: A web application needs to cache the 100 most recent user
       searches for instant retrieval.  Which data structure is
       most appropriate?
    A: An OrderedDict (or LRU cache) — it maintains insertion order
       and allows O(1) eviction of the oldest entry.

Type 4d — Reasoning/Inference
  Cognitive skill: Deep analytical reasoning — the student explains
    *why* something works, derives consequences from first principles,
    or evaluates trade-offs with justification.
  Trigger: The source chunk contains complexity analysis, performance
    trade-offs, design rationale, or causal explanations.
  Signal words: "why", "explain why", "what happens if", "the reason
    is", "because", O(n) notation, "trade-off", "at the cost of",
    "the consequence of", "this guarantees that".
  Example:
    Q: Why does Python's `list.append()` run in amortized O(1) time
       even though the underlying array occasionally needs resizing?
    A: The array doubles in capacity on resize, so the expensive copy
       is amortised across the many cheap appends that preceded it.

Type 4e — Misconception Targeting
  Cognitive skill: Error detection and correction — the question
    directly confronts a known incorrect mental model that students
    commonly hold, forcing the student to recognize and reject it.
  Trigger: The source chunk discusses a concept where common wrong
    beliefs exist (e.g. pass-by-reference vs. pass-by-object-reference
    in Python, mutable default arguments, integer interning).
  Signal words: "a student claims that …", "is it true that …",
    "always", "never", "common mistake", "misconception",
    "students often believe", "contrary to expectation".
  Example:
    Q: A student claims that Python passes integers to functions
       by value and lists by reference.  Is this correct?
    A: No.  Python uses pass-by-object-reference for all types.
       Integers appear to be passed by value only because they are
       immutable — the reference itself is always passed.

────────────────────────────────────────────────────────────────────────
"""


# ═══════════════════════════════════════════════════════════════════════════════
# MASTERY → ELIGIBLE QUESTION TYPES
# ═══════════════════════════════════════════════════════════════════════════════
#
# Hard ceiling: a type outside this list is NEVER generated regardless of the
# student's per-topic score category.  The ceiling widens as mastery increases.
# ═══════════════════════════════════════════════════════════════════════════════

MASTERY_TYPE_ELIGIBILITY: dict[str, list[str]] = {
    "Novice": ["1", "4a"],
    "Intermediate": ["1", "2", "3", "4b", "4c"],
    "Expert": ["1", "2", "3", "4a", "4b", "4c", "4d", "4e"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE CATEGORY → TYPE OVERRIDE
# ═══════════════════════════════════════════════════════════════════════════════
#
# Per-topic score category can force or bias the type selection within the
# mastery ceiling.  None means "use mastery eligibility unchanged".
# ═══════════════════════════════════════════════════════════════════════════════

SCORE_CATEGORY_TYPE_OVERRIDE: dict[str, list[str] | None] = {
    "very_weak": ["4a"],        # forces definition question regardless of mastery
    "weak": None,               # use mastery eligibility, prefer lowest cognitive level
    "moderate": None,           # use mastery eligibility unchanged
    "strong": None,             # use mastery eligibility, prefer highest cognitive level
}


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE CATEGORY → DISTRACTOR DIFFICULTY MODIFIER
# ═══════════════════════════════════════════════════════════════════════════════

SCORE_CATEGORY_DISTRACTOR_MODIFIER: dict[str, str] = {
    "very_weak": "keep_moderate",       # clearly distinguishable, student needs confidence
    "weak": "slightly_below_standard",  # plausible but not subtle
    "moderate": "standard",             # distractors match mastery-level expectations
    "strong": "push_to_ceiling",        # as hard as mastery ceiling allows
}


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE SETS AND MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════════

CODE_QUESTION_TYPES: set[str] = {"1", "2", "3"}

CONCEPTUAL_QUESTION_TYPES: set[str] = {"4a", "4b", "4c", "4d", "4e"}

TYPE_COGNITIVE_LEVEL: dict[str, int] = {
    "4a": 1,
    "1": 2,
    "4b": 2,
    "2": 3,
    "3": 3,
    "4c": 3,
    "4d": 4,
    "4e": 4,
}
