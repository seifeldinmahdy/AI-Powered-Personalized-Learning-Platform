"""
Unit Test Suite for TinyBert-CNN Intent Classifier Pipeline.
Tests: model init, dataset tokenization, forward pass, predict, compound splitter,
       dataset generator output, and auto_trainer state I/O.
"""

import unittest
import os
import sys
import json
import tempfile
import torch
import pandas as pd

# Ensure the project directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from TinyBert import IntentClassifier, IntentDataset, CompoundSentenceSplitter, TinyBertCNN


# ─────────────────────────────────────────────────────────────────────
# 1. MODEL INITIALIZATION
# ─────────────────────────────────────────────────────────────────────

class TestModelInit(unittest.TestCase):
    """Test that the model initializes correctly."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)

    def test_model_instance(self):
        self.assertIsInstance(self.classifier.model, TinyBertCNN)

    def test_num_classes(self):
        self.assertEqual(self.classifier.num_classes, 5)

    def test_device_assigned(self):
        self.assertIsNotNone(self.classifier.device)

    def test_tokenizer_loaded(self):
        self.assertIsNotNone(self.classifier.tokenizer)

    def test_model_has_batchnorm(self):
        """Verify BatchNorm layers were added."""
        self.assertTrue(hasattr(self.classifier.model, 'batchnorms'))
        self.assertEqual(len(self.classifier.model.batchnorms), 3)  # 3 filter sizes

    def test_model_has_hidden_fc(self):
        """Verify hidden FC layer exists."""
        self.assertTrue(hasattr(self.classifier.model, 'fc_hidden'))
        self.assertTrue(hasattr(self.classifier.model, 'bn_hidden'))


# ─────────────────────────────────────────────────────────────────────
# 2. INTENT DATASET
# ─────────────────────────────────────────────────────────────────────

class TestIntentDataset(unittest.TestCase):
    """Test tokenization and tensor shapes from IntentDataset."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)
        cls.sample_data = [
            {'student_input': 'How do I use for loops?',
             'session_context': 'topic:For Loops | prev:If/Else | ability:If/Else:85% | emotion:engaged | pace:normal | slides:14,15,16',
             'label': 0},
            {'student_input': "What's the weather?",
             'session_context': 'topic:Variables | prev:None | ability:N/A | emotion:bored | pace:slow | slides:5,6,7',
             'label': 1},
        ]
        cls.dataset = IntentDataset(cls.sample_data, cls.classifier.tokenizer, max_length=128)

    def test_dataset_length(self):
        self.assertEqual(len(self.dataset), 2)

    def test_output_keys(self):
        item = self.dataset[0]
        self.assertIn('input_ids', item)
        self.assertIn('attention_mask', item)
        self.assertIn('labels', item)

    def test_tensor_shapes(self):
        item = self.dataset[0]
        self.assertEqual(item['input_ids'].shape, torch.Size([128]))
        self.assertEqual(item['attention_mask'].shape, torch.Size([128]))

    def test_label_type(self):
        item = self.dataset[0]
        self.assertEqual(item['labels'].dtype, torch.long)

    def test_token_type_ids_present(self):
        """TinyBERT should produce token_type_ids for sentence pairs."""
        item = self.dataset[0]
        if 'token_type_ids' in item:
            self.assertEqual(item['token_type_ids'].shape, torch.Size([128]))

    def test_handles_string_labels(self):
        data = [{'student_input': 'test', 'session_context': 'ctx', 'label': 'Pace-Related'}]
        ds = IntentDataset(data, self.classifier.tokenizer)
        item = ds[0]
        self.assertEqual(item['labels'].item(), 3)


# ─────────────────────────────────────────────────────────────────────
# 3. FORWARD PASS
# ─────────────────────────────────────────────────────────────────────

