#!/usr/bin/env python3
"""
Comprehensive Data Quality Audit Script for Content Specialist Seq2Seq JSONL Dataset.
Evaluates basic statistics, structural validity, artifacts, and outputs a full markdown report,
visualizations, and split JSONL files (clean, salvageable, discard).
"""

import json
import re
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from transformers import AutoTokenizer

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = BASE_DIR / "results/audit/content_train_cleaned.jsonl"
RESULTS_DIR = BASE_DIR / "results/audit_post_clean"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CLEAN_OUT = RESULTS_DIR / "clean.jsonl"
SALVAGEABLE_OUT = RESULTS_DIR / "salvageable.jsonl"
DISCARD_OUT = RESULTS_DIR / "discard.jsonl"
REPORT_OUT = RESULTS_DIR / "audit_report.md"

TOKENIZER_NAME = "google/flan-t5-base"

# ==============================================================================
# REGEX DEFINITIONS
# ==============================================================================
PERSONA_REGEX = re.compile(r"\[MASTERY:\s*(.+?)\]\s*\[MODE:\s*(.+?)\]\s*\[LANG:\s*(.+?)\]", re.IGNORECASE)

# Artifact Regexes
OCR_LIGATURE_REGEX = re.compile(r"[\ufb00-\ufb06]")
# Null bytes and control characters (excluding tab \t, newline \n, return \r)
NULL_CONTROL_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PAGE_CONT_REGEX = re.compile(r"(?i)(continues on( next)? page|continued from( previous)? page|\bpage\s+\d+\b)")
INDEX_STYLE_REGEX = re.compile(r"^[A-Z][\w\s\-]+,\s*\d+(?:\s*,\s*\d+)*$", re.MULTILINE)
# Broken word boundaries: lowercase immediately followed by uppercase, or code terms embedded
BROKEN_WORD_REGEX = re.compile(r"(?<=[a-z])(?=[A-Z])")
# Encoding artifacts like unicode replacement char or common utf-8 misdecodings
ENCODING_ARTIFACT_REGEX = re.compile(r"(\ufffd|â€|Â|Ã)")
DOUBLE_PUNCT_REGEX = re.compile(r"(\.{2,}|,{2,}|;{2,})")

# ==============================================================================
# STATE & ACCUMULATORS
# ==============================================================================
stats = {
    "total_lines": 0,
    "malformed_json": 0,
    "valid_samples": 0,
    
    "input_char_lengths": [],
    "target_char_lengths": [],
    "input_token_lengths": [],
    "target_token_lengths": [],
    
    # Structural Checks
    "has_title": 0,
    "has_bullet": 0,
    "has_define": 0,
    "has_both": 0,
    "has_neither": 0,
    "malformed_persona": 0,
    "empty_target": 0,
}

distributions = {
    "mastery": Counter(),
    "mode": Counter(),
    "lang": Counter(),
    "persona_combo": Counter(),
    "artifacts": Counter(),
    "classification": Counter()
}

clean_samples = []
salvageable_samples = []
discard_samples = []

