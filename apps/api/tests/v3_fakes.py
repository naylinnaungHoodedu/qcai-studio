"""Fakes for the Phase 6 V3 tests (Phase 6 spec 13.1). Not a test module: a fresh in-memory database with the V3 tables
and triggers, synthetic legacy deliveries, a shadow V3 record of query 30 through the V2 pipeline, synthetic reviewer
headers, staging settings, a fixed clock for fresh databases and a cache that never hits. No learner data: ids are
synthetic (turn-{UUID(int=i)}, uuid4 demo users), and no test writes a backdated queue item into the shared database
(FIXED_NOW is for fresh_v3_sessions() only; conftest.py fails a test that does).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

FIXED_NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
QUERIES_PATH = Path(__file__).resolve().parent / "data" / "score_floor_queries.json"
CRITICAL_QUERY_INDEX = 30
CRITICAL_CLAIMS = ("claim-5986f3f1a2e538431cad1eba9de377a7", "claim-f7a69a03bf419134f7104233b637aed6", "claim-71143cadf24a121f65b59a75a9b9ec53")


def in_domain(index: int) -> str:
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))["in_domain"][index]["query"]


CRITICAL_QUERY = in_domain(CRITICAL_QUERY_INDEX)


@contextmanager
def fresh_v3_sessions() -> Iterator[tuple]:
    """(session_factory, engine) over a fresh in-memory SQLite with every table and trigger; disposed on exit."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        engine.dispose()


def synthetic_id(index: int) -> str:
    return f"turn-{UUID(int=index)}"


def synthetic_deliveries(n: int, *, start: int = 1, decision: str = "answer", text: str = "Routing adds SWAP gates on sparse hardware.",
                         span_id: str = "span-" + "1" * 64) -> list:
    from tutor_fakes import make_entry

    return [make_entry(synthetic_id(index), decision=decision, text=text, span_id=span_id) for index in range(start, start + n)]


def append_all(factory, entries, *, now: datetime | None = None) -> list:
    from app.services.ledger import append_ledger_entry

    return [append_ledger_entry(entry, session_factory=factory, budget_ms=60000, attempts=3, now=now) for entry in entries]


def reviewer(name: str) -> dict[str, str]:
    return {"x-demo-user": f"synthetic-{name}", "x-demo-role": "reviewer"}


def staging_settings(**overrides):
    from app.core.config import Settings

    options = dict(environment="staging", enable_demo_auth=True, guest_token_secret="s" * 32, allowed_origins=["https://staging.example.test"])
    options.update(overrides)
    return Settings(**options)


def dev_settings(**overrides):
    from app.core.config import Settings

    return Settings(environment="development", **overrides)


class NoCache:
    """An evidential cache that never hits, so every correction cycle calls every member again."""

    def get(self, kind, key):
        return None

    def put(self, kind, key, value) -> None:
        if kind not in ("claim_plan", "verdict"):
            raise TypeError(kind)


def objecting_adapters(registry, objector: str, claim_texts: dict[str, tuple[str, ...]], *, ehmf: str = "A", fail_calls=()):
    """Scripted fakes: `objector` contradicts each given claim text on its spans with EHMF `ehmf`; it also fails on the
    given call numbers (leaving the panel)."""
    from v2_fakes import adapters_of, claim_key

    script = {claim_key(text, span_id): ("CONTRADICTED", ehmf) for text, spans in claim_texts.items() for span_id in spans}
    options = {objector: {"script": script, "fail_calls": tuple(fail_calls)}}
    return adapters_of(registry, **options)


def critical_claims_of(pipeline) -> list:
    """The locked claims of the critical query (query 30) in the development pipeline."""
    from v1_fakes import run

    return [claim for claim in run(pipeline, CRITICAL_QUERY).locked.claims if claim.claim_id in CRITICAL_CLAIMS]


def shadow_v3_record(query: str = CRITICAL_QUERY, *, settings=None, adapters=None, generator=None, cache=None, v3_stop=None):
    """(result, entry) of a two-pass run through the V2 pipeline (development registry fakes unless adapters given)."""
    from v1_fakes import run
    from v2_fakes import fresh_gateway, make_registry, v2_pipeline

    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    kwargs = {}
    if generator is not None:
        kwargs["generator"] = generator
    if v3_stop is not None:
        kwargs["v3_stop"] = v3_stop
    pipeline = v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=registry, cache=cache, **kwargs)
    result = run(pipeline, query)
    return result, result.entry


_QUOTABLE: list = []


def quotable_claim() -> tuple[str, str]:
    """(text, span id) of a locked claim of the development pipeline: a public, quotable span a reviewer is shown."""
    if not _QUOTABLE:
        from v1_fakes import dev_pipeline, run

        claim = run(dev_pipeline(), CRITICAL_QUERY).locked.claims[0]
        _QUOTABLE.append((claim.text, claim.span_ids[0]))
    return _QUOTABLE[0]


def reviewable_deliveries(n: int, *, start: int = 1, decision: str = "answer") -> list:
    text, span_id = quotable_claim()
    return synthetic_deliveries(n, start=start, decision=decision, text=text, span_id=span_id)


def seed_items(factory, entries, *, package, now, trigger: str = "X6", double_review: bool | None = None) -> list[str]:
    """Append the entries and give each record a response item with `trigger`; returns the item ids."""
    from sqlalchemy import update

    from app.db_models import V3QueueItem
    from app.services.v3 import queue
    from app.services.v3.triggers import response_spec

    appended = append_all(factory, entries)
    ids = []
    with factory() as db:
        for record in appended:
            row = queue.record_row(db, record.seq)
            entry = queue.parse_entry(row)
            item_id, _ = queue.upsert_item(db, record_row=row, spec=response_spec(entry, trigger), entry=entry, package=package, now=now)
            if double_review is not None:
                db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item_id).values(double_review=double_review))
            ids.append(item_id)
        db.commit()
    return ids


def supported_labels(entry):
    from app.services.v3.contracts import AdjudicationRequest, ClaimLabel

    def request(client_key: str, verdict: str = "SUPPORTED", ehmf: str | None = None):
        labels = tuple(ClaimLabel(claim_id=claim.claim_id, verdict=verdict, ehmf_type=ehmf)
                       for claim in sorted(entry.claims, key=lambda claim: claim.claim_id))
        return AdjudicationRequest(client_key=client_key, claim_labels=labels,
                                   abstention_label="correct" if entry.decision == "abstain" else None)

    return request
