"""Synthetic student context generator for development and testing.

When the placement test is not yet implemented, this class produces a
plausible ``StudentContext`` with randomised but realistic values so
that the full pathway generation pipeline can be tested end-to-end.

The generator is injectable: swap it with the real placement-test
result parser once that component is built.
"""

from __future__ import annotations

import random

import structlog

from pathway.models.schemas import StudentContext

logger = structlog.get_logger(__name__)

# ── Mastery probabilities ────────────────────────────────────────
_MASTERY_WEIGHTS = {
    "Novice": 0.45,
    "Intermediate": 0.40,
    "Expert": 0.15,
}

# Mastery level → ChromaDB difficulty tier for weakness selection
_MASTERY_TO_DIFFICULTY = {
    "Novice": "beginner",
    "Intermediate": "intermediate",
    "Expert": "expert",
}


class SyntheticContextGenerator:
    """Generates a valid synthetic ``StudentContext`` for a given course.

    Parameters
    ----------
    seed:
        Optional RNG seed for reproducibility in tests.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def generate(
        self,
        student_id: str,
        course_id: str,
        available_topics: list[str],
        difficulty_topics: list[str] | None = None,
        mastery_level: str | None = None,
    ) -> StudentContext:
        """Build a synthetic student context.

        Parameters
        ----------
        student_id:
            Identifier for the synthetic student.
        course_id:
            Course identifier (matches ChromaDB ``course`` field).
        available_topics:
            Full list of unique topic strings discovered in the course.
            A random subset will be assigned to strengths.
        difficulty_topics:
            Topics filtered by the difficulty tier matching the student's
            mastery level. Weaknesses are selected only from this list.
            If None, falls back to selecting from available_topics.
        mastery_level:
            If provided, use this mastery level instead of randomly choosing.

        Returns
        -------
        StudentContext
            A fully populated context object with ``use_synthetic_context=True``.
        """
        if mastery_level is None:
            mastery_level = self._rng.choices(
                population=list(_MASTERY_WEIGHTS.keys()),
                weights=list(_MASTERY_WEIGHTS.values()),
                k=1,
            )[0]

        composition_mode = self._rng.choice(
            ["visual_heavy", "text_heavy", "balanced"]
        )

        language_proficiency = self._rng.choice(
            ["Elementary", "Intermediate", "Advanced", "Native"]
        )

        # Use difficulty-filtered topics for weaknesses if available
        weakness_pool = difficulty_topics if difficulty_topics else available_topics

        # Decide how many topics fall into strengths vs weaknesses.
        n_topics = len(available_topics)
        n_weakness_pool = len(weakness_pool)

        if n_topics == 0:
            strengths: list[str] = []
            weaknesses: list[str] = []
            topic_performance: dict[str, float] = {}
        else:
            # 10–25% of topics are strengths, 10–25% are weaknesses
            n_strengths = max(1, self._rng.randint(
                n_topics // 10, max(n_topics // 10 + 1, n_topics // 4)
            ))
            n_weaknesses = max(1, self._rng.randint(
                max(1, n_weakness_pool // 10),
                max(2, n_weakness_pool // 4),
            ))
            # Cap weaknesses at the pool size
            n_weaknesses = min(n_weaknesses, n_weakness_pool)

            # Select strengths from the full topic list
            shuffled_all = list(available_topics)
            self._rng.shuffle(shuffled_all)
            strengths = shuffled_all[:n_strengths]
            strength_set = set(strengths)

            # Select weaknesses from difficulty-filtered pool,
            # ensuring no overlap with strengths
            weakness_candidates = [t for t in weakness_pool if t not in strength_set]
            self._rng.shuffle(weakness_candidates)
            weaknesses = weakness_candidates[:n_weaknesses]

            # Generate plausible performance scores
            topic_performance = {}
            for t in strengths:
                topic_performance[t] = round(self._rng.uniform(0.75, 1.0), 2)
            for t in weaknesses:
                topic_performance[t] = round(self._rng.uniform(0.0, 0.35), 2)
            # Neutral topics get middling scores
            assigned = strength_set | set(weaknesses)
            neutral = [t for t in shuffled_all if t not in assigned]
            for t in neutral:
                topic_performance[t] = round(self._rng.uniform(0.35, 0.75), 2)

        ctx = StudentContext(
            student_id=student_id,
            course_id=course_id,
            mastery_level=mastery_level,
            composition_mode=composition_mode,
            language_proficiency=language_proficiency,
            strengths=strengths,
            weaknesses=weaknesses,
            topic_performance=topic_performance,
            incorrectly_answered=[],
            use_synthetic_context=True,
        )

        logger.info(
            "synthetic_context_generated",
            student_id=student_id,
            course_id=course_id,
            mastery_level=mastery_level,
            n_strengths=len(strengths),
            n_weaknesses=len(weaknesses),
            weakness_pool_size=n_weakness_pool,
        )

        return ctx
