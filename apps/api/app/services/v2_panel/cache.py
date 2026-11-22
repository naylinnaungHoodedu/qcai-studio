"""The evidential cache (plan Phase 5 task 5.7; AC-5-8, AC-5-11; R-47; Phase 5 spec 4.15, conflicts 2-3; PD-27).

It holds evidential outputs only: claim plans and verifier verdicts (one per claim and span pair). Rendered text,
alignment verdicts and ledger entries are never cached, so nothing a learner was shown is shared across learners
(plan 5.7 "rendered text never shared across learners").
  claim-plan key  canonical sha256 of the evidential envelope (the resolved text and the lesson-scoped evidence the
                  generator saw, so the same question under another lesson scope misses), corpus_version, the
                  configuration package's version and sha256, the generator id and model id, and the evidential
                  prompt hash (plan 5.7's fields)
  verdict key     the union of plan 5.7's fields and plan 7.3's hash(claim_text, span_id, verifier_model_id,
                  verifier_prompt_hash): the claim text's and the span content's hashes, the span id, the verifier's
                  adapter id, model id and model version, the verifier prompt hash, the tool contract version, the
                  resolved question's sha256, corpus_version, the package's version and sha256, the generator id and
                  model id
So a configuration bump (config_package_sha256) or a model change (verifier_model_version) misses. No key or value
holds a learner identifier, a thread or response id or any text: keys are hashes, values are ClaimPlan or
AdapterVerdict (put refuses any other type). The hashes live only in process memory, bounded by the LRU, and are
never logged, persisted or exported. The cache is per process (no shared store exists; DI-79) and starts cold
(plan G). get_cache() is the process cache; reset_process_cache() is the test seam.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
import threading
from typing import Any, Literal, Protocol

from app.core.config_package import canonical_sha256
from app.gateway.contracts import AdapterVerdict
from app.services.tutor_pipeline.contracts import ClaimPlan, sha256_hex

Kind = Literal["claim_plan", "verdict"]
VALUE_TYPES = {"claim_plan": ClaimPlan, "verdict": AdapterVerdict}
KEY_RULE = "plan-5.7-envelope-union-7.3-v1"


class EvidentialCache(Protocol):
    def get(self, kind: Literal["claim_plan", "verdict"], key: str): ...

    def put(self, kind: Literal["claim_plan", "verdict"], key: str, value: ClaimPlan | AdapterVerdict) -> None: ...   # any other type: TypeError


class ProcessEvidentialCache:   # thread-safe; one LRU per kind, max_entries from v4 gateway.cache (1024 plans, 8192 verdicts)
    def __init__(self, *, max_plans: int = 1024, max_verdicts: int = 8192) -> None:
        self._limits = {"claim_plan": int(max_plans), "verdict": int(max_verdicts)}
        self._entries: dict[str, OrderedDict] = {"claim_plan": OrderedDict(), "verdict": OrderedDict()}
        self._lock = threading.Lock()
        self.hits: Counter = Counter()
        self.misses: Counter = Counter()

    def get(self, kind: Kind, key: str):
        with self._lock:
            entries = self._entries[kind]
            value = entries.get(key)
            if value is None:
                self.misses[kind] += 1
                return None
            entries.move_to_end(key)
            self.hits[kind] += 1
            return value

    def put(self, kind: Kind, key: str, value) -> None:
        expected = VALUE_TYPES.get(kind)
        if expected is None or not isinstance(value, expected):
            raise TypeError(f"the evidential cache holds only {expected.__name__ if expected else 'evidential'} values for {kind}")
        with self._lock:
            entries = self._entries[kind]
            entries[key] = value
            entries.move_to_end(key)
            while len(entries) > self._limits[kind]:
                entries.popitem(last=False)

    def evict(self, kind: Kind, key: str) -> None:
        with self._lock:
            self._entries[kind].pop(key, None)

    def values(self, kind: Kind) -> list:
        with self._lock:
            return list(self._entries[kind].values())

    def keys(self, kind: Kind) -> list[str]:
        with self._lock:
            return list(self._entries[kind])

    def snapshot(self) -> dict:
        with self._lock:
            return {kind: {"hits": self.hits[kind], "misses": self.misses[kind], "entries": len(entries)}
                    for kind, entries in self._entries.items()}


def plan_cacheable(generator: Any) -> bool:
    """Only a wired generator's proposals are cached (tutor_pipeline.evidential.GENERATORS): its plan is a function of its
    ref and the envelope. Any other generator (a test double that shares a wired ref, a reviser) is never read from or
    written to the cache."""
    from app.services.tutor_pipeline.evidential import GENERATORS

    factory = GENERATORS.get(getattr(getattr(generator, "ref", None), "generator_id", None))
    return isinstance(factory, type) and type(generator) is factory


def claim_plan_key(envelope: Any, package: Any, generator_ref: Any) -> str:
    return canonical_sha256({
        "kind": "claim_plan",
        "envelope_sha256": canonical_sha256(envelope.model_dump(mode="json")),
        "corpus_version": envelope.corpus_version,
        "config_package_version": package.package_version,
        "config_package_sha256": package.sha256,
        "generator_id": generator_ref.generator_id,
        "generator_model_id": generator_ref.model_id,
        "evidential_prompt_hash": generator_ref.prompt_hash,
    })


def verdict_key(*, claim_text: str, span_id: str, span_content_hash: str, spec: Any, verifier_prompt_hash: str,
                tool_contract_version: str, resolved_question_sha256: str, corpus_version: str, package: Any,
                generator_ref: Any) -> str:
    return canonical_sha256({
        "kind": "verdict",
        "claim_text_sha256": sha256_hex(claim_text),
        "span_id": span_id,
        "span_content_hash": span_content_hash,
        "verifier_adapter_id": spec.adapter_id,
        "verifier_model_id": spec.model_id,
        "verifier_model_version": spec.model_version,
        "verifier_prompt_hash": verifier_prompt_hash,
        "tool_contract_version": tool_contract_version,
        "resolved_question_sha256": resolved_question_sha256,
        "corpus_version": corpus_version,
        "config_package_version": package.package_version,
        "config_package_sha256": package.sha256,
        "generator_id": generator_ref.generator_id,
        "generator_model_id": generator_ref.model_id,
    })


_PROCESS: ProcessEvidentialCache | None = None
_LOCK = threading.Lock()


def get_cache() -> ProcessEvidentialCache:
    global _PROCESS
    with _LOCK:
        if _PROCESS is None:
            from app.core.config import get_settings
            from app.core.config_package import get_config_package

            package = get_config_package(get_settings())
            gateway = package.gateway
            _PROCESS = (ProcessEvidentialCache(max_plans=gateway.cache_max_plans, max_verdicts=gateway.cache_max_verdicts)
                        if gateway is not None else ProcessEvidentialCache())
        return _PROCESS


def reset_process_cache() -> None:
    global _PROCESS
    with _LOCK:
        _PROCESS = None
