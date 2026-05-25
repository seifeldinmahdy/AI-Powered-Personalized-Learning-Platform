#!/usr/bin/env python3
"""
Production Dataset Cleaning Script for Visual Classifier Training Data.

Performs in-place cleanup of PDF-parsing artifacts (OCR ligatures, broken words,
control characters, page noise, etc.) on classifier_train JSONL files.

Each sample has:
  {"text": "...", "label": "..."}

The cleaning is text-only — labels are preserved as-is.

Usage:
    python scripts/clean_classifier_dataset.py
    python scripts/clean_classifier_dataset.py --input data/agent_training/classifier_train_v3.jsonl
"""

import json
import re
import argparse
from pathlib import Path
from collections import Counter
from tqdm import tqdm

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "data/agent_training/classifier_train_v3.jsonl"
DEFAULT_OUTPUT = BASE_DIR / "data/agent_training/classifier_train_v3_cleaned.jsonl"
DEFAULT_DISCARDED = BASE_DIR / "results/audit/classifier_discarded.jsonl"
DEFAULT_REPORT = BASE_DIR / "results/audit/classifier_cleaning_report.md"


# ==============================================================================
# REGEX & REPLACEMENT CONSTANTS
# ==============================================================================

# Step 1: OCR Ligatures
LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
    "\u2011": "-",   # non-breaking hyphen
    "\u00a0": " ",   # non-breaking space
    "\u2019": "'",   # right single quote
    "\u2018": "'",   # left single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2013": "-",   # en-dash
    "\u2014": "-",   # em-dash
    "\u2022": "*",   # bullet point → asterisk (uniform)
}

# Step 2: Null and Control Characters (\x00-\x08, \x0b, \x0c, \x0e-\x1f)
CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Step 3: Page Continuation / Header Noise
PAGE_TEXT_REGEX = re.compile(
    r"(?i)(continues on next page|continued from previous page)"
)
# Lines that are purely page numbers or short book headers
# e.g. "42", "3", "Problem Solving with Algorithms and Data Structures, Release 3.0"
STANDALONE_PAGE_REGEX = re.compile(r"^\s*\d{1,4}\s*$")
BOOK_HEADER_REGEX = re.compile(
    r"^(Chapter \d+|Problem Solving with .+|Release \d+\.\d+|"
    r"\d+\.\d+\s+\w|Figure \d+|Table \d+)",
    re.IGNORECASE,
)

# Step 4: Broken Word Boundaries (missing spaces from PDF line-wrapping)
# Catches lowercase-to-uppercase transitions outside of code: "problemSolving" → "problem Solving"
LOWER_UPPER_REGEX = re.compile(r"([a-z])([A-Z][a-z]+)")
# Common camelCase identifiers to SKIP (don't break these)
CAMEL_CASE_WHITELIST = {
    "forEach", "indexOf", "toString", "valueOf", "charAt", "parseInt",
    "isEmpty", "getSize", "pushBack", "popFront", "addFirst", "addLast",
    "removeFirst", "removeLast", "hasNext", "getNext", "getLeft", "getRight",
    "setData", "getData", "getRoot", "setRoot", "leftChild", "rightChild",
    "insertBefore", "insertAfter", "nextNode", "prevNode",
    "isConnected", "getDegree", "getWeight", "setWeight",
    "enQueue", "deQueue",
}

# Step 5: Double Punctuation Normalization
DOUBLE_COMMA_REGEX = re.compile(r",{2,}")
DOUBLE_SEMICOLON_REGEX = re.compile(r";{2,}")
DOUBLE_PERIOD_REGEX = re.compile(r"(?<!\.)\.\.(?!\.)(?=\s|$)")

# Step 6: Encoding Artifacts
ENCODING_ARTIFACTS = ["\ufffd", "\uffff", "â€", "Â", "Ã"]

# Step 7: Whitespace Normalization
MULTI_SPACE_REGEX = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE_REGEX = re.compile(r"\n{3,}")

# Step 8: Mathematical Italic Symbols → plain Greek/Latin equivalents
# These are PDF math-mode artifacts (U+1D400–U+1D7FF)
MATH_ITALIC_MAP = {
    "\U0001D714": "omega",    # 𝜔 → omega
    "\U0001D717": "theta",    # 𝜗 → theta
    "\U0001D700": "epsilon",  # 𝜀 → epsilon
    "\U0001D71B": "pi",       # 𝜛 → pi
    "\U0001D71A": "rho",      # 𝜚 → rho
}

