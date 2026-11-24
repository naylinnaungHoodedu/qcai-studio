"""Phase 10: evidence pointers through the catalog and the span lookup (spec 3.4, 4.3; PD-62)."""

from __future__ import annotations

import pytest

from evaluation.qcai_eval import synthetic
from evaluation.qcai_eval.canonical import canonical_sha256
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver, content_sha256, resolve_items


def catalog_lines():
    return synthetic.synthetic_catalog(synthetic.synthetic_dataset(synthetic.SMALL))


def test_the_catalog_sha_is_computed_with_the_text_dropped_and_the_text_is_not_kept():
    lines = catalog_lines()
    catalog = EvidenceCatalog.from_lines(lines)
    stripped = sorted(({k: v for k, v in line.items() if k != "text"} for line in lines), key=lambda entry: entry["evidence_id"])
    assert catalog.sha256 == canonical_sha256(stripped)
    assert catalog.sha256 == EvidenceCatalog.from_lines(synthetic.synthetic_catalog(synthetic.synthetic_dataset(synthetic.SMALL), with_text=False)).sha256
    record = catalog.get(lines[0]["evidence_id"])
    assert "text" not in vars(record) and lines[0]["text"] not in repr(record)


@pytest.mark.parametrize(("change", "message"), [
    (lambda line: line.update(text=line["text"] + "!"), "hash_mismatch"),
    (lambda line: line.update(byte_length=line["byte_length"] + 1), "byte_length"),
    (lambda line: line.update(page=0), "page"),
    (lambda line: line.update(char_end=line["char_start"]), "char offsets"),
    (lambda line: line.update(volume="elsewhere"), "volume"),
    (lambda line: line.update(evidence_id="EV-SYN-p1-1"), "evidence_id"),
    (lambda line: line.update(extra=1), "unexpected"),
])
def test_the_catalog_loader_refuses_a_bad_line_by_field(change, message):
    lines = catalog_lines()
    change(lines[0])
    with pytest.raises(ValueError, match=message) as raised:
        EvidenceCatalog.from_lines(lines)
    assert "Synthetic evidence sentence" not in str(raised.value)


def test_a_catalog_has_one_corpus_version():
    lines = catalog_lines()
    lines[0]["corpus_version"] = "QCAI-CORPUS-2026-01-01"
    with pytest.raises(ValueError, match="corpus_version"):
        EvidenceCatalog.from_lines(lines)


def test_every_resolution_status_is_reached_and_no_locator_holds_text():
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    catalog = EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items))
    corpus = synthetic.corpus_text(items)
    ev = "EV-SYN-p001-01"
    span = "span-" + "a" * 64
    known = {span: {"item_id": "x", "item_version": "1", "start": 0, "end": 5, "byte_length": 5, "content_hash": "f" * 64, "text": "hello"}}
    resolver = PointerResolver(catalog=catalog, span_lookup=known.get, corpus_text=corpus.get, corpus_version=catalog.corpus_version)
    assert resolver.resolve(ev).status == "resolved"
    assert "text" not in resolver.resolve(ev).locator
    assert resolver.resolve(span).status == "resolved" and "text" not in resolver.resolve(span).locator
    assert resolver.resolve("span-" + "b" * 64).status == "unknown_pointer"
    assert resolver.resolve("EV-SYN-p999-99").status == "unknown_pointer"
    assert resolver.resolve("not-a-pointer").status == "malformed"
    assert PointerResolver().resolve(ev).status == "no_catalog"
    assert PointerResolver().resolve(span).status == "no_span_lookup"
    assert PointerResolver(catalog=catalog, corpus_version="QCAI-CORPUS-2030-01-01").resolve(ev).status == "corpus_version_mismatch"
    changed = dict(corpus)
    document = f"syn-doc-{ev.lower()}"
    changed[document] = changed[document].replace("Synthetic", "Synthetik")
    assert PointerResolver(catalog=catalog, corpus_text=changed.get).resolve(ev).status == "hash_mismatch"
    assert resolver.byte_length(ev) == len(synthetic.evidence_text(ev).encode("utf-8"))
    assert resolver.content_hash(ev) == content_sha256(synthetic.evidence_text(ev))


def test_resolve_items_reports_item_path_and_status():
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    catalog = EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items))
    report = resolve_items(items, PointerResolver(catalog=catalog))
    assert report.problems == () and report.resolved == report.total > 0
    items[0]["evidence_ids"] = ["EV-SYN-p990-01"]
    report = resolve_items(items, PointerResolver(catalog=catalog))
    assert report.problems == (("SYN-A-001", "evidence_ids[0]", "unknown_pointer", "evidence"),)


def test_a_resolution_says_whether_the_corpus_text_was_checked():
    items = synthetic.synthetic_dataset({"A": 1, "B": 1})
    catalog = EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items))
    corpus = synthetic.corpus_text(items)
    unchecked = resolve_items(items, PointerResolver(catalog=catalog))
    checked = resolve_items(items, PointerResolver(catalog=catalog, corpus_text=corpus.get))
    assert unchecked.problems == checked.problems == () and unchecked.evidence_resolved == checked.evidence_resolved == 3
    assert unchecked.text_verified == 0 and checked.text_verified == 3
    pointer = items[0]["evidence_ids"][0]
    assert PointerResolver(catalog=catalog).resolve(pointer).verified is False
    assert PointerResolver(catalog=catalog, corpus_text=corpus.get).resolve(pointer).verified is True