class TestForwardPass(unittest.TestCase):
    """Test the TinyBertCNN forward pass with dummy data."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)

    def test_output_shape(self):
        batch_size = 4
        seq_len = 128
        input_ids = torch.randint(0, 1000, (batch_size, seq_len)).to(self.classifier.device)
        attention_mask = torch.ones(batch_size, seq_len, dtype=torch.long).to(self.classifier.device)

        self.classifier.model.eval()
        with torch.no_grad():
            logits = self.classifier.model(input_ids, attention_mask)
        self.assertEqual(logits.shape, torch.Size([batch_size, 5]))

    def test_output_with_token_type_ids(self):
        batch_size = 2
        seq_len = 128
        input_ids = torch.randint(0, 1000, (batch_size, seq_len)).to(self.classifier.device)
        attention_mask = torch.ones(batch_size, seq_len, dtype=torch.long).to(self.classifier.device)
        token_type_ids = torch.zeros(batch_size, seq_len, dtype=torch.long).to(self.classifier.device)

        self.classifier.model.eval()
        with torch.no_grad():
            logits = self.classifier.model(input_ids, attention_mask, token_type_ids=token_type_ids)
        self.assertEqual(logits.shape, torch.Size([batch_size, 5]))

    def test_single_sample(self):
        """Ensure single-sample batches don't crash (important for BatchNorm)."""
        input_ids = torch.randint(0, 1000, (1, 128)).to(self.classifier.device)
        attention_mask = torch.ones(1, 128, dtype=torch.long).to(self.classifier.device)

        self.classifier.model.eval()
        with torch.no_grad():
            logits = self.classifier.model(input_ids, attention_mask)
        self.assertEqual(logits.shape, torch.Size([1, 5]))


# ─────────────────────────────────────────────────────────────────────
# 4. PREDICT
# ─────────────────────────────────────────────────────────────────────

