#!/usr/bin/env python3
"""
Production Dataset Cleaning Script for Seq2Seq Content Specialist Data.
Performs in-place cleanup of artifacts (OCR ligatures, broken words, control characters, etc.)
and filters out the fundamentally broken samples based on structural criteria.
"""

import json
import re
from pathlib import Path
from collections import Counter
from tqdm import tqdm

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data/agent_training/content_train.jsonl"
OUTPUT_CLEANED = BASE_DIR / "results/audit/content_train_cleaned.jsonl"
OUTPUT_DISCARDED = BASE_DIR / "results/audit/content_train_discarded.jsonl"
REPORT_PATH = BASE_DIR / "results/audit/cleaning_report.md"

# Ensure output directories exist
OUTPUT_CLEANED.parent.mkdir(parents=True, exist_ok=True)

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
    "\u2011": "-",
    "\u00a0": " ",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-"
}

# Step 2: Null and Control Characters (\x00-\x08, \x0b, \x0c, \x0e-\x1f)
CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Step 3: Page Continuation Noise
# Matches entire lines containing explicit strings
PAGE_TEXT_REGEX = re.compile(r"(?i)(continues on next page|continued from previous page)")
# Matches lines purely composed of digits, optionally followed by a short pattern
STANDALONE_PAGE_REGEX = re.compile(r"^\s*\d+\s*(?:\|?\s*.{0,50})?\s*$", re.MULTILINE)

# Step 4: Broken Word Boundaries
PYTHON_IMPORTS_MAP = {
    "importnumpy": "import numpy",
    "importmatplotlib": "import matplotlib",
    "importpandas": "import pandas",
    "fromnumpy": "from numpy",
    "asnp": "as np",
    "aspd": "as pd"
}
PYTHON_IMPORTS_REGEX = re.compile(r"\b(importnumpy|importmatplotlib|importpandas|fromnumpy|asnp|aspd)\b")
# Conservative sentence/word boundary fix: fixes missing spaces after lowercase letters before uppercase letters
# We will use this globally but skip inside markdown backticks.
LOWER_UPPER_REGEX = re.compile(r"([a-z])([A-Z][a-z]+)")

# Step 5: Double Punctuation Normalization
DOUBLE_COMMA_REGEX = re.compile(r",{2,}")
DOUBLE_SEMICOLON_REGEX = re.compile(r";{2,}")
# Fix exactly two periods if followed by a space or end of line (avoids touching file..txt)
DOUBLE_PERIOD_REGEX = re.compile(r"(?<!\.)\.\.(?!\.)(?=\s|$)")

# Step 6: Encoding Artifacts
ENCODING_ARTIFACTS_ONESHOTS = ["\ufffd", "\uffff", "â€", "Â", "Ã"]

# Step 6b: Mathematical Italic Symbols → plain text (PDF math-mode artifacts U+1D400–U+1D7FF)
MATH_ITALIC_MAP = {
    "\U0001D714": "omega",    # 𝜔
    "\U0001D717": "theta",    # 𝜗
    "\U0001D700": "epsilon",  # 𝜀
    "\U0001D71B": "pi",       # 𝜛
    "\U0001D71A": "rho",      # 𝜚
}

# Step 6c: Private Use Area characters (U+E000–U+F8FF) — PDF font garbage
PUA_REGEX = re.compile(r"[\uE000-\uF8FF]")

