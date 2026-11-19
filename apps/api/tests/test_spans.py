"""Span identity units (plan Phase 2 task 2.2; spec 3.1-3.3, 3.8)."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services import spans
from app.services.content_assembler import MODULE_BLUEPRINTS
from app.services.spans import (
    SpanBuildError,
    build_spans,
    canonical_authored,
    canonical_document,
    check_library_versions,
    content_hash,
    excerpt_key,
    legacy_excerpt_keys,
    make_splitter,
    span_id_for,
)
from app.services.text_utils import truncate_display_excerpt

PACKAGE = get_config_package(Settings())


def test_every_span_is_its_offsets_in_the_canonical_text():
    splitter = make_splitter(PACKAGE)
    items = [canonical_authored(MODULE_BLUEPRINTS, item_version="sha256:" + "0" * 16)]
    document = Settings().source_documents[0]
    items.append(canonical_document(document, item_id="doc", item_version="sha256:" + "1" * 16, source_title="Doc"))
    for item in items:
        records = build_spans(item, splitter)
        assert records
        for record in records:
            assert item.text[record.start : record.end] == record.text
            assert record.content_hash == hashlib.sha256(record.text.encode("utf-8")).hexdigest()
            section = item.sections[record.section_ordinal]
            assert section.body_start <= record.start and record.end <= section.body_start + len(section.body)
        assert len({record.span_id for record in records}) == len(records)
    assert len(build_spans(items[0], splitter)) == 41  # the authored lessons, as Phase 1 split them


def test_the_library_versions_are_read_through_importlib_metadata(monkeypatch):
    check_library_versions(PACKAGE, force=True)  # the pinned versions are installed
    real = spans.importlib.metadata.version
    monkeypatch.setattr(spans.importlib.metadata, "version", lambda name: "0.0.0" if name == "langchain-text-splitters" else real(name))
    with pytest.raises(SpanBuildError, match="langchain-text-splitters 0.0.0 installed"):
        check_library_versions(PACKAGE, force=True)


def test_the_span_id_hashes_exactly_scheme_item_offsets_and_content_hash():
    digest = "a" * 64
    expected = "span-" + hashlib.sha256(
        json.dumps({"scheme": "span-v2", "item_id": "x", "start": 0, "end": 10, "content_hash": digest}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert span_id_for("x", 0, 10, digest) == expected
    # A golden value: changing the scheme's inputs or encoding must be a new scheme version.
    assert span_id_for("authored-curriculum", 0, 5, content_hash("hello")) == (
        "span-" + hashlib.sha256(b'{"content_hash":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824","end":5,'
                                 b'"item_id":"authored-curriculum","scheme":"span-v2","start":0}').hexdigest()
    )
    assert span_id_for("x", 0, 10, digest) != span_id_for("y", 0, 10, digest) != span_id_for("x", 1, 10, digest)


def test_item_version_corpus_version_and_lesson_slugs_do_not_enter_the_id():
    splitter = make_splitter(PACKAGE)
    first = [r.span_id for r in build_spans(canonical_authored(MODULE_BLUEPRINTS, item_version="sha256:" + "0" * 16), splitter)]
    second = [r.span_id for r in build_spans(canonical_authored(MODULE_BLUEPRINTS, item_version="sha256:" + "f" * 16), splitter)]
    assert first == second


def test_legacy_keys_are_the_lexical_and_semantic_display_excerpts():
    text = "The routing overhead grows quickly. " * 30
    lexical, semantic = legacy_excerpt_keys(text)
    once = truncate_display_excerpt(text, 320)
    assert semantic == excerpt_key(once)
    assert lexical == excerpt_key(truncate_display_excerpt(once, 320))
    assert excerpt_key("  a   b \n c ") == excerpt_key("a b c")
