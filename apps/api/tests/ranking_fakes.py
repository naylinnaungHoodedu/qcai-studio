"""Fakes for the Phase 9 ranking tests (Phase 9 spec 13.1). Not a test module: settings with the ranking in shadow, a
two-family development registry with fake generate members, synthetic event logs (numbers and ids only, never text),
a pure fold of a log, a commissioning input, and development shadow records appended to a fresh in-memory database. No
learner data and no network call; nothing is written into the checkout.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, load_config_package

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = load_config_package(DEFAULT_PACKAGE_PATH, governed=False)
BLOCK = json.loads(json.dumps(PACKAGE.ranking.block))
STATIC = "extractive-d19-v1"
CLONE = "fake-delta-v1"
FIXED_NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"


def ranking_settings(**overrides) -> Settings:
    options = dict(environment="development", ranking="shadow", v3_queue="shadow", model_gateway="shadow", ehmf="shadow")
    options.update(overrides)
    return Settings(**options)


def block_with(edit) -> dict:
    block = copy.deepcopy(BLOCK)
    edit(block)
    return block


def at(seconds: int) -> str:
    return (FIXED_NOW + timedelta(seconds=int(seconds))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def model(adapter_id: str, family: str, *, version: str = "2026-11-21", cost: int = 0) -> dict:
    return {"adapter_id": adapter_id, "family": family, "provider": "fake", "model_id": f"{adapter_id}-model", "model_version": version,
            "cost_units_per_call": cost}


class Log:
    """An input-event log built by hand: config, models (commissioned by default), outcomes, ticks and operator inputs."""

    def __init__(self, block: dict | None = None) -> None:
        self.block = block or BLOCK
        self.events: list[dict] = []
        self.ledger = 0
        self.add("config", {"package_version": "test", "package_sha256": "0" * 64,
                            "parameters_sha256": canonical_sha256(self.block), "parameters": self.block})

    def add(self, kind: str, payload: dict) -> "Log":
        self.events.append({"seq": len(self.events) + 1, "kind": kind, "payload": copy.deepcopy(payload)})
        return self

    def models(self, *refs: dict, clean: int = 40, failed: int = 0, commission: bool = True, mean_q: str = "0.9") -> "Log":
        for ref in refs:
            self.add("model_seen", {"model": ref})
        self.add("availability", {"models": {ref["adapter_id"]: None for ref in refs}})
        if commission:
            for ref in refs:
                self.commission(ref, clean=clean, failed=failed, mean_q=mean_q)
        return self

    def commission(self, ref: dict, *, clean: int = 40, failed: int = 0, mean_q: str = "0.9") -> "Log":
        return self.add("commission", {"adapter_id": ref["adapter_id"], "version": ref["model_version"], "clean": clean, "failed": failed,
                                       "generated": clean + failed, "mean_q": mean_q, "run_sha256": "0" * 64})

    def outcome(self, adapter_id: str, y: int = 1, *, cluster: str = "unscoped", tier: int = 2, t: int | None = None, v: str = "1",
                k: str | None = "1", h: str | None = "0", f: str | None = None, ledger_seq: int | None = None) -> "Log":
        self.ledger += 1
        seq = self.ledger if ledger_seq is None else ledger_seq
        return self.add("outcome", {"ledger_seq": seq, "created_at": at(30 * seq if t is None else t), "model": adapter_id,
                                    "context": {"cluster": cluster, "task_type": "quiz_item" if tier == 1 else "explanation", "tier": tier},
                                    "y": int(y), "signals": {"V": v, "S": None, "K": k, "H": h, "F": f}, "cost_units": 0,
                                    "latency_ms": None, "tier_source": "v2"})

    def batch(self, adapter_id: str, n: int = 25, *, y: int = 1, **kwargs) -> "Log":
        for _ in range(n):
            self.outcome(adapter_id, y, **kwargs)
        return self

    def tick(self, seconds: int) -> "Log":
        return self.add("tick", {"at": at(seconds)})


def apply_all(events: list[dict]) -> tuple[dict, list[tuple[str, dict]]]:
    """The pure fold of an input log: (final state, [(kind, payload)] of every derived event)."""
    from app.services.ranking.replay import replay

    replayed = replay(events)
    return replayed.state, [(kind, json.loads(payload)) for _seq, kind, payload in replayed.derived]


def derived_of(events: list[dict], kind: str) -> list[dict]:
    return [payload for derived_kind, payload in apply_all(events)[1] if derived_kind == kind]


def two_family_registry():
    """A development registry: three verifier fakes and two fake generate members of two more families (the clone rule)."""
    from app.gateway.registry import AdapterRegistry
    from v2_fakes import fake_spec

    members = [fake_spec(family) for family in ("fake-alpha", "fake-beta", "fake-gamma")]
    for family in ("fake-delta", "fake-epsilon"):
        spec = fake_spec(family, capabilities=("generate", "verify"))
        members.append(clone_member(spec))
    return AdapterRegistry(name="development", members=tuple(members))


def clone_member(spec, *, version: str | None = None):
    from dataclasses import replace

    return replace(spec, fake_generate_rule="extractive-clone-v1", **({"model_version": version} if version else {}))


def package_copy(tmp_path: Path, edit) -> Path:
    """A copy of the shipped package directory with `edit` applied to the shipped package file (and its sidecar rewritten)."""
    import shutil

    target = tmp_path / "config_package"
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent, target)
    path = target / DEFAULT_PACKAGE_PATH.name
    payload = json.loads(path.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    path.with_name(path.name + ".sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8", newline="\n")
    return path


def shadow_record(factory, query: str = TIER2, *, settings: Settings | None = None, generator=None, adapters=None, now=None, checker=None):
    """A development shadow run through the V2 pipeline, appended to the ledger of `factory`. A checker (v1_fakes'
    AlwaysContradictedChecker) gives a record whose first pass failed (y = 0)."""
    from v1_fakes import run
    from v2_fakes import fresh_gateway, v2_pipeline

    kwargs = {"generator": generator} if generator is not None else {}
    if checker is not None:
        kwargs["checker"] = checker
    pipeline = v2_pipeline(settings or Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking="off"),
                           gateway=fresh_gateway(adapters=adapters), session_factory=factory, v3_stop=lambda: False, **kwargs)
    return run(pipeline, query, legacy_decision="answer", record=True)


def commission_static(factory, *, settings: Settings | None = None, package=PACKAGE, clean: int = 40, failed: int = 0, gateway=None):
    """Append the static generator's commission input (as the worker's commission command records it)."""
    from app.services.ranking.models import candidates
    from app.services.ranking.scan import append_inputs
    from v2_fakes import fresh_gateway

    settings = settings or ranking_settings()
    ref = next(item for item in candidates(package, settings) if item.adapter_id == STATIC)
    with factory() as db:
        append_inputs(db, [("commission", {"adapter_id": STATIC, "version": ref.model_version, "clean": clean, "failed": failed,
                                           "generated": clean + failed, "mean_q": "0.9", "run_sha256": "0" * 64})],
                      settings=settings, package=package, now=FIXED_NOW, gateway=gateway or fresh_gateway())
        db.commit()


def scan(factory, *, settings: Settings | None = None, package=PACKAGE, gateway=None, now=FIXED_NOW, limit: int = 500, store=None):
    from app.services.ranking.scan import run_scan
    from v2_fakes import fresh_gateway

    return run_scan(settings=settings or ranking_settings(), package=package, session_factory=factory, now=now, limit=limit,
                    gateway=gateway or fresh_gateway(), store=store)


def events_of(factory, kind: str | None = None) -> list[dict]:
    from sqlalchemy import select

    from app.db_models import RankingEvent

    with factory() as db:
        query = select(RankingEvent).order_by(RankingEvent.seq)
        if kind is not None:
            query = query.where(RankingEvent.kind == kind)
        return [{"seq": row.seq, "kind": row.kind, "payload": json.loads(row.payload), "v3_event_seq": row.v3_event_seq, "note": row.note,
                 "ledger_seq": row.ledger_seq, "context_key": row.context_key} for row in db.execute(query).scalars()]


def small_window_package(tmp_path: Path, deliveries: int = 4):
    """A package copy whose X5 window is `deliveries` learner deliveries (v3.triggers.x5.window_deliveries), so a test
    can close a window; the ranking block is unchanged."""
    return load_config_package(package_copy(tmp_path, lambda payload: payload["v3"]["triggers"]["x5"].update(window_deliveries=int(deliveries))),
                               governed=False)


def session_factory_for(database_url: str):
    """(session_factory, engine) over a database of the session's dialect (conftest's fresh_database_url), with every table
    and trigger; the caller disposes of the engine."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine


def stored_state(factory) -> dict:
    from app.db_models import RankingState
    from app.services.ranking.vocabulary import STATE_KEY

    with factory() as db:
        return json.loads(db.get(RankingState, STATE_KEY).payload)