# Step 6d: Unicode Math/Symbol/Greek → ASCII equivalents
# This is the critical step that prevents T5 from learning to output
# raw math notation in bullets (which would duplicate the math extractor).
UNICODE_SYMBOL_MAP = {
    # Arrows
    "\u2192": "->",   # → RIGHTWARDS ARROW
    "\u2190": "<-",   # ← LEFTWARDS ARROW
    "\u2191": "^",    # ↑ UPWARDS ARROW
    "\u2193": "v",    # ↓ DOWNWARDS ARROW
    "\u21D2": "=>",   # ⇒ RIGHTWARDS DOUBLE ARROW
    "\u2194": "<->",  # ↔ LEFT RIGHT ARROW
    # Math operators
    "\u2212": "-",    # − MINUS SIGN
    "\u00D7": "x",    # × MULTIPLICATION SIGN
    "\u00F7": "/",    # ÷ DIVISION SIGN
    "\u2211": "sum",  # ∑ N-ARY SUMMATION
    "\u221A": "sqrt", # √ SQUARE ROOT
    "\u2264": "<=",   # ≤ LESS-THAN OR EQUAL TO
    "\u2265": ">=",   # ≥ GREATER-THAN OR EQUAL TO
    "\u2248": "~=",   # ≈ ALMOST EQUAL TO
    "\u226B": ">>",   # ≫ MUCH GREATER-THAN
    "\u226A": "<<",   # ≪ MUCH LESS-THAN
    "\u2208": "in",   # ∈ ELEMENT OF
    "\u2209": "not in",  # ∉ NOT ELEMENT OF
    "\u00B1": "+/-",  # ± PLUS-MINUS SIGN
    "\u2225": "||",   # ∥ PARALLEL TO
    "\u2217": "*",    # ∗ ASTERISK OPERATOR
    "\u2032": "'",    # ′ PRIME
    "\u00B7": ".",    # · MIDDLE DOT
    "\u00AF": "-",    # ¯ MACRON
    "\u2044": "/",    # ⁄ FRACTION SLASH
    "\u2026": "...",  # … HORIZONTAL ELLIPSIS
    # Modifier / combining characters
    "\u02C6": "^",    # ˆ MODIFIER LETTER CIRCUMFLEX
    "\u0302": "",     # ̂  COMBINING CIRCUMFLEX — remove (already on the letter)
    "\u0304": "",     # ̄  COMBINING MACRON — remove
    "\u00B5": "u",    # µ MICRO SIGN
    "\u2113": "l",    # ℓ SCRIPT SMALL L
    "\u00DF": "ss",   # ß SHARP S
    "\u00B0": " degrees",  # ° DEGREE SIGN
    # Superscript digits → ^N
    "\u00B2": "^2",   # ²
    "\u00B3": "^3",   # ³
    "\u00B9": "^1",   # ¹
    "\u207F": "^n",   # ⁿ
    "\u207B": "^-",   # ⁻ SUPERSCRIPT MINUS
    "\u207A": "^+",   # ⁺ SUPERSCRIPT PLUS
    "\u2070": "^0",   # ⁰
    "\u2074": "^4",   # ⁴
    "\u2075": "^5",   # ⁵
    "\u2076": "^6",   # ⁶
    "\u2077": "^7",   # ⁷
    "\u2078": "^8",   # ⁸
    "\u2079": "^9",   # ⁹
    # Subscript digits → _N
    "\u2080": "_0",   # ₀
    "\u2081": "_1",   # ₁
    "\u2082": "_2",   # ₂
    "\u2083": "_3",   # ₃
    "\u2084": "_4",   # ₄
    "\u2085": "_5",   # ₅
    "\u2086": "_6",   # ₆
    "\u2087": "_7",   # ₇
    "\u2088": "_8",   # ₈
    "\u2089": "_9",   # ₉
    # Greek letters → spelled out for T5 comprehension
    "\u03B1": "alpha",
    "\u03B2": "beta",
    "\u03B3": "gamma",
    "\u03B4": "delta",
    "\u03B5": "epsilon",
    "\u03F5": "epsilon",
    "\u03B6": "zeta",
    "\u03B7": "eta",
    "\u03B8": "theta",
    "\u03B9": "iota",
    "\u03BA": "kappa",
    "\u03BB": "lambda",
    "\u03BC": "mu",
    "\u03BD": "nu",
    "\u03BE": "xi",
    "\u03C0": "pi",
    "\u03C1": "rho",
    "\u03C3": "sigma",
    "\u03C4": "tau",
    "\u03C5": "upsilon",
    "\u03C6": "phi",
    "\u03C7": "chi",
    "\u03C8": "psi",
    "\u03C9": "omega",
    # Capital Greek
    "\u0393": "Gamma",
    "\u0394": "Delta",
    "\u0398": "Theta",
    "\u039B": "Lambda",
    "\u03A0": "Pi",
    "\u03A3": "Sigma",
    "\u03A6": "Phi",
    "\u03A8": "Psi",
    "\u03A9": "Omega",
    # Accented Latin used in math contexts
    "\u0177": "y",    # ŷ (y-hat) → y
    "\u00EF": "i",    # ï → i
    # Narrow no-break space (PDF formatting artifact)
    "\u202F": " ",
}