# Step 9: Private Use Area characters (U+E000–U+F8FF) — PDF font garbage
PUA_REGEX = re.compile(r"[\uE000-\uF8FF]")

# Step 10: Unicode Math/Symbol Operators → ASCII equivalents
UNICODE_SYMBOL_MAP = {
    "\u2192": "->",   # → RIGHTWARDS ARROW
    "\u2190": "<-",   # ← LEFTWARDS ARROW
    "\u2191": "^",    # ↑ UPWARDS ARROW
    "\u2193": "v",    # ↓ DOWNWARDS ARROW
    "\u2212": "-",    # − MINUS SIGN
    "\u00D7": "x",    # × MULTIPLICATION SIGN
    "\u2211": "sum",  # ∑ N-ARY SUMMATION
    "\u221A": "sqrt", # √ SQUARE ROOT
    "\u2264": "<=",   # ≤ LESS-THAN OR EQUAL TO
    "\u2265": ">=",   # ≥ GREATER-THAN OR EQUAL TO
    "\u2208": "in",   # ∈ ELEMENT OF
    "\u2225": "||",   # ∥ PARALLEL TO
    "\u2217": "*",    # ∗ ASTERISK OPERATOR
    "\u2032": "'",    # ′ PRIME
    "\u02C6": "^",    # ˆ MODIFIER LETTER CIRCUMFLEX
    "\u00B7": ".",    # · MIDDLE DOT
    "\u00B5": "u",    # µ MICRO SIGN
    "\u2113": "l",    # ℓ SCRIPT SMALL L
    "\u00AF": "-",    # ¯ MACRON
    "\u00DF": "ss",   # ß SHARP S
    # Greek letters → spelled out for DistilBERT comprehension
    "\u03B1": "alpha",
    "\u03B2": "beta",
    "\u03B3": "gamma",
    "\u03B4": "delta",
    "\u03F5": "epsilon",
    "\u03B8": "theta",
    "\u03BB": "lambda",
    "\u03C0": "pi",
    "\u03C3": "sigma",
    "\u03C6": "phi",
    "\u03A3": "Sigma",
}


# ==============================================================================
# CLEANING FUNCTIONS
# ==============================================================================

def _clean_broken_words_outside_code(text: str, counter: Counter) -> str:
    """Fix missing spaces at word boundaries, but skip inside backtick code spans."""
    parts = text.split("`")
    cleaned = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # outside backticks
            def _repl(m):
                full = m.group(0)
                if full in CAMEL_CASE_WHITELIST:
                    return full
                word1, word2 = m.group(1), m.group(2)
                fixed = f"{word1} {word2}"
                counter[f"{word1}{word2} → {fixed}"] += 1
                return fixed
            part = LOWER_UPPER_REGEX.sub(_repl, part)
        cleaned.append(part)
    return "`".join(cleaned)


