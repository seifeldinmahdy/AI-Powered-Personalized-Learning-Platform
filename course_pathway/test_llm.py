import sys
import logging
from pathlib import Path

# Setup simple stdout logging to capture structlog output
logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, 'src')
from pathway.config import get_settings
from pathway.chromadb_reader import ChromaDBReader
from pathway.llm.naming import OllamaClient
from pathway.llm.ordering import reorder_sections_pedagogically
from pathway.discovery.section_builder import SectionBuilder
from pathway.discovery.graph_builder import GraphBuilder

settings = get_settings()

print(f"--- API Key configured: {'Yes' if settings.ollama_api_key else 'No'} ---")

# 1. Setup minimal dependencies
reader = ChromaDBReader(
    persist_dir=settings.chroma_db_path,
    collection_name=settings.chroma_collection_name,
)
chunks = reader.get_all_course_chunks("pythonlearn")

sb = SectionBuilder()
sections = sb.discover_sections(chunks)

gb = GraphBuilder()
topo_sorted = gb.build_and_sort(sections, chunks)

client = OllamaClient(
    host=settings.ollama_host,
    model=settings.ollama_model,
    api_key=settings.ollama_api_key,
    max_retries=1
)

# 2. Run just the pedagogical ordering
print("\n--- Running Pedagogical Ordering ---")
try:
    pedagogical_order = reorder_sections_pedagogically(
        client=client,
        topo_sorted_sections=topo_sorted[:10], # Just test first 10 for speed
        course_intent="Introduction to Python",
        max_retries=1
    )
    
    print("\n--- Original Topo-Sort Order ---")
    for s in topo_sorted[:10]:
        print(f"{s.canonical_topic}")
        
    print("\n--- LLM Pedagogical Order ---")
    for s in pedagogical_order:
        print(f"{s.canonical_topic}")

except Exception as e:
    print(f"\nLLM Call Failed: {e}")

