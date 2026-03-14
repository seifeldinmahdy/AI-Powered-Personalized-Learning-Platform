"""
Content Data Generator — Generates T5 training data.

Focused on generating title + bullets ONLY. No visuals, code, or a11y.
Uses validation and retry-with-feedback from the original factory.

Output format: {input: text+profile, target: "TITLE:...\nBULLET:..."}
"""

import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import requests
import yaml
from tqdm import tqdm

from slide_gen.core.profile_schema import (
    StudentProfile,
    MasteryLevel,
    CompositionMode,
    LanguageProficiency,
)
from slide_gen.data_engine.utils import (
    VARIATION_GENERATORS,
    format_training_input,
    is_valid_chunk,
    extract_json_from_response,
)


# =========================================================================
# CONTENT-SPECIFIC VALIDATION
# =========================================================================

# Generic titles to reject
GENERIC_TITLES = [
    "introduction", "overview", "summary", "conclusion", "review",
    "chapter", "section", "slide", "page", "content", "topic",
    "untitled", "title", "heading", "main", "part",
]

# Code patterns to detect in bullets (short, distinctive constructs)
# A bullet with 2+ of these is considered "code-contaminated"
# IMPORTANT: every pattern must be code-specific — NO natural English words
#
# REMOVED as too risky for English false positives:
#   "import " (matches "we import data"), "except " ("except for"),
#   "raise " ("raise concerns"), "yield " ("yield results"),
#   "assert " ("assert that"), "document." ("the document."),
#   "window." ("the window."), "lambda " ("lambda functions")
BULLET_CODE_PATTERNS = [
    # Python built-in functions (parenthesis makes them code-specific)
    "print(", "input(", "len(", "range(", "type(",
    "int(", "str(", "float(", "list(", "dict(",
    "sorted(", "enumerate(", "zip(", "map(", "filter(",
    "open(", "isinstance(", "hasattr(", "getattr(",
    "super(", "iter(", "next(",
    # Python syntax (colon/underscore/specific combos — no English overlap)
    "def ", "return(",
    ">>> ", "try:", "except:", "finally:",
    "if __name__", "elif ",
    "for i in", "for _ in",
    "with open", "as f:", "as e:",
    # Python methods (dot + parenthesis = code-only)
    ".append(", ".extend(", ".insert(", ".remove(", ".pop(",
    ".format(", ".join(", ".split(", ".strip(", ".replace(",
    ".keys()", ".values()", ".items()",
    ".read(", ".write(", ".close(",
    "self.", "__init__", "__str__", "__repr__", "__len__",
    "@property", "@staticmethod", "@classmethod",
    # Python operators (very specific syntax)
    " := ", " **= ", " //= ",
    # JavaScript (API-specific, not English words)
    "console.log(", "document.get", "document.query",
    "document.create", "window.location", "window.addEventListener",
    "function(", ".then(", ".catch(",
    "=> {", "=> (",
    "addEventListener(", "querySelector(",
    "require(", "module.exports", "import(",
    "JSON.parse(", "JSON.stringify(",
    # Java / C / C++ (distinctive syntax)
    "public static", "System.out", "void main",
    "printf(", "scanf(", "cout <<", "cin >>",
    "#include", "std::", "malloc(", "free(",
    "nullptr",
    # SQL (multi-word patterns — no English overlap)
    "SELECT ", "INSERT INTO", "DELETE FROM",
    "CREATE TABLE", "ALTER TABLE",
    # Assignment patterns (= followed by specific values)
    "= True", "= False", "= None",
    # Semicolon-terminated (always code)
    "null;", "undefined;", "true;", "false;",
    "++;", "--;",
]


