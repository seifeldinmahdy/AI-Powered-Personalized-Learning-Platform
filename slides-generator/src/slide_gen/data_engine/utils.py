"""
Shared utilities for data generation.

Extracted from the monolithic factory.py — these are used by both
the ContentDataGenerator and ClassifierDataGenerator.
"""

import json
import random
from pathlib import Path
from typing import Any

import yaml

from slide_gen.core.profile_schema import (
    CompositionMode,
    LanguageProficiency,
    MasteryLevel,
    StudentProfile,
)


# =============================================================================
# PROFILE GENERATION - MULTI-PERSPECTIVE STRATEGY
# =============================================================================

def generate_novice_profile() -> StudentProfile:
    """
    Variation 1: The Novice
    Forces: Mastery=Novice, Composition=Visual_Heavy, Language=Elementary
    Teaches the model to simplify & visualize for beginners.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.NOVICE,
        composition_mode=CompositionMode.VISUAL_HEAVY,
        language_proficiency=LanguageProficiency.ELEMENTARY,
        screen_reader_active=random.choice([True, False]),
    )


def generate_expert_profile() -> StudentProfile:
    """
    Variation 2: The Expert
    Forces: Mastery=Expert, Composition=Text_Heavy, Language=Advanced
    Teaches the model to retain complexity for advanced users.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.EXPERT,
        composition_mode=CompositionMode.TEXT_HEAVY,
        language_proficiency=LanguageProficiency.ADVANCED,
        screen_reader_active=random.choice([True, False]),
    )




def generate_intermediate_profile() -> StudentProfile:
    """
    Variation 4: The Intermediate
    Forces: Mastery=Intermediate, Composition=Balanced
    Teaches the model to create balanced content for typical learners.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.INTERMEDIATE,
        composition_mode=CompositionMode.BALANCED,
        language_proficiency=random.choice([LanguageProficiency.INTERMEDIATE, LanguageProficiency.ADVANCED]),
        screen_reader_active=random.choice([True, False]),
    )


def generate_visual_expert_profile() -> StudentProfile:
    """
    Variation 5: The Visual Expert
    Forces: Mastery=Expert, Composition=Visual_Heavy
    Teaches the model that experts can also prefer visual explanations.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.EXPERT,
        composition_mode=CompositionMode.VISUAL_HEAVY,
        language_proficiency=LanguageProficiency.NATIVE,
        screen_reader_active=random.choice([True, False]),
    )


def generate_novice_text_profile() -> StudentProfile:
    """
    Variation 6: The Text Novice
    Forces: Mastery=Novice, Composition=Text_Heavy
    Teaches the model that beginners sometimes need detailed text explanations.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.NOVICE,
        composition_mode=CompositionMode.TEXT_HEAVY,
        language_proficiency=LanguageProficiency.INTERMEDIATE,
        screen_reader_active=random.choice([True, False]),
    )


def generate_bilingual_profile() -> StudentProfile:
    """
    Variation 7: The Bilingual Learner
    Forces: Language=Elementary (non-native speaker)
    Teaches the model to use simple language for ESL learners.
    """
    return StudentProfile(
        mastery_level=random.choice([MasteryLevel.INTERMEDIATE, MasteryLevel.EXPERT]),
        composition_mode=random.choice(list(CompositionMode)),
        language_proficiency=LanguageProficiency.ELEMENTARY,
        screen_reader_active=random.choice([True, False]),
    )


def generate_random_profile() -> StudentProfile:
    """
    Variation 8: Random
    Completely random profile to cover the rest of the distribution.
    """
    return StudentProfile(
        mastery_level=random.choice(list(MasteryLevel)),
        composition_mode=random.choice(list(CompositionMode)),
        language_proficiency=random.choice(list(LanguageProficiency)),
        screen_reader_active=random.choice([True, False]),
    )


def generate_balanced_novice_profile() -> StudentProfile:
    """
    Variation 9: The Balanced Novice
    Forces: Mastery=Novice, Composition=Balanced

    CRITICAL FOR T5: This breaks the Novice→Visual_Heavy pattern!
    Teaches the model that mastery_level and composition_mode are
    INDEPENDENT dimensions. Beginners can have balanced learning styles.
    Without this, T5 would overfit to always use Visual_Heavy for Novice.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.NOVICE,
        composition_mode=CompositionMode.BALANCED,
        language_proficiency=LanguageProficiency.INTERMEDIATE,
        screen_reader_active=random.choice([True, False]),
    )


def generate_intermediate_visual_profile() -> StudentProfile:
    """
    Variation 8: The Intermediate Visual Learner
    Forces: Intermediate + Visual_Heavy + Elementary
    Fills the Intermediate+Visual_Heavy gap and gives Elementary a second mode.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.INTERMEDIATE,
        composition_mode=CompositionMode.VISUAL_HEAVY,
        language_proficiency=LanguageProficiency.ELEMENTARY,
        screen_reader_active=random.choice([True, False]),
    )


def generate_expert_balanced_profile() -> StudentProfile:
    """
    Variation 9: The Expert Balanced Learner
    Forces: Expert + Balanced + Native
    Fills the Expert+Balanced gap and gives Native a second mode.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.EXPERT,
        composition_mode=CompositionMode.BALANCED,
        language_proficiency=LanguageProficiency.NATIVE,
        screen_reader_active=random.choice([True, False]),
    )


def generate_intermediate_text_profile() -> StudentProfile:
    """
    Variation 10: The Intermediate Text-Heavy Learner
    Forces: Intermediate + Text_Heavy + Native
    Fills the last Mastery×Mode gap and gives Intermediate a Native example.
    """
    return StudentProfile(
        mastery_level=MasteryLevel.INTERMEDIATE,
        composition_mode=CompositionMode.TEXT_HEAVY,
        language_proficiency=LanguageProficiency.NATIVE,
        screen_reader_active=random.choice([True, False]),
    )


