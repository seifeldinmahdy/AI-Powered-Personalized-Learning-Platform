"""
Classifier Data Generator — Generates DistilBERT training data.

Focused on visual template classification ONLY: bullets → template_id.
Uses validation and retry-with-feedback.
Supports checkpoint/resume for long generation runs.

Output format: {text: bullet_text, label: template_id}
"""

import json
import os
import random
import re
import signal
import sys
from collections import Counter
from pathlib import Path

import requests
import yaml
from tqdm import tqdm

from slide_gen.core.profile_schema import (
    StudentProfile,
    CompositionMode,
)
from slide_gen.data_engine.utils import (
    VARIATION_GENERATORS,
    is_valid_chunk,
    extract_json_from_response,
)
from slide_gen.core.hierarchy import ALL_TEMPLATE_IDS


# Valid template IDs (all templates + "none")
VALID_TEMPLATE_IDS = ALL_TEMPLATE_IDS

# Template-to-keyword mapping for content validation
# (adapted from factory.py rule 9)
TEMPLATE_KEYWORDS = {
    "linear_chain": ["linked list", "chain", "pointer", "next", "node", "singly", "doubly"],
    "binary_tree": ["tree", "binary", "root", "left", "right", "child", "parent", "leaf"],
    "general_tree": ["tree", "hierarchy", "root", "child", "parent", "trie", "B-tree", "file system", "inheritance"],
    "stack": ["stack", "lifo", "push", "pop"],
    "queue": ["queue", "fifo", "enqueue", "dequeue", "front", "rear"],
    "graph": ["graph", "vertex", "edge", "adjacen", "network", "path", "shortest"],
    # architecture_diagram covers former layered_stack domain (osi, software layers, abstraction)
    "layers": ["layer", "architecture", "abstraction", "tier", "level"],
    "flowchart": ["if", "else", "condition", "decision", "branch", "algorithm"],
    "process_flow": ["step", "process", "procedure", "workflow", "sequence"],
    "comparison": ["compare", "versus", "vs", "difference", "pros", "cons", "advantage"],
    "cycle": ["cycle", "loop", "circular", "repeat", "iterate"],
    "timeline": ["timeline", "history", "year", "version", "evolution", "released"],
    "bar_chart": ["percentage", "frequency", "count", "categories"],
    "architecture_diagram": [
        "neural network", "transformer", "encoder", "decoder", "attention", "LSTM", "CNN", "ResNet",
        "microservices", "pipeline", "compiler", "model architecture", "system architecture",
        "layer", "abstraction", "osi", "software layer", "software stack", "technology stack",
        "tier", "abstraction level", "operating system", "kernel",
    ],
    "sequence": ["message", "request", "response", "actor", "api", "call"],
}


# =========================================================================
# CLASSIFIER-SPECIFIC VALIDATION (relaxed)
# =========================================================================

def validate_classifier_output(
    parsed: dict,
    bullets_text: str,
) -> tuple[bool, str]:
    """
    Validate classifier output quality.

    Rules:
    1. Must have valid template_id
    2. Must have reasoning
    3. Template-content match: accepts if EITHER chunk keywords match
       OR reasoning mentions relevant domain terms. Only rejects
       if both fail (truly wrong classification).
    """
    template_id = parsed.get("template_id", "").strip().lower()
    reasoning = parsed.get("reasoning", "")

    # Rule 1: Valid template ID
    if template_id not in VALID_TEMPLATE_IDS:
        return False, "invalid_template_id"

    # Rule 2: Must include reasoning
    if not reasoning or len(reasoning.strip()) < 10:
        return False, "missing_reasoning"

    # Rule 3: Relaxed template-content match
    # Accept if EITHER the chunk keywords match OR the reasoning is relevant
    if template_id in TEMPLATE_KEYWORDS:
        keywords = TEMPLATE_KEYWORDS[template_id]
        text_lower = bullets_text.lower()
        reasoning_lower = reasoning.lower()

        chunk_matches = any(kw in text_lower for kw in keywords)
        reasoning_matches = any(kw in reasoning_lower for kw in keywords)

        if not chunk_matches and not reasoning_matches:
            return False, "template_content_mismatch"

    return True, "valid"


