#!/usr/bin/env python3
"""
Generate content training data for T5 fine-tuning.

Processes PDFs with multi-perspective profiles and generates
title + bullets training examples with quality validation.

Usage:
    python scripts/generate_content_data.py

Make sure to:
1. Place your PDFs in data/raw_books/
2. Have Ollama running with the configured model
3. Configure .env with correct settings
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.training.content_data_generator import ContentDataGenerator
from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate content training data")
    parser.add_argument("--append", action="store_true", help="Append to existing data instead of overwriting")
    args = parser.parse_args()

    load_dotenv(project_root / ".env")

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    api_key = os.getenv("OLLAMA_API_KEY")  # None for local, set for cloud

    raw_books_dir = project_root / "data" / "raw_books"
    output_dir = project_root / "data" / "agent_training"
    prompts_path = project_root / "config" / "prompts_content.yaml"

    pdf_files = sorted(raw_books_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"Error: No PDF files found in {raw_books_dir}")
        sys.exit(1)

    print("=" * 70)
    print("CONTENT DATA GENERATOR (T5 Training)")
    print("=" * 70)
    print(f"\nFound {len(pdf_files)} PDF(s):")
    for i, pdf in enumerate(pdf_files, 1):
        size_mb = pdf.stat().st_size / (1024 * 1024)
        print(f"  {i}. {pdf.name} ({size_mb:.1f} MB)")

    print(f"\nOllama: {ollama_host} / {ollama_model}")
    print(f"Cloud API: {'Yes (API key set)' if api_key else 'No (local)'}")
    print(f"Max retries: {max_retries}")
    print("-" * 70)

    # Load all PDFs
    all_chunks = []
    for pdf_path in pdf_files:
        print(f"\nLoading: {pdf_path.name}")
        try:
            chunks = load_and_chunk_pdf(pdf_path, chunk_size=1000, chunk_overlap=100)
            print(f"  → {len(chunks)} chunks extracted")
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  ⚠ Error: {e}")
            continue

    if not all_chunks:
        print("Error: No chunks extracted.")
        sys.exit(1)

    print(f"\nTotal chunks: {len(all_chunks)}")

    # Generate
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
        append=args.append,
    )

    print(f"\n✅ Done! Generated {total_generated} content examples.")
    print(f"   Output: {output_dir / 'content_train.jsonl'}")
    print(f"\n   Next: Run scripts/generate_classifier_data.py")


if __name__ == "__main__":
    main()
