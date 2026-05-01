"""Data engine module for PDF loading and data generation utilities."""

from slide_gen.data_engine.utils import (
    VARIATION_GENERATORS,
    VARIATIONS_PER_CHUNK,
    generate_novice_profile,
    generate_expert_profile,
    generate_intermediate_profile,
    generate_visual_expert_profile,
    generate_novice_text_profile,
    generate_balanced_novice_profile,
    generate_intermediate_visual_profile,
    generate_expert_balanced_profile,
    generate_intermediate_text_profile,
    generate_random_profile,
    format_training_input,
    is_valid_chunk,
    chunk_has_code,
    extract_json_from_response,
    load_prompts,
)
from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf

__all__ = [
    "VARIATION_GENERATORS",
    "VARIATIONS_PER_CHUNK",
    "generate_novice_profile",
    "generate_expert_profile",
    "generate_intermediate_profile",
    "generate_visual_expert_profile",
    "generate_novice_text_profile",
    "generate_balanced_novice_profile",
    "generate_intermediate_visual_profile",
    "generate_expert_balanced_profile",
    "generate_intermediate_text_profile",
    "generate_random_profile",
    "format_training_input",
    "is_valid_chunk",
    "chunk_has_code",
    "extract_json_from_response",
    "load_prompts",
    "load_and_chunk_pdf",
]