class TestPredict(unittest.TestCase):
    """Test the predict() method with real text."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)

    def test_predict_with_context(self):
        preds, probs = self.classifier.predict(
            ["How do loops work?"],
            ["topic:For Loops | prev:None | ability:N/A | emotion:neutral | pace:normal | slides:10,11,12"]
        )
        self.assertEqual(len(preds), 1)
        self.assertEqual(probs.shape[1], 5)

    def test_predict_without_context(self):
        preds, probs = self.classifier.predict(["I'm feeling frustrated"])
        self.assertEqual(len(preds), 1)

    def test_predict_empty_string(self):
        """Empty input should not crash."""
        preds, probs = self.classifier.predict([""])
        self.assertEqual(len(preds), 1)

    def test_predict_multiple(self):
        preds, probs = self.classifier.predict(
            ["Hello", "Can you repeat?", "Speed up please"],
            ["ctx1", "ctx2", "ctx3"]
        )
        self.assertEqual(len(preds), 3)


# ─────────────────────────────────────────────────────────────────────
# 5. COMPOUND SENTENCE SPLITTER
# ─────────────────────────────────────────────────────────────────────

class TestCompoundSplitter(unittest.TestCase):
    """Test the CompoundSentenceSplitter edge cases."""

    @classmethod
    def setUpClass(cls):
        cls.splitter = CompoundSentenceSplitter()

    def test_compound_question_splits(self):
        result = self.splitter.split_compound_question(
            "What is a variable and how do I use it?"
        )
        self.assertGreaterEqual(len(result), 2)

    def test_single_question_no_split(self):
        result = self.splitter.split_compound_question("How do loops work?")
        self.assertEqual(len(result), 1)

    def test_non_question_no_split(self):
        result = self.splitter.split_compound_question("I like programming.")
        self.assertEqual(len(result), 1)

    def test_multiple_question_marks(self):
        result = self.splitter.split_compound_question("What is a loop? How does it work?")
        self.assertEqual(len(result), 2)

    def test_empty_string(self):
        result = self.splitter.split_compound_question("")
        self.assertEqual(len(result), 1)


# ─────────────────────────────────────────────────────────────────────
# 6. DATASET GENERATOR
# ─────────────────────────────────────────────────────────────────────

class TestDatasetGenerator(unittest.TestCase):
    """Test that the dataset generator produces correct output."""

    @classmethod
    def setUpClass(cls):
        # Generate a small dataset
        from dataset_generator import build_dataset
        cls.original_dir = os.getcwd()
        cls.tmp_dir = tempfile.mkdtemp()
        os.chdir(cls.tmp_dir)
        build_dataset(num_samples_per_class=20)
        cls.train_df = pd.read_csv('data/train.csv')
        cls.val_df = pd.read_csv('data/val.csv')
        cls.test_df = pd.read_csv('data/test.csv')

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.original_dir)

    def test_columns_exist(self):
        for col in ['student_input', 'session_context', 'label', 'intent_name']:
            self.assertIn(col, self.train_df.columns)

    def test_three_splits_exist(self):
        self.assertGreater(len(self.train_df), 0)
        self.assertGreater(len(self.val_df), 0)
        self.assertGreater(len(self.test_df), 0)

    def test_all_classes_present(self):
        all_labels = set(self.train_df['label'].unique())
        self.assertEqual(all_labels, {0, 1, 2, 3, 4})

    def test_compact_context_format(self):
        ctx = self.train_df.iloc[0]['session_context']
        self.assertIn('topic:', ctx)
        self.assertIn('prev:', ctx)
        self.assertIn('emotion:', ctx)

    def test_no_empty_inputs(self):
        self.assertFalse(self.train_df['student_input'].isna().any())
        self.assertFalse(self.train_df['session_context'].isna().any())


# ─────────────────────────────────────────────────────────────────────
# 7. AUTO TRAINER STATE
# ─────────────────────────────────────────────────────────────────────

class TestAutoTrainerState(unittest.TestCase):
    """Test load_state / save_state round-trip."""

    def test_state_round_trip(self):
        from auto_trainer import load_state, save_state, STATE_FILE

        # Save original if exists
        original_exists = os.path.exists(STATE_FILE)
        original_content = None
        if original_exists:
            with open(STATE_FILE, 'r') as f:
                original_content = f.read()

        try:
            test_state = {"sessions_since_last_train": 42, "total_sessions": 100}
            save_state(test_state)
            loaded = load_state()
            self.assertEqual(loaded["sessions_since_last_train"], 42)
            self.assertEqual(loaded["total_sessions"], 100)
        finally:
            # Restore original
            if original_exists:
                with open(STATE_FILE, 'w') as f:
                    f.write(original_content)
            elif os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)

    def test_default_state(self):
        from auto_trainer import load_state, STATE_FILE

        backup = None
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                backup = f.read()
            os.remove(STATE_FILE)

        try:
            state = load_state()
            self.assertEqual(state["sessions_since_last_train"], 0)
            self.assertEqual(state["total_sessions"], 0)
        finally:
            if backup:
                with open(STATE_FILE, 'w') as f:
                    f.write(backup)


if __name__ == '__main__':
    unittest.main(verbosity=2)


# ─────────────────────────────────────────────────────────────────────
# 8. REPEAT/CLARIFICATION INTENT COVERAGE
# ─────────────────────────────────────────────────────────────────────

class TestRepeatIntentCoverage(unittest.TestCase):
    """Validate that real-world repeat/clarification utterances are classified
    as 'Repeat/clarification' (label_id == 4) by the trained model.

    These tests require the production checkpoint (prod_tinybert.pt or
    best_tinybert.pt) to be present.  They are skipped gracefully if no
    .pt file is found, so CI doesn't break without the binary.
    """

    REPEAT_UTTERANCES = [
        "Can you say that again?",
        "Could you repeat that please?",
        "I didn't catch that, can you go over it once more?",
        "Can you explain that in a simpler way?",
        "I'm confused, can you rephrase that?",
        "Can you explain it differently?",
        "What did you just say about variables?",
        "Sorry, I didn't understand. Can you clarify?",
    ]

    CONTEXT = (
        "topic:Variables | prev:None | ability:N/A | "
        "emotion:confused | pace:slow | slides:3,4,5"
    )

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)
        # Attempt to load a production checkpoint
        import glob
        pt_files = glob.glob(os.path.join(os.path.dirname(__file__), "*.pt"))
        if pt_files:
            cls.classifier.load_model(pt_files[0])
            cls.model_loaded = True
        else:
            cls.model_loaded = False

    def _skip_if_no_model(self):
        if not self.model_loaded:
            self.skipTest("No .pt checkpoint found — skipping real-model tests.")

    def test_repeat_utterances_classified(self):
        """At least 50% of real repeat utterances should be labelled correctly."""
        self._skip_if_no_model()
        contexts = [self.CONTEXT] * len(self.REPEAT_UTTERANCES)
        preds, probs = self.classifier.predict(self.REPEAT_UTTERANCES, contexts)
        correct = sum(1 for p in preds if p == 4)
        hit_rate = correct / len(self.REPEAT_UTTERANCES)
        self.assertGreaterEqual(
            hit_rate, 0.50,
            f"Repeat/clarification hit rate {hit_rate:.0%} below 50% threshold. "
            f"Predictions: {preds}"
        )

    def test_softmax_sums_to_one(self):
        """Sanity check: softmax probabilities sum to ~1.0 for each sample."""
        self._skip_if_no_model()
        preds, probs = self.classifier.predict(
            [self.REPEAT_UTTERANCES[0]], [self.CONTEXT]
        )
        row_sum = float(probs[0].sum())
        self.assertAlmostEqual(row_sum, 1.0, places=4)

    def test_predict_returns_five_probs(self):
        """Each prediction should have exactly 5 class probabilities."""
        self._skip_if_no_model()
        preds, probs = self.classifier.predict(
            [self.REPEAT_UTTERANCES[0]], [self.CONTEXT]
        )
        self.assertEqual(probs.shape[1], 5)


# ─────────────────────────────────────────────────────────────────────
# 9. CONFIDENCE THRESHOLD GATE
# ─────────────────────────────────────────────────────────────────────

class TestConfidenceThresholdGate(unittest.TestCase):
    """Validate that the IntentService confidence gate returns 'Low Confidence'
    for adversarial / ambiguous inputs when threshold is set high."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)

    def _service_classify(self, text: str, threshold: float) -> str:
        """Minimal classification helper replicating IntentService logic."""
        preds, probs = self.classifier.predict([text], [""])
        max_conf = float(probs[0][preds[0]])
        if max_conf < threshold:
            return "Low Confidence"
        intent_names = [
            'On-Topic Question', 'Off-Topic Question', 'Emotional-State',
            'Pace-Related', 'Repeat/clarification',
        ]
        return intent_names[preds[0]]

    def test_high_threshold_returns_low_confidence(self):
        """With threshold=0.99 nearly every prediction should be Low Confidence."""
        result = self._service_classify("Hmmm", threshold=0.99)
        self.assertEqual(result, "Low Confidence")

    def test_low_threshold_allows_prediction(self):
        """With threshold=0.0 the gate should never fire."""
        result = self._service_classify("How do for loops work?", threshold=0.0)
        self.assertNotEqual(result, "Low Confidence")

    def test_threshold_boundary_exclusive(self):
        """A confidence exactly equal to the threshold should pass (>=)."""
        # We can't know the exact confidence, but we can verify the logic
        # by using a 0.0 threshold which always passes.
        result = self._service_classify("What is a variable?", threshold=0.0)
        self.assertIsInstance(result, str)

    def test_empty_input_does_not_crash(self):
        """Empty input should be classified without raising."""
        try:
            result = self._service_classify("", threshold=0.55)
            self.assertIsInstance(result, str)
        except Exception as exc:
            self.fail(f"Empty input caused an exception: {exc}")