# =========================================================================
# ERROR FEEDBACK MESSAGES
# =========================================================================

CLASSIFIER_ERROR_FEEDBACK = {
    "invalid_template_id": (
        "ERROR: Invalid template_id. You MUST choose from exactly these options: "
        f"{', '.join(sorted(VALID_TEMPLATE_IDS))}. "
        "Check your spelling carefully."
    ),
    "missing_reasoning": (
        "ERROR: You must include a 'reasoning' field explaining why this template fits. "
        "Example: {\"template_id\": \"stack\", \"reasoning\": \"Content describes LIFO push/pop operations\"}"
    ),
    "json_parse_error": (
        "ERROR: Your output was not valid JSON. "
        "Output ONLY: {\"template_id\": \"...\", \"reasoning\": \"...\"}"
    ),
    "missing_fields": (
        "ERROR: Your JSON must have both 'template_id' and 'reasoning' fields."
    ),
}

# Templates that have no keyword requirements (always pass Rule 3)
KEYWORD_FREE_TEMPLATES = sorted(
    set(VALID_TEMPLATE_IDS) - set(TEMPLATE_KEYWORDS.keys())
)


# =========================================================================
# PARAPHRASE AUGMENTATION FOR RARE CLASSES
# =========================================================================

def augment_rare_classes(
    data_path: str | Path,
    output_path: str | Path,
    ollama_host: str | None = None,
    model: str | None = None,
    min_samples: int = 50,
    paraphrases_per_sample: int = 3,
    api_key: str | None = None,
):
    """
    Augment rare classes by generating LLM paraphrases.

    For every class with fewer than `min_samples` samples,
    generates `paraphrases_per_sample` paraphrased versions of each
    existing sample, keeping the same label.

    Validation:
    - Paraphrased text must be ≥70% different (Jaccard distance)
    - Must share ≥3 content words with original (topical relevance)
    - Retries up to 3 times on failure

    Args:
        data_path: Path to classifier_train.jsonl
        output_path: Path to write augmented data
        ollama_host: Ollama API endpoint
        model: LLM model name
        min_samples: Classes below this threshold get augmented
        paraphrases_per_sample: Number of paraphrases per sample
        api_key: Optional API key for cloud Ollama
    """
    import requests
    from dotenv import load_dotenv
    load_dotenv()

    # Resolve from env if not passed
    ollama_host = (ollama_host or os.getenv("OLLAMA_HOST")).rstrip("/")
    model = model or os.getenv("OLLAMA_MODEL", "llama3")
    api_key = api_key or os.getenv("OLLAMA_API_KEY")

    data_path = Path(data_path)
    output_path = Path(output_path)

    # Load all samples
    samples = []
    with open(data_path) as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    # Find rare classes
    label_counts = Counter(s["label"] for s in samples)
    rare_classes = {label for label, count in label_counts.items() if count < min_samples}

    if not rare_classes:
        print(f"✅ No rare classes (all have ≥{min_samples} samples). Skipping augmentation.")
        # Just copy the original file
        import shutil
        shutil.copy(data_path, output_path)
        return

    print(f"\n🔄 Augmenting {len(rare_classes)} rare classes: {sorted(rare_classes)}")
    for label in sorted(rare_classes):
        print(f"   {label}: {label_counts[label]} samples → target ~{label_counts[label] * (1 + paraphrases_per_sample)}")

    # Generate paraphrases for rare class samples
    augmented = list(samples)  # start with all original samples
    rare_samples = [s for s in samples if s["label"] in rare_classes]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    total_generated = 0
    total_failed = 0

    for idx, sample in enumerate(rare_samples):
        original_text = sample["text"]
        label = sample["label"]

        for p in range(paraphrases_per_sample):
            prompt = (
                f"Rephrase the following educational text passage. "
                f"Keep the same meaning, concepts, and technical terms, "
                f"but change the sentence structure and wording significantly.\n\n"
                f"Original text:\n{original_text}\n\n"
                f"Rephrased text (output ONLY the rephrased text, nothing else):"
            )

            paraphrased = None
            for retry in range(3):
                try:
                    resp = requests.post(
                        f"{ollama_host}/api/generate",
                        headers=headers,
                        json={"model": model, "prompt": prompt, "stream": False},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    candidate = resp.json().get("response", "").strip()

                    # Validate paraphrase quality
                    if _validate_paraphrase(original_text, candidate):
                        paraphrased = candidate
                        break
                except Exception as e:
                    if retry == 2:
                        print(f"   ⚠️ Failed to paraphrase [{label}] sample {idx}: {e}")

            if paraphrased:
                augmented.append({"text": paraphrased, "label": label})
                total_generated += 1
            else:
                total_failed += 1

        if (idx + 1) % 10 == 0:
            print(f"   Processed {idx + 1}/{len(rare_samples)} rare samples...")

    # Write augmented file
    with open(output_path, "w") as f:
        for sample in augmented:
            f.write(json.dumps(sample) + "\n")

    # Summary
    new_counts = Counter(s["label"] for s in augmented)
    print(f"\n✅ Augmentation complete: {total_generated} paraphrases generated, {total_failed} failed")
    print(f"   Original: {len(samples)} → Augmented: {len(augmented)}")
    for label in sorted(rare_classes):
        print(f"   {label}: {label_counts[label]} → {new_counts[label]}")


def _validate_paraphrase(original: str, candidate: str) -> bool:
    """
    Check paraphrase quality:
    - Must be ≥70% different from original (Jaccard distance)
    - Must share ≥3 content words (topical relevance)
    - Must be at least 50 chars
    """
    if not candidate or len(candidate) < 50:
        return False

    # Tokenize into word sets
    orig_words = set(original.lower().split())
    cand_words = set(candidate.lower().split())

    # Jaccard distance: 1 - |intersection| / |union|
    if not orig_words or not cand_words:
        return False
    intersection = orig_words & cand_words
    union = orig_words | cand_words
    jaccard_sim = len(intersection) / len(union)

    # Must be ≥70% different (jaccard similarity ≤ 0.3)
    if jaccard_sim > 0.3:
        return False  # too similar to original

    # Must share ≥3 content words (not just stopwords)
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
                 "to", "for", "of", "and", "or", "but", "with", "by", "from",
                 "that", "this", "it", "as", "be", "has", "have", "had", "do",
                 "does", "did", "will", "would", "can", "could", "not", "no"}
    content_overlap = len(intersection - stopwords)
    if content_overlap < 3:
        return False  # not topically related

    return True


