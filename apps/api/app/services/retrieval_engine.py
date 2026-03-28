from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings
from app.schemas import SearchResult
from app.services.content_assembler import CourseStore

try:
    from pinecone import Pinecone
except Exception as exc:  # pragma: no cover - import error path depends on environment packaging.
    Pinecone = None
    PINECONE_IMPORT_ERROR = exc
else:  # pragma: no cover - exercised through mocked backends in tests.
    PINECONE_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)
RRF_K = 60


@dataclass
class RetrievalResponse:
    results: list[SearchResult]
    mode: str


class PineconeSemanticBackend:
    def __init__(self, store: CourseStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.namespace = settings.pinecone_namespace
        self._sync_checked = False

    @property
    def enabled(self) -> bool:
        return bool(
            Pinecone
            and self.settings.openai_api_key
            and self.settings.openai_embedding_model
            and self.settings.pinecone_api_key
            and self.settings.pinecone_index
        )

    @cached_property
    def _embeddings(self) -> OpenAIEmbeddings:
        return OpenAIEmbeddings(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_embedding_model,
        )

    @cached_property
    def _client(self):
        if not Pinecone:
            raise RuntimeError(f"Pinecone SDK is unavailable: {PINECONE_IMPORT_ERROR}")
        return Pinecone(api_key=self.settings.pinecone_api_key)

    @cached_property
    def _index(self):
        return self._client.Index(self.settings.pinecone_index)

    def ensure_index_synced(self, refresh: bool = False) -> None:
        if not self.enabled:
            return
        if self._sync_checked and not refresh:
            return

        namespace_vector_count = self._namespace_vector_count()
        if not refresh and namespace_vector_count == len(self.store.chunks) and namespace_vector_count > 0:
            self._sync_checked = True
            return

        if refresh:
            self._index.delete(delete_all=True, namespace=self.namespace)

        payloads = self._build_vector_payloads()
        batch_size = max(1, self.settings.pinecone_upsert_batch_size)
        for start in range(0, len(payloads), batch_size):
            self._index.upsert(vectors=payloads[start : start + batch_size], namespace=self.namespace)
        self._sync_checked = True

    def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> list[SearchResult]:
        self.ensure_index_synced()
        query_vector = self._embeddings.embed_query(query)
        kwargs: dict[str, Any] = {
            "vector": query_vector,
            "top_k": top_k,
            "include_metadata": True,
            "namespace": self.namespace,
        }
        if lesson_slug:
            kwargs["filter"] = {"lesson_slug": {"$eq": lesson_slug}}

        raw_response = self._index.query(**kwargs)
        return self._matches_to_results(raw_response)

    def _build_vector_payloads(self) -> list[dict[str, Any]]:
        if not self.store.chunks:
            return []

        embeddings = self._embeddings.embed_documents([chunk.excerpt for chunk in self.store.chunks])
        payloads: list[dict[str, Any]] = []
        for chunk, vector in zip(self.store.chunks, embeddings, strict=True):
            payloads.append(
                {
                    "id": chunk.chunk_id,
                    "values": vector,
                    "metadata": {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "source_kind": chunk.source_kind,
                        "source_title": chunk.source_title,
                        "excerpt": chunk.excerpt,
                        "lesson_slug": chunk.lesson_slug,
                        "score_boost": chunk.score_boost,
                        "timestamp_label": chunk.timestamp_label,
                    },
                }
            )
        return payloads

    def _namespace_vector_count(self) -> int:
        stats = self._index.describe_index_stats()
        namespaces = stats.get("namespaces") if isinstance(stats, dict) else getattr(stats, "namespaces", {})
        if not namespaces:
            return 0
        namespace_stats = namespaces.get(self.namespace, {})
        if isinstance(namespace_stats, dict):
            return int(namespace_stats.get("vector_count", 0))
        return int(getattr(namespace_stats, "vector_count", 0) or 0)

    def _matches_to_results(self, raw_response: Any) -> list[SearchResult]:
        raw_matches = raw_response.get("matches") if isinstance(raw_response, dict) else getattr(raw_response, "matches", [])
        results: list[SearchResult] = []
        for match in raw_matches or []:
            metadata = match.get("metadata") if isinstance(match, dict) else getattr(match, "metadata", {}) or {}
            raw_score = match.get("score") if isinstance(match, dict) else getattr(match, "score", 0.0)
            chunk_id = match.get("id") if isinstance(match, dict) else getattr(match, "id", metadata.get("chunk_id"))
            score_boost = float(metadata.get("score_boost", 0.0) or 0.0)
            results.append(
                SearchResult(
                    chunk_id=chunk_id or metadata.get("chunk_id", "semantic-result"),
                    title=metadata.get("title", "Retrieved context"),
                    source_kind=metadata.get("source_kind", "document"),
                    source_title=metadata.get("source_title", metadata.get("title", "Retrieved context")),
                    excerpt=metadata.get("excerpt", ""),
                    lesson_slug=metadata.get("lesson_slug"),
                    score=round(float(raw_score or 0.0) + score_boost, 6),
                    timestamp_label=metadata.get("timestamp_label"),
                )
            )
        return results


class RetrievalEngine:
    def __init__(self, store: CourseStore, settings: Settings):
        self.store = store
        self.settings = settings
        self._semantic_backend = PineconeSemanticBackend(store, settings)

    @property
    def semantic_enabled(self) -> bool:
        return self._semantic_backend.enabled

    def sync_semantic_index(self, refresh: bool = False) -> bool:
        if not self.semantic_enabled:
            return False
        self._semantic_backend.ensure_index_synced(refresh=refresh)
        return True

    def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> RetrievalResponse:
        lexical_results = self.store.search(query, lesson_slug=lesson_slug, top_k=max(top_k * 2, top_k))
        if not self.semantic_enabled:
            return RetrievalResponse(results=lexical_results[:top_k], mode="lexical")

        try:
            semantic_results = self._semantic_backend.search(query, lesson_slug=lesson_slug, top_k=max(top_k * 2, top_k))
        except Exception as exc:
            LOGGER.warning("Semantic retrieval failed; falling back to lexical search: %s", exc)
            return RetrievalResponse(results=lexical_results[:top_k], mode="lexical-fallback")

        if not semantic_results:
            return RetrievalResponse(results=lexical_results[:top_k], mode="lexical-fallback")

        return RetrievalResponse(
            results=self._reciprocal_rank_fusion(semantic_results, lexical_results, top_k=top_k),
            mode="hybrid-pinecone",
        )

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[SearchResult],
        lexical_results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        fused_scores: dict[str, float] = {}
        canonical_results: dict[str, SearchResult] = {}

        for weight, results in ((1.35, semantic_results), (1.0, lexical_results)):
            for rank, result in enumerate(results, start=1):
                fused_scores[result.chunk_id] = fused_scores.get(result.chunk_id, 0.0) + (weight / (RRF_K + rank))
                canonical_results.setdefault(result.chunk_id, result)

        ranked = sorted(
            canonical_results.values(),
            key=lambda result: (fused_scores.get(result.chunk_id, 0.0), result.score),
            reverse=True,
        )
        return [
            result.model_copy(update={"score": round(fused_scores[result.chunk_id], 6)})
            for result in ranked[:top_k]
        ]