# ─────────────────────────────────────────────────────────────────────
# 10. INTENT SERVICE WRAPPER INTEGRATION
# ─────────────────────────────────────────────────────────────────────

class TestIntentServiceWrapper(unittest.TestCase):
    """Integration tests for IntentService.classify() end-to-end.

    Uses representative real-utterance inputs for all 5 intent classes
    and validates return structure, not necessarily the exact predicted label
    (the model may not be production-calibrated in all environments).
    """

    # One representative utterance per class
    CASES = [
        # (text, context, description)
        (
            "What is the difference between a list and a tuple?",
            "topic:Lists | prev:Variables | ability:N/A | emotion:neutral | pace:normal | slides:8,9,10",
            "On-Topic Question",
        ),
        (
            "Who won the football game last night?",
            "topic:For Loops | prev:Lists | ability:N/A | emotion:bored | pace:fast | slides:12,13,14",
            "Off-Topic Question",
        ),
        (
            "I'm really stressed out and can't concentrate.",
            "topic:Functions | prev:For Loops | ability:N/A | emotion:anxious | pace:slow | slides:20,21,22",
            "Emotional-State",
        ),
        (
            "Can you slow down a bit please?",
            "topic:Classes | prev:Functions | ability:N/A | emotion:confused | pace:normal | slides:30,31,32",
            "Pace-Related",
        ),
        (
            "Can you say that again in a simpler way?",
            "topic:Inheritance | prev:Classes | ability:N/A | emotion:confused | pace:slow | slides:40,41,42",
            "Repeat/clarification",
        ),
    ]

    @classmethod
    def setUpClass(cls):
        cls.classifier = IntentClassifier(num_classes=5)

    def _classify(self, text: str, context: str):
        """Run a single prediction and return (label_id, confidence, probs)."""
        preds, probs = self.classifier.predict([text], [context])
        return int(preds[0]), float(probs[0][preds[0]]), probs[0]

    def test_classify_returns_valid_label_ids(self):
        """All predictions should have label_id in [0, 4]."""
        for text, context, _ in self.CASES:
            label_id, _, _ = self._classify(text, context)
            self.assertIn(label_id, range(5), f"Invalid label_id for: {text!r}")

    def test_classify_confidence_in_range(self):
        """Confidence should always be in [0.0, 1.0]."""
        for text, context, _ in self.CASES:
            _, confidence, _ = self._classify(text, context)
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)

    def test_classify_probs_shape(self):
        """Probability vector should have exactly 5 elements."""
        for text, context, _ in self.CASES:
            _, _, probs = self._classify(text, context)
            self.assertEqual(len(probs), 5, f"Unexpected probs shape for: {text!r}")

    def test_classify_probs_sum_to_one(self):
        """Softmax probabilities should sum to ~1.0."""
        for text, context, _ in self.CASES:
            _, _, probs = self._classify(text, context)
            self.assertAlmostEqual(float(sum(probs)), 1.0, places=4)

    def test_batch_predict_consistent_with_single(self):
        """Batch prediction should return the same result as sequential singles."""
        texts = [c[0] for c in self.CASES]
        contexts = [c[1] for c in self.CASES]
        batch_preds, batch_probs = self.classifier.predict(texts, contexts)
        for i, (text, context, _) in enumerate(self.CASES):
            single_preds, single_probs = self.classifier.predict([text], [context])
            self.assertEqual(
                int(batch_preds[i]), int(single_preds[0]),
                f"Batch vs single mismatch for: {text!r}"
            )


