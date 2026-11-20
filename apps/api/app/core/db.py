import atexit
from collections.abc import Callable, Generator
import logging
import socket
import threading
import time
from typing import Any

from google.cloud.sql.connector import Connector, IPTypes
import pg8000.dbapi
from sqlalchemy import create_engine, event, exc as sa_exc
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.structured_logging import FIELDS


class Base(DeclarativeBase):
    pass


LOGGER = logging.getLogger("qcai.db")

# Replace a pooled connection after 30 minutes, before Cloud SQL or the network drops it while idle
# (Google's recommended setting for Cloud SQL). The pre-ping below handles one that dies sooner.
POOL_RECYCLE_SECONDS = 1800

# The longest a new Cloud SQL connection may take: the connector's Admin API refresh, the TCP connect and TLS
# handshake to the instance, and the PostgreSQL startup. The connector bounds none of these. Connector.connect waits
# for its coroutine with no timeout, and the coroutine opens the socket and does the TLS handshake with none. Its own
# `timeout` reaches only pg8000, which ignores it for a socket it is given. So cloud_sql_creator enforces the bound
# (bounded_connect); ledger.attempt_horizon_s counts it.
CONNECT_TIMEOUT_S = 30
# How many connects may run at once: the pool's 20 connections and 10 overflow. A connect that outlives its bound
# keeps its thread until the connector returns, so a stalled instance cannot add threads without limit.
CONNECT_MAX_PENDING = 30

# A reply on a connection that is already open. The connector opens its socket with no timeout and no keepalive, and
# pg8000 keeps a socket it is given as it is, so a read whose peer is gone (a failover, a silent network partition, a
# frozen host) would wait for the life of the process. cloud_sql_creator turns TCP keepalive on for each new
# connection's socket (enable_tcp_keepalive): after KEEPALIVE_IDLE_S without traffic the kernel probes the peer every
# KEEPALIVE_INTERVAL_S and drops the connection after KEEPALIVE_PROBES unanswered probes, so such a read ends within
# DEAD_PEER_BOUND_S of the connection's last traffic. On Linux, TCP_USER_TIMEOUT ends a connection whose sent data
# stays unacknowledged for as long. Neither ends a wait on a server whose TCP stack still answers but which never
# replies: nothing in the code does, so that wait lasts until the server replies or the process exits
# (ledger.dead_peer_horizon_s; infra/cloudrun/deployment.md, Phase 3).
KEEPALIVE_IDLE_S = 30
KEEPALIVE_INTERVAL_S = 10
KEEPALIVE_PROBES = 3
DEAD_PEER_BOUND_S = KEEPALIVE_IDLE_S + KEEPALIVE_INTERVAL_S * KEEPALIVE_PROBES


class ConnectTimeout(pg8000.dbapi.OperationalError):
    """A new database connection did not complete within its bound.

    It is a pg8000 OperationalError, so SQLAlchemy raises it as sqlalchemy.exc.OperationalError, as it does for a
    refused connection, and start-up retries it."""


def bounded_connect(
    connect: Callable[[], Any],
    *,
    timeout_s: float,
    slots: threading.BoundedSemaphore,
    close: Callable[[Any], None] = lambda connection: connection.close(),
) -> Any:
    """Return connect()'s connection, or raise ConnectTimeout once timeout_s has passed.

    connect() runs on a daemon thread, so a process can still exit while one is stalled. A connection that arrives
    after the caller has given up is closed and never reaches the pool. `slots` caps the connects still running;
    waiting for a free slot counts toward timeout_s. An error that connect() raises within the bound is raised
    unchanged."""
    started = time.monotonic()
    if not slots.acquire(timeout=timeout_s):
        _log_connect_timeout(timeout_s, slot_free=False)
        raise ConnectTimeout(f"no database connect slot came free within {timeout_s} s")
    lock = threading.Lock()
    done = threading.Event()
    outcome: dict[str, Any] = {}

    def run() -> None:
        late = None
        try:
            connection = connect()
        except BaseException as exc:  # noqa: BLE001 - handed to the caller, which raises it
            with lock:
                outcome["error"] = exc
        else:
            with lock:
                if outcome.get("abandoned"):
                    late = connection
                else:
                    outcome["connection"] = connection
        finally:
            slots.release()
            done.set()
        if late is not None:
            try:
                close(late)
            except Exception:  # noqa: BLE001 - the late connection is discarded either way
                pass

    threading.Thread(target=run, name="db-connect", daemon=True).start()
    done.wait(max(0.0, timeout_s - (time.monotonic() - started)))
    with lock:
        if "connection" in outcome:
            return outcome["connection"]
        error = outcome.get("error")
        if error is None:
            outcome["abandoned"] = True
    if error is not None:
        raise error
    _log_connect_timeout(timeout_s, slot_free=True)
    raise ConnectTimeout(f"a new database connection took longer than {timeout_s} s")


