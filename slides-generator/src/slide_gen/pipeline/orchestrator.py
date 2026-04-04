"""
Orchestrator — Main entry point for the presentation pipeline.

Runs all 5 stages end-to-end:
1. Document Processing (PDF → sections)
2. Structural Slides (title, agenda, dividers)
3. Content Pipeline (Flan-T5-Large + DistilBERT + deterministic agents)
4. Summary Generation (Flan-T5-Small, profile-aware)
5. Deck Assembly (ordering + numbering)
"""

import json
import time
from pathlib import Path

from slide_gen.core.profile_schema import StudentProfile
from slide_gen.core.document_plan import DocumentPlan
from slide_gen.pipeline.document_processor import process_document
from slide_gen.pipeline.structural_slides import generate_all_structural_slides
from slide_gen.pipeline.content_pipeline import process_section_chunks
from slide_gen.pipeline.summary_generator import generate_summary_slide
from slide_gen.pipeline.deck_assembler import assemble_deck, deck_to_json
from slide_gen.pipeline.validation import validate_deck

# Resolve local model paths
_ORCH_DIR = Path(__file__).parent
_PROJECT_ROOT = _ORCH_DIR.parent.parent.parent
DEFAULT_T5_PATH = str(_PROJECT_ROOT / "models" / "content_specialist")
DEFAULT_CLASSIFIER_PATH = str(_PROJECT_ROOT / "models" / "visual_classifier")


def generate_presentation(
    pdf_path: str | Path,
    profile: StudentProfile,
    output_path: str | Path | None = None,
    t5_model_path: str = DEFAULT_T5_PATH,
    classifier_model_path: str = DEFAULT_CLASSIFIER_PATH,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    similarity_threshold: float = 0.65,
    max_chunks: int | None = None,
) -> list[dict]:
    """
    Generate a complete presentation from a PDF and student profile.

    Args:
        pdf_path: Path to the source PDF
        profile: Student profile for personalization
        output_path: Optional path to save the output JSON
        t5_model_path: Path to fine-tuned Flan-T5-Large model
        classifier_model_path: Path to fine-tuned DistilBERT model
        chunk_size: Text chunk size in characters
        chunk_overlap: Overlap between chunks
        similarity_threshold: Topic boundary detection sensitivity
        max_chunks: Limit total chunks processed (for testing)

    Returns:
        List of slide dicts (the complete presentation)
    """
    pipeline_start = time.time()

    print("=" * 60)
    print("PRESENTATION PIPELINE")
    print("=" * 60)
    print(f"  PDF: {pdf_path}")
    print(f"  Profile: {profile.mastery_level.value} / "
          f"{profile.composition_mode.value} / "
          f"{profile.language_proficiency.value}")
    print(f"  Content model: {t5_model_path}")
    print(f"  Classifier model: {classifier_model_path}")

    # ---- Stage 1: Document Processing ----
    t0 = time.time()
    print("\n[Stage 1/5] Processing document...")
    plan = process_document(
        pdf_path, chunk_size, chunk_overlap, similarity_threshold
    )
    print(f"  ⏱ Stage 1 completed in {time.time() - t0:.1f}s")

    # ---- Stage 2: Structural Slides ----
    t0 = time.time()
    print("\n[Stage 2/5] Generating structural slides...")
    structural = generate_all_structural_slides(plan)
    print(f"  Generated: Title + Agenda + {len(plan.sections)} dividers")
    print(f"  ⏱ Stage 2 completed in {time.time() - t0:.1f}s")

    # ---- Stage 3: Content Pipeline ----
    t0 = time.time()
    print("\n[Stage 3/5] Processing content through compound AI pipeline...")
    content_slides = {}
    total_chunks_processed = 0
    sections_to_process = plan.sections

    if max_chunks is not None:
        print(f"  ⚡ max_chunks={max_chunks} — limiting processing")

    for section in sections_to_process:
        # Check if we've hit the chunk limit
        if max_chunks is not None and total_chunks_processed >= max_chunks:
            print(f"\n  ⚡ Reached max_chunks limit ({max_chunks}), skipping remaining sections")
            break

        # Determine how many chunks to process from this section
        section_chunks = section.chunks
        if max_chunks is not None:
            remaining = max_chunks - total_chunks_processed
            section_chunks = section_chunks[:remaining]

        print(f"\n  Section {section.id}: '{section.title}' ({len(section_chunks)} chunks)")
        slides = process_section_chunks(
            section_chunks, profile, t5_model_path, classifier_model_path
        )
        content_slides[section.id] = slides
        total_chunks_processed += len(section_chunks)
        print(f"  → Generated {len(slides)} content slides (total chunks: {total_chunks_processed})")

    print(f"\n  ⏱ Stage 3 completed in {time.time() - t0:.1f}s")

    # ---- Stage 4: Summary Slides ----
    t0 = time.time()
    print("\n[Stage 4/5] Generating section summaries...")
    summary_slides = {}
    # Only summarize sections that were actually processed
    processed_section_ids = list(content_slides.keys())
    for section in plan.sections:
        if section.id not in processed_section_ids:
            continue
        print(f"  Summarizing section: '{section.title}'...")
        summary = generate_summary_slide(
            content_slides[section.id],
            section.title,
            profile,
        )
        summary_slides[section.id] = summary
    print(f"  ⏱ Stage 4 completed in {time.time() - t0:.1f}s")

    # ---- Stage 5: Deck Assembly + Validation ----
    t0 = time.time()
    print("\n[Stage 5/5] Assembling and validating final deck...")
    section_ids = [s.id for s in plan.sections]
    deck = assemble_deck(structural, content_slides, summary_slides, section_ids)

    # Run validation layer (Component 6)
    deck = validate_deck(deck, profile)

    deck_json = deck_to_json(deck)

    print(f"\n  ⏱ Stage 5 completed in {time.time() - t0:.1f}s")

    # ---- Summary ----
    total_time = time.time() - pipeline_start
    total_content = sum(len(v) for v in content_slides.values())
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE: {len(deck_json)} total slides in {total_time:.1f}s")
    print(f"    - 1 title + 1 agenda + {len(plan.sections)} dividers")
    print(f"    - {total_content} content slides")
    print(f"    - {len(summary_slides)} summary slides")
    print(f"{'=' * 60}")

    # Save if output path provided
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(deck_json, f, indent=2)
        print(f"\n  Saved to: {output_path}")

    return deck_json