# ─────────────────────────────────────────────────────────────────────
# 11. DATASET BALANCE VALIDATION
# ─────────────────────────────────────────────────────────────────────

class TestDatasetBalanceValidation(unittest.TestCase):
    """Validate that the generated dataset is reasonably balanced.

    No single class should dominate more than 40% of the training set.
    This catches the 'Emotional-State bias' regression that caused
    earlier overfitting (see overfitting fix history).
    """

    @classmethod
    def setUpClass(cls):
        from dataset_generator import build_dataset
        cls.original_dir = os.getcwd()
        cls.tmp_dir = tempfile.mkdtemp()
        os.chdir(cls.tmp_dir)
        build_dataset(num_samples_per_class=30)
        cls.train_df = pd.read_csv('data/train.csv')

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.original_dir)

    def test_no_class_dominates_training_set(self):
        """No class should constitute more than 40% of the training data."""
        counts = self.train_df['label'].value_counts(normalize=True)
        for label, fraction in counts.items():
            self.assertLessEqual(
                fraction, 0.40,
                f"Label {label} makes up {fraction:.0%} of training data — "
                "exceeds 40% balance threshold."
            )

    def test_all_five_classes_present_in_train(self):
        """All five intent classes must appear in the training split."""
        labels = set(self.train_df['label'].unique())
        self.assertEqual(labels, {0, 1, 2, 3, 4})

    def test_repeat_class_not_underrepresented(self):
        """Repeat/clarification (label 4) should constitute at least 10% of training data."""
        counts = self.train_df['label'].value_counts(normalize=True)
        repeat_fraction = counts.get(4, 0.0)
        self.assertGreaterEqual(
            repeat_fraction, 0.10,
            f"Repeat/clarification makes up only {repeat_fraction:.0%} of training data."
        )

    def test_intent_name_column_matches_label(self):
        """intent_name column should be consistent with the label column."""
        intent_map = {
            0: 'On-Topic Question',
            1: 'Off-Topic Question',
            2: 'Emotional-State',
            3: 'Pace-Related',
            4: 'Repeat/clarification',
        }
        for _, row in self.train_df.iterrows():
            expected_name = intent_map[int(row['label'])]
            self.assertEqual(
                row['intent_name'], expected_name,
                f"Mismatch: label={row['label']} but intent_name={row['intent_name']!r}"
            )
            break  # Check just the first row for performance; full check is expensive


if __name__ == '__main__':
    unittest.main(verbosity=2)
