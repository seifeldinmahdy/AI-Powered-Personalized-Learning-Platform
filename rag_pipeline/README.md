# RAG Pipeline — Document Indexing & Conversational QA

A production-grade offline indexing and retrieval-augmented generation system for the AI-Powered Personalized Learning Platform.  Processes CS textbook PDFs into a shared ChromaDB collection that serves both the **Course Pathway Generator** (metadata-filtered queries) and the **Conversational RAG Agent** (semantic similarity queries).

---

## Folder Structure

```
rag_pipeline/
├── .env / .env.example        # Configuration (Ollama Cloud, ChromaDB, chunking)
├── .gitignore
├── requirements.txt
├── raw_books/                  # Drop PDF textbooks here
├── data/chroma/                # ChromaDB persistent storage (auto-created)
├── apps/
│   └── rag_tester.py           # Streamlit test UI
├── scripts/
│   └── run_indexer.py          # CLI entry point for offline indexing
├── src/
│   ├── config/
│   │   └── settings.py         # Pydantic-settings central config
│   ├── models/
│   │   └── schemas.py          # Pydantic v2 data contracts
│   ├── indexing/
│   │   ├── chunker.py          # PDF extraction + semantic chunking
│   │   ├── analyzer.py         # Per-chunk LLM analysis (1 call per chunk)
│   │   ├── embedder.py         # Sentence-transformer embedding
│   │   ├── store.py            # ChromaDB read/write operations
│   │   └── pipeline.py         # Indexing orchestrator
│   ├── retrieval/
│   │   ├── retriever.py        # ChromaDB query + filter builder
│   │   ├── generator.py        # LLM answer generation with citations
│   │   └── engine.py           # Single ask() entry point
│   ├── llm/
│   │   └── client.py           # Injectable Ollama Cloud HTTP client
│   └── logger/
│       └── setup.py            # Structlog JSON logging
└── tests/
    ├── conftest.py             # Shared fixtures (mock LLM, mock ChromaDB)
    ├── test_chunker.py         # Chunker unit tests
    ├── test_analyzer.py        # LLM parser unit tests
    └── test_rag.py             # RAG query builder + retriever tests
```

---

## Prerequisites

- Python 3.12+
- An Ollama Cloud API key (or compatible endpoint)

---

## Installation

```bash
cd rag_pipeline/

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Copy the example and fill in your API key:

```bash
cp .env.example .env
# Edit .env with your OLLAMA_API_KEY
```

All settings are configurable via environment variables.  Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `https://ollama.com` | Ollama Cloud base URL |
| `OLLAMA_MODEL` | `gpt-oss:120b` | LLM model for analysis & RAG |
| `OLLAMA_API_KEY` | — | Your API key |
| `CHROMA_DB_PATH` | `./data/chroma` | ChromaDB persistent storage path |
| `CHROMA_COLLECTION_NAME` | `course_chunks` | Collection name |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `CHUNK_MIN_TOKENS` | `300` | Minimum chunk size |
| `CHUNK_MAX_TOKENS` | `400` | Maximum chunk size |
| `CHUNK_OVERLAP_TOKENS` | `50` | Token overlap between chunks |
| `RAW_BOOKS_DIR` | `./raw_books` | Directory containing PDF textbooks |
| `TOP_K` | `5` | Default number of chunks to retrieve |

---

## Running the Indexer

1. Place your PDF textbooks in `raw_books/`.
2. Run the indexing pipeline:

```bash
cd rag_pipeline/
python -m scripts.run_indexer
```

The pipeline will:
- Extract text from each PDF using PyMuPDF
- Split into 300–400 token chunks with 50-token overlap
- Analyze each chunk via the Ollama Cloud API (topic, difficulty, etc.)
- Embed each chunk with `all-MiniLM-L6-v2`
- Store everything in ChromaDB

**Resumability:** If interrupted, re-running will skip already-indexed chunks automatically.

---

## Running the Test App

```bash
cd rag_pipeline/
streamlit run apps/rag_tester.py
```

The Streamlit app lets you:
- Type a question in natural language
- Filter by course and difficulty
- Adjust the number of retrieved chunks (top-k)
- View the grounded answer with source citations

---

## Running Tests

```bash
cd rag_pipeline/
python -m pytest tests/ -v
```

Tests use mocked LLM and ChromaDB clients — no API calls or database required.

---

## Architecture Notes

- **One collection, two consumers:** The ChromaDB collection is designed for both metadata-filtered queries (Pathway Generator) and semantic similarity queries (RAG Agent).
- **Injectable LLM client:** `OllamaCloudClient` can be replaced with a mock for testing.  Pass any object with matching `chat()` / `chat_json()` methods.
- **Deterministic chunk IDs:** Format `{book_stem}_{page_start}_{chunk_index}` ensures idempotent re-indexing.
- **`depends_on` serialization:** Stored as a JSON string in ChromaDB metadata (which only supports scalar types).

---

## ChromaDB Metadata Schema

Each chunk is stored with the following metadata fields:

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | Main concept (1-3 words) |
| `difficulty` | `str` | `beginner` / `intermediate` / `expert` |
| `is_definitional` | `bool` | Whether the chunk defines a concept |
| `depends_on` | `str` (JSON) | Prerequisite topics |
| `summary` | `str` | One-sentence description |
| `book` | `str` | Source book filename stem |
| `course` | `str` | Course identifier |
| `page_start` | `int` | Starting page (1-indexed) |
| `page_end` | `int` | Ending page (1-indexed) |
| `chunk_index` | `int` | Sequential chunk index within the book |