# Ordered list of profile generators for the 10 variations
# Coverage analysis (Mastery × Mode — COMPLETE):
#   Visual_Heavy: Novice (1), Intermediate (8), Expert (4)  ✓ all 3
#   Balanced:     Novice (6), Intermediate (3), Expert (9)  ✓ all 3
#   Text_Heavy:   Novice (5), Intermediate (10), Expert (2) ✓ all 3
# Language coverage:
#   Elementary:   (1, 8)
#   Intermediate: (5, 6)
#   Advanced:     (2, 3)
#   Native:       (4, 9, 10)
VARIATION_GENERATORS = [
    ("Novice", generate_novice_profile),                     # 1: Novice + Visual_Heavy + Elementary
    ("Expert", generate_expert_profile),                     # 2: Expert + Text_Heavy + Advanced
    ("Intermediate", generate_intermediate_profile),         # 3: Intermediate + Balanced + Advanced
    ("VisualExpert", generate_visual_expert_profile),         # 4: Expert + Visual_Heavy + Native
    ("TextNovice", generate_novice_text_profile),             # 5: Novice + Text_Heavy + Intermediate
    ("BalancedNovice", generate_balanced_novice_profile),     # 6: Novice + Balanced + Intermediate
    ("IntermediateVisual", generate_intermediate_visual_profile),  # 8: Intermediate + Visual_Heavy + Elementary
    ("ExpertBalanced", generate_expert_balanced_profile),     # 9: Expert + Balanced + Native
    ("IntermediateText", generate_intermediate_text_profile), # 10: Intermediate + Text_Heavy + Native
    ("Random", generate_random_profile),                     # 7: Full random distribution coverage
]

VARIATIONS_PER_CHUNK = len(VARIATION_GENERATORS)


# =============================================================================
# INPUT FORMATTING - T5 CONDITIONING
# =============================================================================

def format_training_input(chunk_text: str, profile: StudentProfile) -> str:
    """
    Format input string with explicit tagging for T5 encoder attention.

    Required Format:
    [MASTERY: <str>] [MODE: <str>] [LANG: <str>]
    Context: <raw_text_chunk>

    This explicit "tagging" at the start forces the T5 encoder to pay attention
    to the constraints before it reads the content.
    """
    mastery = profile.mastery_level.value
    mode = profile.composition_mode.value
    lang = profile.language_proficiency.value

    return (
        f"[MASTERY: {mastery}] [MODE: {mode}] [LANG: {lang}]\n"
        f"Context: {chunk_text}"
    )


# =============================================================================
# QUALITY CONTROL
# =============================================================================

# Strict code patterns - only match definite programming constructs
CODE_PATTERNS = [
    'def ',          # Python function definition
    'class ',        # Class definition
    'import ',       # Python import
    'from ',         # Python from import
    '>>> ',          # Python REPL prompt
    'return ',       # Return statement
    'print(',        # Print function call
    '= function',    # JavaScript function assignment
    'const ',        # JavaScript const
    'let ',          # JavaScript let
    'var ',          # JavaScript var
    'function(',     # JavaScript function
    'async def',     # Async function
    '@property',     # Python decorator
    '@staticmethod', # Python decorator
]


def chunk_has_code(chunk: str) -> bool:
    """
    Detect if a chunk contains programming code.

    Uses strict patterns to avoid false positives from English text.
    Requires multiple indicators of code presence.
    """
    pattern_matches = sum(1 for pattern in CODE_PATTERNS if pattern in chunk)

    # Need at least 2 code patterns for high confidence
    if pattern_matches >= 2:
        return True

    # Single pattern match + other code indicators
    if pattern_matches >= 1:
        lines = chunk.split('\n')
        has_indented_block = any(
            line.startswith('    ') or line.startswith('\t')
            for line in lines
        )
        if has_indented_block:
            return True

    return False


def is_valid_chunk(chunk: str) -> tuple[bool, str]:
    """
    Validate chunk quality before processing.

    Returns:
        Tuple of (is_valid, reason)
    """
    # Too short - not enough content
    if len(chunk) < 150:
        return False, "too_short"

    # Mostly numbers (likely tables or indices)
    digit_ratio = sum(c.isdigit() for c in chunk) / len(chunk)
    if digit_ratio > 0.25:
        return False, "too_many_numbers"

    # Table of contents pattern (many dots)
    if chunk.count('...') > 5 or chunk.count('. . .') > 3:
        return False, "table_of_contents"

    # Mostly whitespace or special characters
    alpha_ratio = sum(c.isalpha() for c in chunk) / len(chunk)
    if alpha_ratio < 0.4:
        return False, "low_text_content"

    # Repetitive content (like headers only)
    lines = chunk.strip().split('\n')
    if len(lines) < 3:
        return False, "too_few_lines"

    return True, "valid"


# =============================================================================
# JSON EXTRACTION UTILITIES
# =============================================================================

def extract_json_from_response(text: str) -> dict[str, Any] | None:
    """
    Extract JSON from LLM response, handling markdown code blocks.

    Returns None if no valid JSON found.
    """
    text = text.strip()

    # Try to find JSON in markdown code block
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()

    # Find JSON object boundaries
    start_idx = text.find("{")
    end_idx = text.rfind("}") + 1

    if start_idx == -1 or end_idx <= start_idx:
        return None

    json_str = text[start_idx:end_idx]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def load_prompts(config_path: str | Path) -> dict[str, str]:
    """Load prompts from YAML configuration file."""
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Prompts config not found: {config_path}")

    with open(config_path, "r") as f:
        return yaml.safe_load(f)
