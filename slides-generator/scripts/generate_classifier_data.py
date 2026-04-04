#!/usr/bin/env python3
"""
Generate classifier training data for DistilBERT fine-tuning.

Default: Classifies raw PDF chunks directly (recommended).
Optional: Can also classify from pre-generated content_train.jsonl.

Usage:
    # Default: From raw PDFs (recommended)
    python scripts/generate_classifier_data.py

    # Alternative: From existing content data
    python scripts/generate_classifier_data.py --from-content-data
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.training.classifier_data_generator import ClassifierDataGenerator
from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate classifier training data")
    parser.add_argument(
        "--from-content-data", action="store_true",
        help="Generate from content_train.jsonl instead of raw PDFs"
    )
    parser.add_argument(
        "--content-data", type=str, default=None,
        help="Path to content_train.jsonl (only used with --from-content-data)"
    )
    args = parser.parse_args()

    load_dotenv(project_root / ".env")

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    api_key = os.getenv("OLLAMA_API_KEY")  # None for local, set for cloud

    output_dir = project_root / "data" / "agent_training"
    prompts_path = project_root / "config" / "prompts_classifier.yaml"

    print("=" * 70)
    print("CLASSIFIER DATA GENERATOR (DistilBERT Training)")
    print("=" * 70)
    print(f"\nOllama: {ollama_host} / {ollama_model}")
    print(f"Cloud API: {'Yes (API key set)' if api_key else 'No (local)'}")
    print(f"Max retries: {max_retries}")

    generator = ClassifierDataGenerator(
        prompts_path=prompts_path,
        output_dir=output_dir,
        ollama_host=ollama_host,
        model=ollama_model,
        max_retries=max_retries,
        api_key=api_key,
    )

    if args.from_content_data:
        # Alternative: From content_train.jsonl
        content_path = args.content_data or (output_dir / "content_train.jsonl")
        content_path = Path(content_path)

        if not content_path.exists():
            print(f"\nError: {content_path} not found!")
            print("Run scripts/generate_content_data.py first, or omit --from-content-data.")
            sys.exit(1)

        print(f"\nMode: From content data ({content_path})")
        print("-" * 70)

        total_gen, total_processed = generator.run_from_content_data(
            content_jsonl_path=content_path,
            output_filename="classifier_train.jsonl",
            resume=True,
        )
    else:
        # Default: From raw PDFs
        raw_books_dir = project_root / "data" / "raw_books"
        pdf_files = sorted(raw_books_dir.glob("*.pdf"))

        if not pdf_files:
            print(f"Error: No PDFs in {raw_books_dir}")
            sys.exit(1)

        print(f"\nMode: From raw PDFs ({len(pdf_files)} files)")
        print("-" * 70)

        all_chunks = []
        for pdf_path in pdf_files:
            print(f"Loading: {pdf_path.name}")
            try:
                chunks = load_and_chunk_pdf(pdf_path, chunk_size=1000, chunk_overlap=100)
                print(f"  → {len(chunks)} chunks")
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"  ⚠ Error: {e}")

        total_gen, total_chunks = generator.run_from_chunks(
            chunks=all_chunks,
            output_filename="classifier_train.jsonl",
            resume=True,
        )

    print(f"\n✅ Done! Generated {total_gen} classifier examples.")
    print(f"   Output: {output_dir / 'classifier_train.jsonl'}")


if __name__ == "__main__":
    main()
