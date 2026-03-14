"""
Orchestrator — Main entry point for the presentation pipeline.

Runs all 5 stages end-to-end:
1. Document Processing (PDF → sections)
2. Structural Slides (title, agenda, dividers)
3. Content Pipeline (T5 + DistilBERT + deterministic agents)
4. Summary Generation (Flan-T5-Small, profile-aware)
5. Deck Assembly (ordering + numbering)
"""

import json
from pathlib import Path

from slide_gen.core.profile_schema import StudentProfile
from slide_gen.core.document_plan import DocumentPlan
from slide_gen.pipeline.document_processor import process_document
from slide_gen.pipeline.structural_slides import generate_all_structural_slides
from slide_gen.pipeline.content_pipeline import process_section_chunks
from slide_gen.pipeline.summary_generator import generate_summary_slide
from slide_gen.pipeline.deck_assembler import assemble_deck, deck_to_json


def generate_presentation(
    pdf_path: str | Path,
    profile: StudentProfile,
    output_path: str | Path | None = None,
    t5_model_path: str = "t5-base",
    classifier_model_path: str = "distilbert-base-uncased",
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    similarity_threshold: float = 0.65,
) -> list[dict]:
    """
    Generate a complete presentation from a PDF and student profile.

    Args:
        pdf_path: Path to the source PDF
        profile: Student profile for personalization
        output_path: Optional path to save the output JSON
        t5_model_path: Path to fine-tuned T5 model
        classifier_model_path: Path to fine-tuned DistilBERT model
        chunk_size: Text chunk size in characters
        chunk_overlap: Overlap between chunks
        similarity_threshold: Topic boundary detection sensitivity

    Returns:
        List of slide dicts (the complete presentation)
    """
    print("=" * 60)
    print("PRESENTATION PIPELINE")
    print("=" * 60)

    # ---- Stage 1: Document Processing ----
    print("\n[Stage 1/5] Processing document...")
    plan = process_document(
        pdf_path, chunk_size, chunk_overlap, similarity_threshold
    )

    # ---- Stage 2: Structural Slides ----
    print("\n[Stage 2/5] Generating structural slides...")
    structural = generate_all_structural_slides(plan)
    print(f"  Generated: Title + Agenda + {len(plan.sections)} dividers")

    # ---- Stage 3: Content Pipeline ----
    print("\n[Stage 3/5] Processing content through compound AI pipeline...")
    content_slides = {}
    for section in plan.sections:
        print(f"\n  Section {section.id}: '{section.title}'")
        slides = process_section_chunks(
            section.chunks, profile, t5_model_path, classifier_model_path
        )
        content_slides[section.id] = slides
        print(f"  → Generated {len(slides)} content slides")

    # ---- Stage 4: Summary Slides ----
    print("\n[Stage 4/5] Generating section summaries...")
    summary_slides = {}
    for section in plan.sections:
        print(f"  Summarizing section: '{section.title}'...")
        summary = generate_summary_slide(
            content_slides[section.id],
            section.title,
            profile,
        )
        summary_slides[section.id] = summary

    # ---- Stage 5: Deck Assembly ----
    print("\n[Stage 5/5] Assembling final deck...")
    section_ids = [s.id for s in plan.sections]
    deck = assemble_deck(structural, content_slides, summary_slides, section_ids)
    deck_json = deck_to_json(deck)

    print(f"\n  COMPLETE: {len(deck_json)} total slides")
    print(f"    - 1 title + 1 agenda + {len(plan.sections)} dividers")
    total_content = sum(len(v) for v in content_slides.values())
    print(f"    - {total_content} content slides")
    print(f"    - {len(summary_slides)} summary slides")

    # Save if output path provided
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(deck_json, f, indent=2)
        print(f"\n  Saved to: {output_path}")

    return deck_json
