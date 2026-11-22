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
AdapterVerdict (put refuses any other type).
Two implementations:
  DatabaseEvidentialCache  shared by every API instance through the application database (evidential_cache_entries;
                           plan 5.7 "Shared cache", 7.5 "shared verdict cache"): each key is stored as a keyed digest
                           (HMAC with the guest-token secret, so a stored key cannot be matched against a guessed
                           question), each value as the canonical JSON of its ClaimPlan or AdapterVerdict; a hit
                           refreshes used_at, and a put evicts the least recently used entries beyond the kind's bound.
                           The table starts empty with its migration (plan G "cold cache"); the keys are never logged
                           or exported. Package v4 gateway.cache.scope "database" makes it the process cache.
  ProcessEvidentialCache   one LRU per kind in process memory: a test's, or the fixture runner's, own cache.
get_cache() is the process's cache; reset_process_cache() is the test seam (a new object and an empty shared table).
"""

from __future__ import annotations

from collections import Counter, OrderedDict
import json
import threading
import time
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


def _table():
    from app.db_models import EvidentialCacheEntry

    return EvidentialCacheEntry.__table__


def _engine():
    from app.core.db import engine

    return engine


class DatabaseEvidentialCache:   # shared by every instance (evidential_cache_entries); bounds from v4 gateway.cache
    def __init__(self, *, max_plans: int = 1024, max_verdicts: int = 8192, clock=time.time) -> None:
        self._limits = {"claim_plan": int(max_plans), "verdict": int(max_verdicts)}
        self._clock = clock
        self._lock = threading.Lock()
        self.hits: Counter = Counter()
        self.misses: Counter = Counter()

    @staticmethod
    def stored_key(key: str) -> str:
        from app.core.client_identity import keyed_digest

        return keyed_digest(key, "evidential-cache")

    def get(self, kind: Kind, key: str):
        from sqlalchemy import select, update

        if kind not in VALUE_TYPES:
            raise KeyError(kind)
        table, stored = _table(), self.stored_key(key)
        where = (table.c.kind == kind, table.c.key == stored)
        with _engine().begin() as connection:
            value = connection.execute(select(table.c.value).where(*where)).scalar_one_or_none()
            if value is not None:
                connection.execute(update(table).where(*where).values(used_at=self._clock()))
        with self._lock:
            (self.misses if value is None else self.hits)[kind] += 1
        return None if value is None else VALUE_TYPES[kind].model_validate_json(value)

    def put(self, kind: Kind, key: str, value) -> None:
        from sqlalchemy import delete, func, select
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        expected = VALUE_TYPES.get(kind)
        if expected is None or not isinstance(value, expected):
            raise TypeError(f"the evidential cache holds only {expected.__name__ if expected else 'evidential'} values for {kind}")
        table, engine = _table(), _engine()
        text = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        insert = postgresql_insert if engine.dialect.name == "postgresql" else sqlite_insert
        now = self._clock()
        statement = insert(table).values(kind=kind, key=self.stored_key(key), value=text, used_at=now)
        statement = statement.on_conflict_do_update(index_elements=[table.c.kind, table.c.key], set_={"value": text, "used_at": now})
        with engine.begin() as connection:
            connection.execute(statement)
            count = int(connection.execute(select(func.count()).select_from(table).where(table.c.kind == kind)).scalar_one())
            excess = count - self._limits[kind]
            if excess > 0:
                oldest = select(table.c.key).where(table.c.kind == kind).order_by(table.c.used_at, table.c.key).limit(excess)
                connection.execute(delete(table).where(table.c.kind == kind, table.c.key.in_([row.key for row in connection.execute(oldest)])))

    def evict(self, kind: Kind, key: str) -> None:
        from sqlalchemy import delete

        table = _table()
        with _engine().begin() as connection:
            connection.execute(delete(table).where(table.c.kind == kind, table.c.key == self.stored_key(key)))

    def _rows(self, kind: Kind) -> list:
        from sqlalchemy import select

        table = _table()
        with _engine().connect() as connection:
            return list(connection.execute(select(table.c.key, table.c.value).where(table.c.kind == kind).order_by(table.c.used_at, table.c.key)))

    def values(self, kind: Kind) -> list:
        return [VALUE_TYPES[kind].model_validate_json(row.value) for row in self._rows(kind)]

    def keys(self, kind: Kind) -> list[str]:
        """The stored keys (keyed digests), least recently used first."""
        return [row.key for row in self._rows(kind)]

    def snapshot(self) -> dict:
        from sqlalchemy import func, select

        table = _table()
        with _engine().connect() as connection:
            counts = dict(connection.execute(select(table.c.kind, func.count()).group_by(table.c.kind)).all())
        with self._lock:
            return {kind: {"hits": self.hits[kind], "misses": self.misses[kind], "entries": int(counts.get(kind, 0))} for kind in VALUE_TYPES}


def clear_shared_cache() -> None:
    from sqlalchemy import delete

    with _engine().begin() as connection:
        connection.execute(delete(_table()))


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


_PROCESS: DatabaseEvidentialCache | ProcessEvidentialCache | None = None
_LOCK = threading.Lock()


def get_cache() -> DatabaseEvidentialCache | ProcessEvidentialCache:
    """The process's cache: the shared DatabaseEvidentialCache when package v4 names the database scope, else (a package
    without a gateway block) a per-process one."""
    global _PROCESS
    with _LOCK:
        if _PROCESS is None:
            from app.core.config import get_settings
            from app.core.config_package import get_config_package

            package = get_config_package(get_settings())
            gateway = package.gateway
            if gateway is None:
                _PROCESS = ProcessEvidentialCache()
            elif gateway.cache_scope == "database":
                _PROCESS = DatabaseEvidentialCache(max_plans=gateway.cache_max_plans, max_verdicts=gateway.cache_max_verdicts)
            else:
                _PROCESS = ProcessEvidentialCache(max_plans=gateway.cache_max_plans, max_verdicts=gateway.cache_max_verdicts)
        return _PROCESS


def reset_process_cache() -> None:
    """The test seam (conftest's autouse fixture; the invariant-1 fixture): a new cache object and an empty shared table."""
    global _PROCESS
    with _LOCK:
        _PROCESS = None
    clear_shared_cache()
