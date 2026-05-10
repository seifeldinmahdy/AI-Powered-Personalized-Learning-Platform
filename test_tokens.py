import sys
from pathlib import Path
from transformers import AutoTokenizer

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "slides-generator/src"))

from slide_gen.agents.content_specialist import _load_model, format_input, DEFAULT_MODEL_PATH

chunk = "Python is an interpreted high-level general-purpose programming language."
profile = {"mastery_level": "Novice", "composition_mode": "Balanced", "language_proficiency": "Intermediate"}

print("== Loading Model ==")
model, _ = _load_model(DEFAULT_MODEL_PATH)
input_text = format_input(chunk, profile)

tokenizer = AutoTokenizer.from_pretrained(DEFAULT_MODEL_PATH)
inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True)

outputs = model.generate(**inputs, max_length=20)   # Default greedy decoding
print("GREEDY OUTPUT:", tokenizer.decode(outputs[0], skip_special_tokens=True))
