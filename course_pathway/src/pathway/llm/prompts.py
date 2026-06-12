"""First-class prompt templates for LLM interactions.

All prompts used by the pathway generator live here as named constants.
Business logic modules import from this module rather than inlining prompts.
"""

from __future__ import annotations

# ── Top-Down Curriculum Design ───────────────────────────────────

CURRICULUM_SYSTEM_PROMPT = (
    "You are an expert university-level curriculum designer. "
    "Your task is to design a complete, pedagogically ordered course "
    "from a flat list of topic tags extracted from a textbook.\n\n"

    "Rules:\n"
    "1. Design a SMALL, fixed number of logical learning sessions for the whole "
    "course (the requested range is given in the user message). The number of "
    "sessions must reflect the conceptual structure of the subject — NOT how many "
    "topics there are. If there are many topics, put MORE topics in each session "
    "rather than creating more sessions. Never exceed the requested maximum.\n"
    "2. Order sessions so foundational concepts come first: variables before loops, "
    "loops before functions, functions before recursion, basics before OOP, "
    "simple data structures before algorithms, etc.\n"
    "3. Within each session, topics should flow naturally from simple to complex.\n"
    "4. Give each session a clear, pedagogically meaningful title (3-7 words).\n"
    "5. Assign a difficulty tier to each session: 'beginner', 'intermediate', or 'expert'.\n"
    "6. You must use ONLY topic strings from the provided list — do NOT invent new topics.\n"
    "7. Every topic from the list must appear in exactly one session — no omissions, "
    "no duplicates.\n"
    "8. Filter out obvious textbook boilerplate topics (like 'Index', 'Glossary', "
    "'Acknowledgments', 'Creative Commons') by simply not including them.\n\n"

    "Return ONLY a JSON object with this exact structure:\n"
    "{\n"
    '  "sessions": [\n'
    "    {\n"
    '      "session_number": 1,\n'
    '      "session_title": "Getting Started with Python",\n'
    '      "topics": ["topic_a", "topic_b", "topic_c"],\n'
    '      "difficulty": "beginner"\n'
    "    },\n"
    "    ...\n"
    "  ]\n"
    "}\n"
    "No other text, no explanation, no markdown fences."
)

CURRICULUM_USER_TEMPLATE = (
    "Course intent: {course_intent}\n\n"
    "Design the curriculum as approximately {target_sessions} learning sessions "
    "for the ENTIRE course — at least {min_sessions} and AT MOST {max_sessions} "
    "sessions, regardless of how many topics are listed below. If there are many "
    "topics, group more topics into each session instead of adding sessions.\n\n"
    "Topic tags ({count} total — you must use ONLY these exact strings):\n"
    "{topic_listing}\n"
)
