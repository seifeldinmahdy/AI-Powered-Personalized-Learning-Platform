"""Shared topic-string → Concept matcher.

Used by both ``tag_chunks_with_concepts`` (courses) and
``migrate_topic_performance_to_concepts`` (progress) so concept matching is
identical everywhere. Uses sentence-transformer cosine similarity when the lib
is installed, falling back to normalized-exact then difflib ratio so it runs in
the Django venv without the heavy AI deps.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


class ConceptMatcher:
    def __init__(self, concepts):
        self.concepts = list(concepts)
        self.labels = [c.label for c in self.concepts]
        self._norm_labels = [norm(c.label) for c in self.concepts]
        self._embedder = None
        self._label_emb = None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._label_emb = self._embedder.encode(
                self.labels, convert_to_numpy=True, show_progress_bar=False,
            )
        except Exception:
            self._embedder = None

    def match(self, topic: str):
        """Return (Concept|None, confidence 0..1)."""
        if not topic or not self.concepts:
            return None, 0.0
        nt = norm(topic)
        for c, nl in zip(self.concepts, self._norm_labels):
            if nl and nl == nt:
                return c, 1.0
        if self._embedder is not None:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity
            q = self._embedder.encode([topic], convert_to_numpy=True, show_progress_bar=False)
            sims = cosine_similarity(q, self._label_emb)[0]
            idx = int(np.argmax(sims))
            return self.concepts[idx], float(sims[idx])
        best_c, best_r = None, 0.0
        for c, nl in zip(self.concepts, self._norm_labels):
            r = SequenceMatcher(None, nt, nl).ratio()
            if r > best_r:
                best_c, best_r = c, r
        return best_c, best_r


def build_matcher(concepts) -> ConceptMatcher:
    return ConceptMatcher(concepts)
