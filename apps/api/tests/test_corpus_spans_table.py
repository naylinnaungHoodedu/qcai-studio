"""The append-only, text-free corpus_spans table (plan Phase 2 task 2.2; spec 2.2, 4.6). Runs on SQLite here and
on PostgreSQL 16 in the api-postgres CI job."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import SessionLocal, engine
from app.db_models import CorpusSpan
from app.services.span_store import persist_spans
from app.services.spans import SpanRecord, content_hash, legacy_excerpt_keys, span_id_for


def _record(marker: str) -> SpanRecord:
    body = f"Span text {marker}"
    digest = content_hash(body)
    return SpanRecord(span_id_for(f"item-{marker}", 0, len(body), digest), "span-v2", f"item-{marker}", "sha256:" + "0" * 16,
                      "document", "public", 0, "Section", "Source", "doc.docx", 0, len(body), digest, body, legacy_excerpt_keys(body))


def test_spans_are_inserted_if_missing_and_hold_no_text():
    record = _record(uuid4().hex)
    with SessionLocal() as db:
        assert persist_spans(db, [record], corpus_version="corpus-a", registered_by="register-job") == 1
        assert persist_spans(db, [record, record], corpus_version="corpus-b", registered_by="write-through") == 0
        db.commit()
        rows = db.scalars(select(CorpusSpan).where(CorpusSpan.span_id == record.span_id)).all()
    assert len(rows) == 1 and rows[0].corpus_version_first_seen == "corpus-a"
    columns = {column["name"] for column in inspect(engine).get_columns("corpus_spans")}
    assert not {"text", "excerpt", "body"} & columns
    assert not [name for name in columns if name.endswith("_id") and name.split("_")[0] in {"user", "guest", "learner", "author", "account"}]


def test_a_new_item_version_of_the_same_span_is_a_new_row():
    record = _record(uuid4().hex)
    with SessionLocal() as db:
        persist_spans(db, [record, replace(record, item_version="sha256:" + "1" * 16)], corpus_version="corpus-a", registered_by="register-job")
        db.commit()
        assert len(db.scalars(select(CorpusSpan).where(CorpusSpan.span_id == record.span_id)).all()) == 2


@pytest.mark.parametrize("statement", ["UPDATE corpus_spans SET registered_by = 'x' WHERE span_id = :s", "DELETE FROM corpus_spans WHERE span_id = :s"])
def test_update_and_delete_are_refused(statement):
    record = _record(uuid4().hex)
    with SessionLocal() as db:
        persist_spans(db, [record], corpus_version="corpus-a", registered_by="register-job")
        db.commit()
        with pytest.raises(DBAPIError):
            db.execute(text(statement), {"s": record.span_id})
        db.rollback()
        assert db.scalar(select(CorpusSpan.registered_by).where(CorpusSpan.span_id == record.span_id)) == "register-job"


def test_every_way_to_remove_rows_is_guarded_on_this_dialect():
    with SessionLocal() as db:
        if engine.dialect.name == "postgresql":
            with pytest.raises(DBAPIError):
                db.execute(text("TRUNCATE corpus_spans"))
            db.rollback()
        else:
            # SQLite has no TRUNCATE; its DELETE (and so its truncate optimisation) is refused by the trigger.
            names = set(db.scalars(text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'corpus_spans'")).all())
            assert names == {"corpus_spans_no_update", "corpus_spans_no_delete"}


def test_the_check_constraint_refuses_a_private_plane_row():
    record = _record(uuid4().hex)
    with SessionLocal() as db:
        db.add(CorpusSpan(span_id=record.span_id, scheme="span-v2", item_id="private-item", item_version="v", item_kind="document",
                          plane="private", section_ordinal=0, char_start=0, char_end=1, content_hash="0" * 64,
                          source_title_hash="0" * 64, section_title_hash="0" * 64, legacy_key_lexical="0" * 64,
                          legacy_key_semantic="0" * 64, corpus_version_first_seen="c", registered_by="register-job"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    with SessionLocal() as db:
        assert persist_spans(db, [replace(record, plane="private")], corpus_version="c", registered_by="register-job") == 0
