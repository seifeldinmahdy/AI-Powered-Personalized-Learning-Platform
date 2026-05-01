"""
Tests for training data validation and integrity.

Tests:
1. classifier_train.jsonl format and label validity
2. content_train.jsonl format and structure
3. Content validation rules (code-in-bullets, title, bullets)
4. Classifier validation rules (template-keyword match)
"""

import json
import pytest
from pathlib import Path
from collections import Counter


DATA_DIR = Path("data/agent_training")


# ============================================================
# TEST 1: classifier_train.jsonl integrity
# ============================================================

@pytest.mark.skipif(not (DATA_DIR / "classifier_train.jsonl").exists(), reason="Classifier data not found")
class TestClassifierData:

    def setup_method(self):
        self.data = []
        with open(DATA_DIR / "classifier_train.jsonl") as f:
            for line in f:
                if line.strip():
                    self.data.append(json.loads(line))

    def test_not_empty(self):
        """Must have generated data."""
        assert len(self.data) > 0, "classifier_train.jsonl is empty"

    def test_required_fields(self):
        """Every example must have 'text' and 'label'."""
        for i, example in enumerate(self.data):
            assert "text" in example, f"Example {i} missing 'text'"
            assert "label" in example, f"Example {i} missing 'label'"

    def test_labels_are_valid(self):
        """All labels must be from the 18 valid template classes."""
        from slide_gen.agents.visual_classifier import LABEL_LIST
        valid = set(LABEL_LIST)
        for i, example in enumerate(self.data):
            assert example["label"] in valid, f"Example {i} has invalid label: {example['label']}"

    def test_text_not_empty(self):
        """No example should have empty text."""
        for i, example in enumerate(self.data):
            assert len(example["text"].strip()) > 10, f"Example {i} has too-short text"

    def test_label_distribution_coverage(self):
        """At least 10 distinct labels should be present (out of 18)."""
        labels = [ex["label"] for ex in self.data]
        unique = set(labels)
        assert len(unique) >= 10, f"Only {len(unique)} unique labels — need at least 10 for meaningful training"

    def test_no_duplicate_entries(self):
        """No exact duplicate (text, label) pairs."""
        seen = set()
        duplicates = 0
        for ex in self.data:
            key = (ex["text"][:100], ex["label"])  # first 100 chars + label
            if key in seen:
                duplicates += 1
            seen.add(key)
        assert duplicates < len(self.data) * 0.05, f"{duplicates} duplicates found (>{5}% of data)"


# ============================================================
# TEST 2: content_train.jsonl integrity
# ============================================================

@pytest.mark.skipif(not (DATA_DIR / "content_train.jsonl").exists(), reason="Content data not found")
class TestContentData:

    def setup_method(self):
        self.data = []
        with open(DATA_DIR / "content_train.jsonl") as f:
            for line in f:
                if line.strip():
                    self.data.append(json.loads(line))

    def test_not_empty(self):
        """Must have generated data."""
        assert len(self.data) > 0, "content_train.jsonl is empty"

    def test_required_fields(self):
        """Every example must have 'input' and 'target'."""
        for i, example in enumerate(self.data):
            assert "input" in example, f"Example {i} missing 'input'"
            assert "target" in example, f"Example {i} missing 'target'"

    def test_input_has_profile_tags(self):
        """Input must start with [MASTERY: ...] profile tags."""
        for i, example in enumerate(self.data):
            inp = example["input"]
            assert "[MASTERY:" in inp, f"Example {i} missing MASTERY tag"
            assert "[MODE:" in inp, f"Example {i} missing MODE tag"
            assert "[LANG:" in inp, f"Example {i} missing LANG tag"

    def test_target_has_title_and_bullets(self):
        """Target must contain TITLE: and at least one BULLET or DEFINE."""
        for i, example in enumerate(self.data):
            target = example["target"]
            assert "TITLE:" in target, f"Example {i} target missing TITLE"
            assert "BULLET" in target or "DEFINE" in target, f"Example {i} target missing BULLET/DEFINE"

    def test_input_has_context(self):
        """Input must have 'Context:' with actual text after it."""
        for i, example in enumerate(self.data):
            assert "Context:" in example["input"], f"Example {i} missing Context:"
            context_start = example["input"].index("Context:") + 8
            context_text = example["input"][context_start:].strip()
            assert len(context_text) > 50, f"Example {i} context too short"


# ============================================================
# TEST 3: Content validation rules
# ============================================================

