"""Metadata-driven erasure over every user-keyed table (plan task 1.5, AC-1-2).

Targets come from the ORM metadata, not a hand-kept list: any table with a column named in
USER_KEY_COLUMNS is user-keyed, and rows that reference a deleted row through a foreign key are
deleted with it. A new table is therefore covered as soon as it uses one of these column names.
"""

from collections.abc import Callable

from sqlalchemy import ColumnElement, Table, delete, or_, select
from sqlalchemy.orm import Session

import app.db_models  # noqa: F401  (registers every table on Base.metadata)
from app.core.db import Base

# Column names that hold a learner identity (account, guest, Auth0 subject or Arena player id).
USER_KEY_COLUMNS = ("user_id", "reviewer_user_id", "player_id", "opponent_id", "guest_id")

# Tables deliberately left in place by erasure, with the reason. Keep this short and justified.
ERASURE_EXEMPT_TABLES = {
    "guest_revocations": "Security record: erasing it would re-enable a revoked guest token.",
}

LeafCondition = Callable[[Table], ColumnElement[bool] | None]


def user_keyed_tables() -> list[Table]:
    return [
        table
        for table in Base.metadata.sorted_tables
        if any(name in table.c for name in USER_KEY_COLUMNS)
    ]


def _deletion_conditions(leaf: LeafCondition) -> dict[str, ColumnElement[bool]]:
    """Per table, the rows to delete: rows matching `leaf`, plus rows whose parent row is deleted."""
    conditions: dict[str, ColumnElement[bool]] = {}
    for table in Base.metadata.sorted_tables:  # parents before children
        if table.name in ERASURE_EXEMPT_TABLES:
            continue
        clauses = []
        own = leaf(table)
        if own is not None:
            clauses.append(own)
        for foreign_key in table.foreign_keys:
            parent_condition = conditions.get(foreign_key.column.table.name)
            if parent_condition is not None:
                clauses.append(foreign_key.parent.in_(select(foreign_key.column).where(parent_condition)))
        if clauses:
            conditions[table.name] = or_(*clauses)
    return conditions


def _delete_children_first(db: Session, conditions: dict[str, ColumnElement[bool]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        condition = conditions.get(table.name)
        if condition is None:
            continue
        deleted = db.execute(delete(table).where(condition)).rowcount or 0
        if deleted:
            counts[table.name] = deleted
    return counts


def _rows_of(user_id: str) -> LeafCondition:
    def leaf(table: Table) -> ColumnElement[bool] | None:
        columns = [table.c[name] for name in USER_KEY_COLUMNS if name in table.c]
        return or_(*(column == user_id for column in columns)) if columns else None

    return leaf


def erase_user(db: Session, user_id: str) -> dict[str, int]:
    """Delete every row keyed to `user_id`, whatever the provider. The caller commits."""
    return _delete_children_first(db, _deletion_conditions(_rows_of(user_id)))


def erase_stale_guest_rows(db: Session, cutoff) -> dict[str, int]:
    """Delete guest rows created before `cutoff`, with the rows that depend on them. The caller commits."""

    def leaf(table: Table) -> ColumnElement[bool] | None:
        columns = [table.c[name] for name in USER_KEY_COLUMNS if name in table.c]
        if not columns or "created_at" not in table.c:
            return None
        return or_(*(column.like("guest-%") for column in columns)) & (table.c.created_at < cutoff)

    return _delete_children_first(db, _deletion_conditions(leaf))