def _log_connect_timeout(timeout_s: float, *, slot_free: bool) -> None:
    LOGGER.warning(
        "A new database connection exceeded its bound",
        extra={FIELDS: {"event": "db.connect.timeout", "timeout_s": timeout_s, "slot_free": slot_free}},
    )


def keepalive_options() -> list[tuple[str, int, int, int]]:
    """(name, level, option, value) of each keepalive option this platform has, SO_KEEPALIVE first."""
    options = [("SO_KEEPALIVE", socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    for name, value in (
        ("TCP_KEEPIDLE", KEEPALIVE_IDLE_S),
        ("TCP_KEEPINTVL", KEEPALIVE_INTERVAL_S),
        ("TCP_KEEPCNT", KEEPALIVE_PROBES),
        ("TCP_USER_TIMEOUT", DEAD_PEER_BOUND_S * 1000),  # milliseconds; Linux only
    ):
        option = getattr(socket, name, None)
        if option is not None:
            options.append((name, socket.IPPROTO_TCP, option, value))
    return options


def enable_tcp_keepalive(connection: Any) -> tuple[str, ...]:
    """Turn TCP keepalive on for a pg8000 connection's socket and return the options set.

    pg8000 keeps the socket it was given (the connector's TLS socket) as Connection._usock. A connection whose socket
    cannot be reached, or an option the kernel refuses, is logged (db.connect.keepalive_unset) and the connection is
    kept: it works as it did before, without that bound."""
    sock = getattr(connection, "_usock", None)
    if not isinstance(sock, socket.socket):
        _log_keepalive_unset("SO_KEEPALIVE", "no_socket")
        return ()
    applied: list[str] = []
    for name, level, option, value in keepalive_options():
        try:
            sock.setsockopt(level, option, value)
        except OSError as exc:
            _log_keepalive_unset(name, type(exc).__name__)
            continue
        applied.append(name)
    return tuple(applied)


def _log_keepalive_unset(option: str, error: str) -> None:
    LOGGER.warning(
        "A database connection's socket keepalive could not be set",
        extra={FIELDS: {"event": "db.connect.keepalive_unset", "option": option, "error": error}},
    )


def cloud_sql_creator(
    connector: Connector,
    connection_name: str,
    *,
    user: str,
    password: str,
    db: str,
    ip_type: IPTypes,
    timeout_s: float = CONNECT_TIMEOUT_S,
    max_pending: int = CONNECT_MAX_PENDING,
) -> Callable[[], Any]:
    """The engine's creator for Cloud SQL: one pg8000 connection through the connector, bounded by timeout_s, with TCP
    keepalive on its socket (enable_tcp_keepalive)."""
    slots = threading.BoundedSemaphore(max_pending)

    def connect() -> Any:
        connection = connector.connect(connection_name, "pg8000", user=user, password=password, db=db, ip_type=ip_type)
        enable_tcp_keepalive(connection)
        return connection

    def creator() -> Any:
        return bounded_connect(connect, timeout_s=timeout_s, slots=slots)

    return creator


def treat_dead_sockets_as_disconnects(engine: Engine) -> None:
    """Let the pool pre-ping recover from a connection whose socket has died.

    SQLAlchemy's pre-ping reconnects only when the driver reports a DBAPI disconnect error. After an idle
    period pg8000 reports a dead TLS socket to Cloud SQL as a raw OSError (BrokenPipeError), which the pool
    re-raises, so each stale connection failed one request before it was discarded: 6 API 5xx on
    2026-11-18 at 05:06-05:10Z (Release R1.3). A ping that fails at the socket now counts as a disconnect,
    so the pool invalidates its older connections and the request gets a fresh one.
    """
    ping: Callable[[object], bool] = engine.dialect.do_ping

    def do_ping(dbapi_connection) -> bool:
        try:
            return ping(dbapi_connection)
        except OSError as exc:
            # Countable in the logs, so a recovery is not mistaken for a server error (the pool still logs its
            # own ERROR while closing the dead connection).
            LOGGER.warning(
                "Pool pre-ping found a dead database socket; reconnecting",
                extra={FIELDS: {"event": "db.pool.dead_socket", "error": type(exc).__name__}},
            )
            return False

    engine.dialect.do_ping = do_ping  # type: ignore[method-assign]


# PEP 249 classes by SQLSTATE class, as psycopg (the CI driver) raises them. pg8000 (the production driver) raises
# IntegrityError only for 23505 and ProgrammingError for every other server error, so code that catches
# IntegrityError, DataError or OperationalError behaved differently in production than in CI (DI-46).
_SQLSTATE_CLASSES: dict[str, type[sa_exc.DBAPIError]] = {
    "22": sa_exc.DataError,
    "23": sa_exc.IntegrityError,
    "08": sa_exc.OperationalError,
    "40": sa_exc.OperationalError,
    "53": sa_exc.OperationalError,
    "54": sa_exc.OperationalError,
    "55": sa_exc.OperationalError,
    "57": sa_exc.OperationalError,
    "58": sa_exc.OperationalError,
}


def pg8000_sqlstate(error: BaseException | None) -> str | None:
    arguments = getattr(error, "args", ())
    if arguments and isinstance(arguments[0], dict):
        code = arguments[0].get("C")
        return code if isinstance(code, str) else None
    return None


@event.listens_for(Engine, "handle_error", retval=True)
def classify_pg8000_errors(context):
    """Raise a pg8000 server error as the PEP 249 class its SQLSTATE names (psycopg's mapping), on every engine.

    Only pg8000's catch-all classes are re-classified, and the driver error stays the wrapped .orig, so SQLSTATE
    checks (main._sqlstate) and disconnect handling are unchanged."""
    if context.dialect is None or context.dialect.driver != "pg8000" or context.is_disconnect:
        return None
    original = context.original_exception
    wrapped = context.sqlalchemy_exception
    target = _SQLSTATE_CLASSES.get((pg8000_sqlstate(original) or "")[:2])
    if target is None or wrapped is None or isinstance(wrapped, target):
        return None
    if not isinstance(wrapped, (sa_exc.ProgrammingError, sa_exc.InternalError, sa_exc.DatabaseError)):
        return None
    replacement = target(context.statement, context.parameters, original, connection_invalidated=wrapped.connection_invalidated)
    return replacement


settings = get_settings()
engine_kwargs: dict[str, object] = {}
cloud_sql_connector: Connector | None = None
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in settings.database_url or settings.database_url.rstrip("/") == "sqlite:":
        engine_kwargs["poolclass"] = StaticPool
elif settings.database_url.startswith(("postgresql", "postgres")):
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = POOL_RECYCLE_SECONDS

if settings.cloud_sql_connection_name and settings.database_url.startswith(("postgresql", "postgres")):
    parsed_url = make_url(settings.database_url)
    database_name = parsed_url.database
    database_user = parsed_url.username
    if not database_name or not database_user:
        raise ValueError("DATABASE_URL must include a database name and username when CLOUD_SQL_CONNECTION_NAME is set.")

    cloud_sql_connector = Connector(refresh_strategy="lazy")
    # Close the connector's HTTP session at exit; otherwise every run of a short job (the retention job)
    # ends with "Unclosed client session" errors in its log.
    atexit.register(cloud_sql_connector.close)
    cloud_sql_ip_type = IPTypes.PRIVATE if settings.cloud_sql_ip_type.upper() == "PRIVATE" else IPTypes.PUBLIC
    get_cloud_sql_connection = cloud_sql_creator(
        cloud_sql_connector,
        settings.cloud_sql_connection_name,
        user=database_user,
        password=parsed_url.password or "",
        db=database_name,
        ip_type=cloud_sql_ip_type,
    )
    engine = create_engine(URL.create("postgresql+pg8000"), creator=get_cloud_sql_connection, **engine_kwargs)
else:
    engine = create_engine(settings.database_url, **engine_kwargs)

if settings.database_url.startswith(("postgresql", "postgres")):
    treat_dead_sockets_as_disconnects(engine)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