# ==============================================================================
# CORE WORKER
# ==============================================================================
def process_dataset():
    print(f"Loading tokenizer: {TOKENIZER_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
    
    if not DATASET_PATH.exists():
        print(f"Error: Dataset not found at {DATASET_PATH}")
        return False
        
    print(f"Processing dataset: {DATASET_PATH}")
    
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line_num, line in enumerate(tqdm(lines, desc="Auditing Samples", unit="sample"), 1):
        line = line.strip()
        if not line:
            continue
            
        stats["total_lines"] += 1
        
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"\n[Warning] Line {line_num} malformed JSON: {e}")
            stats["malformed_json"] += 1
            continue
            
        if "input" not in data or "target" not in data:
            print(f"\n[Warning] Line {line_num} missing 'input' or 'target' keys.")
            stats["malformed_json"] += 1
            continue
            
        inp = data["input"]
        tgt = data["target"]
        
        stats["valid_samples"] += 1
        
        # 1. Length & Basic Stats
        stats["input_char_lengths"].append(len(inp))
        stats["target_char_lengths"].append(len(tgt))
        
        # Tokenize (disable warning logs momentarily if needed, but standard tokenization is fine)
        inp_toks = len(tokenizer.encode(inp, add_special_tokens=False))
        tgt_toks = len(tokenizer.encode(tgt, add_special_tokens=False))
        stats["input_token_lengths"].append(inp_toks)
        stats["target_token_lengths"].append(tgt_toks)
        
        # 2. Structural Checks (Persona matching)
        persona_match = PERSONA_REGEX.match(inp.strip())
        if persona_match:
            mastery, mode, lang = persona_match.groups()
            distributions["mastery"][mastery] += 1
            distributions["mode"][mode] += 1
            distributions["lang"][lang] += 1
            distributions["persona_combo"][f"{mastery} | {mode} | {lang}"] += 1
            
            # Extract context after tags
            context_text = inp[persona_match.end():].replace("Context:", "", 1).strip()
        else:
            stats["malformed_persona"] += 1
            context_text = inp.strip()
            
        # Target structural checks
        has_t = "TITLE:" in tgt
        has_b = "BULLET" in tgt
        has_d = "DEFINE" in tgt
        
        if has_t: stats["has_title"] += 1
        if has_b: stats["has_bullet"] += 1
        if has_d: stats["has_define"] += 1
        if has_b and has_d: stats["has_both"] += 1
        if not has_b and not has_d: stats["has_neither"] += 1
        if len(tgt) < 50: stats["empty_target"] += 1
        
        # 3. Artifact Detection
        combined_text = inp + "\n" + tgt
        sample_artifacts = []
        
        if OCR_LIGATURE_REGEX.search(combined_text):
            sample_artifacts.append("OCR Ligatures")
        if NULL_CONTROL_REGEX.search(combined_text):
            sample_artifacts.append("Null/Control Characters")
        if PAGE_CONT_REGEX.search(combined_text):
            sample_artifacts.append("Page Continuation Noise")
        if INDEX_STYLE_REGEX.search(combined_text):
            sample_artifacts.append("Index-Style Lines")
        if BROKEN_WORD_REGEX.search(combined_text):
            sample_artifacts.append("Broken Word Boundaries")
        if ENCODING_ARTIFACT_REGEX.search(combined_text):
            sample_artifacts.append("Encoding Artifacts")
        if DOUBLE_PUNCT_REGEX.search(combined_text):
            sample_artifacts.append("Double Punctuation")
        if len(context_text) < 100:
            sample_artifacts.append("Extremely Short Input Context")
            
        for art in sample_artifacts:
            distributions["artifacts"][art] += 1
            
        # 4. Classification
        is_discard = False
        is_salvageable = False
        
        # Severe structural failures -> Discard
        if len(tgt) < 50 or (not has_b and not has_d) or not persona_match or len(context_text) < 100:
            is_discard = True
        
        # Severe artifacts -> Discard
        fatal_artifacts = {"Index-Style Lines", "Page Continuation Noise", "Null/Control Characters", "Encoding Artifacts"}
        if any(a in fatal_artifacts for a in sample_artifacts):
            is_discard = True
            
        # Multiple minor artifacts -> Discard
        if len(sample_artifacts) >= 3:
            is_discard = True
            
        # Any remaining minor artifacts -> Salvageable
        if not is_discard and len(sample_artifacts) > 0:
            is_salvageable = True
            
        if is_discard:
            distributions["classification"]["Discard"] += 1
            discard_samples.append(data)
        elif is_salvageable:
            distributions["classification"]["Salvageable"] += 1
            salvageable_samples.append(data)
        else:
            distributions["classification"]["Clean"] += 1
            clean_samples.append(data)
            
    print("Dataset processing complete.\n")
    return True

