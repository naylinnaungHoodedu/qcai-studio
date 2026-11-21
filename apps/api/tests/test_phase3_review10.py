"""Phase 3, tenth review round (2026-11-20; Phase 3 spec 18.4, review history, round 10). Each test fails if its
defect comes back.

K1  the invariant 1 fixture tells learners apart by every field it is meant to compare: a learner-dependent
    abstention reason, floor, margin, sufficiency score, counts or top_k each fails it, and the record it compares
    keeps every field of the shadow record but its ids.
K2  a new Cloud SQL connection is bounded by app.core.db (CONNECT_TIMEOUT_S), as the attempt horizon assumes: the
    connector bounds none of it.
K3  the Phase 3 records state the current code only (P2-12-D-03): no narrative markers in the authoritative text, one
    review-history row per round in the spec, a test-strategy map of every test_phase3_*.py file and spec section 3
    listed from the code. The evidence package's current-state sections and register rows are checked by its own
    00_meta/check_records.py (check_k3_*): no repository test reads outside the repository.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import logging
import math
from pathlib import Path
import re
import threading
import time

from google.cloud.sql.connector import IPTypes
import pg8000.dbapi
import pytest
from sqlalchemy import create_engine, exc as sa_exc
from sqlalchemy.engine import URL
from sqlalchemy.pool import QueuePool

from app.core import db as db_module
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import CONNECT_MAX_PENDING, CONNECT_TIMEOUT_S, ConnectTimeout, bounded_connect, cloud_sql_creator
from app.core.structured_logging import FIELDS
from app.services import ledger
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.pipeline import TwoPassPipeline

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


# ============================================================================================================ K1


def _old_projection(item: dict) -> dict:
    """The five fields the invariant 1 test compared before the ninth round."""
    record = item["record"]
    return {"request": item["retrieve"]["request"], "envelopes": item["envelopes"],
            "bundle": [(span["span_id"], span["score"]) for span in record["retrieval"]["evidence"]],
            "claim_set_hash": record["claim_set_hash"], "decision": record["decision"]}


_LEARNER = {"mastery": None}


def _for_one_learner(mutate):
    """mutate(value) for the 0.9 learner only; the others see the value unchanged."""
    return lambda value: mutate(value) if _LEARNER["mastery"] == 0.9 else value


def _patch_entry(monkeypatch, mutate) -> None:
    # Both record builders: _entry (ledger-entry-v1) and, with V1 running in the shadow (Phase 4), _entry_v2.
    mutate_one = _for_one_learner(mutate)
    for name in ("_entry", "_entry_v2"):
        real = getattr(TwoPassPipeline, name)
        monkeypatch.setattr(TwoPassPipeline, name, lambda self, *args, _real=real, **kwargs: mutate_one(_real(self, *args, **kwargs)))


def _patch_bundle(monkeypatch, mutate) -> None:
    real = pipeline_module.retrieve
    mutate_one = _for_one_learner(mutate)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kwargs: mutate_one(real(engine, request, **kwargs)))


def _sufficiency(**changes):
    def mutate(bundle):
        sufficiency = bundle.sufficiency
        update = {key: change(getattr(sufficiency, key)) for key, change in changes.items()}
        return bundle.model_copy(update={"sufficiency": sufficiency.model_copy(update=update)})
    return mutate


def _other_reason(entry):
    if entry.decision != "abstain":
        return entry
    other = next(reason for reason in contracts.GATE_ABSTENTION_REASONS if reason != entry.abstention_reason)
    assert other in contracts.ABSTENTION_REASONS
    return entry.model_copy(update={"abstention_reason": other})


def _more_render_attempts(entry):
    return entry.model_copy(update={"counts": entry.counts.model_copy(update={"render_attempts": entry.counts.render_attempts + 1})})


def _learner_dependent_top_k(monkeypatch) -> None:
    """The pipeline asks for one more span for the 0.9 learner, and the retrieval itself still uses the packaged
    top_k: the bundle, the record and the old five fields stay equal, and only the retrieval call differs."""
    real_retrieve = pipeline_module.retrieve
    real_run = TwoPassPipeline.run

    def run(self, item, **kwargs):
        if _LEARNER["mastery"] != 0.9:
            return real_run(self, item, **kwargs)
        params = self.params
        self.params = dataclasses.replace(params, top_k=params.top_k + 1)
        try:
            return real_run(self, item, **kwargs)
        finally:
            self.params = params

    monkeypatch.setattr(TwoPassPipeline, "run", run)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, *, top_k, registry: real_retrieve(
        engine, request, top_k=packaged_top_k(), registry=registry))


def packaged_top_k() -> int:
    return get_config_package(Settings()).tutor_pipeline.top_k


LEARNER_DEPENDENT = {
    # A learner-dependent abstention reason: the decision, spans and hash stay equal (finding K1 named it).
    "abstention_reason": lambda monkeypatch: _patch_entry(monkeypatch, _other_reason),
    "counts": lambda monkeypatch: _patch_entry(monkeypatch, _more_render_attempts),
    # A learner-dependent floor, margin or sufficiency score that leaves the same results above it.
    "floor": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(floor=lambda value: value + 0.001)),
    "margin": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(margin=lambda value: value + 0.001)),
    "sufficiency_score": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(score=lambda value: (value or 0.0) + 0.001)),
    # Plan 12.4(c) and CT-04: an identical top-k.
    "top_k": _learner_dependent_top_k,
}


@pytest.mark.parametrize("field", sorted(LEARNER_DEPENDENT))
def test_k1_each_learner_dependent_value_fails_the_invariant_1_fixture(monkeypatch, field):
    from test_phase3_acceptance import observe_three_learners

    monkeypatch.setitem(_LEARNER, "mastery", None)
    LEARNER_DEPENDENT[field](monkeypatch)
    observed, captured, _ = observe_three_learners(monkeypatch, prefix=f"k1-{field.replace('_', '-')}",
                                                   on_learner=lambda mastery: _LEARNER.__setitem__("mastery", mastery))
    # The comparison before the ninth round could not see it: its five fields are equal for all three learners.
    assert all([_old_projection(item) for item in learner] == [_old_projection(item) for item in observed[0]] for learner in observed)
    # The fixture does: the 0.1 and 0.5 learners agree and the 0.9 learner differs.
    assert observed[1] == observed[0] and observed[2] != observed[0]
    differing = [index for index, (item, other) in enumerate(zip(observed[2], observed[0])) if item != other]
    assert differing
    if field == "top_k":
        top_ks = {call["top_k"] for call in captured["requests"]}
        assert len(top_ks) == 2 and all(observed[2][index]["retrieve"] != observed[0][index]["retrieve"] for index in differing)
        assert all(observed[2][index]["record"] == observed[0][index]["record"] for index in range(len(observed[0])))
    else:
        assert all(observed[2][index]["record"] != observed[0][index]["record"] for index in differing)
    if field == "abstention_reason":
        assert any(item["record"]["decision"] == "abstain" for item in observed[2])


def _perturbed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "-other"
    if value is None:
        return "other"
    if isinstance(value, list):
        return [*value, {"other": 1}]
    if isinstance(value, dict):
        return {**value, "other": 1}
    raise AssertionError(type(value))


def _leaves(value, path=()):
    """Every leaf of a JSON value (an empty list or object counts as one), with its path."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _leaves(item, (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path, value


