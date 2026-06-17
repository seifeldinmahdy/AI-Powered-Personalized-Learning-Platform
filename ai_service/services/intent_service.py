"""
Intent Classifier Service wrapping the TinyBert-CNN model.

Adds a confidence_threshold gate: when the top softmax probability falls
below the threshold the label is overridden to ``"Low Confidence"`` so the
upstream tutor service can request clarification from the student instead
of acting on a likely-wrong prediction.
"""

import sys
import os
import time
import logging
from typing import List, Dict, Tuple, Optional

try:
    from better_profanity import profanity
    profanity.load_censor_words()
    _PROFANITY_AVAILABLE = True
except ImportError:
    _PROFANITY_AVAILABLE = False

logger = logging.getLogger(__name__)


class IntentService:
    """Wrapper around the TinyBert-CNN intent classifier.

    Parameters
    ----------
    model_path : str
        Filename of the PyTorch checkpoint inside the ``intent_model/``
        directory.  Defaults to ``"best_model.pt"``.
    """

    def __init__(self, model_path: str = "best_model.pt") -> None:
        # Resolve intent_model dir relative to this file, falling back to cwd
        base = os.path.dirname(os.path.abspath(__file__)) if os.path.isabs(__file__) else os.getcwd()
        intent_model_dir = os.path.abspath(os.path.join(base, "intent_model")) \
            if "services" not in base \
            else os.path.abspath(os.path.join(base, "..", "intent_model"))

        if intent_model_dir not in sys.path:
            sys.path.insert(0, intent_model_dir)

        logger.info(f"IntentService: loading TinyBert from {intent_model_dir}")

        import importlib
        tb = importlib.import_module("TinyBert")
        IntentClassifier_ = tb.IntentClassifier
        CompoundSentenceSplitter_ = tb.CompoundSentenceSplitter

        self.intent_model_dir = intent_model_dir
        self.model_path = os.path.join(intent_model_dir, model_path)
        logger.info(f"Initializing IntentService using model: {self.model_path}")

        # Initialize the wrapper class
        self.classifier = IntentClassifier_(num_classes=6)
        self.splitter = CompoundSentenceSplitter_()
        
        # Load the production weights
        if os.path.exists(self.model_path):
            self.classifier.load_model(self.model_path)
            logger.info("Intent model loaded successfully.")
        else:
            # Try cwd-based path as fallback
            fallback = os.path.join(os.getcwd(), "intent_model", model_path)
            if os.path.exists(fallback):
                self.model_path = fallback
                self.classifier.load_model(self.model_path)
                logger.info("Intent model loaded from fallback path.")
            else:
                logger.error(f"Model file not found at: {self.model_path}")
                raise FileNotFoundError(f"Missing intent model: {self.model_path}")
            
    def classify(
        self,
        student_input: str,
        session_context: str = "",
        split_compound: bool = True,
        confidence_threshold: float = 0.65,
    ) -> Tuple[List[Dict], float]:
        """Classify the given student input into pedagogical intents.

        When the maximum softmax probability for a prediction falls below
        ``confidence_threshold``, the returned label is overridden to
        ``"Low Confidence"`` and the raw (unthresholded) prediction is
        preserved in ``raw_prediction`` / ``raw_confidence`` so the caller
        can decide how to handle it (e.g. ask the student to rephrase).

        Parameters
        ----------
        student_input : str
            The student's raw text.
        session_context : str
            Compact key-value context string the model was trained on.
        split_compound : bool
            Whether to split compound sentences before classifying.
        confidence_threshold : float
            Minimum softmax probability to accept a prediction.  Defaults
            to ``0.55``.

        Returns
        -------
        tuple[list[dict], float]
            ``(predictions, inference_time_seconds)``
        """
        start_time = time.time()
        
        # Optionally split compound
        if split_compound:
            segments = self.splitter.split_compound_question(student_input)
        else:
            segments = [student_input]
            
        # Context list
        contexts = [session_context] * len(segments)
        
        try:
            # Batch predict
            preds, probs = self.classifier.predict(segments, contexts)
            
            results: List[Dict] = []
            intent_names = [
                'On-Topic Question',
                'Off-Topic Question',
                'Emotional-State',
                'Pace-Related',
                'Repeat/clarification',
                'Debugging/Code-Sharing',
            ]
            
            # Profanity check on full input (detect but do NOT strip)
            input_has_profanity = False
            if _PROFANITY_AVAILABLE:
                input_has_profanity = profanity.contains_profanity(student_input)
                if input_has_profanity:
                    logger.info("Profanity detected in student input.")
            
            for i, (pred_id, prob_arr) in enumerate(zip(preds, probs)):
                prob_dict = {
                    intent_names[j]: float(prob_arr[j])
                    for j in range(len(intent_names))
                }
                
                max_confidence = float(prob_arr[pred_id])
                predicted_name = intent_names[pred_id]

                # ── Confidence gate ─────────────────────────────────
                if max_confidence < confidence_threshold:
                    results.append({
                        "text": segments[i],
                        "intent_name": "Unknown",
                        "label_id": int(pred_id),
                        "confidence": max_confidence,
                        "probabilities": prob_dict,
                        "raw_prediction": predicted_name,
                        "raw_confidence": max_confidence,
                        "contains_profanity": input_has_profanity,
                    })
                else:
                    results.append({
                        "text": segments[i],
                        "intent_name": predicted_name,
                        "label_id": int(pred_id),
                        "confidence": max_confidence,
                        "probabilities": prob_dict,
                        "raw_prediction": None,
                        "raw_confidence": None,
                        "contains_profanity": input_has_profanity,
                    })
                
            inference_time = time.time() - start_time
            return results, inference_time
            
        except Exception as e:
            logger.error(f"Error during intent classification: {str(e)}")
            raise

# Global instance
_intent_service: Optional[IntentService] = None


def get_intent_service() -> IntentService:
    """Get or create the global intent service instance."""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService()
    return _intent_service


def reload_intent_service(model_path: str = "best_model.pt") -> IntentService:
    """
    Reload the global intent service from a new checkpoint.

    Called after a feedback-aware retraining pipeline promotes a new model.
    If the load fails, the previous service instance is preserved.
    """
    global _intent_service
    previous = _intent_service
    try:
        new_service = IntentService(model_path=model_path)
        _intent_service = new_service
        logger.info("Intent service reloaded from %s", new_service.model_path)
        return new_service
    except Exception as exc:
        logger.exception("Failed to reload intent service from %s", model_path)
        if previous is not None:
            _intent_service = previous
        raise
