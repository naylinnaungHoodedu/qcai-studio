import atexit
from collections.abc import Callable, Generator
import logging

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine, event
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

    def get_cloud_sql_connection():
        return cloud_sql_connector.connect(
            settings.cloud_sql_connection_name,
            "pg8000",
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