# Step 7: Whitespace Normalization
MULTI_SPACE_REGEX = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE_REGEX = re.compile(r"\n{3,}")

# Classification Regexes
PERSONA_REGEX = re.compile(r"\[MASTERY:\s*(.+?)\]\s*\[MODE:\s*(.+?)\]\s*\[LANG:\s*(.+?)\]", re.IGNORECASE)
INDEX_STYLE_REGEX = re.compile(r"^[A-Z][\w\s\-]+,\s*\d+(?:\s*,\s*\d+)*$", re.MULTILINE)


# ==============================================================================
# CLEANING FUNCTIONS
# ==============================================================================
def clean_broken_words_outside_code(text, broken_word_counter):
    parts = text.split("`")
    cleaned_parts = []
    
    for i, part in enumerate(parts):
        # Even indices (0, 2, 4) are outside backticks; Odd are inside backticks
        if i % 2 == 0:
            def repl(match):
                word1 = match.group(1)
                word2 = match.group(2)
                # Ignore common camelCase occurrences like 'userId'
                # Provide space for standard boundary failure
                fixed = f"{word1} {word2}"
                broken_word_counter[f"{word1}{word2} -> {fixed}"] += 1
                return fixed
            
            # Apply regex replace and keep track
            part = LOWER_UPPER_REGEX.sub(repl, part)
        cleaned_parts.append(part)
        
    return "`".join(cleaned_parts)

def process_text_field(text, artifact_counts, broken_word_counter):
    orig_text = text
    
    # --- Step 1: OCR Ligature Replacement ---
    for lig, rep in LIGATURE_MAP.items():
        if lig in text:
            artifact_counts["OCR Ligatures Fixed"] += text.count(lig)
            text = text.replace(lig, rep)
            
    # --- Step 2: Null and Control Character Removal ---
    matches = CONTROL_CHAR_REGEX.findall(text)
    if matches:
        artifact_counts["Control Characters Removed"] += len(matches)
        text = CONTROL_CHAR_REGEX.sub("", text)
        
    # --- Step 3: Page Continuation Noise Removal ---
    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if PAGE_TEXT_REGEX.search(line) or STANDALONE_PAGE_REGEX.match(line):
            artifact_counts["Page Noise Lines Removed"] += 1
            continue
        new_lines.append(line)
    text = "\n".join(new_lines)

    # --- Step 4: Broken Word Boundaries ---
    def import_repl(m):
        orig_word = m.group(1)
        fixed_word = PYTHON_IMPORTS_MAP[orig_word]
        broken_word_counter[f"{orig_word} -> {fixed_word}"] += 1
        artifact_counts["Python Import Broken Words Fixed"] += 1
        return fixed_word
    
    text = PYTHON_IMPORTS_REGEX.sub(import_repl, text)
    
    # Fix lowercase-to-uppercase boundary issues (missing space) outside code blocks
    if LOWER_UPPER_REGEX.search(text):
        old_text = text
        text = clean_broken_words_outside_code(text, broken_word_counter)
        if text != old_text:
            artifact_counts["Natural Broken Words Fixed"] += 1
            
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
    for art in ENCODING_ARTIFACTS_ONESHOTS:
        if art in text:
            artifact_counts["Encoding Artifacts Removed"] += text.count(art)
            text = text.replace(art, "")

    # --- Step 6b: Math Italic Symbols → plain text ---
    for sym, repl in MATH_ITALIC_MAP.items():
        if sym in text:
            artifact_counts["Math Italic Symbols Normalized"] += text.count(sym)
            text = text.replace(sym, repl)

    # --- Step 6c: Private Use Area garbage removal ---
    pua_matches = PUA_REGEX.findall(text)
    if pua_matches:
        artifact_counts["Private Use Area Chars Removed"] += len(pua_matches)
        text = PUA_REGEX.sub("", text)

    # --- Step 6d: Unicode Math/Symbol/Greek → ASCII ---
    for sym, repl in UNICODE_SYMBOL_MAP.items():
        if sym in text:
            artifact_counts["Unicode Symbols Normalized"] += text.count(sym)
            text = text.replace(sym, repl)

    # --- Step 7: Whitespace Normalization ---
    lines = text.split("\n")
    processed_lines = []
    is_code_block = False
    
    for line in lines:
        stripped = line.lstrip()
        # Toggle inside markdown code block
        if line.startswith("```"):
            is_code_block = not is_code_block
            processed_lines.append(line.rstrip())
            continue
            
        # Detect indented code lines natively
        is_indented_code = (line.startswith(" ") or line.startswith("\t")) and any(
            kw in line for kw in ["def ", "class ", "import ", "return ", "if ", "for ", "while "]
        )
        
        if is_code_block or is_indented_code:
            processed_lines.append(line.rstrip())
        else:
            # Flatten multiple spaces in natural text
            p_line = MULTI_SPACE_REGEX.sub(" ", line)
            processed_lines.append(p_line.strip())
            
    text = "\n".join(processed_lines)
    text = MULTI_NEWLINE_REGEX.sub("\n\n", text)
    text = text.strip()

    return text

