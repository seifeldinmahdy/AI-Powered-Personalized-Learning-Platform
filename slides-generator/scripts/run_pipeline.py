#!/usr/bin/env python3
"""
Run Pipeline — CLI script to generate a complete slide deck from a PDF.

Usage:
    python scripts/run_pipeline.py \\
        --pdf data/raw_books/pythonlearn.pdf \\
        --mastery Novice \\
        --mode Balanced \\
        --lang Elementary \\
        --output output/deck.json

    # With accessibility enabled:
    python scripts/run_pipeline.py \\
        --pdf data/raw_books/pythonlearn.pdf \\
        --mastery Expert \\
        --mode Visual_Heavy \\
        --lang Advanced \\
        --a11y \\
        --output output/deck_expert.json

    # Limit chunks for faster testing:
    python scripts/run_pipeline.py \\
        --pdf data/raw_books/pythonlearn.pdf \\
        --max-chunks 5 \\
        --output output/deck_test.json
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path so we can import slide_gen
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

# Load .env file (OLLAMA_HOST, OLLAMA_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    print(f"✅ Loaded .env (OLLAMA_HOST={os.getenv('OLLAMA_HOST', 'not set')})")
except ImportError:
    print("⚠ python-dotenv not installed, reading env vars from shell only")

from slide_gen.core.profile_schema import (
    CompositionMode,
    LanguageProficiency,
    MasteryLevel,
    StudentProfile,
)
from slide_gen.pipeline.orchestrator import generate_presentation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a slide deck from a PDF using the AI pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--pdf",
        type=str,
        required=True,
        help="Path to the source PDF file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/deck.json",
        help="Output path for the deck JSON (default: output/deck.json)",
    )

    # Student profile
    parser.add_argument(
        "--mastery",
        type=str,
        choices=["Novice", "Intermediate", "Expert"],
        default="Intermediate",
        help="Student mastery level (default: Intermediate)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["Visual_Heavy", "Balanced", "Text_Heavy"],
        default="Balanced",
        help="Slide composition mode (default: Balanced)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        choices=["Elementary", "Intermediate", "Advanced", "Native"],
        default="Intermediate",
        help="Language proficiency (default: Intermediate)",
    )
    parser.add_argument(
        "--a11y",
        action="store_true",
        help="Enable screen reader / accessibility mode",
    )

    # Pipeline config
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Text chunk size in characters (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=100,
        help="Overlap between chunks (default: 100)",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.65,
        help="Topic boundary similarity threshold (default: 0.65)",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Limit total chunks processed (for testing)",
    )

    # Model paths (overrides)
    parser.add_argument(
        "--t5-model",
        type=str,
        default=None,
        help="Path to Content Specialist model (default: models/content_specialist)",
    )
    parser.add_argument(
        "--classifier-model",
        type=str,
        default=None,
        help="Path to Visual Classifier model (default: models/visual_classifier)",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Build student profile
    profile = StudentProfile(
        mastery_level=MasteryLevel(args.mastery),
        composition_mode=CompositionMode(args.mode),
        language_proficiency=LanguageProficiency(args.lang),
        screen_reader_active=args.a11y,
    )

    # Build kwargs
    kwargs = {
        "pdf_path": args.pdf,
        "profile": profile,
        "output_path": args.output,
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "similarity_threshold": args.similarity_threshold,
        "max_chunks": args.max_chunks,
    }

    if args.t5_model:
        kwargs["t5_model_path"] = args.t5_model
    if args.classifier_model:
        kwargs["classifier_model_path"] = args.classifier_model

    # Run pipeline
    start = time.time()
    print(f"\n🚀 Starting slide generation pipeline...")
    print(f"   PDF: {args.pdf}")
    print(f"   Profile: {args.mastery} / {args.mode} / {args.lang}")
    print(f"   Accessibility: {'ON' if args.a11y else 'OFF'}")
    print()

    deck_json = generate_presentation(**kwargs)

    elapsed = time.time() - start

    # Print summary
    print(f"\n{'─' * 50}")
    print(f"📊 Deck Summary:")
    print(f"   Total slides: {len(deck_json)}")

    # Count by type
    type_counts = {}
    for slide in deck_json:
        st = slide.get("slide_type", "Content")
        type_counts[st] = type_counts.get(st, 0) + 1

    for slide_type, count in sorted(type_counts.items()):
        print(f"   - {slide_type}: {count}")

    # Count visuals
    visual_count = sum(1 for s in deck_json if s.get("visual"))
    code_count = sum(1 for s in deck_json if s.get("code_block"))
    print(f"   - Slides with visuals: {visual_count}")
    print(f"   - Slides with code: {code_count}")
    print(f"\n   ⏱ Total time: {elapsed:.1f}s")
    print(f"   📁 Output: {args.output}")
    print(f"{'─' * 50}")


if __name__ == "__main__":
    main()