def clean_text(text: str, artifact_counts: Counter, broken_word_counter: Counter) -> str:
    """Apply all cleaning steps to a text string."""

    # --- Step 1: OCR Ligature Replacement ---
    for lig, rep in LIGATURE_MAP.items():
        if lig in text:
            artifact_counts["OCR Ligatures Fixed"] += text.count(lig)
            text = text.replace(lig, rep)

    # --- Step 2: Control Character Removal ---
    matches = CONTROL_CHAR_REGEX.findall(text)
    if matches:
        artifact_counts["Control Characters Removed"] += len(matches)
        text = CONTROL_CHAR_REGEX.sub("", text)

    # --- Step 3: Page / Header Noise Removal ---
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if PAGE_TEXT_REGEX.search(stripped):
            artifact_counts["Page Continuation Lines Removed"] += 1
            continue
        if STANDALONE_PAGE_REGEX.match(stripped):
            artifact_counts["Standalone Page Numbers Removed"] += 1
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # --- Step 4: Broken Word Boundaries ---
    if LOWER_UPPER_REGEX.search(text):
        old_text = text
        text = _clean_broken_words_outside_code(text, broken_word_counter)
        if text != old_text:
            artifact_counts["Broken Word Boundaries Fixed"] += 1

    # --- Step 5: Double Punctuation Normalization ---
    if DOUBLE_COMMA_REGEX.search(text):
        artifact_counts["Double Commas Normalized"] += len(DOUBLE_COMMA_REGEX.findall(text))
        text = DOUBLE_COMMA_REGEX.sub(",", text)

    if DOUBLE_SEMICOLON_REGEX.search(text):
        artifact_counts["Double Semicolons Normalized"] += len(DOUBLE_SEMICOLON_REGEX.findall(text))
        text = DOUBLE_SEMICOLON_REGEX.sub(";", text)

    if DOUBLE_PERIOD_REGEX.search(text):
        artifact_counts["Double Periods Normalized"] += len(DOUBLE_PERIOD_REGEX.findall(text))
        text = DOUBLE_PERIOD_REGEX.sub(".", text)

    # --- Step 6: Encoding Artifact Removal ---
    for art in ENCODING_ARTIFACTS:
        if art in text:
            artifact_counts["Encoding Artifacts Removed"] += text.count(art)
            text = text.replace(art, "")

    # --- Step 8: Math Italic Symbols → plain text ---
    for sym, repl in MATH_ITALIC_MAP.items():
        if sym in text:
            artifact_counts["Math Italic Symbols Normalized"] += text.count(sym)
            text = text.replace(sym, repl)

    # --- Step 9: Private Use Area garbage removal ---
    pua_matches = PUA_REGEX.findall(text)
    if pua_matches:
        artifact_counts["Private Use Area Chars Removed"] += len(pua_matches)
        text = PUA_REGEX.sub("", text)

    # --- Step 10: Unicode Math/Symbol → ASCII ---
    for sym, repl in UNICODE_SYMBOL_MAP.items():
        if sym in text:
            artifact_counts["Unicode Symbols Normalized"] += text.count(sym)
            text = text.replace(sym, repl)

    # --- Step 7: Whitespace Normalization ---
    lines = text.split("\n")
    processed = []
    is_code = False
    for line in lines:
        if line.strip().startswith("```"):
            is_code = not is_code
            processed.append(line.rstrip())
            continue
        # Detect indented code
        is_indented = (line.startswith("    ") or line.startswith("\t")) and any(
            kw in line for kw in ["def ", "class ", "import ", "return ", "if ", "for ", "while ", "print("]
        )
        if is_code or is_indented:
            processed.append(line.rstrip())
        else:
            processed.append(MULTI_SPACE_REGEX.sub(" ", line).strip())
    text = "\n".join(processed)
    text = MULTI_NEWLINE_REGEX.sub("\n\n", text)
    text = text.strip()

    return text


# ==============================================================================
# DISCARD LOGIC
# ==============================================================================

# Valid labels in the current hierarchy
VALID_LABELS = {
    "linear_chain", "binary_tree", "general_tree", "stack", "queue", "graph",
    "flowchart", "cycle",
    "comparison",
    "bar_chart",
    "concept_box",
    "architecture_diagram",  # layered_stack merged into architecture_diagram
    "none",
}


def should_discard(text: str, label: str, reasons: Counter) -> bool:
    """Decide if a sample should be discarded (structurally broken)."""

    # 1. Invalid label
    if label not in VALID_LABELS:
        reasons[f"Invalid label: '{label}'"] += 1
        return True

    # 2. Text too short after cleaning (< 30 chars = almost certainly garbage)
    if len(text) < 30:
        reasons["Text too short after cleaning (< 30 chars)"] += 1
        return True

    # 3. Text is mostly digits/punctuation (> 70% non-alpha)
    alpha_count = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and (alpha_count / len(text)) < 0.3:
        reasons["Text dominated by non-alphabetic characters (< 30% alpha)"] += 1
        return True

    return False


# ==============================================================================
# MAIN
# ==============================================================================

