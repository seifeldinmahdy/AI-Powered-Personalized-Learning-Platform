"""
Intent Classifier Service wrapping the TinyBert-CNN model.
"""

import sys
import os
import time
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

# Add the intent classifier project explicitly to python path so we can import TinyBert
# Resolve the path relative to the current service file
INTENT_MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Intent_Classifier_Model"))

if INTENT_MODEL_DIR not in sys.path:
    sys.path.insert(0, INTENT_MODEL_DIR)

try:
    from TinyBert import IntentClassifier, CompoundSentenceSplitter
except ImportError as e:
    logger.error(f"Failed to import IntentClassifier from {INTENT_MODEL_DIR}. Error: {e}")
    # Will raise when service is initialized if not fixed

class IntentService:
    def __init__(self, model_path: str = "prod_tinybert.pt"):
        
        self.model_path = os.path.join(INTENT_MODEL_DIR, model_path)
        logger.info(f"Initializing IntentService using model: {self.model_path}")
        
        # Initialize the wrapper class
        self.classifier = IntentClassifier(num_classes=5)
        self.splitter = CompoundSentenceSplitter()
        
        # Load the production weights
        if os.path.exists(self.model_path):
            self.classifier.load_model(self.model_path)
            logger.info("Intent model loaded successfully.")
        else:
            logger.error(f"Model file not found at: {self.model_path}")
            raise FileNotFoundError(f"Missing intent model: {self.model_path}")
            
    def classify(self, student_input: str, session_context: str = "", split_compound: bool = True) -> Tuple[List[Dict], float]:
        """
        Classifies the given input.
        Returns a tuple: (list of prediction dicts, inference_time)
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
            
            results = []
            intent_names = ['On-Topic Question', 'Off-Topic Question', 'Emotional-State', 'Pace-Related', 'Repeat/clarification']
            
            for i, (pred_id, prob_arr) in enumerate(zip(preds, probs)):
                prob_dict = {intent_names[j]: float(prob_arr[j]) for j in range(len(intent_names))}
                
                results.append({
                    "text": segments[i],
                    "intent_name": intent_names[pred_id],
                    "label_id": int(pred_id),
                    "confidence": float(prob_arr[pred_id]),
                    "probabilities": prob_dict
                })
                
            inference_time = time.time() - start_time
            return results, inference_time
            
        except Exception as e:
            logger.error(f"Error during intent classification: {str(e)}")
            raise

# Global instance
_intent_service = None

def get_intent_service() -> IntentService:
    """Get or create the global intent service instance."""
    global _intent_service
    if _intent_service is None:
        _intent_service = IntentService()
    return _intent_service