def get_classifier_feedback(error_code: str, chunk_text: str = "") -> str:
    """
    Get feedback message for classifier validation error.

    For template_content_mismatch, generates a DYNAMIC message that tells
    the LLM exactly which templates match the chunk's keywords.
    """
    if error_code == "template_content_mismatch" and chunk_text:
        return _build_mismatch_feedback(chunk_text)

    return CLASSIFIER_ERROR_FEEDBACK.get(
        error_code,
        f"ERROR: {error_code.replace('_', ' ')}. Please fix this issue."
    )


def _build_mismatch_feedback(chunk_text: str) -> str:
    """Build a specific feedback message listing which templates match the chunk."""
    text_lower = chunk_text.lower()

    # Find all templates whose keywords match this chunk
    matching = []
    for template, keywords in TEMPLATE_KEYWORDS.items():
        matched_kws = [kw for kw in keywords if kw in text_lower]
        if matched_kws:
            matching.append((template, matched_kws))

    msg = (
        "ERROR: Your chosen template doesn't match this content. "
    )

    if matching:
        msg += "Based on the keywords in the text, these templates are valid:\n"
        for template, kws in matching:
            msg += f"  - \"{template}\" (matched: {', '.join(kws[:3])})\n"
    else:
        msg += "No keyword-specific templates match this text. "

    msg += (
        f"\nThese templates are ALWAYS valid (no keyword requirements): "
        f"{', '.join(KEYWORD_FREE_TEMPLATES)}.\n"
        f"Pick the template that best fits, or use 'concept_box' for general content."
    )

    return msg


# =========================================================================
# CLASSIFIER DATA GENERATOR
# =========================================================================

