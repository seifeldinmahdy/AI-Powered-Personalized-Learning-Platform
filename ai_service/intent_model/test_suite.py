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
