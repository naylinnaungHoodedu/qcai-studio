from collections.abc import Generator

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


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

if settings.cloud_sql_connection_name and settings.database_url.startswith(("postgresql", "postgres")):
    parsed_url = make_url(settings.database_url)
    database_name = parsed_url.database
    database_user = parsed_url.username
    if not database_name or not database_user:
        raise ValueError("DATABASE_URL must include a database name and username when CLOUD_SQL_CONNECTION_NAME is set.")

    cloud_sql_connector = Connector(refresh_strategy="lazy")
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