# ==============================================================================
# VISUALIZATIONS
# ==============================================================================
def create_visualizations():
    print("Generating visualizations...")
    sns.set_theme(style="whitegrid")
    
    # 1. Input Length Distribution
    plt.figure(figsize=(10, 6))
    sns.histplot(stats["input_char_lengths"], bins=50, color="skyblue")
    plt.title("Input Length Distribution (Characters)")
    plt.xlabel("Characters")
    plt.ylabel("Frequency")
    plt.savefig(RESULTS_DIR / "input_length_chars.png", dpi=300)
    plt.close()
    
    # 2. Target Length Distribution
    plt.figure(figsize=(10, 6))
    sns.histplot(stats["target_char_lengths"], bins=50, color="lightgreen")
    plt.title("Target Length Distribution (Characters)")
    plt.xlabel("Characters")
    plt.ylabel("Frequency")
    plt.savefig(RESULTS_DIR / "target_length_chars.png", dpi=300)
    plt.close()
    
    # 3. Token Length Distribution Overlay
    plt.figure(figsize=(10, 6))
    sns.histplot(stats["input_token_lengths"], bins=50, color="blue", alpha=0.5, label="Input Tokens")
    sns.histplot(stats["target_token_lengths"], bins=50, color="green", alpha=0.5, label="Target Tokens")
    plt.axvline(512, color='red', linestyle='--', label='Max Input (512)')
    plt.axvline(256, color='orange', linestyle='--', label='Max Target (256)')
    plt.title("Token Length Distribution Overlay")
    plt.xlabel("Tokens")
    plt.ylabel("Frequency")
    plt.legend()
    plt.savefig(RESULTS_DIR / "token_length_overlay.png", dpi=300)
    plt.close()
    
    # 4. Artifact Frequency
    if distributions["artifacts"]:
        plt.figure(figsize=(12, 6))
        arts, counts = zip(*distributions["artifacts"].most_common())
        sns.barplot(x=list(counts), y=list(arts), palette="rocket")
        plt.title("Artifact Type Frequency")
        plt.xlabel("Count")
        plt.tight_layout()
        plt.savefig(RESULTS_DIR / "artifact_frequency.png", dpi=300)
        plt.close()
        
    # 5. Quality Breakdown
    plt.figure(figsize=(8, 8))
    labels = ["Clean", "Salvageable", "Discard"]
    sizes = [distributions["classification"][l] for l in labels]
    colors = ['#2ecc71', '#f1c40f', '#e74c3c']
    if sum(sizes) > 0:
        plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
        plt.title("Sample Quality Breakdown")
        plt.savefig(RESULTS_DIR / "quality_breakdown.png", dpi=300)
        plt.close()

    # 6. Persona Heatmap (Mastery vs Mode)
    # We will build a matrix of Mastery x Mode counts
    mastery_list = list(distributions["mastery"].keys())
    mode_list = list(distributions["mode"].keys())
    
    if mastery_list and mode_list:
        matrix = [[0 for _ in mode_list] for _ in mastery_list]
        for combo, count in distributions["persona_combo"].items():
            parts = [p.strip() for p in combo.split("|")]
            if len(parts) >= 2:
                m, mo = parts[0], parts[1]
                if m in mastery_list and mo in mode_list:
                    matrix[mastery_list.index(m)][mode_list.index(mo)] += count
                    
        plt.figure(figsize=(10, 8))
        sns.heatmap(matrix, annot=True, fmt="d", cmap="YlGnBu", xticklabels=mode_list, yticklabels=mastery_list)
        plt.title("Persona Tag Combinations (Mastery vs Mode)")
        plt.xlabel("Mode")
        plt.ylabel("Mastery")
        plt.tight_layout()
        plt.savefig(RESULTS_DIR / "persona_heatmap.png", dpi=300)
        plt.close()

# ==============================================================================
# REPORTING & EXPORT
# ==============================================================================
def write_jsonl(path, dataset):
    with open(path, 'w', encoding='utf-8') as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")

