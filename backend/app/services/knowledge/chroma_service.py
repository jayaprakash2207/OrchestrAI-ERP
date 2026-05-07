from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

import chromadb

from app.core.config import settings
from app.services.ai.gemini_client import InMemoryTTLCache
from app.services.orchestration.state import RetrievedDocument

logger = logging.getLogger("app.knowledge.chroma")


class ChromaKnowledgeService:
    def __init__(self) -> None:
        self.cache = InMemoryTTLCache(settings.retrieval_cache_ttl_seconds)
        self.client: Any | None = None
        self.collection = None

    def initialize(self) -> None:
        if self.client is not None and self.collection is not None:
            return
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        self.collection = self.client.get_or_create_collection(name=settings.chroma_jde_collection_name)

    @staticmethod
    def _chunk_document(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
        if len(text) <= chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start = max(end - overlap, start + 1)
        return chunks

    def populate_defaults(self) -> None:
        rows = [
            ("gl_structure", "finance", "General ledger accounts follow parent-child hierarchy and support assets, liabilities, equity, revenue, and expenses."),
            ("ap_process", "finance", "AP invoices move through draft, approval, posting, payment, and void workflows with audit logging."),
            ("inventory_policy", "supply_chain", "Inventory adjustments require reasons, auditability, and stock-level monitoring."),
        ]
        self.add_documents([
            (
                chunk,
                f"{source}-{index}-{uuid4().hex[:8]}",
                {"source": source, "category": category, "version": "1.0"},
            )
            for source, category, body in rows
            for index, chunk in enumerate(self._chunk_document(body, 240, 30))
        ])

    def add_documents(self, documents: list[tuple[str, str, dict[str, Any]]]) -> None:
        self.initialize()
        assert self.collection is not None
        if not documents:
            return
        self.collection.add(
            documents=[item[0] for item in documents],
            ids=[item[1] for item in documents],
            metadatas=[item[2] for item in documents],
        )

    def bulk_upload(self, documents: list[dict[str, Any]]) -> None:
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for document in documents:
            for index, chunk in enumerate(self._chunk_document(document["content"], 400, 40)):
                rows.append(
                    (
                        chunk,
                        f"{document.get('source', 'bulk')}-{uuid4().hex[:10]}-{index}",
                        {
                            "source": document.get("source", "bulk_upload"),
                            "category": document.get("category", "general"),
                            "version": document.get("version", "1.0"),
                        },
                    )
                )
        self.add_documents(rows)

    def retrieve(self, query: str, *, module: str | None = None, limit: int | None = None) -> list[RetrievedDocument]:
        cache_key = f"retrieve:{module}:{query}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        self.initialize()
        assert self.collection is not None
        where = {"category": module} if module else None
        started = datetime.utcnow()
        results = self.collection.query(query_texts=[query], n_results=limit or settings.chroma_retrieval_limit, where=where)
        elapsed_ms = (datetime.utcnow() - started).total_seconds() * 1000
        docs: list[RetrievedDocument] = []
        for idx, document in enumerate(results.get("documents", [[]])[0]):
            distance = results.get("distances", [[]])[0][idx] if results.get("distances") else None
            relevance = None if distance is None else max(0.0, 1 - float(distance))
            if relevance is not None and relevance < settings.chroma_similarity_threshold:
                continue
            metadata = results.get("metadatas", [[]])[0][idx] if results.get("metadatas") else {}
            docs.append(
                RetrievedDocument(
                    document_id=results.get("ids", [[]])[0][idx],
                    content=document,
                    source=metadata.get("source", "unknown"),
                    category=metadata.get("category", "general"),
                    version=metadata.get("version"),
                    relevance_score=relevance,
                    metadata=metadata,
                )
            )
        logger.info("Chroma retrieval completed query=%s results=%s latency_ms=%.2f", query[:120], len(docs), elapsed_ms)
        self.cache.set(cache_key, docs)
        return docs
