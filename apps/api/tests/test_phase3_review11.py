"""Phase 3, eleventh review round (2026-11-20; Phase 3 spec 18.4, review history, round 11). Each test fails if its
defect comes back.

L1  spec 4.12 lists an append attempt's statements in the code's order: the PostgreSQL SET LOCALs first, then the
    response_id read they bound.
L2  spec section 7 names every production file the phase changes, and states the database, start-up and
    requirements changes (classify_pg8000_errors, the bounded Cloud SQL creator, keepalive, the pydantic floor and
    import refusal) with the code's values; 18.1 lists them as production-image changes.
L3  a reply on an open Cloud SQL connection: each new connection's socket gets TCP keepalive, so a read whose peer is
    gone ends within DEAD_PEER_BOUND_S; a server that never replies is not bounded, and the records say so, with the
    840 s dead-peer horizon and the runbook's replace-the-instance step.
L4  spec 13.2 describes the retry test test_response_ledger.py holds (an IntegrityError at commit), not a faked
    stale head.
L5  the ADR-005 revision withdraws the overlap ClaimGate and keeps fail-closed abstention; it no longer says the
    decision stands as first written.
L6  spec 5.1 names every owner decision package v2 adds (D-19, D-12, PLAN-3.3, PLAN-12.8), and its listing names
    every tutor_pipeline block.
L7  F-2's stand-in audit exists: package v2 pins the legacy path's ids and containment rule hash (tutor_pipeline.legacy,
    compared with the code and on /ready), ledger_provenance compares every record with the pins, and the worker and
    the script run it (--check-provenance). The evidence package's own 00_meta/check_records.py checks its records.
L8  spec 4.3, 4.5, 4.10 and 13.1 item 3 say what the code does: a bundle the license gate empties abstains at
    retrieval and `top` is the first kept result; the budget is checked between render attempts, never after a
    passing or the last one; the ClaimPlan and threshold mutations are test_j2_*'s.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import json
import logging
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from google.cloud.sql.connector import IPTypes
import pg8000.dbapi
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.core.db import Base, cloud_sql_creator, enable_tcp_keepalive, keepalive_options
from app.core.schema_upgrades import run_schema_upgrades
from app.core.structured_logging import FIELDS
from app.main import app
from app.services import claim_gate, ledger
from app.services.contained_answers import EXTRACTIVE_MODE
from app.services.ledger import (
    LegacyDelivery,
    append_ledger_entry,
    build_legacy_entry,
    ledger_provenance,
    record_legacy_delivery,
    verify_response_ledger,
)
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import ENTRY_SCHEMAS, LedgerEntry, PresentationPlan
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline, render_checked
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.retrieve import build_request, retrieve
from tutor_fakes import make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
AUTHORITATIVE_SPEC = SPEC.split("## 18. Implementation record", 1)[0]
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
ADR_005 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
V1_RAW = json.loads((API_ROOT / "app" / "config_package" / "v1.json").read_text(encoding="utf-8"))
V2_RAW = json.loads((API_ROOT / "app" / "config_package" / "v2.json").read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


@pytest.fixture
def isolated(fresh_database_url):
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _pipeline_run(pipeline: TwoPassPipeline, query: str, *, record: bool = False):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=record)


# ============================================================================================================ L1


# Each append statement: the phrase spec 4.12 names it by, and the code that issues it in append_ledger_entry.
APPEND_STATEMENTS = (
    ("SET LOCAL lock_timeout", 'text(f"SET LOCAL lock_timeout'),
    ("If a row with `response_id` exists", "ResponseLedgerRecord.response_id == entry.response_id"),
    ("insert(ResponseLedgerHead)", "module.insert(ResponseLedgerHead)"),
    ("FOR UPDATE", ".with_for_update()"),
    ("`INSERT` the record", "insert(ResponseLedgerRecord)"),
    ("UPDATE response_ledger_head", "update(ResponseLedgerHead)"),
)


def _append_steps() -> list[tuple[int, str]]:
    block = _section("**Append** (at most", "\n\nOn success")
    return [(int(number), text) for number, text in re.findall(r"^(\d)\. (.+)$", block, flags=re.MULTILINE)]


def test_l1_spec_4_12_lists_the_append_statements_in_the_code_s_order():
    source = inspect.getsource(ledger.append_ledger_entry)
    in_code_order = sorted(APPEND_STATEMENTS, key=lambda statement: source.index(statement[1]))
    # The SET LOCALs come first in the code: every later statement of the attempt, the response_id read included,
    # is bounded by the budget left (the ATTEMPT_STATEMENTS count starts after them).
    assert in_code_order[0][0] == "SET LOCAL lock_timeout" and in_code_order[1][0].startswith("If a row with")
    steps = _append_steps()
    assert [number for number, _ in steps] == list(range(1, 8))
    for (number, text), (phrase, _) in zip(steps, in_code_order):
        assert phrase in text, (number, phrase)
    read_step = next(number for number, text in steps if "If a row with `response_id` exists" in text)
    assert f"re-read as in step {read_step})" in steps[-1][1]
    comment = (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8").split("ATTEMPT_STATEMENTS = ", 1)[0].rsplit("\n\n", 1)[1]
    assert "after its PostgreSQL SET LOCALs" in comment and "the response_id read" in comment


# ============================================================================================================ L2


# The production files under apps/api this phase changes or adds (beside docs, infra and CI, which sections 14 and 15
# cover). Spec section 7 must name each one.
PRODUCTION_FILES = (
    "alembic/env.py", "alembic/versions/20261119_phase2_corpus_spans.py", "alembic/versions/20261119_phase3_response_ledger.py",
    "app/api/routes/assistant.py", "app/api/routes/ledger.py",
    "app/api/routes/qa.py", "app/api/routes/spans.py", "app/api/routes/tutor.py", "app/config_package/v2.json",
    "app/config_package/v2.json.sha256", "app/core/authorization.py", "app/core/config.py", "app/core/config_package.py",
    "app/core/corpus_governance.py", "app/core/db.py", "app/core/schema_upgrades.py", "app/db_models.py", "app/main.py", "app/schemas.py",
    "app/services/claim_gate.py", "app/services/contained_answers.py", "app/services/evidence_panel.py", "app/services/ledger.py",
    "app/services/qa_engine.py", "app/services/retention.py", "app/services/retrieval_engine.py", "app/services/teaching_assistant.py",
    "app/services/turn_idempotency.py", "app/services/tutor_followups.py", "app/services/tutor_orchestrator.py",
    "app/workers/response_ledger.py", "requirements.txt",
)


def _section_7() -> str:
    return _section("## 7. File-by-file changes", "## 8. Database")


def _names(section: str, relative: str) -> bool:
    base = relative.rsplit("/", 1)[-1]
    return relative in section or f"`{base}`" in section or f"/{base}`" in section


def test_l2_spec_section_7_names_every_production_file_the_phase_changes():
    section = _section_7()
    for relative in PRODUCTION_FILES:
        assert (API_ROOT / relative).exists(), relative
        assert _names(section, relative), relative
    # The tutor_pipeline package is listed module by module.
    for path in (API_ROOT / "app" / "services" / "tutor_pipeline").glob("*.py"):
        assert f"`{path.name}`" in section, path.name


def test_l2_section_7_states_the_database_start_up_and_requirements_changes_with_the_code_s_values():
    db_entry = _section("### 7.19 MOD `app/core/db.py`", "### 7.20")
    assert "**`classify_pg8000_errors`**" in db_entry and "handle_error" in db_entry and "every `Engine`" in db_entry
    by_class: dict[str, list[str]] = {}
    for prefix, cls in db_module._SQLSTATE_CLASSES.items():
        by_class.setdefault(cls.__name__, []).append(prefix)
    listed = db_entry.split("(`_SQLSTATE_CLASSES`: ", 1)[1].split(")", 1)[0]
    for name, prefixes in by_class.items():
        part = next(piece for piece in listed.split(";") if f"`{name}`" in piece)
        assert sorted(re.findall(r"\b\d\d\b", part)) == sorted(prefixes), name
    assert f"`CONNECT_TIMEOUT_S` ({db_module.CONNECT_TIMEOUT_S} s" in db_entry
    assert f"`CONNECT_MAX_PENDING` ({db_module.CONNECT_MAX_PENDING}:" in db_entry and "`db.connect.timeout`" in db_entry
    for name in ("KEEPALIVE_IDLE_S", "KEEPALIVE_INTERVAL_S"):
        assert f"`{name}`, {getattr(db_module, name)} s" in db_entry, name
    assert f"`KEEPALIVE_PROBES`, {db_module.KEEPALIVE_PROBES}" in db_entry
    assert f"`DEAD_PEER_BOUND_S`, {db_module.DEAD_PEER_BOUND_S} s" in db_entry and "`db.connect.keepalive_unset`" in db_entry
    schemas_entry = _section("### 7.20 MOD `app/schemas.py`", "### 7.21")
    schemas_source = (API_ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    assert "class _ExcludeIfProbe(BaseModel):" in schemas_source and "**`_ExcludeIfProbe`**" in schemas_entry
    message = re.search(r'"(pydantic >= [0-9.]+ is required)', schemas_source).group(1)
    assert message in schemas_entry and "does not start" in schemas_entry
    floor = next(line for line in (API_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if re.match(r"pydantic[<>=]", line))
    assert f"`{floor}`" in _section("### 7.21 MOD `apps/api/requirements.txt`", "### 7.22")
    # 18.1 lists them beside the other production departures.
    production = next(line for line in _section("### 18.1 Departures", "### 18.2").splitlines() if "Production-image changes" in line)
    for needed in ("classify_pg8000_errors", "cloud_sql_creator", "enable_tcp_keepalive", f"`{floor}`", "7.19-7.21"):
        assert needed in production, needed


# ============================================================================================================ L3


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        block = connection.recv(size - len(data))
        if not block:
            raise ConnectionError("closed")
        data += block
    return data


class _SilentPostgres:
    """A peer that completes the PostgreSQL startup (AuthenticationOk, ReadyForQuery), then reads whatever it is sent
    and never replies: a server whose TCP stack answers while the database does not."""

    def __init__(self) -> None:
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.accepted: list[socket.socket] = []
        self.received = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        connection, _ = self.listener.accept()
        self.accepted.append(connection)
        length = struct.unpack("!i", _recv_exact(connection, 4))[0]
        _recv_exact(connection, length - 4)
        connection.sendall(b"R" + struct.pack("!ii", 8, 0) + b"Z" + struct.pack("!i", 5) + b"I")
        try:
            while connection.recv(4096):
                self.received.set()
        except OSError:
            pass

    def close(self) -> None:
        for connection in self.accepted:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.listener.close()


class _SocketConnector:
    """A Cloud SQL connector that returns a real pg8000 connection over a plain socket to `server`."""

    def __init__(self, server: _SilentPostgres) -> None:
        self.server = server

    def connect(self, connection_name, driver, **kwargs):
        sock = socket.create_connection(self.server.listener.getsockname())  # no timeout, no keepalive: as the connector
        return pg8000.dbapi.connect(kwargs["user"], database=kwargs["db"], password=kwargs["password"], sock=sock, ssl_context=False)


def test_l3_each_cloud_sql_connection_gets_tcp_keepalive_on_its_pg8000_socket():
    server = _SilentPostgres()
    try:
        creator = cloud_sql_creator(_SocketConnector(server), "project:region:instance", user="app", password="pw", db="qcai",
                                    ip_type=IPTypes.PRIVATE, timeout_s=10)
        connection = creator()
        sock = connection._usock  # pg8000 keeps the socket it was given here
        assert isinstance(sock, socket.socket) and sock.gettimeout() is None
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        options = keepalive_options()
        names = {name for name, *_ in options}
        assert {"SO_KEEPALIVE", "TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"} <= names
        if sys.platform.startswith("linux"):
            assert "TCP_USER_TIMEOUT" in names
        for name, level, option, value in options[1:]:
            assert sock.getsockopt(level, option) == value, name
        assert db_module.DEAD_PEER_BOUND_S == db_module.KEEPALIVE_IDLE_S + db_module.KEEPALIVE_INTERVAL_S * db_module.KEEPALIVE_PROBES == 60
        # The documented limit: a peer whose TCP stack answers but which never replies is not ended by keepalive.
        outcome: dict = {}

        def query() -> None:
            try:
                connection.cursor().execute("SELECT 1")
            except Exception as exc:  # noqa: BLE001 - recorded for the assertion
                outcome["error"] = exc

        worker = threading.Thread(target=query, daemon=True)
        worker.start()
        assert server.received.wait(5)
        worker.join(1.0)
        assert worker.is_alive(), "the read on a silent but live peer is still waiting"
        server.close()  # only the peer ending the connection ends it
        worker.join(10)
        assert not worker.is_alive() and isinstance(outcome.get("error"), (pg8000.dbapi.InterfaceError, OSError))
    finally:
        server.close()


class _RefusingSocket(socket.socket):
    def setsockopt(self, level, option, value, *rest):  # noqa: D401 - a socket whose kernel refuses one option
        if option == getattr(socket, "TCP_KEEPIDLE", -1):
            raise OSError("option refused (test)")
        return super().setsockopt(level, option, value, *rest)


def test_l3_a_refused_keepalive_option_is_logged_and_the_connection_is_kept(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.db")
    with _RefusingSocket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        applied = enable_tcp_keepalive(SimpleNamespace(_usock=sock))
        assert "SO_KEEPALIVE" in applied and "TCP_KEEPIDLE" not in applied and "TCP_KEEPCNT" in applied
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
    events = [getattr(record, FIELDS, {}) for record in caplog.records if getattr(record, FIELDS, {}).get("event") == "db.connect.keepalive_unset"]
    assert events == [{"event": "db.connect.keepalive_unset", "option": "TCP_KEEPIDLE", "error": "OSError"}]
    caplog.clear()

    class _NoSocketConnector:
        def connect(self, connection_name, driver, **kwargs):
            return SimpleNamespace(closed=False)

    made = cloud_sql_creator(_NoSocketConnector(), "p:r:i", user="app", password="pw", db="qcai", ip_type=IPTypes.PRIVATE, timeout_s=5)()
    assert made.closed is False  # kept, without the bound
    events = [getattr(record, FIELDS, {}) for record in caplog.records if getattr(record, FIELDS, {}).get("event") == "db.connect.keepalive_unset"]
    assert events == [{"event": "db.connect.keepalive_unset", "option": "SO_KEEPALIVE", "error": "no_socket"}]


def test_l3_the_records_state_the_unbounded_wait_and_the_dead_peer_horizon():
    params = ledger.ledger_params(PACKAGE)
    budget = params.ledger_append_budget_ms
    assert ledger.attempt_horizon_s(params, budget) == 360
    rounds = -(-params.ledger_append_max_in_flight // params.ledger_append_workers)
    per_append = (ledger.POOL_CHECKOUT_TIMEOUT_S + db_module.CONNECT_TIMEOUT_S + (ledger.ATTEMPT_STATEMENTS + 1) * budget / 1000
                  + ledger.DEAD_PEER_READS * db_module.DEAD_PEER_BOUND_S)
    assert ledger.dead_peer_horizon_s(params, budget) == 60 * -(-(rounds * per_append + ledger.HORIZON_MARGIN_S) // 60) == 840
    assert ledger.DEAD_PEER_BOUND_S is db_module.DEAD_PEER_BOUND_S
    horizon_doc = inspect.getdoc(ledger.attempt_horizon_s)
    texts = {"attempt_horizon_s": horizon_doc, "spec 4.12": _section("### 4.12 Ledger", "### 4.13"), "runbook": RUNBOOK,
             "observability": OBSERVABILITY, "db.py": (API_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")}
    for name, text in texts.items():
        text = " ".join(text.replace("#", " ").split())  # comments and wrapped lines read as prose
        assert "kernel's TCP timeouts" not in text, name
        assert "keepalive" in text and "never replies" in text, name
    for name in ("spec 4.12", "runbook", "observability"):
        assert "840 s" in texts[name], name
    assert "Replace the instance" in RUNBOOK and "new revision" in RUNBOOK
    assert "dead_peer_horizon_s" in horizon_doc and "process exits" in horizon_doc


# ============================================================================================================ L4


def test_l4_spec_13_2_describes_the_retry_test_test_response_ledger_holds():
    row = next(line for line in _section("### 13.2 NEW unit test files", "### 13.3").splitlines() if line.startswith("| `test_response_ledger.py` |"))
    assert "stale head (monkeypatched" not in row and "monkeypatched stale head" not in SPEC
    assert "`IntegrityError` at commit retried onto the head" in row and "`OperationalError` raised at once, never retried" in row
    source = (API_ROOT / "tests" / "test_response_ledger.py").read_text(encoding="utf-8")
    test = source.split("def test_an_integrity_error_retries_onto_the_head_and_other_errors_fail_at_once", 1)[1].split("\ndef ", 1)[0]
    assert "_Flaky(factory, 1, IntegrityError(" in test and "OperationalError(" in test and "attempts == 1" in test
    assert "chain_head" not in test and "monkeypatch" not in test  # the head is never faked


# ============================================================================================================ L5


def test_l5_the_adr_005_revision_withdraws_the_overlap_gate_and_keeps_fail_closed_abstention():
    decision = ADR_005.split("## Decision", 1)[1].split("## Consequences", 1)[0]
    assert "overlap" in decision  # the original decision is the overlap gate
    revision = ADR_005.split("## Revision 2026-11-19", 1)[1]
    opening = next(line for line in revision.splitlines() if line.startswith("The "))
    assert "stands as first written" not in revision
    assert "overlap `ClaimGate` of the decision above is withdrawn" in opening and "fail-closed rule stands" in opening
    assert "**The overlap `ClaimGate` is removed**" in revision
    assert not hasattr(claim_gate, "ClaimGate") and not hasattr(claim_gate, "evidence_digest")


# ============================================================================================================ L6


def test_l6_spec_5_1_names_the_owner_decisions_v2_keeps_and_adds_and_lists_every_tutor_pipeline_block():
    section = _section("### 5.1 File", "### 5.2")
    bullet = next(line for line in section.splitlines() if "`owner_decisions` keeps" in line)
    kept = re.findall(r"`([A-Z][A-Z0-9.-]+)`", bullet.split("`owner_decisions` keeps", 1)[1].split("unchanged", 1)[0])
    added = re.findall(r"`([A-Z][A-Z0-9.-]+)`", bullet.split(" adds ", 1)[1])
    assert set(kept) == set(V1_RAW["owner_decisions"])
    assert set(added) == set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"]) == {"D-19", "D-12", "PLAN-3.3", "PLAN-12.8"}
    assert all(V2_RAW["owner_decisions"][name] == V1_RAW["owner_decisions"][name] for name in kept)
    listing = section.split("```json", 1)[1].split("```", 1)[0]
    owner = listing.split('"owner_decisions": {', 1)[1]
    assert set(re.findall(r'"([A-Z][A-Z0-9.-]+)": ', owner)) == set(V2_RAW["owner_decisions"])
    tutor = listing.split('"tutor_pipeline": {', 1)[1].split('\n},', 1)[0]
    for key in V2_RAW["tutor_pipeline"]:
        assert f'"{key}":' in tutor, key
    legacy = tutor.split('"legacy": {', 1)[1].split("}", 1)[0]
    assert set(re.findall(r'"([a-z_]+)":', legacy)) == set(V2_RAW["tutor_pipeline"]["legacy"])


# ============================================================================================================ L7


def test_l7_package_v2_pins_the_legacy_path_and_package_check_compares_it():
    assert (PARAMS.legacy_pipeline_version, PARAMS.legacy_generator_id, PARAMS.legacy_generator_model_id, PARAMS.legacy_containment_rule_hash) == (
        ledger.LEGACY_PIPELINE_VERSION, ledger.LEGACY_GENERATOR_ID, EXTRACTIVE_MODE, ledger.LEGACY_CONTAINMENT_RULE_HASH)
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == []
    for field, value in (("legacy_pipeline_version", "legacy-contained-v2"), ("legacy_generator_id", "contained-answers-v2"),
                         ("legacy_generator_model_id", "extractive-other"), ("legacy_containment_rule_hash", "e" * 64)):
        changed = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, **{field: value}))
        problems = check_tutor_pipeline_package(changed, structural=False)
        assert any(f"tutor_pipeline.legacy.{field.removeprefix('legacy_')} in the package ({value})" in problem for problem in problems), field
    unknown = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, legacy_pipeline_version="legacy-contained-v2"))
    assert any("not a pipeline the LedgerEntry contract accepts" in problem for problem in check_tutor_pipeline_package(unknown, structural=False))
    # The loader refuses a v2 package without the block, or with a malformed hash.
    for mutate in (lambda p: p["tutor_pipeline"].pop("legacy"), lambda p: p["tutor_pipeline"]["legacy"].update(containment_rule_hash="0" * 63),
                   lambda p: p["tutor_pipeline"]["legacy"].pop("generator_id")):
        payload = copy.deepcopy(V2_RAW)
        mutate(payload)
        with pytest.raises(ConfigPackageError):
            parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    # /ready reports the pins an operator compares records with.
    body = TestClient(app).get("/ready").json()
    assert body["tutor_pipeline"]["legacy"] == {
        "pipeline_version": PARAMS.legacy_pipeline_version, "generator_id": PARAMS.legacy_generator_id,
        "generator_model_id": PARAMS.legacy_generator_model_id, "containment_rule_hash": PARAMS.legacy_containment_rule_hash,
    }


def _legacy(*, claims: tuple = ()) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=f"turn-{uuid4()}", decision="answer" if claims else "abstain", reason="no_approved_span", claims=claims, quoted=(),
        retrieved=None, answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none",
        model=EXTRACTIVE_MODE, corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1",
        floor=6.0, margin=0.0, policy_version="cs595-v1",
    )


CLAIM = (("Routing adds SWAP gates on sparse hardware.", ("span-" + "1" * 64,)),)


def _changed(entry: LedgerEntry, *, entry_provenance: dict | None = None, claim_provenance: dict | None = None,
             resolver_prompt_hash: str | None = None) -> LedgerEntry:
    """A copy of entry under a new response id, with its record's and/or its claims' provenance changed."""
    data = entry.model_dump(mode="json")
    if resolver_prompt_hash is not None:
        data["resolved_question"]["resolver"]["prompt_hash"] = resolver_prompt_hash
    prefix = data["response_id"].split("-", 1)[0]
    data["response_id"] = f"{prefix}-{uuid4()}"
    if data["shadowed_response_id"] is not None:
        data["shadowed_response_id"] = f"turn-{uuid4()}"
    data["provenance"].update(entry_provenance or {})
    for claim in data["claims"]:
        claim["response_id"] = data["response_id"]
        claim["provenance"] = {**data["provenance"], **(claim_provenance or {})} if claim_provenance else dict(data["provenance"])
    # Each record validates as its own entry schema (a two-pass record is ledger-entry-v2 since Phase 4).
    return ENTRY_SCHEMAS[data["entry_schema"]].model_validate(data)


def test_l7_the_provenance_audit_passes_on_the_records_the_code_writes_and_names_each_record_that_differs(isolated):
    _, factory = isolated
    settings = Settings()
    assert record_legacy_delivery(_legacy(claims=CLAIM), settings=settings, session_factory=factory).seq == 1
    assert record_legacy_delivery(_legacy(), settings=settings, session_factory=factory).seq == 2
    pipeline = TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings, session_factory=factory)
    answered = _pipeline_run(pipeline, MULTI_CLAIM, record=True)
    abstained = _pipeline_run(pipeline, "the of and", record=True)
    assert answered.decision == "answer" and answered.entry.claims and abstained.decision == "abstain" and not abstained.entry.claims
    with factory() as db:
        audit = ledger_provenance(db, PACKAGE)
    assert audit == {"package_version": PACKAGE.package_version, "package_sha256": PACKAGE.sha256, "records": 4, "checked": 4, "other_package": 0,
                     "problem_count": 0, "problems": []}
    legacy_entry = build_legacy_entry(_legacy(claims=CLAIM), settings=settings, package=PACKAGE, manifest_sha256=None)
    budget = 5000
    append_ledger_entry(_changed(legacy_entry, entry_provenance={"evidential_prompt_hash": "d" * 64}), session_factory=factory, budget_ms=budget)
    generator = legacy_entry.model_dump(mode="json")
    generator["response_id"] = f"turn-{uuid4()}"
    generator["versions"]["generator_id"] = "contained-answers-v9"
    for claim in generator["claims"]:
        claim["response_id"] = generator["response_id"]
    append_ledger_entry(ENTRY_SCHEMAS[generator["entry_schema"]].model_validate(generator), session_factory=factory, budget_ms=budget)
    append_ledger_entry(_changed(abstained.entry, entry_provenance={"pedagogical_prompt_hash": "e" * 64}), session_factory=factory, budget_ms=budget)
    append_ledger_entry(_changed(answered.entry, resolver_prompt_hash="f" * 64), session_factory=factory, budget_ms=budget)
    append_ledger_entry(make_entry(), session_factory=factory, budget_ms=budget)  # stamped with another package (b * 64)
    with factory() as db:
        audit = ledger_provenance(db, PACKAGE)
        chain = verify_response_ledger(db)
    assert chain.ok and chain.count == 9  # every record is a sound link: the audit checks what the chain check cannot
    assert (audit["records"], audit["checked"], audit["other_package"]) == (9, 8, 1)
    assert audit["problems"] == [
        "seq 5 provenance.evidential_prompt_hash is not the package pin",
        "seq 6 versions.generator_id is not the package pin",
        "seq 7 provenance.pedagogical_prompt_hash is not the package pin",
        "seq 8 resolved_question.resolver.prompt_hash is not the package pin",
    ] and audit["problem_count"] == 4
    # A record naming a pipeline the package does not pin, and one whose generator it does not allow.
    two_pass = json.loads(json.dumps(answered.entry.model_dump(mode="json")))
    assert ledger._provenance_problems(10, {**two_pass, "pipeline": "two-pass-v9"}, PARAMS, PACKAGE.v1) == ["seq 10 names a pipeline the package does not pin"]
    two_pass["versions"]["generator_id"] = "gateway-v1"
    assert ledger._provenance_problems(11, two_pass, PARAMS, PACKAGE.v1) == ["seq 11 versions.generator_id is not a generator the package allows"]
    # A claim whose provenance differs from its record's: the LedgerEntry contract refuses one, so the audit's check is a
    # second line, shown here on a raw entry.
    legacy = legacy_entry.model_dump(mode="json")
    legacy["claims"][0]["provenance"] = {**legacy["provenance"], "threshold_set_version": "other"}
    assert ledger._provenance_problems(12, legacy, PARAMS, PACKAGE.v1) == ["seq 12 has a claim whose provenance differs from its record's"]


def _run_worker(database_url: str, *args: str) -> tuple[int, dict]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    report = next(line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line)
    return completed.returncode, json.loads(report[report.index("{"):])


def _load_verify_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase3_verify_ledger_l7", REPO_ROOT / "scripts" / "verify_ledger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l7_the_worker_and_the_script_check_provenance(fresh_database_url, isolated, capsys):
    _, factory = isolated
    settings = Settings()
    record_legacy_delivery(_legacy(claims=CLAIM), settings=settings, session_factory=factory)
    returncode, report = _run_worker(fresh_database_url, "--check-provenance")
    assert returncode == 0 and report["status"] == "ok" and report["provenance"]["checked"] == 1 and report["provenance"]["problems"] == []
    returncode, report = _run_worker(fresh_database_url)
    assert returncode == 0 and "provenance" not in report  # only when asked
    script = _load_verify_script()
    assert script.main(["--database-url", fresh_database_url, "--check-provenance"]) == 0
    assert json.loads(capsys.readouterr().out)["provenance"]["problem_count"] == 0
    entry = build_legacy_entry(_legacy(claims=CLAIM), settings=settings, package=PACKAGE, manifest_sha256=None)
    append_ledger_entry(_changed(entry, entry_provenance={"evidential_prompt_hash": "d" * 64}, claim_provenance={"evidential_prompt_hash": "d" * 64}),
                        session_factory=factory, budget_ms=5000)
    returncode, report = _run_worker(fresh_database_url, "--check-provenance")
    assert returncode == 1 and (report["status"], report["severity"]) == ("provenance_mismatch", "ERROR")
    assert report["problems"] == [] and report["provenance"]["problems"] == ["seq 2 provenance.evidential_prompt_hash is not the package pin"]
    assert script.main(["--database-url", fresh_database_url, "--check-provenance"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "provenance_mismatch"
    assert script.main(["--database-url", fresh_database_url]) == 0  # the chain itself is sound
    capsys.readouterr()


def test_l7_the_records_say_the_audit_exists_and_what_package_v2_pins():
    di_49 = next(line for line in SPEC.splitlines() if line.startswith("| DI-49 |"))
    assert "--check-provenance" in di_49 and "`test_l7_*`" in di_49 and "not yet run in production" in di_49
    assert "--check-provenance" in RUNBOOK and "provenance_mismatch" in RUNBOOK and "provenance_mismatch" in OBSERVABILITY
    assert "**`ledger_provenance(db, package)`**" in _section("### 4.12 Ledger", "### 4.13")
    assert "| legacy |" in _section("### 5.2 Loader", "### 5.3") and "`legacy.containment_rule_hash` against" in _section("### 5.4", "### 5.5")
    # The register's DI-49 row and the closure notes are checked by the evidence package's 00_meta/check_records.py
    # (check_l7_*).


# ============================================================================================================ L8


def test_l8_a_bundle_the_license_gate_empties_abstains_at_retrieval_and_top_is_the_first_kept_result(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    pipeline = TwoPassPipeline(engine, settings)
    registry = pipeline.registry
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", MULTI_CLAIM), package=PACKAGE)
    request = build_request(resolved, lesson_slug=None, corpus_version=engine.store.corpus_version)
    baseline = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert baseline.sufficiency.decision != "abstain" and len(baseline.spans) >= 2
    original = registry.license_class
    calls: list[int] = []

    def drop_the_first(**kwargs):
        calls.append(1)
        return None if len(calls) == 1 else original(**kwargs)

    monkeypatch.setattr(registry, "license_class", drop_the_first)
    kept = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert [span.span_id for span in kept.spans] == [span.span_id for span in baseline.spans[1:]]
    assert kept.sufficiency.score == baseline.spans[1].score != baseline.sufficiency.score  # the first kept result, not the top-ranked one
    monkeypatch.setattr(registry, "license_class", lambda **kwargs: None)
    emptied = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert emptied.spans == () and (emptied.sufficiency.decision, emptied.sufficiency.reason) == ("abstain", "no_quotable_evidence")

    def no_envelope_step(*args, **kwargs):
        raise AssertionError("the envelope step runs only for a bundle that did not abstain")

    monkeypatch.setattr(pipeline_module, "build_envelope", no_envelope_step)
    result = _pipeline_run(pipeline, MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.envelope) == ("abstain", "no_quotable_evidence", None)
    section_4_3 = _section("### 4.3 Retrieve", "### 4.4")
    assert "the license gate dropped every one: `abstain`, reason `no_quotable_evidence`, at this retrieval step" in section_4_3
    assert "`top` = the first result the license gate kept" in section_4_3 and "the top-ranked result unless" in section_4_3
    assert "A bundle the license gate emptied never reaches this step" in _section("### 4.5 Evidential pass", "### 4.6")
    assert "`no_quotable_evidence` when the license gate dropped every result (4.3)" in _section("### 4.10 Pipeline", "### 4.11")


class _Raising:
    renderer_id = "template-renderer-v1"

    def render(self, locked, presentation, *, attempt):
        raise RuntimeError("render fault (test)")


def test_l8_the_budget_is_checked_between_render_attempts_never_after_a_passing_or_the_last_one():
    settings = Settings()
    result = _pipeline_run(TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings), MULTI_CLAIM)
    assert result.decision == "answer"
    presentation = PresentationPlan(plan_id="concise", source="request")
    checks: list[int] = []

    def over() -> bool:
        checks.append(1)
        return True

    rendered, attempts, reason = render_checked(TemplateRenderer(PACKAGE), result.locked, presentation, max_regenerations=2, over=over)
    assert rendered is not None and (attempts, reason, checks) == (1, None, [])  # a passing attempt is never checked
    rendered, attempts, reason = render_checked(_Raising(), result.locked, presentation, max_regenerations=2, over=over)
    assert (rendered, attempts, reason, len(checks)) == (None, 1, "budget_exceeded", 1)  # checked after a failed attempt
    checks.clear()
    rendered, attempts, reason = render_checked(_Raising(), result.locked, presentation, max_regenerations=0, over=over)
    assert (rendered, attempts, reason, checks) == (None, 1, "render_failed", [])  # the last attempt is never checked
    section = _section("### 4.10 Pipeline", "### 4.11")
    assert "after each of steps 2, 4, 5 and each render attempt" not in section
    assert "between render attempts (step 7): never after a passing attempt or the last one" in section


def test_l8_spec_13_1_attributes_each_learner_dependent_mutation_to_its_test():
    item = next(line for line in _section("### 13.1 NEW", "### 13.2").splitlines() if line.startswith("3. `test_ac_3_1_what_the_evidential_pass"))
    j2 = item.split("`test_j2_*` makes ", 1)[1].split(", and `test_k1_*`", 1)[0]
    k1 = item.split(", and `test_k1_*` ", 1)[1].split(", each in turn", 1)[0]
    assert j2 == "the ClaimPlan and the threshold version learner-dependent"
    source = (API_ROOT / "tests" / "test_phase3_review10.py").read_text(encoding="utf-8")
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LEARNER_DEPENDENT")
    fields = {key.value for key in node.value.keys}
    assert fields == {"abstention_reason", "counts", "floor", "margin", "sufficiency_score", "top_k"}
    named = {"abstention_reason": "the abstention reason", "counts": "the counts", "floor": "the floor", "margin": "the margin",
             "sufficiency_score": "the sufficiency score", "top_k": "`top_k`"}
    assert all(named[field] in k1 for field in fields) and "ClaimPlan" not in k1 and "threshold" not in k1
    review9 = (API_ROOT / "tests" / "test_phase3_review9.py").read_text(encoding="utf-8")
    assert re.search(r"^def test_j2_a_learner_dependent_claim_plan_\w+\(", review9, flags=re.MULTILINE)
    assert re.search(r"^def test_j2_a_learner_dependent_threshold_\w+\(", review9, flags=re.MULTILINE)
