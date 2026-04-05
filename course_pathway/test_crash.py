import sys
sys.path.insert(0, './src')
from pathway.config import get_settings
from pathway.models.schemas import StudentContext
from pathway.chromadb_reader import ChromaDBReader
from pathway.storage.plan_store import PlanStore
from pathway.llm.naming import OllamaClient
from pathway.generator import PathwayGenerator

settings = get_settings()
reader = ChromaDBReader(
    persist_dir=settings.chroma_db_path,
    collection_name=settings.chroma_collection_name,
)
store = PlanStore(db_path=settings.sqlite_db_path)
llm_client = OllamaClient(
    host=settings.ollama_host,
    model=settings.ollama_model,
    api_key=settings.ollama_api_key,
    max_retries=settings.max_retries,
) if settings.ollama_api_key else None

gen = PathwayGenerator(
    settings=settings,
    reader=reader,
    store=store,
    llm_client=llm_client,
)

ctx = StudentContext(
    student_id="test_user",
    course_id="pythonlearn",
    mastery_level="Intermediate",
    use_synthetic_context=True,
    course_intent=""
)

try:
    res = gen.generate(ctx)
    print("Success:", len(res.sessions))
except Exception as e:
    import traceback
    traceback.print_exc()