# ==============================================================================
# CORE WORKER
# ==============================================================================
def run_dataset_cleaning():
    if not INPUT_PATH.exists():
        print(f"Error: Dataset not found at {INPUT_PATH}")
        return
        
    print(f"Loading dataset from: {INPUT_PATH}")
    
    total_samples = 0
    kept_count = 0
    discard_count = 0
    
    artifact_counts = Counter()
    broken_word_counter = Counter()
    discard_reasons = Counter()
    
    # Length tracking
    input_lens_before = []
    input_lens_after = []
    target_lens_before = []
    target_lens_after = []
    
    with open(INPUT_PATH, 'r', encoding='utf-8') as f_in, \
         open(OUTPUT_CLEANED, 'w', encoding='utf-8') as f_clean, \
         open(OUTPUT_DISCARDED, 'w', encoding='utf-8') as f_discard:
         
        # We read all lines up front so tqdm knows the total progress
        lines = f_in.readlines()
        
        for line_num, line in enumerate(tqdm(lines, desc="Cleaning Dataset", unit="sample"), 1):
            line = line.strip()
            if not line:
                continue
                
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[Warning] Line {line_num} malformed JSON: {e}")
                continue
                
            total_samples += 1
            raw_inp = data.get("input", "")
            raw_tgt = data.get("target", "")
            
            input_lens_before.append(len(raw_inp))
            target_lens_before.append(len(raw_tgt))
            
            # Application of ALL cleaning operations to BOTH fields
            clean_inp = process_text_field(raw_inp, artifact_counts, broken_word_counter)
            clean_tgt = process_text_field(raw_tgt, artifact_counts, broken_word_counter)
            
            input_lens_after.append(len(clean_inp))
            target_lens_after.append(len(clean_tgt))
            
            # --- CLASSIFICATION LOGIC ---
            is_discard = False
            
            # 1. Target has neither BULLET nor DEFINE tag
            has_bullet = "BULLET" in clean_tgt
            has_define = "DEFINE" in clean_tgt
            if not has_bullet and not has_define:
                discard_reasons["Structurally broken target (No BULLET/DEFINE)"] += 1
                is_discard = True
                
            # 2. Target is under 50 characters
            elif len(clean_tgt) < 50:
                discard_reasons["Empty or useless target (<50 chars)"] += 1
                is_discard = True
                
            # 3. Persona tags are malformed or missing entirely
            persona_match = PERSONA_REGEX.match(clean_inp)
            if not persona_match:
                discard_reasons["Malformed or missing persona tags"] += 1
                is_discard = True
            else:
                # 4. Context section after persona tags is under 100 characters
                context_text = clean_inp[persona_match.end():].replace("Context:", "", 1).strip()
                if len(context_text) < 100:
                    discard_reasons["No real content (<100 chars context)"] += 1
                    is_discard = True
                    
                # 5. More than 50% of input lines are index-style entries
                context_lines = [L for L in context_text.split("\n") if L.strip()]
                if context_lines:
                    index_matches = sum(1 for L in context_lines if INDEX_STYLE_REGEX.match(L.strip()))
                    if (index_matches / len(context_lines)) > 0.5:
                        discard_reasons["Dominated by Index-style entries"] += 1
                        is_discard = True
            
            output_data = {
                "input": clean_inp,
                "target": clean_tgt
            }
            
            if is_discard:
                discard_count += 1
                f_discard.write(json.dumps(output_data) + "\n")
            else:
                kept_count += 1
                f_clean.write(json.dumps(output_data) + "\n")
                
    # --- REPORT GENERATION ---
    print("\nCleaning Process Complete. Generating report...")
    
    def calculate_avg(lens):
        return sum(lens) / len(lens) if lens else 0
        
    avg_inp_before = calculate_avg(input_lens_before)
    avg_inp_after = calculate_avg(input_lens_after)
    avg_tgt_before = calculate_avg(target_lens_before)
    avg_tgt_after = calculate_avg(target_lens_after)
    
    kept_pct = (kept_count / total_samples * 100) if total_samples else 0
    disc_pct = (discard_count / total_samples * 100) if total_samples else 0
    
    if kept_count > 15000:
        recommendation = "✅ EXCELLENT: Dataset is highly viable for production training."
    elif 12000 <= kept_count <= 15000:
        recommendation = "🟡 GOOD: Dataset is perfectly fine for training but could optionally be expanded."
    else:
        recommendation = "🔴 NEEDS REGENERATION: Final kept dataset size is critically low (<12000)."
        
    report = f"""# Final Dataset Cleaning Report

## 📦 Summary
- **Total Samples Processed:** {total_samples}
- **Kept (Production Ready):** {kept_count} ({kept_pct:.1f}%)
- **Discarded (Unusable):** {discard_count} ({disc_pct:.1f}%)

**➡️ Recommendation:** {recommendation}

---

## 🧹 Cleaning Operations Performed (Artifacts Fixed)
"""
    for artifact, count in artifact_counts.most_common():
        report += f"- **{artifact}:** {count} occurrences fixed\n"
        
    report += f"""
---

## 📏 Impact on Token/Char Lengths
- **Input Character Avg:** {avg_inp_before:.1f} → {avg_inp_after:.1f} (Reduced by {avg_inp_before - avg_inp_after:.1f} chars)
- **Target Character Avg:** {avg_tgt_before:.1f} → {avg_tgt_after:.1f} (Reduced by {avg_tgt_before - avg_tgt_after:.1f} chars)

---

## 🔍 Top 10 Broken Word Boundary Fixes
"""
    if broken_word_counter:
        for bw, count in broken_word_counter.most_common(10):
            report += f"- `{bw}` ({count} times)\n"
    else:
        report += "- None detected.\n"
        
    report += """
---

## 🗑️ Discard Reasons Breakdown
"""
    if discard_reasons:
        for reason, count in discard_reasons.most_common():
            report += f"- **{reason}:** {count} samples\n"
    else:
        report += "- No samples were discarded.\n"
        
    report += f"""
---
*Cleaned data exported to `{OUTPUT_CLEANED.name}`.*
*Discarded data exported to `{OUTPUT_DISCARDED.name}`.*
"""
    
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)
        
    print("\n" + report)
    print(f"\n✅ Cleaned dataset successfully written to {OUTPUT_CLEANED}")

if __name__ == "__main__":
    run_dataset_cleaning()