def run_cleaning(input_path: Path, output_path: Path, discarded_path: Path, report_path: Path):
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return

    # Ensure output dirs exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    discarded_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset from: {input_path}")

    artifact_counts = Counter()
    broken_word_counter = Counter()
    discard_reasons = Counter()
    label_dist_before = Counter()
    label_dist_after = Counter()

    total = 0
    kept = 0
    discarded = 0
    text_lens_before = []
    text_lens_after = []

    with open(input_path, "r", encoding="utf-8") as f_in:
        raw_lines = f_in.readlines()

    with open(output_path, "w", encoding="utf-8") as f_out, \
         open(discarded_path, "w", encoding="utf-8") as f_disc:

        for line in tqdm(raw_lines, desc="Cleaning classifier data", unit="sample"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            text = data.get("text", "")
            label = data.get("label", "none")

            label_dist_before[label] += 1
            text_lens_before.append(len(text))

            # Clean the text
            cleaned_text = clean_text(text, artifact_counts, broken_word_counter)
            text_lens_after.append(len(cleaned_text))

            # Discard check
            if should_discard(cleaned_text, label, discard_reasons):
                discarded += 1
                f_disc.write(json.dumps({"text": cleaned_text, "label": label}) + "\n")
            else:
                kept += 1
                label_dist_after[label] += 1
                f_out.write(json.dumps({"text": cleaned_text, "label": label}) + "\n")

    # ─── REPORT ───
    avg_before = sum(text_lens_before) / len(text_lens_before) if text_lens_before else 0
    avg_after = sum(text_lens_after) / len(text_lens_after) if text_lens_after else 0
    kept_pct = (kept / total * 100) if total else 0
    disc_pct = (discarded / total * 100) if total else 0

    report = f"""# Visual Classifier Dataset Cleaning Report

## 📦 Summary
- **Input File:** `{input_path.name}`
- **Total Samples Processed:** {total}
- **Kept (Production Ready):** {kept} ({kept_pct:.1f}%)
- **Discarded (Unusable):** {discarded} ({disc_pct:.1f}%)

---

## 🧹 Cleaning Operations Performed
"""
    for artifact, count in artifact_counts.most_common():
        report += f"- **{artifact}:** {count} occurrences\n"

    report += f"""
---

## 📏 Impact on Text Length
- **Avg Text Length:** {avg_before:.0f} → {avg_after:.0f} chars (reduced by {avg_before - avg_after:.0f})
- **Min Text Length (before):** {min(text_lens_before) if text_lens_before else 0} chars
- **Min Text Length (after):** {min(text_lens_after) if text_lens_after else 0} chars

---

## 🔍 Top 15 Broken Word Boundary Fixes
"""
    if broken_word_counter:
        for bw, count in broken_word_counter.most_common(15):
            report += f"- `{bw}` ({count} times)\n"
    else:
        report += "- None detected.\n"

    report += """
---

## 🏷️ Label Distribution (Before → After Cleaning)
"""
    all_labels = sorted(set(label_dist_before.keys()) | set(label_dist_after.keys()),
                        key=lambda x: -label_dist_before.get(x, 0))
    for label in all_labels:
        before = label_dist_before.get(label, 0)
        after = label_dist_after.get(label, 0)
        diff = after - before
        diff_str = f"({diff:+d})" if diff != 0 else "(=)"
        report += f"- **{label}:** {before} → {after} {diff_str}\n"

    report += """
---

## 🗑️ Discard Reasons
"""
    if discard_reasons:
        for reason, count in discard_reasons.most_common():
            report += f"- **{reason}:** {count} samples\n"
    else:
        report += "- No samples were discarded.\n"

    report += f"""
---

*Cleaned data exported to `{output_path.name}`.*
*Discarded data exported to `{discarded_path.name}`.*
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + report)
    print(f"\n✅ Cleaned dataset written to {output_path}")
    print(f"   Discarded samples: {discarded_path}")
    print(f"   Report: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean visual classifier training dataset"
    )
    parser.add_argument(
        "--input", "-i", type=str, default=str(DEFAULT_INPUT),
        help="Input JSONL file (default: classifier_train_v3.jsonl)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=str(DEFAULT_OUTPUT),
        help="Output cleaned JSONL file"
    )
    parser.add_argument(
        "--discarded", type=str, default=str(DEFAULT_DISCARDED),
        help="Output discarded samples JSONL file"
    )
    parser.add_argument(
        "--report", type=str, default=str(DEFAULT_REPORT),
        help="Output cleaning report markdown file"
    )
    args = parser.parse_args()

    run_cleaning(
        Path(args.input),
        Path(args.output),
        Path(args.discarded),
        Path(args.report),
    )
