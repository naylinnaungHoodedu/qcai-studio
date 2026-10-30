"""Rate-limit counters in the application database, shared by every API instance (task 1.6, P1-D-06).

A `limits` storage backend, so slowapi uses it through `storage_uri="qcai-database://"`. Each counter is
a row of `rate_limit_counters`, keyed by a keyed digest of the limiter's key, which holds a principal id
or a client address. An increment is one atomic upsert: a counter whose window has ended starts again.
"""

import time

from limits.storage import Storage
from sqlalchemy import case, delete, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.client_identity import keyed_digest

DATABASE_STORAGE_URI = "qcai-database://"


def _engine():
    # Imported here: app.core.db builds the engine from settings, and the limiter is built at import time.
    from app.core.db import engine

    return engine


def _table():
    from app.db_models import RateLimitCounter

    return RateLimitCounter.__table__


class DatabaseStorage(Storage):
    STORAGE_SCHEME = ["qcai-database"]

    def __init__(self, uri: str | None = None, wrap_exceptions: bool = False, **options) -> None:
        super().__init__(uri, wrap_exceptions=wrap_exceptions, **options)

    @property
    def base_exceptions(self) -> type[Exception]:
        return SQLAlchemyError

    @staticmethod
    def _digest(key: str) -> str:
        return keyed_digest(key, "rate-limit")

    def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        now = time.time()
        table = _table()
        engine = _engine()
        insert = postgresql_insert if engine.dialect.name == "postgresql" else sqlite_insert
        expired = table.c.expires_at <= now
        statement = (
            insert(table)
            .values(key=self._digest(key), count=amount, expires_at=now + expiry)
            .on_conflict_do_update(
                index_elements=[table.c.key],
                set_={
                    "count": case((expired, amount), else_=table.c.count + amount),
                    "expires_at": case((expired, now + expiry), else_=table.c.expires_at),
                },
            )
            .returning(table.c.count)
        )
        with engine.begin() as connection:
            return int(connection.execute(statement).scalar_one())

    def _live(self, key: str):
        table = _table()
        with _engine().connect() as connection:
            return connection.execute(
                select(table.c.count, table.c.expires_at).where(
                    table.c.key == self._digest(key), table.c.expires_at > time.time()
                )
            ).first()

    def get(self, key: str) -> int:
        row = self._live(key)
        return int(row.count) if row else 0

    def get_expiry(self, key: str) -> float:
        row = self._live(key)
        return float(row.expires_at) if row else time.time()

    def check(self) -> bool:
        try:
            with _engine().connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def reset(self) -> int | None:
        with _engine().begin() as connection:
            return connection.execute(delete(_table())).rowcount

    def clear(self, key: str) -> None:
        table = _table()
        with _engine().begin() as connection:
            connection.execute(delete(table).where(table.c.key == self._digest(key)))
