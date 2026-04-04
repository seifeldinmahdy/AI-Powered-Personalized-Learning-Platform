#!/usr/bin/env python3
"""
Generate ALL training data in parallel.

Runs content (T5) and classifier (DistilBERT) data generation
simultaneously using multiprocessing. Both generators support
checkpoint/resume — press Ctrl+C to pause, re-run to continue.

Usage:
    python scripts/generate_all_data.py

Both generators will:
- Resume from their last checkpoint automatically
- Save progress on Ctrl+C or error
- Append to existing output files (never overwrite on resume)
"""

import os
import sys
import signal
import multiprocessing
from pathlib import Path

from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def run_content_generator(ollama_host, ollama_model, max_retries, api_key,
                          raw_books_dir, output_dir, prompts_path):
    """Run content data generation in a subprocess."""
    # Re-import inside subprocess (multiprocessing)
    sys.path.insert(0, str(project_root / "src"))
    from slide_gen.training.content_data_generator import ContentDataGenerator
    from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf

    pdf_files = sorted(raw_books_dir.glob("*.pdf"))
    all_chunks = []
    for pdf_path in pdf_files:
        print(f"[CONTENT] Loading: {pdf_path.name}")
        try:
            chunks = load_and_chunk_pdf(pdf_path, chunk_size=1000, chunk_overlap=100)
            print(f"[CONTENT]   → {len(chunks)} chunks extracted")
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"[CONTENT]   ⚠ Error: {e}")
            continue

    if not all_chunks:
        print("[CONTENT] Error: No chunks extracted.")
        return

    generator = ContentDataGenerator(
        prompts_path=prompts_path,
        output_dir=output_dir,
        ollama_host=ollama_host,
        model=ollama_model,
        max_retries=max_retries,
        api_key=api_key,
    )

    total_generated, total_chunks = generator.run(
        chunks=all_chunks,
        output_filename="content_train.jsonl",
        resume=True,
    )

    print(f"\n[CONTENT] ✅ Done! Generated {total_generated} content examples.")


def run_classifier_generator(ollama_host, ollama_model, max_retries, api_key,
                             raw_books_dir, output_dir, prompts_path):
    """Run classifier data generation in a subprocess."""
    sys.path.insert(0, str(project_root / "src"))
    from slide_gen.training.classifier_data_generator import ClassifierDataGenerator
    from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf

    pdf_files = sorted(raw_books_dir.glob("*.pdf"))
    all_chunks = []
    for pdf_path in pdf_files:
        print(f"[CLASSIFIER] Loading: {pdf_path.name}")
        try:
            chunks = load_and_chunk_pdf(pdf_path, chunk_size=1000, chunk_overlap=100)
            print(f"[CLASSIFIER]   → {len(chunks)} chunks extracted")
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"[CLASSIFIER]   ⚠ Error: {e}")
            continue

    if not all_chunks:
        print("[CLASSIFIER] Error: No chunks extracted.")
        return

    generator = ClassifierDataGenerator(
        prompts_path=prompts_path,
        output_dir=output_dir,
        ollama_host=ollama_host,
        model=ollama_model,
        max_retries=max_retries,
        api_key=api_key,
    )

    total_generated, total_chunks = generator.run_from_chunks(
        chunks=all_chunks,
        output_filename="classifier_train.jsonl",
        resume=True,
    )

    print(f"\n[CLASSIFIER] ✅ Done! Generated {total_generated} classifier examples.")


def main():
    load_dotenv(project_root / ".env")

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    api_key = os.getenv("OLLAMA_API_KEY")

    raw_books_dir = project_root / "data" / "raw_books"
    output_dir = project_root / "data" / "agent_training"
    content_prompts = project_root / "config" / "prompts_content.yaml"
    classifier_prompts = project_root / "config" / "prompts_classifier.yaml"

    pdf_files = sorted(raw_books_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"Error: No PDF files found in {raw_books_dir}")
        sys.exit(1)

    print("=" * 70)
    print("PARALLEL DATA GENERATION (Content + Classifier)")
    print("=" * 70)
    print(f"\nFound {len(pdf_files)} PDF(s):")
    for i, pdf in enumerate(pdf_files, 1):
        size_mb = pdf.stat().st_size / (1024 * 1024)
        print(f"  {i}. {pdf.name} ({size_mb:.1f} MB)")

    print(f"\nOllama: {ollama_host} / {ollama_model}")
    print(f"Cloud API: {'Yes (API key set)' if api_key else 'No (local)'}")
    print(f"Max retries: {max_retries}")

    # Check for existing checkpoints
    content_cp = output_dir / ".content_train.jsonl.checkpoint.json"
    classifier_cp = output_dir / ".classifier_train.jsonl.checkpoint.json"

    if content_cp.exists() or classifier_cp.exists():
        print(f"\n♻️  Checkpoints detected:")
        if content_cp.exists():
            print(f"   - Content: will resume from checkpoint")
        if classifier_cp.exists():
            print(f"   - Classifier: will resume from checkpoint")

    print(f"\n🚀 Launching both generators in parallel...")
    print(f"   Press Ctrl+C to pause both (checkpoints will be saved)")
    print("-" * 70)

    # Shared args
    content_args = (ollama_host, ollama_model, max_retries, api_key,
                    raw_books_dir, output_dir, content_prompts)
    classifier_args = (ollama_host, ollama_model, max_retries, api_key,
                       raw_books_dir, output_dir, classifier_prompts)

    # Launch as separate processes
    content_proc = multiprocessing.Process(
        target=run_content_generator, args=content_args, name="ContentGen"
    )
    classifier_proc = multiprocessing.Process(
        target=run_classifier_generator, args=classifier_args, name="ClassifierGen"
    )

    content_proc.start()
    classifier_proc.start()

    # Handle Ctrl+C in main process — send SIGINT to children
    def parent_signal_handler(signum, frame):
        print("\n\n⏸️  Stopping both generators (saving checkpoints)...")
        # Children have their own signal handlers that save checkpoints
        if content_proc.is_alive():
            os.kill(content_proc.pid, signal.SIGINT)
        if classifier_proc.is_alive():
            os.kill(classifier_proc.pid, signal.SIGINT)

    signal.signal(signal.SIGINT, parent_signal_handler)

    # Wait for both to finish
    content_proc.join()
    classifier_proc.join()

    print("\n" + "=" * 70)
    print("PARALLEL GENERATION COMPLETE")
    print("=" * 70)

    content_out = output_dir / "content_train.jsonl"
    classifier_out = output_dir / "classifier_train.jsonl"

    if content_out.exists():
        content_lines = sum(1 for _ in open(content_out))
        print(f"  Content:    {content_lines} examples → {content_out}")
    if classifier_out.exists():
        classifier_lines = sum(1 for _ in open(classifier_out))
        print(f"  Classifier: {classifier_lines} examples → {classifier_out}")

    # Check if checkpoints remain (paused)
    if content_cp.exists() or classifier_cp.exists():
        print(f"\n⏸️  Generation was paused. Run again to resume.")
    else:
        print(f"\n✅ All generation complete!")
        print(f"\nNext steps:")
        print(f"  python scripts/train_content.py")
        print(f"  python scripts/train_classifier.py")


if __name__ == "__main__":
    main()