def validate_content_output(
    parsed: dict,
    profile: StudentProfile,
) -> tuple[bool, str]:
    """
    Validate content-specific output quality.

    Adapted from factory.is_valid_output, keeping only content-relevant rules.
    """
    title = parsed.get("title", "")
    bullets = parsed.get("bullets", [])

    # Rule 1: Title must exist and be meaningful (≥ 5 chars)
    if not title or len(title.strip()) < 5:
        return False, "invalid_title"

    # Rule 2: No generic titles
    title_lower = title.strip().lower()
    if title_lower in GENERIC_TITLES:
        return False, "generic_title"
    for generic in ["chapter", "section", "part", "slide", "page"]:
        if title_lower.startswith(generic):
            return False, "generic_title"

    # Rule 3: Must have at least 1 bullet
    if not bullets or len(bullets) == 0:
        return False, "no_bullets"

    # Rule 4: Bullets must be list of dicts with 'text' field
    for b in bullets:
        if not isinstance(b, dict) or "text" not in b:
            return False, "invalid_bullet_format"

    # Rule 5: Bullet count by composition mode
    count = len(bullets)
    mode = profile.composition_mode

    if mode == CompositionMode.VISUAL_HEAVY:
        if count > 3:
            return False, "visual_heavy_too_many_bullets"
    elif mode == CompositionMode.TEXT_HEAVY:
        if count < 4:
            return False, "text_heavy_too_few_bullets"
    elif mode == CompositionMode.BALANCED:
        if count < 2 or count > 5:
            return False, "balanced_wrong_bullet_count"

    # Rule 6: No duplicate bullets
    bullet_texts = [b["text"].strip().lower() for b in bullets]
    if len(bullet_texts) != len(set(bullet_texts)):
        return False, "duplicate_bullets"

    # Rule 7: Minimum bullet length (≥ 10 chars)
    for b in bullets:
        if len(b["text"].strip()) < 10:
            return False, "bullet_too_short"

    # Rule 8: Highlight variety for 4+ bullets
    if len(bullets) >= 4:
        highlight_types = [b.get("highlight_type", "none") for b in bullets]
        if len(set(highlight_types)) == 1:
            return False, "no_highlight_variety"

    # Rule 9: Valid highlight types
    valid_highlights = {"none", "definition", "example", "key_concept", "attention", "code"}
    for b in bullets:
        ht = b.get("highlight_type", "none")
        if ht not in valid_highlights:
            return False, "invalid_highlight_type"

    # Rule 10: No raw code in bullets
    for b in bullets:
        text = b["text"]
        # Check for explicit code patterns
        text_lower = text.lower()
        code_pattern_count = sum(1 for p in BULLET_CODE_PATTERNS if p in text)
        if code_pattern_count >= 2:
            return False, "bullet_has_code"
        # Check for high density of code characters
        code_chars = sum(1 for c in text if c in "(){}[];=")
        if len(text) > 0 and code_chars / len(text) > 0.08:
            return False, "bullet_has_code"

    # Rule 11: Definition validation
    definitions = [b for b in bullets if b.get("term")]
    if len(definitions) > 2:
        return False, "too_many_definitions"
    for d in definitions:
        term = d["term"].strip()
        if len(term) < 2 or len(term) > 50:
            return False, "invalid_term_length"
        if d.get("highlight_type", "none") != "definition":
            return False, "term_requires_definition_highlight"

    return True, "valid"


# =========================================================================
# ERROR FEEDBACK MESSAGES (for retry self-correction)
# =========================================================================

CONTENT_ERROR_FEEDBACK = {
    "invalid_title": (
        "ERROR: Your title is too short or empty. "
        "Provide a meaningful, descriptive title with at least 5 characters."
    ),
    "generic_title": (
        "ERROR: Your title is too generic (e.g., 'Introduction', 'Overview'). "
        "Create a specific, descriptive title that reflects the actual content."
    ),
    "no_bullets": (
        "ERROR: You did not include any bullets. "
        "Add bullet points with text and highlight_type."
    ),
    "invalid_bullet_format": (
        "ERROR: Each bullet must be an object with 'text' and 'highlight_type' fields. "
        "Example: {\"text\": \"Your point here\", \"highlight_type\": \"none\"}"
    ),
    "visual_heavy_too_many_bullets": (
        "ERROR: Visual_Heavy mode should have 1-2 bullet points (max 3), but you included more. "
        "Reduce to 2 concise bullet points."
    ),
    "text_heavy_too_few_bullets": (
        "ERROR: Text_Heavy mode should have 4-6 bullet points, but you only included a few. "
        "Add more detailed bullet points to explain the concept thoroughly."
    ),
    "balanced_wrong_bullet_count": (
        "ERROR: Balanced mode should have 2-4 bullet points. "
        "Adjust your bullets to have exactly 3 bullet points."
    ),
    "duplicate_bullets": (
        "ERROR: Your bullets have duplicate text. "
        "Each bullet must have unique content — no repeating the same text."
    ),
    "bullet_too_short": (
        "ERROR: One or more bullets are too short (less than 10 characters). "
        "Each bullet must have meaningful content, not just a few words."
    ),
    "no_highlight_variety": (
        "ERROR: You have 4+ bullets but all have the same highlight_type. "
        "Use a MIX of highlight types: definition, example, key_concept, none."
    ),
    "invalid_highlight_type": (
        "ERROR: Invalid highlight_type. Valid types are: none, definition, "
        "example, key_concept, attention, code."
    ),
    "bullet_has_code": (
        "ERROR: Your bullets contain raw code syntax (e.g., print(), def, try/except, >>>). "
        "Do NOT paste code into bullets. A separate Code Extractor agent handles the actual code. "
        "Your job is to explain the CONCEPT in plain natural language. "
        "BAD: 'Use try: print(math.sqrt(x)) except: print(error)' "
        "GOOD: 'The try/except construct captures runtime errors and allows graceful recovery'"
    ),
    "json_parse_error": (
        "ERROR: Your output was not valid JSON. "
        "Output ONLY a valid JSON object with no markdown, no explanations."
    ),
    "missing_fields": (
        "ERROR: Your JSON is missing required fields. "
        "You MUST include: title (string), bullets (array of {text, highlight_type})."
    ),
}