def _set(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


IDS = {("response_id",), ("shadowed_response_id",)}


def _is_id(path) -> bool:
    """The fields that name the response, the turn it shadows and the learner's own turns: learner_independent leaves
    out exactly these."""
    return (path in IDS or path[:2] == ("resolved_question", "source_turn_ids")
            or (len(path) == 3 and path[0] == "claims" and path[2] == "response_id"))


def test_k1_the_compared_record_keeps_every_field_of_the_shadow_record_but_its_ids(monkeypatch):
    from test_phase3_acceptance import entry_of, learner_independent, observe_three_learners, records

    observed, _, _ = observe_three_learners(monkeypatch, prefix="k1-leaves")
    entries = [entry_of(row) for row in records(delivery="shadow")[-len(observed[0]) * 3:]]
    answered = next(entry for entry in entries if entry["decision"] == "answer" and entry["claims"])
    abstained = next(entry for entry in entries if entry["decision"] == "abstain")
    checked = 0
    for entry in (answered, abstained):
        reference = learner_independent(entry)
        for path, value in _leaves(entry):
            changed = copy.deepcopy(entry)
            _set(changed, path, _perturbed(value))
            if _is_id(path):
                assert learner_independent(changed) == reference, path
            else:
                assert learner_independent(changed) != reference, path
                checked += 1
    # The fields plan 7.8 invariant 1, 12.4(c) and CT-04 name are among those compared.
    named = {("abstention_reason",), ("retrieval", "floor"), ("retrieval", "margin"), ("retrieval", "threshold_version"),
             ("retrieval", "sufficiency", "decision"), ("retrieval", "sufficiency", "floor"), ("counts", "render_attempts")}
    assert named <= {path for path, _ in _leaves(abstained)} | {path for path, _ in _leaves(answered)}
    assert checked > 60


def test_k1_the_retrieval_call_the_fixture_records_holds_the_top_k_the_pipeline_passed(monkeypatch):
    from test_phase3_acceptance import observe_three_learners

    observed, captured, _ = observe_three_learners(monkeypatch, prefix="k1-topk")
    assert {call["top_k"] for call in captured["requests"]} == {packaged_top_k()}
    assert all(item["retrieve"]["top_k"] == packaged_top_k() for learner in observed for item in learner)


# ============================================================================================================ K2


class _Connection:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class _StalledConnector:
    """A Cloud SQL connector whose connect waits until released (an instance that accepts TCP and never answers)."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.release = threading.Event()
        self.calls: list[tuple] = []
        self.made: list[_Connection] = []
        self.error = error

    def connect(self, connection_name, driver, **kwargs):
        self.calls.append((connection_name, driver, kwargs))
        self.release.wait(10)
        if self.error is not None:
            raise self.error
        connection = _Connection()
        self.made.append(connection)
        return connection


def _creator(connector, *, timeout_s=0.3, max_pending=CONNECT_MAX_PENDING):
    return cloud_sql_creator(connector, "project:region:instance", user="app", password="pw", db="qcai", ip_type=IPTypes.PRIVATE,
                             timeout_s=timeout_s, max_pending=max_pending)


def test_k2_a_stalled_cloud_sql_connect_raises_at_its_bound_and_its_late_connection_is_closed(caplog):
    connector = _StalledConnector()
    creator = _creator(connector)
    caplog.set_level(logging.WARNING, logger="qcai.db")
    started = time.monotonic()
    with pytest.raises(ConnectTimeout):
        creator()
    elapsed = time.monotonic() - started
    assert 0.25 <= elapsed < 1.5, elapsed
    events = [getattr(record, FIELDS, {}).get("event") for record in caplog.records]
    assert "db.connect.timeout" in events
    # The connector returns later: that connection never reaches the pool, it is closed.
    connector.release.set()
    deadline = time.monotonic() + 5
    while not connector.made and time.monotonic() < deadline:
        time.sleep(0.01)
    assert connector.made and connector.made[0].closed.wait(5)
    assert issubclass(ConnectTimeout, pg8000.dbapi.OperationalError)


def test_k2_a_connect_within_the_bound_returns_its_connection_and_an_error_is_raised_unchanged():
    connector = _StalledConnector()
    connector.release.set()
    connection = _creator(connector, timeout_s=5)()
    assert connection is connector.made[0] and not connection.closed.is_set()
    assert connector.calls == [("project:region:instance", "pg8000", {"user": "app", "password": "pw", "db": "qcai", "ip_type": IPTypes.PRIVATE})]
    refused = ConnectionRefusedError("refused (test)")
    failing = _StalledConnector(error=refused)
    failing.release.set()
    with pytest.raises(ConnectionRefusedError) as raised:
        _creator(failing, timeout_s=5)()
    assert raised.value is refused


def test_k2_sqlalchemy_raises_a_stalled_connect_as_an_operational_error_within_the_bound():
    connector = _StalledConnector()
    engine = create_engine(URL.create("postgresql+pg8000"), creator=_creator(connector), poolclass=QueuePool)
    try:
        started = time.monotonic()
        with pytest.raises(sa_exc.OperationalError) as raised:
            engine.connect()
        assert time.monotonic() - started < 1.5
        assert isinstance(raised.value.orig, ConnectTimeout)
    finally:
        connector.release.set()
        engine.dispose()


def test_k2_the_connect_slots_cap_the_stalled_connects():
    connector = _StalledConnector()
    creator = _creator(connector, timeout_s=0.2, max_pending=2)
    for _ in range(2):
        with pytest.raises(ConnectTimeout):
            creator()
    started = time.monotonic()
    with pytest.raises(ConnectTimeout, match="slot"):
        creator()  # both slots are held by stalled connects: no third thread, and the wait still ends at the bound
    assert time.monotonic() - started < 1.0 and len(connector.calls) == 2
    connector.release.set()
    deadline = time.monotonic() + 5
    while len(connector.made) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(connection.closed.wait(5) for connection in connector.made)
    fresh = creator()  # the slots came free when the stalled connects returned
    assert fresh is connector.made[-1] and not fresh.closed.is_set()


def test_k2_bounded_connect_releases_its_slot_on_every_outcome():
    slots = threading.BoundedSemaphore(1)
    assert bounded_connect(lambda: "connection", timeout_s=1, slots=slots) == "connection"
    with pytest.raises(KeyError):
        bounded_connect(lambda: {}["missing"], timeout_s=1, slots=slots)
    assert slots.acquire(timeout=1)  # one slot, still free after a success and a failure
    slots.release()


def test_k2_the_production_engine_uses_the_bounded_creator_and_the_horizon_counts_its_bound():
    source = (API_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")
    branch = source.split("if settings.cloud_sql_connection_name and", 1)[1].split("\nelse:", 1)[0]
    assert "get_cloud_sql_connection = cloud_sql_creator(" in branch and "creator=get_cloud_sql_connection" in branch
    assert "cloud_sql_connector.connect(" not in source  # no unbounded connect left
    defaults = inspect.signature(cloud_sql_creator).parameters
    assert defaults["timeout_s"].default == CONNECT_TIMEOUT_S == 30 and defaults["max_pending"].default == CONNECT_MAX_PENDING
    # One slot for each connection the pool can hold, overflow included.
    assert 'engine_kwargs["pool_size"] = 20' in source and 'engine_kwargs["max_overflow"] = 10' in source and 20 + 10 == CONNECT_MAX_PENDING
    # The horizon's connect term is the bound app.core.db enforces, not a library default.
    assert ledger.CONNECT_TIMEOUT_S is db_module.CONNECT_TIMEOUT_S
    ledger_source = (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8")
    assert "from app.core.db import CONNECT_TIMEOUT_S" in ledger_source and "\nCONNECT_TIMEOUT_S =" not in ledger_source
    params = ledger.ledger_params(ledger.get_config_package(Settings()))
    per_append = ledger.POOL_CHECKOUT_TIMEOUT_S + CONNECT_TIMEOUT_S + (ledger.ATTEMPT_STATEMENTS + 1) * params.ledger_append_budget_ms / 1000
    assert ledger.attempt_horizon_s(params, params.ledger_append_budget_ms) == 60 * math.ceil(
        (math.ceil(params.ledger_append_max_in_flight / params.ledger_append_workers) * per_append + ledger.HORIZON_MARGIN_S) / 60) == 360


# ============================================================================================================ K3


SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
# Phrases that narrate what an earlier round's text or code said. P2-12-D-03: the authoritative text states the current
# code only, and each round is one row of the spec's review history (18.4).
NARRATIVE = re.compile(
    r"\b(?:[Cc]orrected|[Ss]uperseded|[Rr]evised|[Rr]enamed|[Rr]eplaced|[Rr]emoved|[Mm]arked|[Aa]dded) in (?:Phase 3 )?(?:spec )?18\.\d"
    r"|\b[Uu]ntil (?:Phase 3 )?(?:spec )?18\.\d|\b[Ss]ince (?:Phase 3 )?(?:spec )?18\.\d|first wording|spec-time|kept as history"
    r"|\bthis (?:said|comment said|docstring said|row said|line said|bullet said|listing said)\b|^\s*History:",
    flags=re.MULTILINE,
)


def _last_round() -> int:
    """The latest review round: round n's tests are in test_phase3_review{n}.py from round 3 on (round 2's in
    test_phase3_hardening.py, round 1's in the acceptance and unit files), and each round is one history row."""
    rounds = [int(match.group(1)) for path in (API_ROOT / "tests").glob("test_phase3_review*.py")
              if (match := re.fullmatch(r"test_phase3_review(\d+)\.py", path.name))]
    assert rounds and min(rounds) == 3 and sorted(rounds) == list(range(3, max(rounds) + 1)), rounds
    return max(rounds)


def _test_functions() -> set[str]:
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^(?:async )?def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return names


def _groups(path: Path) -> set[str]:
    return set(re.findall(r"^def (test_[a-z]\d*)_\w+\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))


def _resolves(text: str, functions: set[str], *, prefix: str | None = None) -> list[str]:
    """Backticked test names, wildcards and suffixes in text that name no test."""
    missing = []
    for match in re.finditer(r"`(test_[a-z0-9_]+)`", text):
        if match.group(1) not in functions:
            missing.append(match.group(1))
    for match in re.finditer(r"`(test_[a-z0-9_]+?)_?\*`", text):
        if not any(name.startswith(match.group(1)) for name in functions):
            missing.append(match.group(0))
    for match in re.finditer(r"`\.\.\.(_[a-z0-9_]+)`", text):
        if not (prefix and prefix + match.group(1) in functions):
            missing.append(match.group(0))
    for match in re.finditer(r"`(test_[a-z0-9_]+\.py)`", text):
        if not (API_ROOT / "tests" / match.group(1)).exists():
            missing.append(match.group(1))
    return missing


def test_k3_the_test_strategy_maps_every_phase3_test_file():
    phase_3 = STRATEGY.split("## Phase 3 acceptance map", 1)[1].split("**Exit gate.**", 1)[0]
    files_table = phase_3.split("### Phase 3 test files", 1)[1]
    rows = {match.group(1): line for line in files_table.splitlines() if (match := re.match(r"\| `(test_phase3_\w+\.py)` \| (.+) \|$", line))}
    files = sorted(path.name for path in (API_ROOT / "tests").glob("test_phase3_*.py"))
    assert files and sorted(rows) == files, (sorted(rows), files)
    for name in files:
        row = rows[name]
        assert len(row) > 120, name  # it says what the file proves, not just its name
        for group in _groups(API_ROOT / "tests" / name):
            if name != "test_phase3_acceptance.py":
                assert f"`{group}_*`" in row, (name, group)
    functions = _test_functions()
    for line in phase_3.splitlines():
        if line.startswith("| AC-3-"):
            prefix = "test_ac_3_" + line[len("| AC-3-")]
            assert _resolves(line, functions, prefix=prefix) == [], line[:60]
        elif line.startswith("| "):
            assert _resolves(line, functions) == [], line[:60]


def test_k3_the_spec_records_each_round_once_in_the_review_history_table():
    record = SPEC.split("## 18. Implementation record", 1)[1]
    headings = re.findall(r"^### (18\.\d+) ", record, flags=re.MULTILINE)
    assert headings == ["18.1", "18.2", "18.3", "18.4"], headings  # no per-round narrative section
    history = record.split("### 18.4 Review history", 1)[1]
    intro = history.split("| Round", 1)[0]
    assert "may describe behaviour that a later round superseded" in intro and "sections 0-17 are authoritative" in intro
    rows = [line for line in history.splitlines() if re.match(r"\| \d+, ", line)]
    assert [int(re.match(r"\| (\d+),", row).group(1)) for row in rows] == list(range(1, _last_round() + 1))
    functions = _test_functions()
    files = {f"test_phase3_review{n}.py": n - 1 for n in range(3, _last_round() + 1)} | {"test_phase3_hardening.py": 1}
    for row in rows:
        commit = row.split(" | ")[1]
        assert re.search(r"`[0-9a-f]{7,40}`", commit), row[:40]
        findings = row.split(" | ", 2)[2].rstrip(" |").split("<br>")
        # Each finding names what fails if its defect comes back: a repository test, a frontend test or, for a finding
        # about the evidence package's own records, a check of the evidence package's 00_meta/check_records.py.
        assert findings and all("`" in finding and ("test_" in finding or ".test.ts" in finding or "check_records.py" in finding)
                                for finding in findings), row[:40]
        assert _resolves(row, functions) == [], (row[:30], _resolves(row, functions))
    for name, index in files.items():
        row = rows[index]
        for group in _groups(API_ROOT / "tests" / name):
            if group != "test_j":
                assert f"`{group}_*`" in row, (name, group)


def _authoritative_texts() -> dict[str, str]:
    texts = {
        "spec 0-17": SPEC.split("## 18. Implementation record", 1)[0],
        "spec 18.1-18.3": SPEC.split("## 18. Implementation record", 1)[1].split("### 18.4 Review history", 1)[0],
        "test strategy": STRATEGY.split("## Phase 3 acceptance map", 1)[1],
        "README": (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8"),
        "env example": (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8"),
        "ci": (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
    }
    for name in ("ADR-001-grounding-separation.md", "ADR-005-abstention-gate.md"):
        texts[name] = (REPO_ROOT / "docs" / "adr" / name).read_text(encoding="utf-8").split("## Revision 2026-11-19", 1)[1]
    for name in ("deployment.md", "observability.md"):
        texts[name] = (REPO_ROOT / "infra" / "cloudrun" / name).read_text(encoding="utf-8").split("## Phase 3", 1)[1]
    for root in ("app", "alembic"):
        for path in (API_ROOT / root).rglob("*.py"):
            texts[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
    for path in (REPO_ROOT / "scripts").glob("*.py"):
        texts[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
    return texts


def test_k3_the_authoritative_text_states_the_current_code_only():
    offending = [(name, match.group(0)) for name, text in _authoritative_texts().items() for match in NARRATIVE.finditer(text)]
    assert offending == []
    # The guard sees each kind of narrative the review rounds left behind.
    for sample in ("(Corrected in 18.10 H1: the rule cut ...)", "since 18.8 F3", "until spec 18.12 J1 it was", "Superseded in 18.5 C3",
                   "the first wording named", "this comment said \"only owners\"", "History: the spec-time block", "(Revised in 18.4"):
        assert NARRATIVE.search(sample), sample
    assert not NARRATIVE.search("the record can then no longer be tied to anyone; 18.4: \"D-19 RECOMMENDATION")


def _code_fields(source: str, name: str) -> list[str]:
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]


def test_k3_spec_section_3_lists_the_code_s_fields():
    section = SPEC.split("## 3. Data shapes", 1)[1].split("## 4. Algorithms", 1)[0]
    contracts = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    schemas = (API_ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    code_classes = {node.name for node in ast.parse(contracts).body if isinstance(node, ast.ClassDef)}
    checked = 0
    for block in re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL):
        for node in ast.parse(block).body:
            if not isinstance(node, ast.ClassDef):
                continue
            source = contracts if node.name in code_classes else schemas
            listed = [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]
            code = _code_fields(source, node.name)
            header = block.splitlines()[node.lineno - 1]
            if "additions only" in header:
                assert listed and set(listed) <= set(code), node.name
            else:
                assert listed == code, node.name
            checked += 1
    assert checked >= 30
    # Every contract the package pins a schema for is listed.
    for name in ("ResolvedQuestion", "RetrievalRequest", "EvidenceBundle", "EvidentialEnvelope", "ClaimPlan", "LockedClaimSet", "PresentationPlan",
                 "LedgerEntry", "BudgetStamp", "PresentationRecord"):
        assert f"class {name}(Contract):" in section, name
