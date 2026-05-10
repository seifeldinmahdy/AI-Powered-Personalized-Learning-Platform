import sys
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "slides-generator/src"))

from slide_gen.agents.content_specialist import DEFAULT_MODEL_PATH
from transformers import AutoModelForSeq2SeqLM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("transformers.modeling_utils")
logger.setLevel(logging.INFO)

print("== Loading Model with INFO logging ==")
model = AutoModelForSeq2SeqLM.from_pretrained(DEFAULT_MODEL_PATH)
