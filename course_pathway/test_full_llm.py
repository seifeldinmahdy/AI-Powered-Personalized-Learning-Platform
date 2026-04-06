import sys
import logging
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, 'src')
from pathway.config import get_settings
from pathway.chromadb_reader import ChromaDBReader
from pathway.llm.naming import OllamaClient
from pathway.llm.ordering import reorder_sections_pedagogically
from pathway.discovery.section_builder import SectionBuilder
from pathway.discovery.graph_builder import GraphBuilder

settings = get_settings()

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

print(f"\n--- Running Pedagogical Ordering for ALL {len(topo_sorted)} sections ---")
result = reorder_sections_pedagogically(
    client=client,
    topo_sorted_sections=topo_sorted,
    course_intent="Introduction to Python",
    max_retries=1
)

print(f"\nResult Length: {len(result)}")
if len(result) > 0:
    print("\nFirst 15 topics in the returned order:")
    for s in result[:15]:
        print(f" - {s.canonical_topic}")
    print("\nLast 5 topics in the returned order:")
    for s in result[-5:]:
        print(f" - {s.canonical_topic}")