def generate_report():
    print("Generating comprehensive markdown report...")
    
    total = stats["valid_samples"]
    if total == 0:
        print("No valid samples to report.")
        return
        
    discard_rate = (distributions["classification"]["Discard"] / total) * 100
    if discard_rate < 10:
        recommendation = "✅ RECOMMENDED ACTION: **Train As-Is.** The dataset has an exceptionally low artifact/discard rate (<10%). It is ready for high-quality fine-tuning."
    elif 10 <= discard_rate <= 25:
        recommendation = "⚠️ RECOMMENDED ACTION: **Clean Before Training.** The dataset has a moderate discard rate (10-25%). You should train exclusively on the `clean.jsonl` and `salvageable.jsonl` filtered files generated by this audit."
    else:
        recommendation = "⛔ RECOMMENDED ACTION: **Regenerate Dataset.** The dataset has a critical discard rate (>25%). Training on this data will degrade model quality. The synthetic extraction data pipeline likely has structural flaws."

    def avg(lst): return sum(lst) / len(lst) if lst else 0

    report = f"""# Data Quality Audit Report

**Dataset Path:** `{DATASET_PATH.resolve()}`
**Total Samples Processed:** {stats["valid_samples"]}
**Malformed JSON Lines Ignored:** {stats["malformed_json"]}

---

## 🚀 Final Recommendation

{recommendation}

---

## 📊 1. Basic Statistics

### Lengths (Averages)
- **Input Character Length:** {avg(stats["input_char_lengths"]):.1f} (Min: {min(stats["input_char_lengths"])}, Max: {max(stats["input_char_lengths"])})
- **Input Token Length:** {avg(stats["input_token_lengths"]):.1f} (Min: {min(stats["input_token_lengths"])}, Max: {max(stats["input_token_lengths"])})
- **Target Character Length:** {avg(stats["target_char_lengths"]):.1f} (Min: {min(stats["target_char_lengths"])}, Max: {max(stats["target_char_lengths"])})
- **Target Token Length:** {avg(stats["target_token_lengths"]):.1f} (Min: {min(stats["target_token_lengths"])}, Max: {max(stats["target_token_lengths"])})

### Persona Tag Distribution
**Mastery Levels:**
"""
    for k, v in distributions["mastery"].most_common(): report += f"- {k}: {v} ({(v/total)*100:.1f}%)\n"
    
    report += "\n**Mode Types:**\n"
    for k, v in distributions["mode"].most_common(): report += f"- {k}: {v} ({(v/total)*100:.1f}%)\n"
    
    report += "\n**Language Types:**\n"
    for k, v in distributions["lang"].most_common(): report += f"- {k}: {v} ({(v/total)*100:.1f}%)\n"

    report += f"""
---

## 🏗️ 2. Structural Validity

- **Missing/Malformed Persona Tags:** {stats["malformed_persona"]} ({(stats["malformed_persona"]/total)*100:.1f}%)
- **Targets < 50 Characters (Empty):** {stats["empty_target"]} ({(stats["empty_target"]/total)*100:.1f}%)
- **Has TITLE:** {stats["has_title"]} ({(stats["has_title"]/total)*100:.1f}%)
- **Has BULLET:** {stats["has_bullet"]} ({(stats["has_bullet"]/total)*100:.1f}%)
- **Has DEFINE:** {stats["has_define"]} ({(stats["has_define"]/total)*100:.1f}%)
- **Has Both BULLET & DEFINE:** {stats["has_both"]} ({(stats["has_both"]/total)*100:.1f}%)
- **Has Neither (Bad Target):** {stats["has_neither"]} ({(stats["has_neither"]/total)*100:.1f}%)

---

## 🦠 3. Detected Artifacts

"""
    if distributions["artifacts"]:
        for art, count in distributions["artifacts"].most_common():
            report += f"- **{art}:** {count} samples ({(count/total)*100:.1f}%)\n"
    else:
        report += "- *No artifacts detected in any sample!* 🎉\n"

    report += f"""
---

## 🗂️ 4. Sample Classification

Total Valid Samples: {total}
- 🟢 **Clean:** {distributions["classification"]["Clean"]} ({(distributions["classification"]["Clean"]/total)*100:.1f}%) — Perfect samples.
- 🟡 **Salvageable:** {distributions["classification"]["Salvageable"]} ({(distributions["classification"]["Salvageable"]/total)*100:.1f}%) — Minor issues.
- 🔴 **Discard:** {distributions["classification"]["Discard"]} ({(distributions["classification"]["Discard"]/total)*100:.1f}%) — Unusable.

*Note: The datasets have been split and exported to the `results/audit/` directory.*

- `{CLEAN_OUT.name}`: {len(clean_samples)} samples
- `{SALVAGEABLE_OUT.name}`: {len(salvageable_samples)} samples
- `{DISCARD_OUT.name}`: {len(discard_samples)} samples

---
*Audit automatically generated by Data Quality Audit Script.*
"""
    
    with open(REPORT_OUT, 'w', encoding='utf-8') as f:
        f.write(report)
        
    print(report)
    
    # Export split datasets
    write_jsonl(CLEAN_OUT, clean_samples)
    write_jsonl(SALVAGEABLE_OUT, salvageable_samples)
    write_jsonl(DISCARD_OUT, discard_samples)
    print(f"\nAll operations complete.\nReport and datasets saved to: {RESULTS_DIR.resolve()}")

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    if process_dataset():
        create_visualizations()
        generate_report()
