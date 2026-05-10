#!/usr/bin/env python3
"""
Recovery script — finds the last chunk covered in content_train.jsonl
and writes a checkpoint so the next --append run continues from exactly
that position.

Run from the slides-generator directory:
    .venv/bin/python3.10 scripts/recover_checkpoint.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf
from slide_gen.data_engine.utils import is_valid_chunk, VARIATION_GENERATORS

# ── Paths (mirrors generate_content_data.py exactly) ─────────────
RAW_BOOKS_DIR  = project_root / "data" / "raw_books"
OUTPUT_DIR     = project_root / "data" / "agent_training"
JSONL_PATH     = OUTPUT_DIR / "content_train.jsonl"
CHECKPOINT_PATH = OUTPUT_DIR / ".content_train.jsonl.checkpoint.json"

OUTPUT_FILENAME = "content_train.jsonl"
CHUNK_SIZE      = 1000
CHUNK_OVERLAP   = 100

# ── Step 1: Extract chunks the same way the generator does ────────
print("=" * 70)
print("CHECKPOINT RECOVERY TOOL")
print("=" * 70)

pdf_files = sorted(RAW_BOOKS_DIR.glob("*.pdf"))
if not pdf_files:
    print(f"ERROR: No PDFs found in {RAW_BOOKS_DIR}")
    sys.exit(1)

print(f"\nLoading {len(pdf_files)} PDF(s)...")
all_raw_chunks = []
for pdf_path in pdf_files:
    print(f"  {pdf_path.name}")
    chunks = load_and_chunk_pdf(pdf_path, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    all_raw_chunks.extend(chunks)

# Apply exactly the same validity filter
valid_chunks = []
for chunk in all_raw_chunks:
    ok, _ = is_valid_chunk(chunk)
    if ok:
        valid_chunks.append(chunk)

n_variations = len(VARIATION_GENERATORS)
total_iterations = len(valid_chunks) * n_variations

print(f"\n  Raw chunks  : {len(all_raw_chunks)}")
print(f"  Valid chunks: {len(valid_chunks)}")
print(f"  Variations  : {n_variations}")
print(f"  Total iters : {total_iterations}")

# ── Step 2: Read the JSONL and build a set of chunk text fingerprints ──
# The input field format is:
#   "[MASTERY: X] [MODE: Y] [LANG: Z]\n<chunk text>"
# We extract the chunk text by skipping the first line (the profile prefix).

print(f"\nReading {JSONL_PATH.name}...")
if not JSONL_PATH.exists():
    print(f"ERROR: {JSONL_PATH} does not exist")
    sys.exit(1)

# Map: chunk_fingerprint (120 chars) → seen
# The input field format is:
#   "[MASTERY: X] [MODE: Y] [LANG: Z]\nContext: <chunk text>"
chunk_fingerprints_in_file: set[str] = set()
total_lines = 0

with open(JSONL_PATH, "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        total_lines += 1
        try:
            sample = json.loads(line)
            inp = sample.get("input", "")
            # Strip the "Context: " prefix that the generator adds
            ctx_start = inp.find("Context: ")
            if ctx_start != -1:
                chunk_text = inp[ctx_start + len("Context: "):]
            else:
                # Fallback: strip the profile prefix line
                chunk_text = inp.split("\n", 1)[1].strip() if "\n" in inp else inp
            fp = chunk_text[:120].strip()
            chunk_fingerprints_in_file.add(fp)
        except Exception:
            continue

print(f"  Total lines in JSONL  : {total_lines}")
print(f"  Distinct chunks found : {len(chunk_fingerprints_in_file)}")

# ── Step 3: Walk valid_chunks in order, find the last covered chunk ──
last_covered_idx = -1

for idx, chunk in enumerate(valid_chunks):
    fp = chunk[:200]
    if fp in chunk_fingerprints_in_file:
        last_covered_idx = idx

print(f"\n  Last chunk with data  : chunk_idx = {last_covered_idx} "
      f"(of 0–{len(valid_chunks)-1})")

# Resume from the chunk AFTER the last one that has any data
resume_chunk_idx = last_covered_idx + 1
resume_var_idx   = 0

if resume_chunk_idx >= len(valid_chunks):
    print("\n✅ All chunks are already covered! Nothing to resume.")
    sys.exit(0)

# Estimate already-completed iterations
completed_iterations = resume_chunk_idx * n_variations

# ── Step 4: Read current stats from existing checkpoint or estimate ──
already_generated = total_lines   # conservative: each line = 1 generated sample
already_failed    = max(0, completed_iterations - already_generated)

# ── Step 5: Write the checkpoint ─────────────────────────────────
checkpoint = {
    "chunk_idx"            : resume_chunk_idx,
    "var_idx"              : resume_var_idx,
    "generated"            : already_generated,
    "failed"               : already_failed,
    "error_counts"         : {},
    "completed_iterations" : completed_iterations,
}

with open(CHECKPOINT_PATH, "w") as f:
    json.dump(checkpoint, f, indent=2)

print(f"\n✅ Checkpoint written to:")
print(f"   {CHECKPOINT_PATH}")
print(f"\n📍 Will resume from:")
print(f"   Chunk {resume_chunk_idx + 1} / {len(valid_chunks)}")
first_resume_chunk = valid_chunks[resume_chunk_idx]
print(f"   Text preview: {first_resume_chunk[:120].strip()!r}...")
print(f"\n   Skipping {completed_iterations} completed iterations")
print(f"   Remaining: {total_iterations - completed_iterations} iterations")
print(f"\n▶  Now run:  .venv/bin/python scripts/generate_content_data.py --append")
