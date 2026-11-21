"""Phase 3: a Cloud SQL connection is bounded when it is made and kept alive on its socket (spec 7.19, 4.12).

K2  a new Cloud SQL connection is bounded by app.core.db (CONNECT_TIMEOUT_S), as the attempt horizon assumes: the
    connector bounds none of it.
L3  each new connection's socket gets TCP keepalive, so a read whose peer is gone ends within DEAD_PEER_BOUND_S; a
    server that never replies is not bounded, and the records say so, with the 840 s dead-peer horizon and the
    runbook's replace-the-instance step.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import inspect
import logging
import math
from pathlib import Path
import socket
import struct
import sys
import threading
import time
from types import SimpleNamespace

from google.cloud.sql.connector import IPTypes
import pg8000
import pg8000.dbapi
import pg8000.exceptions
import pg8000.legacy
import pytest
from sqlalchemy import create_engine
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import URL
from sqlalchemy.pool import QueuePool

from app.core import db as db_module
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import (
    CONNECT_MAX_PENDING,
    CONNECT_TIMEOUT_S,
    ConnectTimeout,
    bounded_connect,
    cloud_sql_creator,
    enable_tcp_keepalive,
    keepalive_options,
)
from app.core.structured_logging import FIELDS
from app.services import ledger


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
PACKAGE = get_config_package(Settings())


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


# =============================================================================================================== K2


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


# =============================================================================================================== L3


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