class ClassifierDataGenerator:
    """
    Generates DistilBERT training data: bullets → template_id.

    Can operate in two modes:
    1. From raw PDF chunks (generates bullets via content generator first)
    2. From existing content_train.jsonl (uses pre-generated bullets)

    Supports checkpoint/resume for both modes.
    """

    def __init__(
        self,
        prompts_path: str | Path,
        output_dir: str | Path,
        ollama_host: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        api_key: str | None = None,
        call_override=None,
    ):
        # Load .env for defaults
        from dotenv import load_dotenv
        load_dotenv()

        # Optional transport override: a callable (system_prompt, user_prompt) ->
        # str | None. When set, classification calls route through it instead of
        # the Ollama /api/generate HTTP path (used to classify via NVIDIA NIM).
        self.call_override = call_override

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ollama_host = (ollama_host or os.getenv("OLLAMA_HOST")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3")
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("MAX_RETRIES", "3"))
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY")

        # Load focused classifier prompts
        prompts = self._load_prompts(prompts_path)
        self.system_prompt = prompts["classifier_system_prompt"]
        self.user_template = prompts["classifier_user_template"]

        # Statistics
        self.stats = {
            "generated": 0,
            "failed": 0,
            "label_distribution": Counter(),
            "error_counts": {},
        }

    @staticmethod
    def _load_prompts(path: str | Path) -> dict:
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _call_ollama(self, prompt: str) -> str | None:
        """Call the LLM and return response text.

        If a transport override is set (e.g. NVIDIA NIM), route through it;
        otherwise hit the Ollama /api/generate endpoint.
        """
        if self.call_override is not None:
            return self.call_override(self.system_prompt, prompt)

        url = f"{self.ollama_host}/api/generate"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": self.system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            },
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result.get("response", "")
        except requests.RequestException as e:
            print(f"    Ollama API error: {e}")
            return None

    def _format_prompt(self, bullets_text: str, title: str) -> str:
        """Format the classifier prompt."""
        return self.user_template.format(
            bullets_text=bullets_text,
            title=title,
        )

    def classify_one(
        self,
        bullets_text: str,
        title: str = "",
    ) -> dict | None:
        """
        Classify a single set of bullets with retry-feedback.

        Returns {text, label} dict or None if all retries fail.
        """
        base_prompt = self._format_prompt(bullets_text, title)
        last_error = None
        prompt = base_prompt

        for attempt in range(self.max_retries):
            # Append feedback on retry
            if attempt > 0 and last_error:
                feedback = get_classifier_feedback(last_error, chunk_text=bullets_text)
                prompt = (
                    f"{base_prompt}\n\n"
                    f"## PREVIOUS ATTEMPT FEEDBACK:\n{feedback}\n\n"
                    f"Fix the issue. Output ONLY valid JSON."
                )

            response_text = self._call_ollama(prompt)

            if not response_text:
                last_error = "no_response"
                continue

            # Parse JSON
            parsed = extract_json_from_response(response_text)
            if not parsed:
                last_error = "json_parse_error"
                self._track_error("json_parse_error")
                continue

            # Check required fields
            if "template_id" not in parsed:
                last_error = "missing_fields"
                self._track_error("missing_fields")
                continue

            # Normalize template_id
            parsed["template_id"] = parsed["template_id"].strip().lower()

            # Validate
            is_valid, error_code = validate_classifier_output(parsed, bullets_text)
            if not is_valid:
                last_error = error_code
                self._track_error(error_code)
                continue

            # Success!
            label = parsed["template_id"]
            return {"text": bullets_text, "label": label}

        return None

    def _track_error(self, error_code: str):
        """Track error frequency."""
        self.stats["error_counts"][error_code] = (
            self.stats["error_counts"].get(error_code, 0) + 1
        )

    def run_from_content_data(
        self,
        content_jsonl_path: str | Path,
        output_filename: str = "classifier_train.jsonl",
        resume: bool = True,
        append: bool = False,
    ) -> tuple[int, int]:
        """
        Generate classifier data from existing content_train.jsonl.

        Supports checkpoint/resume.

        Args:
            content_jsonl_path: Path to content_train.jsonl
            output_filename: Output JSONL filename
            resume: If True, resume from last checkpoint

        Returns:
            (total_generated, total_examples_processed)
        """
        content_jsonl_path = Path(content_jsonl_path)
        output_path = self.output_dir / output_filename
        checkpoint_path = self.output_dir / f".{output_filename}.checkpoint.json"

        # Load content examples
        examples = []
        with open(content_jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    examples.append(json.loads(line))

        # ---- Resume logic ----
        start_idx = 0
        already_generated = 0
        already_failed = 0

        if resume and checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text())
            start_idx = checkpoint.get("idx", 0)
            already_generated = checkpoint.get("generated", 0)
            already_failed = checkpoint.get("failed", 0)

            print(f"\n♻️  RESUMING from checkpoint:")
            print(f"   Example {start_idx + 1}/{len(examples)}")
            print(f"   Already generated: {already_generated}")
            print(f"   Skipping {start_idx} completed examples")
        else:
            if not append and output_path.exists():
                output_path.unlink()
            if checkpoint_path.exists():
                checkpoint_path.unlink()

        self.stats = {
            "generated": already_generated,
            "failed": already_failed,
            "label_distribution": Counter(),
            "error_counts": {},
        }

        print(f"\n📊 Loaded {len(examples)} content examples from {content_jsonl_path}")
        print(f"🔄 Classifying each into visual templates...\n")

        # ---- Graceful shutdown ----
        shutdown_requested = False

        def handle_signal(signum, frame):
            nonlocal shutdown_requested
            if shutdown_requested:
                print("\n\n⚠️  Force exit (checkpoint already saved)")
                sys.exit(1)
            shutdown_requested = True
            print("\n\n⏸️  Graceful shutdown — saving checkpoint...")

        original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, handle_signal)

        try:
            with tqdm(total=len(examples), initial=start_idx,
                      desc="Classifier generation") as pbar:
                for idx in range(start_idx, len(examples)):
                    if shutdown_requested:
                        self._save_checkpoint(checkpoint_path, idx,
                                              self.stats["generated"], self.stats["failed"])
                        print(f"   ✅ Checkpoint saved at example {idx + 1}")
                        print(f"   Run the same command to resume.\n")
                        self._print_summary(output_path, len(examples))
                        return self.stats["generated"], len(examples)

                    example = examples[idx]
                    target = example.get("target", "")
                    title, bullets_text = self._parse_t5_target(target)

                    if not bullets_text:
                        self.stats["failed"] += 1
                    else:
                        result = self.classify_one(bullets_text, title)
                        if result:
                            self.stats["generated"] += 1
                            self.stats["label_distribution"][result["label"]] += 1
                            with open(output_path, "a") as f:
                                f.write(json.dumps(result) + "\n")
                        else:
                            self.stats["failed"] += 1

                    # Save checkpoint
                    self._save_checkpoint(checkpoint_path, idx + 1,
                                          self.stats["generated"], self.stats["failed"])

                    pbar.set_postfix({
                        "ok": self.stats["generated"],
                        "fail": self.stats["failed"],
                    })
                    pbar.update(1)

        except Exception as e:
            self._save_checkpoint(checkpoint_path, idx,
                                  self.stats["generated"], self.stats["failed"])
            print(f"\n\n❌ Error: {e}")
            print(f"   ✅ Checkpoint saved — run again to resume.")
        finally:
            signal.signal(signal.SIGINT, original_sigint)

        # Complete — remove checkpoint
        if not shutdown_requested and checkpoint_path.exists():
            checkpoint_path.unlink()
            print("\n🎉 Generation complete — checkpoint cleared.")

        self._print_summary(output_path, len(examples))
        return self.stats["generated"], len(examples)

    def run_from_chunks(
        self,
        chunks: list[str],
        output_filename: str = "classifier_train.jsonl",
        resume: bool = True,
        append: bool = False,
    ) -> tuple[int, int]:
        """
        Generate classifier data directly from PDF chunks.

        Supports checkpoint/resume.

        Args:
            chunks: Text chunks from PDFs
            output_filename: Output JSONL filename
            resume: If True, resume from last checkpoint

        Returns:
            (total_generated, total_valid_chunks)
        """
        output_path = self.output_dir / output_filename
        checkpoint_path = self.output_dir / f".{output_filename}.checkpoint.json"

        # Filter chunks (deterministic — same order every run)
        valid_chunks = []
        for chunk in chunks:
            is_valid, _ = is_valid_chunk(chunk)
            if is_valid:
                valid_chunks.append(chunk)

        # ---- Resume logic ----
        start_idx = 0
        already_generated = 0
        already_failed = 0

        if resume and checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text())
            start_idx = checkpoint.get("idx", 0)
            already_generated = checkpoint.get("generated", 0)
            already_failed = checkpoint.get("failed", 0)

            print(f"\n♻️  RESUMING from checkpoint:")
            print(f"   Chunk {start_idx + 1}/{len(valid_chunks)}")
            print(f"   Already generated: {already_generated}")
            print(f"   Skipping {start_idx} completed chunks")
        else:
            if not append and output_path.exists():
                output_path.unlink()
            if checkpoint_path.exists():
                checkpoint_path.unlink()

        self.stats = {
            "generated": already_generated,
            "failed": already_failed,
            "label_distribution": Counter(),
            "error_counts": {},
        }

        print(f"\n📊 Valid chunks: {len(valid_chunks)} / {len(chunks)}")
        print(f"🔄 Classifying chunks into visual templates...\n")

        # ---- Graceful shutdown ----
        shutdown_requested = False

        def handle_signal(signum, frame):
            nonlocal shutdown_requested
            if shutdown_requested:
                print("\n\n⚠️  Force exit (checkpoint already saved)")
                sys.exit(1)
            shutdown_requested = True
            print("\n\n⏸️  Graceful shutdown — saving checkpoint...")

        original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, handle_signal)

        try:
            with tqdm(total=len(valid_chunks), initial=start_idx,
                      desc="Classifier generation") as pbar:
                for idx in range(start_idx, len(valid_chunks)):
                    if shutdown_requested:
                        self._save_checkpoint(checkpoint_path, idx,
                                              self.stats["generated"], self.stats["failed"])
                        print(f"   ✅ Checkpoint saved at chunk {idx + 1}")
                        print(f"   Run the same command to resume.\n")
                        self._print_summary(output_path, len(valid_chunks))
                        return self.stats["generated"], len(valid_chunks)

                    chunk = valid_chunks[idx]
                    title = chunk.split(".")[0][:80] if "." in chunk else chunk[:80]

                    result = self.classify_one(chunk, title)

                    if result:
                        self.stats["generated"] += 1
                        self.stats["label_distribution"][result["label"]] += 1
                        with open(output_path, "a") as f:
                            f.write(json.dumps(result) + "\n")
                    else:
                        self.stats["failed"] += 1

                    # Save checkpoint
                    self._save_checkpoint(checkpoint_path, idx + 1,
                                          self.stats["generated"], self.stats["failed"])

                    pbar.set_postfix({
                        "ok": self.stats["generated"],
                        "fail": self.stats["failed"],
                    })
                    pbar.update(1)

        except Exception as e:
            self._save_checkpoint(checkpoint_path, idx,
                                  self.stats["generated"], self.stats["failed"])
            print(f"\n\n❌ Error: {e}")
            print(f"   ✅ Checkpoint saved — run again to resume.")
        finally:
            signal.signal(signal.SIGINT, original_sigint)

        # Complete — remove checkpoint
        if not shutdown_requested and checkpoint_path.exists():
            checkpoint_path.unlink()
            print("\n🎉 Generation complete — checkpoint cleared.")

        self._print_summary(output_path, len(valid_chunks))
        return self.stats["generated"], len(valid_chunks)

    @staticmethod
    def _save_checkpoint(path: Path, idx: int, generated: int, failed: int):
        """Save progress checkpoint to disk."""
        checkpoint = {
            "idx": idx,
            "generated": generated,
            "failed": failed,
        }
        path.write_text(json.dumps(checkpoint))

    @staticmethod
    def _parse_t5_target(target: str) -> tuple[str, str]:
        """
        Parse T5 target format to extract title and bullets text.

        Input format:
            TITLE: Understanding Stacks
            BULLET [definition]: A stack works like...
            BULLET [none]: Items added from top...

        Returns (title, bullets_text)
        """
        title = ""
        bullets = []

        for line in target.strip().split("\n"):
            line = line.strip()
            if line.startswith("TITLE:"):
                title = line[6:].strip()
            elif line.startswith("BULLET"):
                # Remove "BULLET [highlight]:" prefix
                idx = line.find(":")
                if idx > 0:
                    bullets.append(line[idx + 1:].strip())

        return title, " ".join(bullets)

    def _print_summary(self, output_path: Path, total: int):
        """Print comprehensive classifier generation analytics."""
        generated = self.stats["generated"]
        failed = self.stats["failed"]
        success_rate = generated / max(total, 1) * 100

        print(f"\n{'=' * 70}")
        print("📊 CLASSIFIER DATA GENERATION ANALYTICS")
        print(f"{'=' * 70}")

        # ── Overview ──
        print(f"\n📋 Overview:")
        print(f"   Total processed:        {total}")
        print(f"   Successfully generated:  {generated}")
        print(f"   Failed:                 {failed}")
        print(f"   Success rate:           {success_rate:.1f}%")
        print(f"   Unique classes:         {len(self.stats['label_distribution'])}")

        # ── Label Distribution ──
        if self.stats["label_distribution"]:
            dist = self.stats["label_distribution"]
            max_count = max(dist.values()) if dist else 1
            min_count = min(dist.values()) if dist else 0
            imbalance_ratio = max_count / max(min_count, 1)

            print(f"\n📊 Label Distribution:")
            for label, count in dist.most_common():
                pct = count / max(generated, 1) * 100
                bar_len = int(count / max_count * 30)
                bar = "█" * bar_len
                print(f"   {label:20s}: {count:4d} ({pct:5.1f}%) {bar}")

            # ── Class Balance Metrics ──
            counts = list(dist.values())
            avg_count = sum(counts) / len(counts)
            median_count = sorted(counts)[len(counts) // 2]

            print(f"\n⚖️  Class Balance:")
            print(f"   Largest class:   {dist.most_common(1)[0][0]} ({max_count} samples)")
            print(f"   Smallest class:  {dist.most_common()[-1][0]} ({min_count} samples)")
            print(f"   Imbalance ratio: {imbalance_ratio:.1f}x")
            print(f"   Avg per class:   {avg_count:.1f}")
            print(f"   Median per class: {median_count}")

            # ── Rare Class Warnings ──
            rare_threshold = 50
            rare_classes = [(label, count) for label, count in dist.items() if count < rare_threshold]
            if rare_classes:
                print(f"\n⚠️  Rare Classes (below {rare_threshold} samples — candidates for augmentation):")
                for label, count in sorted(rare_classes, key=lambda x: x[1]):
                    deficit = rare_threshold - count
                    print(f"   {label:20s}: {count:3d} samples (need ~{deficit} more)")
            else:
                print(f"\n✅ All classes have ≥{rare_threshold} samples")

            # ── Hierarchical Category Preview ──
            from slide_gen.core.hierarchy import get_category
            cat_dist = Counter()
            for label, count in dist.items():
                cat = get_category(label)
                cat_dist[cat] += count

            print(f"\n🔀 By Category ({len(dist)} templates → {len(cat_dist)} categories):")
            for cat, count in cat_dist.most_common():
                pct = count / max(generated, 1) * 100
                print(f"   {cat:20s}: {count:4d} ({pct:5.1f}%)")

        # ── Error Breakdown ──
        if self.stats["error_counts"]:
            print(f"\n❌ Error Breakdown:")
            total_errors = sum(self.stats["error_counts"].values())
            for err, count in sorted(
                self.stats["error_counts"].items(), key=lambda x: -x[1]
            ):
                pct = count / total_errors * 100
                print(f"   {err:35s}: {count:4d} ({pct:4.1f}%)")

        print(f"\n📁 Output: {output_path}")
        print(f"{'=' * 70}")