class TestContentValidation:

    def _make_profile(self, mode="Balanced"):
        from slide_gen.core.profile_schema import StudentProfile, MasteryLevel, CompositionMode, LanguageProficiency
        modes = {"Visual_Heavy": CompositionMode.VISUAL_HEAVY, "Balanced": CompositionMode.BALANCED, "Text_Heavy": CompositionMode.TEXT_HEAVY}
        return StudentProfile(
            mastery_level=MasteryLevel.INTERMEDIATE,
            composition_mode=modes[mode],
            language_proficiency=LanguageProficiency.INTERMEDIATE,
            screen_reader_active=False,
        )

    def test_valid_output_passes(self):
        """A well-formed output should pass validation."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Understanding Python Variables",
            "bullets": [
                {"text": "Variables store references to data objects in memory", "highlight_type": "definition"},
                {"text": "Assignment binds a name to a value using the equals sign", "highlight_type": "key_concept"},
                {"text": "The type of a variable changes when reassigned to a different type", "highlight_type": "example"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile("Balanced"))
        assert is_valid, f"Valid output rejected: {reason}"

    def test_generic_title_rejected(self):
        """Generic titles like 'Introduction' should be rejected."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Introduction",
            "bullets": [{"text": "This is a meaningful bullet point about something", "highlight_type": "none"}]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert not is_valid
        assert reason == "generic_title"

    def test_code_in_bullets_rejected(self):
        """Bullets containing code syntax should be rejected."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Understanding Functions",
            "bullets": [
                {"text": "Use print(x) and len(list) to debug your .append() calls", "highlight_type": "none"},
                {"text": "Functions help organize code into reusable pieces", "highlight_type": "definition"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert not is_valid
        assert reason == "bullet_has_code"

    def test_too_many_bullets_visual_heavy(self):
        """Visual_Heavy mode should reject more than 3 bullets."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Understanding Variables",
            "bullets": [
                {"text": "First bullet with enough text content here", "highlight_type": "none"},
                {"text": "Second bullet with enough text content here", "highlight_type": "definition"},
                {"text": "Third bullet with enough text content here", "highlight_type": "key_concept"},
                {"text": "Fourth bullet with enough text content here", "highlight_type": "example"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile("Visual_Heavy"))
        assert not is_valid
        assert reason == "visual_heavy_too_many_bullets"

    def test_natural_language_bullets_pass(self):
        """Bullets with natural English should NOT trigger code detection."""
        from slide_gen.training.content_data_generator import validate_content_output
        natural_bullets = [
            "A stack is like a pile of plates where you can only take from the top",
            "The try except construct captures runtime errors and allows graceful recovery",
            "Variables let us store and reuse values throughout our program",
        ]
        parsed = {
            "title": "Understanding Error Handling",
            "bullets": [{"text": b, "highlight_type": "none"} for b in natural_bullets]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert is_valid, f"Natural language incorrectly flagged: {reason}"

    def test_valid_definition_passes(self):
        """A bullet with term field and definition highlight should pass."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Understanding Data Structures",
            "bullets": [
                {"text": "A linear data structure following LIFO ordering", "highlight_type": "definition", "term": "Stack"},
                {"text": "Elements are added and removed from the top only", "highlight_type": "none"},
                {"text": "Common operations include push and pop", "highlight_type": "key_concept"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert is_valid, f"Valid definition rejected: {reason}"

    def test_too_many_definitions_rejected(self):
        """More than 2 definitions per slide should be rejected."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Key Terms in Computing",
            "bullets": [
                {"text": "A named storage location in memory", "highlight_type": "definition", "term": "Variable"},
                {"text": "A reusable block of code that performs a task", "highlight_type": "definition", "term": "Function"},
                {"text": "A sequence of characters enclosed in quotes", "highlight_type": "definition", "term": "String"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert not is_valid
        assert reason == "too_many_definitions"

    def test_term_without_definition_highlight_rejected(self):
        """A bullet with term but wrong highlight_type should be rejected."""
        from slide_gen.training.content_data_generator import validate_content_output
        parsed = {
            "title": "Understanding Variables",
            "bullets": [
                {"text": "A storage location in memory", "highlight_type": "none", "term": "Variable"},
                {"text": "Values can be reassigned at any time", "highlight_type": "none"},
            ]
        }
        is_valid, reason = validate_content_output(parsed, self._make_profile())
        assert not is_valid
        assert reason == "term_requires_definition_highlight"


# ============================================================
# TEST 4: Classifier validation rules
# ============================================================

class TestClassifierValidation:

    def test_valid_classification(self):
        """Valid template + matching keywords should pass."""
        from slide_gen.training.classifier_data_generator import validate_classifier_output
        parsed = {"template_id": "stack", "reasoning": "This describes push and pop operations"}
        is_valid, reason = validate_classifier_output(parsed, "A stack uses push and pop with LIFO ordering")
        assert is_valid, f"Valid classification rejected: {reason}"

    def test_template_keyword_mismatch(self):
        """Picking binary_tree for text about sorting should fail if reasoning also doesn't mention trees."""
        from slide_gen.training.classifier_data_generator import validate_classifier_output
        parsed = {"template_id": "binary_tree", "reasoning": "Some reasoning about sorting algorithms"}
        is_valid, reason = validate_classifier_output(parsed, "Bubble sort compares adjacent elements")
        assert not is_valid
        assert reason == "template_content_mismatch"

    def test_template_keyword_mismatch_passes_with_reasoning(self):
        """Keyword mismatch should PASS if the reasoning mentions relevant keywords."""
        from slide_gen.training.classifier_data_generator import validate_classifier_output
        parsed = {"template_id": "binary_tree", "reasoning": "This describes a tree structure with root and child nodes"}
        is_valid, reason = validate_classifier_output(parsed, "Bubble sort compares adjacent elements")
        assert is_valid, f"Relaxed validation should accept reasoning-based match: {reason}"

    def test_invalid_template_id(self):
        """Non-existent template_id should be rejected."""
        from slide_gen.training.classifier_data_generator import validate_classifier_output
        parsed = {"template_id": "nonexistent_template", "reasoning": "Some reasoning"}
        is_valid, reason = validate_classifier_output(parsed, "Some text")
        assert not is_valid
        assert reason == "invalid_template_id"

    def test_keyword_free_templates_always_pass(self):
        """Templates without keyword requirements should pass for any text."""
        from slide_gen.training.classifier_data_generator import validate_classifier_output
        parsed = {"template_id": "concept_box", "reasoning": "General concept explanation fits box layout"}
        is_valid, reason = validate_classifier_output(parsed, "The weather is nice today")
        assert is_valid, f"Keyword-free template rejected: {reason}"
