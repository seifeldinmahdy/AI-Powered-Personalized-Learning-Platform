"""RAG engine — single public entry point for question answering.

Composes the embedder, retriever, and answer generator into one clean
class with a typed ``ask()`` method.
"""

from __future__ import annotations

import structlog

from src.config.settings import Settings
from src.indexing.embedder import ChunkEmbedder
from src.indexing.store import VectorStore
from src.llm.client import OllamaCloudClient
from src.models.schemas import RAGQuery, RAGResponse
from src.retrieval.generator import AnswerGenerator
from src.retrieval.retriever import Retriever

logger = structlog.get_logger(__name__)


class RAGEngine:
    """Conversational RAG pipeline with a single public method.

    Usage::

        engine = RAGEngine(settings, llm_client)
        response = engine.ask("What is a binary search tree?")
        print(response.answer)
        for src in response.sources:
            print(f"  [{src.book} p.{src.page_start}-{src.page_end}]")
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: OllamaCloudClient,
    ) -> None:
        self.embedder = ChunkEmbedder(model_name=settings.embedding_model)
        self.store = VectorStore(
            persist_dir=settings.chroma_db_path,
            collection_name=settings.chroma_collection_name,
        )
        self.retriever = Retriever(store=self.store)
        self.generator = AnswerGenerator(llm_client=llm_client)

    # ── Public API ────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        course: str | None = None,
        topic: str | None = None,
        difficulty: str | None = None,
        top_k: int = 5,
    ) -> RAGResponse:
        """Answer a student question grounded in course material.

        Parameters
        ----------
        question:
            The student's natural-language question.
        course / topic / difficulty:
            Optional metadata filters to narrow retrieval.
        top_k:
            Number of chunks to retrieve (default 5).

        Returns
        -------
        RAGResponse
            Typed response with answer text and source citations.
        """
        query = RAGQuery(
            question=question,
            course=course,
            topic=topic,
            difficulty=difficulty,
            top_k=top_k,
        )

        logger.info(
            "rag_query_start",
            question=question[:100],
            course=course,
            topic=topic,
        )

        # 1. Embed the question
        q_embedding = self.embedder.embed_single(question)

        # 2. Retrieve relevant chunks
        sources = self.retriever.retrieve(
            query_embedding=q_embedding,
            query=query,
        )

        # 3. Generate grounded answer
        answer = self.generator.generate(
            question=question,
            sources=sources,
        )

        logger.info(
            "rag_query_complete",
            n_sources=len(sources),
            answer_length=len(answer),
        )

        return RAGResponse(
            answer=answer,
            sources=sources,
            question=question,
        )
