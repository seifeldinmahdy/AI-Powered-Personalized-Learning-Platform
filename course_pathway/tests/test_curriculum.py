"""Tests for top-down LLM curriculum designer.

Covers:
1. Valid LLM response → sessions parsed correctly.
2. Invented topics are stripped via fuzzy validation.
3. Missing topics assigned via embedding similarity fallback.
4. LLM failure → alphabetical fallback.
5. Empty topic list → empty result.
6. Boilerplate topics are filtered.
7. Topic fuzzy matching.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pathway.llm.curriculum import (
    _alphabetical_fallback,
    _is_boilerplate,
    _validate_topics,
    design_curriculum,
)
from pathway.models.schemas import LLMCurriculumSession


# ── Sample data ──────────────────────────────────────────────────

SAMPLE_TOPICS = [
    "variables",
    "loops",
    "while loop",
    "for loops",
    "functions",
    "recursion",
    "strings",
    "lists",
    "dictionaries",
    "OOP",
]

VALID_LLM_RESPONSE = {
    "sessions": [
        {
            "session_number": 1,
            "session_title": "Getting Started with Variables",
            "topics": ["variables", "strings"],
            "difficulty": "beginner",
        },
        {
            "session_number": 2,
            "session_title": "Loops and Iteration",
            "topics": ["loops", "while loop", "for loops"],
            "difficulty": "beginner",
        },
        {
            "session_number": 3,
            "session_title": "Functions and Recursion",
            "topics": ["functions", "recursion"],
            "difficulty": "intermediate",
        },
        {
            "session_number": 4,
            "session_title": "Data Structures",
            "topics": ["lists", "dictionaries"],
            "difficulty": "intermediate",
        },
        {
            "session_number": 5,
            "session_title": "Object-Oriented Programming",
            "topics": ["OOP"],
            "difficulty": "expert",
        },
    ]
}


class TestDesignCurriculum:
    def test_valid_response_parses_sessions(self):
        """Valid LLM response → all sessions parsed and topics validated."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = VALID_LLM_RESPONSE

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Introduction to Python",
            max_retries=1,
        )

        assert len(result) == 5
        assert result[0].session_title == "Getting Started with Variables"
        assert "variables" in result[0].topics
        assert result[4].session_title == "Object-Oriented Programming"
        mock_client.chat_json.call_count == 1

    def test_invented_topics_removed(self):
        """Topics not in the original list are stripped."""
        response = {
            "sessions": [
                {
                    "session_number": 1,
                    "session_title": "Basics",
                    "topics": ["variables", "INVENTED_TOPIC_XYZ", "loops"],
                    "difficulty": "beginner",
                },
                {
                    "session_number": 2,
                    "session_title": "More",
                    "topics": ["functions", "strings", "while loop", "for loops",
                               "recursion", "lists", "dictionaries", "OOP"],
                    "difficulty": "intermediate",
                },
            ]
        }

        mock_client = MagicMock()
        mock_client.chat_json.return_value = response

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            max_retries=1,
        )

        all_topics_used = set()
        for s in result:
            all_topics_used.update(s.topics)

        assert "INVENTED_TOPIC_XYZ" not in all_topics_used
        assert "variables" in all_topics_used
        assert "loops" in all_topics_used

    def test_fuzzy_matching_plurals(self):
        """LLM writes 'for loop' (singular) → matches 'for loops' (plural)."""
        response = {
            "sessions": [
                {
                    "session_number": 1,
                    "session_title": "Basics",
                    "topics": ["variables", "loops", "while loop", "for loop",
                               "functions", "recursion", "strings",
                               "lists", "dictionaries", "OOP"],
                    "difficulty": "beginner",
                },
            ]
        }

        mock_client = MagicMock()
        mock_client.chat_json.return_value = response

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            max_retries=1,
        )

        all_topics = set()
        for s in result:
            all_topics.update(s.topics)

        # "for loop" should fuzzy-match to "for loops"
        assert "for loops" in all_topics

    @patch("pathway.llm.curriculum._assign_missing_topics")
    def test_missing_topics_recovered(self, mock_assign):
        """Topics missing from LLM response are recovered."""
        # LLM only returns 3 of 10 topics
        response = {
            "sessions": [
                {
                    "session_number": 1,
                    "session_title": "Basics",
                    "topics": ["variables", "loops", "functions"],
                    "difficulty": "beginner",
                },
            ]
        }

        # Mock _assign_missing_topics to just append to session
        def assign_side_effect(missing, sessions):
            for t in missing:
                sessions[0].topics.append(t)
            return sessions

        mock_assign.side_effect = assign_side_effect

        mock_client = MagicMock()
        mock_client.chat_json.return_value = response

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            max_retries=1,
        )

        all_topics = set()
        for s in result:
            all_topics.update(s.topics)

        # All 10 original topics should be present after recovery
        for topic in SAMPLE_TOPICS:
            assert topic in all_topics, f"Missing: {topic}"

    def test_llm_failure_falls_back_to_alphabetical(self):
        """All retries fail → alphabetical fallback."""
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = RuntimeError("API down")

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            max_retries=2,
        )

        # Should get sessions with alphabetically grouped topics
        assert len(result) >= 1
        all_topics = set()
        for s in result:
            all_topics.update(s.topics)
        # All topics should be present
        for topic in SAMPLE_TOPICS:
            assert topic in all_topics

    def test_invalid_json_retries(self):
        """Invalid response on first try, valid on second."""
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = [
            {"sessions": "not_a_list"},  # Invalid
            VALID_LLM_RESPONSE,  # Valid
        ]

        result = design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            max_retries=3,
        )

        assert len(result) == 5
        assert mock_client.chat_json.call_count == 2

    def test_empty_topics_returns_empty(self):
        """Empty topic list → empty result, no LLM call."""
        mock_client = MagicMock()

        result = design_curriculum(
            client=mock_client,
            topics=[],
            course_intent="Test",
        )

        assert result == []
        mock_client.chat_json.assert_not_called()

    def test_timeout_passed_to_client(self):
        """Timeout is forwarded to the LLM call."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = VALID_LLM_RESPONSE

        design_curriculum(
            client=mock_client,
            topics=SAMPLE_TOPICS,
            course_intent="Test",
            timeout=900,
            max_retries=1,
        )

        call_kwargs = mock_client.chat_json.call_args
        assert call_kwargs[1]["timeout_override"] == 900


class TestBoilerplateFilter:
    def test_index_is_boilerplate(self):
        assert _is_boilerplate("Index") is True
        assert _is_boilerplate("index entries") is True

    def test_glossary_is_boilerplate(self):
        assert _is_boilerplate("Glossary") is True

    def test_real_topic_is_not_boilerplate(self):
        assert _is_boilerplate("variables") is False
        assert _is_boilerplate("while loop") is False

    def test_creative_commons_is_boilerplate(self):
        assert _is_boilerplate("Creative Commons licensing") is True


class TestAlphabeticalFallback:
    def test_groups_into_sessions(self):
        topics = ["z_topic", "a_topic", "m_topic"]
        result = _alphabetical_fallback(topics, topics_per_session=2)

        assert len(result) == 2
        assert result[0].topics == ["a_topic", "m_topic"]
        assert result[1].topics == ["z_topic"]

    def test_single_session_for_small_list(self):
        result = _alphabetical_fallback(["a", "b", "c"], topics_per_session=10)
        assert len(result) == 1
        assert result[0].topics == ["a", "b", "c"]


class TestValidateTopics:
    def test_exact_match_kept(self):
        sessions = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Test",
                topics=["variables", "loops"],
            )
        ]
        result = _validate_topics(sessions, ["variables", "loops", "functions"])
        assert result[0].topics == ["variables", "loops"]

    def test_invented_removed(self):
        sessions = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Test",
                topics=["variables", "FAKE_TOPIC"],
            )
        ]
        result = _validate_topics(sessions, ["variables", "loops"])
        assert "FAKE_TOPIC" not in result[0].topics
        assert "variables" in result[0].topics

    def test_no_duplicates_across_sessions(self):
        sessions = [
            LLMCurriculumSession(
                session_number=1,
                session_title="Session 1",
                topics=["variables"],
            ),
            LLMCurriculumSession(
                session_number=2,
                session_title="Session 2",
                topics=["variables", "loops"],  # duplicate "variables"
            ),
        ]
        result = _validate_topics(sessions, ["variables", "loops"])
        all_topics = []
        for s in result:
            all_topics.extend(s.topics)
        # "variables" should only appear once
        assert all_topics.count("variables") == 1
