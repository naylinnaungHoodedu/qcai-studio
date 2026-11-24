"""Metadata-driven erasure over every user-keyed table (plan task 1.5, AC-1-2).

Targets come from the ORM metadata, not a hand-kept list: any table with a column named in
USER_KEY_COLUMNS is user-keyed, and rows that reference a deleted row through a foreign key are
deleted with it. A new table is therefore covered as soon as it uses one of these column names.
"""

from collections.abc import Callable

from sqlalchemy import ColumnElement, Table, delete, or_, select, tuple_
from sqlalchemy.orm import Session

import app.db_models  # noqa: F401  (registers every table on Base.metadata)
from app.core.db import Base

# Column names that hold a learner identity (account, guest, Auth0 subject or Arena player id).
USER_KEY_COLUMNS = ("user_id", "reviewer_user_id", "player_id", "opponent_id", "guest_id")

# Tables deliberately left in place by erasure, with the reason. Keep this short and justified.
ERASURE_EXEMPT_TABLES = {
    "guest_revocations": "Security record: erasing it would re-enable a revoked guest token.",
}
RETENTION_EXEMPT_TABLES = {
    "learner_subjects": "The binding must remain stable when guest study rows age out.",
    "user_accounts": "Durable credentials remain until account erasure.",
    "user_sessions": "The session expiry rule takes precedence over study age.",
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


def learner_table_conditions(
    identifiers: tuple[str, ...], *, export: bool = False,
) -> dict[str, ColumnElement[bool]]:
    """Shared scope for erasure verification and export, with export-specific ownership."""
    if not export:
        conditions = _deletion_conditions(lambda table: _keys_in(table, identifiers))
        # Previously revoked raw guest credentials are handled by the privacy service.
        return {**conditions, **{
            table.name: _keys_in(table, identifiers)
            for table in user_keyed_tables() if table.name in ERASURE_EXEMPT_TABLES
        }}
    conditions = {}
    for table in Base.metadata.sorted_tables:
        own = _keys_in(table, identifiers, exclude_opponent=True)
        if own is not None:
            conditions[table.name] = own
            continue
        # A table with independent ownership may not inherit ownership from a parent.
        if any(key in table.c for key in USER_KEY_COLUMNS):
            continue
        links = [
            fk.parent.in_(select(fk.column).where(conditions[fk.column.table.name]))
            for fk in table.foreign_keys if fk.column.table.name in conditions
        ]
        if links:
            conditions[table.name] = or_(*links)
    return conditions


def _keys_in(table: Table, identifiers: tuple[str, ...], *, exclude_opponent: bool = False):
    columns = [table.c[key] for key in USER_KEY_COLUMNS if key in table.c and not (exclude_opponent and key == "opponent_id")]
    return or_(*(column.in_(identifiers) for column in columns)) if columns else None


def erasure_verification_conditions(db: Session, identifiers: tuple[str, ...]) -> dict[str, ColumnElement[bool]]:
    """Capture owned FK-only keys before the parent rows disappear."""
    conditions = learner_table_conditions(identifiers)
    for table in Base.metadata.sorted_tables:
        if table.name not in conditions:
            continue
        own = _keys_in(table, identifiers)
        if not table.foreign_keys:
            continue
        columns = list(table.primary_key.columns)
        keys = db.execute(select(*columns).where(conditions[table.name])).all()
        pk = columns[0] if len(columns) == 1 else tuple_(*columns)
        by_pk = pk.in_([row[0] if len(columns) == 1 else tuple(row) for row in keys])
        conditions[table.name] = or_(own, by_pk) if own is not None else by_pk
    return conditions


def guest_retention_age_columns(privacy_on: bool) -> dict[str, str]:
    if not privacy_on:
        return {table.name: "created_at" for table in user_keyed_tables() if "created_at" in table.c}
    from app.services.retention import retention_classes

    columns = {"guest-created/durable-until-erasure": "created_at", "guest-updated/durable-until-erasure": "updated_at"}
    return {
        name: columns[kind] for name, kind in retention_classes().items()
        if kind in columns and name not in RETENTION_EXEMPT_TABLES
    }


def erase_stale_guest_rows(db: Session, cutoff) -> dict[str, int]:
    """Expire guest study rows using the legacy rule or the enabled Phase 8 classes."""
    from app.core.config import get_settings
    from app.db_models import LearnerSubject

    privacy_on = get_settings().learner_privacy == "on"
    age_columns = guest_retention_age_columns(privacy_on)
    bound_guest_subjects = select(LearnerSubject.user_id).where(LearnerSubject.provider == "guest") if privacy_on else None

    def leaf(table: Table) -> ColumnElement[bool] | None:
        columns = [table.c[name] for name in USER_KEY_COLUMNS if name in table.c]
        time_column = age_columns.get(table.name)
        if not columns or not time_column:
            return None
        predicates = [column.like("guest-%") for column in columns]
        if bound_guest_subjects is not None:
            predicates.extend(column.in_(bound_guest_subjects) for column in columns)
        return or_(*predicates) & (table.c[time_column] < cutoff)

    return _delete_children_first(db, _deletion_conditions(leaf))