def get_content_feedback(error_code: str) -> str:
    """Get feedback message for content validation error."""
    return CONTENT_ERROR_FEEDBACK.get(
        error_code,
        f"ERROR: {error_code.replace('_', ' ')}. Please fix this issue."
    )


# =========================================================================
# CONTENT DATA GENERATOR
# =========================================================================

class ContentDataGenerator:
    """
    Generates T5 training data: text+profile → title+bullets.

    Uses Ollama with focused content-only prompts and
    validation with retry-feedback for self-correction.
    """

    def __init__(
        self,
        prompts_path: str | Path,
        output_dir: str | Path,
        ollama_host: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        api_key: str | None = None,
    ):
        # Load .env for defaults
        from dotenv import load_dotenv
        load_dotenv()

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ollama_host = (ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3")
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("MAX_RETRIES", "3"))
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY")

        # Load focused content prompts
        prompts = self._load_prompts(prompts_path)
        self.system_prompt = prompts["content_system_prompt"]
        self.user_template = prompts["content_user_template"]

        # Statistics
        self.stats = {
            "generated": 0,
            "failed": 0,
            "discarded_chunk": 0,
            "error_counts": {},
        }

    @staticmethod
    def _load_prompts(path: str | Path) -> dict:
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _call_ollama(self, prompt: str) -> str | None:
        """Call Ollama API (local or cloud) and return response text."""
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

    def _format_prompt(self, chunk: str, profile: StudentProfile) -> str:
        """Format the user prompt with chunk and profile."""
        return self.user_template.format(
            context=chunk,
            mastery_level=profile.mastery_level.value,
            composition_mode=profile.composition_mode.value,
            language_proficiency=profile.language_proficiency.value,
        )

    def _format_t5_target(self, parsed: dict) -> str:
        """
        Convert parsed JSON to T5 plain-text target format.

        Format:
            TITLE: Understanding Stacks
            DEFINE [Stack]: A linear data structure following LIFO ordering
            BULLET [none]: Items are added and removed from the top
        """
        lines = [f"TITLE: {parsed['title']}"]
        for b in parsed["bullets"]:
            ht = b.get("highlight_type", "none")
            term = b.get("term")
            if term and ht == "definition":
                lines.append(f"DEFINE [{term}]: {b['text']}")
            else:
                lines.append(f"BULLET [{ht}]: {b['text']}")
        return "\n".join(lines)

    def generate_one(
        self,
        chunk: str,
        profile: StudentProfile,
    ) -> dict | None:
        """
        Generate a single content training example with retry-feedback.

        Returns {input, target} dict or None if all retries fail.
        """
        base_prompt = self._format_prompt(chunk, profile)
        last_error = None
        prompt = base_prompt

        for attempt in range(self.max_retries):
            # Append feedback on retry
            if attempt > 0 and last_error:
                feedback = get_content_feedback(last_error)
                prompt = (
                    f"{base_prompt}\n\n"
                    f"## PREVIOUS ATTEMPT FEEDBACK:\n{feedback}\n\n"
                    f"Please fix this issue and try again. Output ONLY valid JSON."
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
            if "title" not in parsed or "bullets" not in parsed:
                last_error = "missing_fields"
                self._track_error("missing_fields")
                continue

            # Validate quality
            is_valid, error_code = validate_content_output(parsed, profile)
            if not is_valid:
                last_error = error_code
                self._track_error(error_code)
                continue

            # Success! Format as T5 training example
            input_text = format_training_input(chunk, profile)
            target_text = self._format_t5_target(parsed)

            return {"input": input_text, "target": target_text}

        return None

    def _track_error(self, error_code: str):
        """Track error frequency for reporting."""
        self.stats["error_counts"][error_code] = (
            self.stats["error_counts"].get(error_code, 0) + 1
        )

    def run(
        self,
        chunks: list[str],
        output_filename: str = "content_train.jsonl",
        resume: bool = True,
    ) -> tuple[int, int]:
        """
        Run content data generation on all chunks with all profile variations.

        Supports checkpoint/resume: saves progress after each example so
        generation can be paused (Ctrl+C or rate limit) and resumed later
        from the exact chunk+variation where it stopped.

        Args:
            chunks: Text chunks from PDFs
            output_filename: Output JSONL filename
            resume: If True, resume from last checkpoint. If False, start fresh.

        Returns:
            (total_generated, total_valid_chunks)
        """
        import signal

        output_path = self.output_dir / output_filename
        checkpoint_path = self.output_dir / f".{output_filename}.checkpoint.json"

        # Filter chunks first (deterministic — same order every run)
        valid_chunks = []
        discarded = 0
        for chunk in chunks:
            is_valid, reason = is_valid_chunk(chunk)
            if is_valid:
                valid_chunks.append(chunk)
            else:
                discarded += 1

        variations = VARIATION_GENERATORS
        total_iterations = len(valid_chunks) * len(variations)

        # ---- Resume logic ----
        start_chunk_idx = 0
        start_var_idx = 0
        already_generated = 0
        already_failed = 0

        if resume and checkpoint_path.exists():
            with open(checkpoint_path, "r") as f:
                checkpoint = json.loads(f.read())
            start_chunk_idx = checkpoint.get("chunk_idx", 0)
            start_var_idx = checkpoint.get("var_idx", 0)
            already_generated = checkpoint.get("generated", 0)
            already_failed = checkpoint.get("failed", 0)
            completed = checkpoint.get("completed_iterations", 0)

            print(f"\n♻️  RESUMING from checkpoint:")
            print(f"   Chunk {start_chunk_idx + 1}/{len(valid_chunks)}, "
                  f"Variation {start_var_idx + 1}/{len(variations)}")
            print(f"   Already generated: {already_generated}")
            print(f"   Already failed: {already_failed}")
            print(f"   Skipping {completed} completed iterations")
        else:
            # Fresh start — clear existing output
            if output_path.exists():
                output_path.unlink()
            if checkpoint_path.exists():
                checkpoint_path.unlink()

        # Reset stats (accumulate from checkpoint)
        self.stats = {
            "generated": already_generated,
            "failed": already_failed,
            "discarded_chunk": discarded,
            "error_counts": {},
        }

        print(f"\n📊 Chunk Quality Control:")
        print(f"   Total chunks: {len(chunks)}")
        print(f"   Valid chunks: {len(valid_chunks)}")
        print(f"   Discarded: {discarded}")
        print(f"\n🔄 Generating content data: {total_iterations} iterations")
        print(f"   ({len(valid_chunks)} chunks × {len(variations)} variations)\n")

        # ---- Graceful shutdown ----
        shutdown_requested = False

        def handle_signal(signum, frame):
            nonlocal shutdown_requested
            if shutdown_requested:
                # Second Ctrl+C — force exit
                print("\n\n⚠️  Force exit (checkpoint already saved)")
                sys.exit(1)
            shutdown_requested = True
            print("\n\n⏸️  Graceful shutdown — saving checkpoint...")

        original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, handle_signal)

        # ---- Compute skip count for progress bar ----
        skip_count = start_chunk_idx * len(variations) + start_var_idx

        try:
            with tqdm(total=total_iterations, initial=skip_count,
                      desc="Content generation") as pbar:
                for chunk_idx, chunk in enumerate(valid_chunks):
                    # Skip already-done chunks
                    if chunk_idx < start_chunk_idx:
                        continue

                    for var_idx, (var_name, var_generator) in enumerate(variations):
                        # Skip already-done variations within the resume chunk
                        if chunk_idx == start_chunk_idx and var_idx < start_var_idx:
                            continue

                        # Check for shutdown
                        if shutdown_requested:
                            self._save_checkpoint(
                                checkpoint_path, chunk_idx, var_idx,
                                self.stats["generated"], self.stats["failed"],
                                skip_count + pbar.n - skip_count,
                            )
                            print(f"   ✅ Checkpoint saved at chunk {chunk_idx + 1}, "
                                  f"variation '{var_name}'")
                            print(f"   Run the same command to resume.\n")
                            self._print_summary(output_path, valid_chunks, variations)
                            return self.stats["generated"], len(valid_chunks)

                        pbar.set_postfix({
                            "chunk": f"{chunk_idx+1}/{len(valid_chunks)}",
                            "var": var_name,
                            "ok": self.stats["generated"],
                            "fail": self.stats["failed"],
                        })

                        profile = var_generator()
                        example = self.generate_one(chunk, profile)

                        if example:
                            self.stats["generated"] += 1
                            with open(output_path, "a") as f:
                                f.write(json.dumps(example) + "\n")
                        else:
                            self.stats["failed"] += 1

                        # Save checkpoint after every example
                        # (next position = current + 1)
                        next_var = var_idx + 1
                        next_chunk = chunk_idx
                        if next_var >= len(variations):
                            next_var = 0
                            next_chunk = chunk_idx + 1

                        completed_so_far = (
                            chunk_idx * len(variations) + var_idx + 1
                        )
                        self._save_checkpoint(
                            checkpoint_path, next_chunk, next_var,
                            self.stats["generated"], self.stats["failed"],
                            completed_so_far,
                        )

                        pbar.update(1)

        except Exception as e:
            # Save checkpoint on any error (rate limit, network, etc.)
            current_completed = chunk_idx * len(variations) + var_idx
            self._save_checkpoint(
                checkpoint_path, chunk_idx, var_idx,
                self.stats["generated"], self.stats["failed"],
                current_completed,
            )
            print(f"\n\n❌ Error: {e}")
            print(f"   ✅ Checkpoint saved — run again to resume.")
        finally:
            signal.signal(signal.SIGINT, original_sigint)

        # Generation complete — remove checkpoint
        if not shutdown_requested and checkpoint_path.exists():
            checkpoint_path.unlink()
            print("\n🎉 Generation complete — checkpoint cleared.")

        self._print_summary(output_path, valid_chunks, variations)
        return self.stats["generated"], len(valid_chunks)

    @staticmethod
    def _save_checkpoint(
        path: Path,
        chunk_idx: int,
        var_idx: int,
        generated: int,
        failed: int,
        completed_iterations: int,
    ):
        """Save progress checkpoint to disk."""
        checkpoint = {
            "chunk_idx": chunk_idx,
            "var_idx": var_idx,
            "generated": generated,
            "failed": failed,
            "completed_iterations": completed_iterations,
        }
        with open(path, "w") as f:
            f.write(json.dumps(checkpoint))

    def _print_summary(self, output_path: Path, valid_chunks: list, variations: list):
        """Print comprehensive generation analytics."""
        total_iterations = len(valid_chunks) * len(variations)
        generated = self.stats["generated"]
        failed = self.stats["failed"]
        success_rate = generated / max(total_iterations, 1) * 100

        print(f"\n{'=' * 70}")
        print("📊 CONTENT DATA GENERATION ANALYTICS")
        print(f"{'=' * 70}")

        # ── Overview ──
        print(f"\n📋 Overview:")
        print(f"   Valid chunks:          {len(valid_chunks)}")
        print(f"   Variations per chunk:  {len(variations)}")
        print(f"   Total attempts:        {total_iterations}")
        print(f"   Successfully generated: {generated}")
        print(f"   Failed:                {failed}")
        print(f"   Success rate:          {success_rate:.1f}%")

        # ── Read generated data for detailed analytics ──
        if output_path.exists() and generated > 0:
            import re
            from collections import Counter

            samples = []
            with open(output_path) as f:
                for line in f:
                    if line.strip():
                        samples.append(json.loads(line))

            if samples:
                # ── Profile Variation Breakdown ──
                variation_counts = Counter()
                for s in samples:
                    inp = s["input"]
                    mastery = re.search(r'\[MASTERY: (\w+)\]', inp)
                    mode = re.search(r'\[MODE: (\w+)\]', inp)
                    lang = re.search(r'\[LANG: (\w+)\]', inp)
                    if mastery and mode:
                        variation_counts[f"{mastery.group(1)}+{mode.group(1)}"] += 1

                print(f"\n👤 Profile Variation Breakdown:")
                for var, count in variation_counts.most_common():
                    pct = count / len(samples) * 100
                    bar = "█" * int(pct / 2)
                    print(f"   {var:30s}: {count:4d} ({pct:4.1f}%) {bar}")

                # ── Mastery Level Distribution ──
                mastery_counts = Counter()
                for s in samples:
                    m = re.search(r'\[MASTERY: (\w+)\]', s["input"])
                    if m:
                        mastery_counts[m.group(1)] += 1

                print(f"\n🎓 Mastery Distribution:")
                for level, count in mastery_counts.most_common():
                    pct = count / len(samples) * 100
                    print(f"   {level:20s}: {count:4d} ({pct:4.1f}%)")

                # ── Composition Mode Distribution ──
                mode_counts = Counter()
                for s in samples:
                    m = re.search(r'\[MODE: (\w+)\]', s["input"])
                    if m:
                        mode_counts[m.group(1)] += 1

                print(f"\n📐 Composition Mode Distribution:")
                for mode, count in mode_counts.most_common():
                    pct = count / len(samples) * 100
                    print(f"   {mode:20s}: {count:4d} ({pct:4.1f}%)")

                # ── Content Analytics ──
                bullet_counts = []
                define_counts = []
                highlight_counts = Counter()
                title_lengths = []
                bullet_lengths = []

                for s in samples:
                    target = s["target"]
                    lines = target.strip().split("\n")

                    bullets = [l for l in lines if l.startswith("BULLET")]
                    defines = [l for l in lines if l.startswith("DEFINE")]
                    bullet_counts.append(len(bullets) + len(defines))
                    define_counts.append(len(defines))

                    # Title length
                    for l in lines:
                        if l.startswith("TITLE:"):
                            title_lengths.append(len(l[6:].strip()))

                    # Highlight types
                    for l in lines:
                        if l.startswith("BULLET"):
                            ht_match = re.search(r'\[(\w+)\]', l)
                            if ht_match:
                                highlight_counts[ht_match.group(1)] += 1
                        elif l.startswith("DEFINE"):
                            highlight_counts["definition (DEFINE)"] += 1

                    # Bullet text lengths
                    for l in lines:
                        if l.startswith("BULLET") or l.startswith("DEFINE"):
                            idx = l.find(":")
                            if idx > 0:
                                bullet_lengths.append(len(l[idx+1:].strip()))

                print(f"\n📝 Content Metrics:")
                print(f"   Avg bullets+definitions/slide: {sum(bullet_counts)/len(bullet_counts):.1f}")
                print(f"   Avg definitions/slide:         {sum(define_counts)/len(define_counts):.2f}")
                print(f"   Slides with definitions:       {sum(1 for d in define_counts if d > 0)} / {len(samples)} ({sum(1 for d in define_counts if d > 0)/len(samples)*100:.1f}%)")
                print(f"   Avg title length:              {sum(title_lengths)/max(len(title_lengths),1):.0f} chars")
                print(f"   Avg bullet text length:        {sum(bullet_lengths)/max(len(bullet_lengths),1):.0f} chars")
                print(f"   Min / Max bullets per slide:   {min(bullet_counts)} / {max(bullet_counts)}")

                print(f"\n🎨 Highlight Type Distribution:")
                total_highlights = sum(highlight_counts.values())
                for ht, count in highlight_counts.most_common():
                    pct = count / max(total_highlights, 1) * 100
                    bar = "█" * int(pct / 2)
                    print(f"   {ht:25s}: {count:4d} ({pct:4.1f}%) {bar}")

                # ── Data Quality Warnings ──
                warnings = []
                if success_rate < 80:
                    warnings.append(f"⚠️  Low success rate ({success_rate:.1f}%) — consider relaxing validation or improving prompts")
                if any(count < len(samples) * 0.05 for count in mastery_counts.values()):
                    underrep = [m for m, c in mastery_counts.items() if c < len(samples) * 0.05]
                    warnings.append(f"⚠️  Underrepresented mastery levels: {underrep}")
                if sum(define_counts) == 0:
                    warnings.append("⚠️  No definitions generated — LLM may not be using the 'term' field")
                if len(highlight_counts) <= 2:
                    warnings.append("⚠️  Low highlight variety — only {len(highlight_counts)} types used")

                if warnings:
                    print(f"\n⚠️  Data Quality Warnings:")
                    for w in warnings:
                        print(f"   {w}")

        # ── Error breakdown ──
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

