"""Retrieval over the Phase 2 span index (plan Phase 2 task 2.5; Phase 2 spec 4.14).

Lexical retrieval is the evidence path: CourseStore.evaluate with the active gate (p1-floor or bm25f-v1). The
semantic (Pinecone) backend is OFF unless SEMANTIC_RETRIEVAL_ENABLED, whatever keys are set; it also needs the D-23
opt-in, openai-embeddings in MODEL_EGRESS_PROVIDERS (PD-22; a refusal logs gateway.egress_refused once per process,
consumer semantic-retrieval), and even then it runs only once it is aligned: its vector ids are span ids and the
namespace holds exactly one vector per index entry. RetrievalEngine.semantic_inactive_reason names why it is off.
Every semantic result is re-gated with the active gate before fusion, so hybrid fusion can never bypass the
abstention floor (the latent hybrid bypass found on 2026-11-17). Nothing here takes a learner input.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
import logging
import time
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings
from app.core.structured_logging import FIELDS
from app.schemas import SearchResult
from app.services.content_assembler import CourseStore
from app.services.lexical_index import ScoredEntry
from app.services.retrieval_metrics import record_decision
from app.services.spans import SPAN_SCHEME

try:
    from pinecone import Pinecone
except Exception as exc:  # pragma: no cover - import error path depends on environment packaging.
    Pinecone = None
    PINECONE_IMPORT_ERROR = exc
else:  # pragma: no cover - exercised through mocked backends in tests.
    PINECONE_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)
DECISION_LOGGER = logging.getLogger("qcai.retrieval")
# The D-23 egress provider name the semantic backend needs in MODEL_EGRESS_PROVIDERS (PD-22).
EMBEDDINGS_PROVIDER = "openai-embeddings"
RRF_K = 60
SEMANTIC_WEIGHT = 1.35
LEXICAL_WEIGHT = 1.0


@dataclass
class RetrievalResponse:
    results: list[SearchResult]
    mode: str
    abstained: bool = False
    reason: str = "evidence"
    gate: str = "p1-floor"
    index_version: str = ""
    floor: float = 0.0
    margin: float = 0.0
    near_floor: int = field(default=0)
    # Span id -> the gate score of each result (ScoredEntry.gate_score: the score the gate compared with its floor, at
    # its precision), so a sufficiency records the score the floor applies to, not a result's display or ranking score
    # (retrieve.sufficiency_of; Phase 4 spec 4.6, M11).
    gate_scores: dict[str, float] = field(default_factory=dict)


class PineconeSemanticBackend:
    def __init__(self, store: CourseStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.namespace = settings.pinecone_namespace
        self._sync_checked = False
        # True only after sync_semantic_index saw one span-id vector per index entry ([R18]).
        self.aligned = False

    @property
    def egress_refused(self) -> bool:
        """The setting is on but the environment has not opted in to the embedding egress (D-23, PD-22)."""
        from app.gateway.egress import egress_allowed

        return bool(self.settings.semantic_retrieval_enabled) and not egress_allowed(self.settings, EMBEDDINGS_PROVIDER)

    @property
    def enabled(self) -> bool:
        # D-23 (PD-22): the embedding egress also needs the environment's opt-in, openai-embeddings in
        # MODEL_EGRESS_PROVIDERS (Phase 5 spec conflict 10); moving it behind the gateway is DI-77.
        from app.gateway.egress import egress_allowed

        return bool(
            self.settings.semantic_retrieval_enabled
            and egress_allowed(self.settings, "openai-embeddings")
            and Pinecone
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

    def ensure_index_synced(self, refresh: bool = False) -> bool:
        """Upsert span-id vectors when needed; returns whether the namespace count equals the entry count."""
        if not self.enabled:
            self.aligned = False
            return False
        if self._sync_checked and not refresh:
            return self.aligned
        expected = len(self.store.chunks)
        namespace_vector_count = self._namespace_vector_count()
        if refresh or namespace_vector_count != expected:
            if namespace_vector_count:
                self._index.delete(delete_all=True, namespace=self.namespace)
            payloads = self._build_vector_payloads()
            batch_size = max(1, self.settings.pinecone_upsert_batch_size)
            for start in range(0, len(payloads), batch_size):
                self._index.upsert(vectors=payloads[start : start + batch_size], namespace=self.namespace)
            namespace_vector_count = self._namespace_vector_count()
        self.aligned = expected > 0 and namespace_vector_count == expected
        if not self.aligned:
            LOGGER.warning(
                "Semantic index is not aligned with the span index; retrieval stays lexical",
                extra={FIELDS: {"event": "semantic.misaligned", "expected": expected, "found": namespace_vector_count}},
            )
        self._sync_checked = True
        return self.aligned

    def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> list[SearchResult]:
        query_vector = self._embeddings.embed_query(query)
        kwargs: dict[str, Any] = {
            "vector": query_vector,
            "top_k": top_k,
            "include_metadata": True,
            "namespace": self.namespace,
        }
        if lesson_slug:
            kwargs["filter"] = {"lesson_slugs": {"$in": [lesson_slug]}}
        raw_response = self._index.query(**kwargs)
        return self._matches_to_results(raw_response)

    def _build_vector_payloads(self) -> list[dict[str, Any]]:
        if not self.store.chunks:
            return []
        embeddings = self._embeddings.embed_documents([entry.excerpt for entry in self.store.chunks])
        # Ids are span ids; metadata carries identity only, no excerpt or title text.
        return [
            {
                "id": entry.span_id,
                "values": vector,
                "metadata": {
                    "span_id": entry.span_id,
                    "span_scheme": SPAN_SCHEME,
                    "item_id": entry.item_id,
                    "item_version": entry.item_version,
                    "lesson_slugs": list(entry.lesson_slugs),
                },
            }
            for entry, vector in zip(self.store.chunks, embeddings, strict=True)
        ]

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
            metadata = (match.get("metadata") if isinstance(match, dict) else getattr(match, "metadata", {})) or {}
            span_id = match.get("id") if isinstance(match, dict) else getattr(match, "id", None)
            if metadata.get("span_scheme") != SPAN_SCHEME:
                continue
            entry = self.store.entry(span_id or "")
            if entry is None:
                continue
            raw_score = match.get("score") if isinstance(match, dict) else getattr(match, "score", 0.0)
            # Built from the in-memory entry only; the score is replaced by the gate's evidence score on fusion.
            results.append(self.store.to_search_result(ScoredEntry(entry, float(raw_score or 0.0), 0, False), None))
        return results


def _gate_scores(scored: "Iterable[ScoredEntry]") -> dict[str, float]:
    """Span id -> gate score of gated results (RetrievalResponse.gate_scores)."""
    return {item.entry.span_id: item.gate_score for item in scored if item.gate_score is not None}


class RetrievalEngine:
    def __init__(self, store: CourseStore, settings: Settings):
        self.store = store
        self.settings = settings
        self._semantic_backend = PineconeSemanticBackend(store, settings)

    @property
    def semantic_enabled(self) -> bool:
        backend = self._semantic_backend
        return bool(self.settings.semantic_retrieval_enabled and backend.enabled and getattr(backend, "aligned", False))

    @property
    def semantic_inactive_reason(self) -> str | None:
        """Why semantic retrieval is off although its setting is on: egress_not_opted_in (D-23), not_configured (a key,
        the SDK or the index is missing) or not_aligned; None when the setting is off or retrieval is hybrid."""
        backend = self._semantic_backend
        if not self.settings.semantic_retrieval_enabled or self.semantic_enabled:
            return None
        if getattr(backend, "egress_refused", False):
            return "egress_not_opted_in"
        return "not_aligned" if backend.enabled else "not_configured"

    def sync_semantic_index(self, refresh: bool = False) -> bool:
        """The one place that computes alignment ([R18]); True when hybrid retrieval may run. A setting that is on
        without the D-23 opt-in logs gateway.egress_refused (once per process) and stays lexical."""
        backend = self._semantic_backend
        if getattr(backend, "egress_refused", False):
            from app.gateway.egress import log_refusal

            log_refusal(EMBEDDINGS_PROVIDER, consumer="semantic-retrieval")
        if not (self.settings.semantic_retrieval_enabled and backend.enabled):
            return False
        backend.ensure_index_synced(refresh=refresh)
        return self.semantic_enabled

    def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8, *, surface: str = "search") -> RetrievalResponse:
        started = time.perf_counter()
        response = self._search(query, lesson_slug, top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        record_decision(surface, response.mode, response.gate, response.abstained, response.reason, latency_ms)
        DECISION_LOGGER.info(
            "Retrieval decision",
            extra={
                FIELDS: {
                    "event": "retrieval.decision",
                    "surface": surface,
                    "mode": response.mode,
                    "gate": response.gate,
                    "abstained": response.abstained,
                    "reason": response.reason,
                    "results": len(response.results),
                    "near_floor": response.near_floor,
                    "top_score": response.results[0].score if response.results else None,
                    "latency_ms": round(latency_ms, 3),
                    "index_version": response.index_version,
                    "threshold_version": self.store.index.threshold_version,
                }
            },
        )
        return response

    def evidence(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> RetrievalResponse:
        """Lexical evidence for the two-pass tutor (Phase 3 spec 7.5, conflict 33).

        The lexical branch of _search, whatever SEMANTIC_RETRIEVAL_ENABLED says: it never calls the semantic
        backend, so no resolved question reaches an embeddings provider (D-12, R-10). It records no Phase 2
        retrieval SLI, so shadow runs never double-count learner-facing decisions.
        """
        decision = self.store.evaluate(query, lesson_slug=lesson_slug, top_k=max(top_k * 2, top_k))
        results = [self.store.to_search_result(scored, lesson_slug) for scored in decision.results][:top_k]
        return RetrievalResponse(
            results=results,
            mode="lexical",
            abstained=not results,
            reason=decision.reason if not results else "evidence",
            gate=decision.gate,
            index_version=self.store.index_version,
            floor=decision.floor,
            margin=decision.margin,
            near_floor=sum(1 for result in results if result.near_floor),
            gate_scores=_gate_scores(decision.results),
        )

    def _search(self, query: str, lesson_slug: str | None, top_k: int) -> RetrievalResponse:
        decision = self.store.evaluate(query, lesson_slug=lesson_slug, top_k=max(top_k * 2, top_k))
        lexical = [self.store.to_search_result(scored, lesson_slug) for scored in decision.results]
        gate_scores = _gate_scores(decision.results)
        common = {"gate": decision.gate, "index_version": self.store.index_version, "floor": decision.floor, "margin": decision.margin,
                  "gate_scores": gate_scores}

        def lexical_response(mode: str) -> RetrievalResponse:
            results = lexical[:top_k]
            return RetrievalResponse(
                results=results,
                mode=mode,
                abstained=not results,
                reason=decision.reason if not results else "evidence",
                near_floor=sum(1 for result in results if result.near_floor),
                **common,
            )

        if not self.semantic_enabled:
            return lexical_response("lexical")
        try:
            semantic_raw = self._semantic_backend.search(query, lesson_slug=lesson_slug, top_k=max(top_k * 2, top_k))
        except Exception as exc:
            LOGGER.warning("Semantic retrieval failed; falling back to lexical search: %s", exc)
            return lexical_response("lexical-fallback")
        semantic: list[SearchResult] = []
        for result in semantic_raw:
            entry = self.store.entry(result.chunk_id)
            if entry is None:  # not a current span id: dropped
                continue
            gated = self.store.index.gate_entry(query, entry, lesson_slug)
            if gated is None:  # the floor applies to every result, whatever the mode
                continue
            gate_scores.update(_gate_scores((gated,)))
            semantic.append(self.store.to_search_result(gated, lesson_slug))
        if not semantic:
            return lexical_response("lexical-fallback")
        fused = self._reciprocal_rank_fusion(semantic, lexical, top_k=top_k)
        return RetrievalResponse(
            results=fused,
            mode="hybrid-pinecone",
            abstained=not fused,
            reason="evidence" if fused else decision.reason,
            near_floor=sum(1 for result in fused if result.near_floor),
            **common,
        )

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[SearchResult],
        lexical_results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        fused_scores: dict[str, float] = {}
        canonical_results: dict[str, SearchResult] = {}
        for weight, results in ((SEMANTIC_WEIGHT, semantic_results), (LEXICAL_WEIGHT, lexical_results)):
            for rank, result in enumerate(results, start=1):
                fused_scores[result.chunk_id] = fused_scores.get(result.chunk_id, 0.0) + (weight / (RRF_K + rank))
                canonical_results.setdefault(result.chunk_id, result)
        ranked = sorted(
            canonical_results.values(),
            key=lambda result: (fused_scores.get(result.chunk_id, 0.0), result.score, result.chunk_id),
            reverse=True,
        )
        # The score stays the active gate's evidence score; fusion only orders.
        return ranked[:top_k]
