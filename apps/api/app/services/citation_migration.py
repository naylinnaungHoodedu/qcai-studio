"""Legacy citation migration (plan Phase 2 task 2.3 and G; decision D3; Phase 2 spec 3.8, 2.7).

A stored v0 (2026-04-05 build) or v1 (CS595, Phase 1) citation migrates only where the hash of its
whitespace-normalised excerpt matches exactly one span (task 2.3: "Citations migrated where the excerpt hash is
unique, the rest counted as legacy_unresolved"). Title equality, excerpt containment and the v1 content_hash are
diagnostics that never change the outcome (spec conflict 3, [R5]). An exact-match regression (D10) is a citation
whose excerpt hash is unique in the current build but which still ends unresolved (an older registered span with
the same text makes it ambiguous), or an already migrated citation whose span no longer resolves; either stops the
run. The D-30 limits are read from the configuration package (legacy_citations), never hard-coded. A migrated citation keeps the full original
under legacy_original (plus legacy_chunk_id and legacy_span_id), so --downgrade restores it; a row is rewritten
only when its stored text is exactly what SQLAlchemy's JSON type writes (json.dumps), so the restored
CAST(col AS TEXT) is byte-for-byte the original on SQLite and PostgreSQL json ([R6]). Every write is a
compare-and-set on that text. --dry-run writes nothing, not even span registrations.

The report holds counts only: no learner id, row id or excerpt.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import Text, cast, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import ConfigPackage
from app.db_models import CorpusSpan, QAInteraction, TutorTurn
from app.services.provenance import CITATION_SCHEMA, UNRESOLVED_LABEL, provisional_flag
from app.services.spans import SpanRecord, SpanRegistry, excerpt_key, sha256_text
from app.services.span_store import persist_spans
from app.services.text_utils import normalize_display_text

REPORT_NAME = "qcai-citation-migration"
FORMAT_VERSION = 1
TABLES = {"qa_interactions": (QAInteraction, ("citations",)), "tutor_turns": (TutorTurn, ("citations", "claims"))}
REASONS = ("excerpt_no_match", "excerpt_ambiguous", "chapter_summary_excluded", "missing_excerpt", "invalid_shape")
EXIT_PASS, EXIT_ERROR, EXIT_USAGE, EXIT_STOP = 0, 1, 2, 3


@dataclass(frozen=True)
class SpanRef:
    span_id: str
    item_id: str
    item_version: str
    start: int
    end: int
    content_hash: str
    source_title_hash: str
    section_title_hash: str
    basis: str
    key_kind: str


@dataclass(frozen=True)
class MatchIndex:
    by_key: Mapping[str, tuple[SpanRef, ...]]
    by_span_id: Mapping[str, SpanRef]
    texts_available: bool
    memory: SpanRegistry | None
    database_rows: int
    # The distinct span ids per key in the current build alone: unique here but not overall is a regression (D10).
    current_by_key: Mapping[str, frozenset[str]] = field(default_factory=dict)


def build_match_index(db: Session, memory: SpanRegistry | None) -> MatchIndex:
    by_key: dict[str, list[SpanRef]] = {}
    by_span_id: dict[str, SpanRef] = {}
    current_by_key: dict[str, set[str]] = {}
    for record in memory.records if memory is not None else ():
        for kind, key in zip(("lexical", "semantic"), record.legacy_keys):
            ref = SpanRef(record.span_id, record.item_id, record.item_version, record.start, record.end, record.content_hash,
                          sha256_text(record.source_title), sha256_text(record.section_title), "memory", kind)
            by_key.setdefault(key, []).append(ref)
            by_span_id.setdefault(record.span_id, ref)
            current_by_key.setdefault(key, set()).add(record.span_id)
    rows = db.scalars(select(CorpusSpan).order_by(CorpusSpan.id.asc())).all()
    for row in rows:
        if row.plane != "public":
            continue
        for kind, key in (("lexical", row.legacy_key_lexical), ("semantic", row.legacy_key_semantic)):
            ref = SpanRef(row.span_id, row.item_id, row.item_version, row.char_start, row.char_end, row.content_hash,
                          row.source_title_hash, row.section_title_hash, "database", kind)
            by_key.setdefault(key, []).append(ref)
            by_span_id.setdefault(row.span_id, ref)
    return MatchIndex(
        {key: tuple(refs) for key, refs in by_key.items()},
        by_span_id,
        memory is not None,
        memory,
        len(rows),
        {key: frozenset(ids) for key, ids in current_by_key.items()},
    )


def is_canonical_json_text(raw: str) -> bool:
    """True when the stored text is exactly json.dumps of its value, as SQLAlchemy's JSON type writes it."""
    try:
        return json.dumps(json.loads(raw)) == raw
    except (TypeError, ValueError):
        return False


def _unresolved(original: dict, reason: str) -> dict:
    return {
        **original,
        "citation_schema": CITATION_SCHEMA,
        "resolution": "legacy_unresolved",
        "migration_status": "legacy_unresolved",
        "unresolved_reason": reason,
        "label": UNRESOLVED_LABEL,
        "provisional": True,
        "legacy_chunk_id": original.get("chunk_id"),
        "legacy_span_id": original.get("span_id"),
        "legacy_original": original,
    }


def _ws(value: str) -> str:
    return " ".join(value.split())


def classify_citation(raw: Any, index: MatchIndex, *, corpus_version: str, settings: Settings) -> tuple[Any, str, dict]:
    """(new value, outcome, diagnostics). Outcomes: native_v2, native_unresolved, already_migrated,
    migrated_unresolvable, already_unresolved, migrated, or legacy_unresolved:<reason>. diagnostics
    "exact_match_regression" marks a citation unique in the current build that still ends unresolved (D10)."""
    diagnostics: dict[str, Any] = {}
    if isinstance(raw, dict) and raw.get("citation_schema") == CITATION_SCHEMA:
        status = raw.get("migration_status")
        if status == "migrated":
            # Re-verified on every run: a migrated citation must keep resolving (AC-2-3), or the run stops (D10).
            ref = index.by_span_id.get(raw.get("span_id") or raw.get("chunk_id") or "")
            if ref is None or ref.content_hash != raw.get("content_hash"):
                return raw, "migrated_unresolvable", diagnostics
            return raw, "already_migrated", diagnostics
        if status == "legacy_unresolved" or raw.get("resolution") != "resolved":
            return raw, "already_unresolved", diagnostics
        ref = index.by_span_id.get(raw.get("span_id") or raw.get("chunk_id") or "")
        if ref is None or ref.content_hash != raw.get("content_hash"):
            return raw, "native_unresolved", diagnostics
        return raw, "native_v2", diagnostics
    if not isinstance(raw, dict) or not isinstance(raw.get("chunk_id"), str) or not isinstance(raw.get("excerpt"), str):
        return (_unresolved(raw, "invalid_shape") if isinstance(raw, dict) else raw), "legacy_unresolved:invalid_shape", diagnostics
    if raw.get("source_kind") == "video":
        return _unresolved(raw, "chapter_summary_excluded"), "legacy_unresolved:chapter_summary_excluded", diagnostics
    if not raw["excerpt"].strip():
        return _unresolved(raw, "missing_excerpt"), "legacy_unresolved:missing_excerpt", diagnostics
    key = excerpt_key(raw["excerpt"])
    refs = index.by_key.get(key, ())
    candidates = sorted({ref.span_id for ref in refs})
    diagnostics["candidates"] = len(candidates)
    if refs:
        diagnostics["key"] = refs[0].key_kind
        diagnostics["match_basis"] = refs[0].basis
    if len(candidates) != 1:
        reason = "excerpt_no_match" if not candidates else "excerpt_ambiguous"
        if len(index.current_by_key.get(key, ())) == 1:
            # Unique in the current build, ambiguous only because corpus_spans holds an older span with the same
            # text (an edit that shifted offsets): D10's "previously exact-match citation into unresolved".
            diagnostics["exact_match_regression"] = True
        return _unresolved(raw, reason), f"legacy_unresolved:{reason}", diagnostics
    ref = next(ref for ref in refs if ref.span_id == candidates[0])
    # Diagnostics only (spec 3.8 step 6): they never change the outcome.
    if isinstance(raw.get("source_title"), str) and isinstance(raw.get("section_title"), str):
        diagnostics["title_equal"] = (
            sha256_text(raw["source_title"]) == ref.source_title_hash and sha256_text(raw["section_title"]) == ref.section_title_hash
        )
    if isinstance(raw.get("content_hash"), str):
        diagnostics["v1_content_hash_agrees"] = raw["content_hash"] in {key, ref.content_hash}
    excerpt = _ws(raw["excerpt"])
    if index.memory is not None and not excerpt.endswith("..."):
        diagnostics["containment_also_in_other_span"] = any(
            record.span_id != ref.span_id and excerpt in _ws(normalize_display_text(record.text)) for record in index.memory.records
        )
    migrated = {
        **raw,
        "chunk_id": ref.span_id,
        "span_id": ref.span_id,
        "content_hash": ref.content_hash,
        "corpus_version": corpus_version,
        "item_id": ref.item_id,
        "item_version": ref.item_version,
        "start": ref.start,
        "end": ref.end,
        "citation_schema": CITATION_SCHEMA,
        "resolution": "resolved",
        "migration_status": "migrated",
        "provisional": provisional_flag("resolved", settings),
        "legacy_chunk_id": raw["chunk_id"],
        "legacy_span_id": raw.get("span_id"),
        "legacy_original": raw,
    }
    return migrated, "migrated", diagnostics


def _empty_table_report(with_claims: bool) -> dict:
    report = {
        "rows_scanned": 0,
        "rows_with_citations": 0,
        "rows_changed": 0,
        "rows_skipped_null": 0,
        "rows_skipped_non_canonical": 0,
        "rows_cas_conflict": 0,
        "citations": {
            "total": 0,
            "native_v2": 0,
            "native_unresolved": 0,
            "already_migrated": 0,
            "migrated": 0,
            "legacy_unresolved": 0,
            "by_reason": {reason: 0 for reason in REASONS},
            "diagnostics": {
                "key_lexical": 0,
                "key_semantic": 0,
                "title_equal": 0,
                "title_differs": 0,
                "containment_also_in_other_span": 0,
                "v1_content_hash_agrees": 0,
            },
            "exact_match_regressions": 0,
            "restored": 0,
        },
    }
    if with_claims:
        report["claims"] = {"total": 0, "remapped": 0, "bound_to_unresolved": 0, "restored": 0}
    return report


def _restore(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict) and "legacy_original" in value:
        return value["legacy_original"], 1
    return value, 0


def _null(raw: str | None) -> bool:
    return raw is None or raw.strip() in {"null", "[]", ""}


def _process_row(raws: dict[str, str | None], mode: str, index: MatchIndex, table: dict, *, corpus_version: str,
                 settings: Settings, matched: set[str]) -> dict[str, Any] | None:
    """The new column values for one row, or None when it is unchanged."""
    citations_raw = raws.get("citations")
    values = {name: None if raw is None else json.loads(raw) for name, raw in raws.items()}
    citations = values.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    claims = values.get("claims") if "claims" in raws else None
    stats = table["citations"]
    if mode == "downgrade":
        restored_citations = []
        for value in citations:
            restored, count = _restore(value)
            stats["restored"] += count
            restored_citations.append(restored)
        changed = {"citations": restored_citations} if restored_citations != citations else {}
        if isinstance(claims, list):
            restored_claims = []
            for value in claims:
                restored, count = _restore(value)
                table["claims"]["restored"] += count
                restored_claims.append(restored)
            if restored_claims != claims:
                changed["claims"] = restored_claims
        return changed or None

    new_citations = []
    remap: dict[str, str] = {}
    unresolved_ids: set[str] = set()
    for value in citations:
        stats["total"] += 1
        new_value, outcome, diagnostics = classify_citation(value, index, corpus_version=corpus_version, settings=settings)
        if outcome == "migrated":
            stats["migrated"] += 1
            matched.add(new_value["span_id"])
            for old in (value.get("span_id"), value.get("chunk_id")):
                if isinstance(old, str) and old:
                    remap[old] = new_value["span_id"]
            if diagnostics.get("key") == "lexical":
                stats["diagnostics"]["key_lexical"] += 1
            elif diagnostics.get("key") == "semantic":
                stats["diagnostics"]["key_semantic"] += 1
            if diagnostics.get("title_equal") is True:
                stats["diagnostics"]["title_equal"] += 1
            elif diagnostics.get("title_equal") is False:
                stats["diagnostics"]["title_differs"] += 1
            if diagnostics.get("containment_also_in_other_span"):
                stats["diagnostics"]["containment_also_in_other_span"] += 1
            if diagnostics.get("v1_content_hash_agrees"):
                stats["diagnostics"]["v1_content_hash_agrees"] += 1
        elif outcome.startswith("legacy_unresolved:"):
            reason = outcome.split(":", 1)[1]
            stats["legacy_unresolved"] += 1
            stats["by_reason"][reason] += 1
            if diagnostics.get("exact_match_regression"):
                stats["exact_match_regressions"] += 1
            if isinstance(value, dict):
                for old in (value.get("span_id"), value.get("chunk_id")):
                    if isinstance(old, str) and old:
                        unresolved_ids.add(old)
        elif outcome == "migrated_unresolvable":
            # Counted as migrated (it is not rewritten) and as a regression: it no longer resolves.
            stats["already_migrated"] += 1
            stats["exact_match_regressions"] += 1
        elif outcome == "already_unresolved":
            stats["legacy_unresolved"] += 1
            reason = value.get("unresolved_reason") if isinstance(value, dict) else None
            if reason in stats["by_reason"]:
                stats["by_reason"][reason] += 1
        else:
            stats[outcome] += 1
        new_citations.append(new_value)
    changed: dict[str, Any] = {}
    if new_citations != citations:
        changed["citations"] = new_citations
    if isinstance(claims, list):
        new_claims = []
        for claim in claims:
            table["claims"]["total"] += 1
            if not isinstance(claim, dict) or not isinstance(claim.get("cited_span_ids"), list) or "legacy_original" in claim:
                new_claims.append(claim)
                continue
            ids = claim["cited_span_ids"]
            mapped = [remap.get(item, item) if isinstance(item, str) else item for item in ids]
            if any(isinstance(item, str) and item in unresolved_ids for item in ids):
                table["claims"]["bound_to_unresolved"] += 1
            if mapped != ids:
                table["claims"]["remapped"] += 1
                new_claims.append({**claim, "cited_span_ids": mapped, "legacy_original": claim})
            else:
                new_claims.append(claim)
        if new_claims != claims:
            changed["claims"] = new_claims
    if citations_raw is not None and not _null(citations_raw):
        table["rows_with_citations"] += 1
    return changed or None


def migrate(
    db_factory: Callable[[], Session],
    *,
    mode: str,
    memory: SpanRegistry | None,
    settings: Settings,
    package: ConfigPackage,
    corpus_version: str,
    tables: Iterable[str] = ("qa_interactions", "tutor_turns"),
    batch_size: int = 500,
) -> dict:
    if mode not in {"dry-run", "apply", "downgrade"}:
        raise ValueError(f"Unknown mode {mode!r}")
    with db_factory() as db:
        index = build_match_index(db, memory)
        dialect = db.get_bind().dialect.name
    report: dict[str, Any] = {
        "report": REPORT_NAME,
        "format_version": FORMAT_VERSION,
        "mode": mode,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": settings.git_sha or "unknown",
        "database_dialect": dialect,
        "span_scheme": package.span_scheme,
        "corpus_version": corpus_version,
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "span_sources": {
            "memory_spans": len(memory) if memory is not None else 0,
            "database_rows": index.database_rows,
            "memory_items": sorted(memory.item_ids) if memory is not None else [],
        },
        "tables": {},
    }
    matched: set[str] = set()
    for name in tables:
        if name not in TABLES:
            raise ValueError(f"Unknown table {name!r}")
        model, columns = TABLES[name]
        table = _empty_table_report("claims" in columns)
        report["tables"][name] = table
        with db_factory() as db:
            ids = [row_id for (row_id,) in db.execute(select(model.id).order_by(model.id.asc())).all()]
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            with db_factory() as db:
                selected = [cast(getattr(model, column), Text).label(column) for column in columns]
                rows = db.execute(select(model.id, *selected).where(model.id.in_(batch)).order_by(model.id.asc())).all()
                for row in rows:
                    table["rows_scanned"] += 1
                    raws = {column: getattr(row, column) for column in columns}
                    if all(_null(raw) for raw in raws.values()):
                        table["rows_skipped_null"] += 1
                        continue
                    if not all(raw is None or is_canonical_json_text(raw) for raw in raws.values()):
                        # Never rewritten: its text could not be restored byte for byte ([R6]).
                        table["rows_skipped_non_canonical"] += 1
                        continue
                    changed = _process_row(raws, mode, index, table, corpus_version=corpus_version, settings=settings, matched=matched)
                    if not changed:
                        continue
                    table["rows_changed"] += 1
                    if mode == "dry-run":
                        continue
                    conditions = [model.id == row.id] + [
                        cast(getattr(model, column), Text) == raws[column] for column in columns if raws[column] is not None
                    ]
                    result = db.execute(update(model).where(*conditions).values(**changed).execution_options(synchronize_session=False))
                    if result.rowcount == 0:
                        table["rows_cas_conflict"] += 1
                        table["rows_changed"] -= 1
                if mode == "dry-run":
                    db.rollback()
                    continue
                if mode == "apply" and memory is not None:
                    # The matched spans are registered in the same transaction as the rows that cite them.
                    records: list[SpanRecord] = [record for span_id in sorted(matched) if (record := memory.get(span_id)) is not None]
                    persist_spans(db, records, corpus_version=corpus_version, registered_by="migration")
                    matched.clear()
                db.commit()
    report["totals"] = _totals(report)
    report["threshold"] = _threshold(report, package, mode)
    return report


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict:
    # The same Wilson score interval as evaluation.qcai_eval.statistics (the image does not ship evaluation/);
    # tests/test_citation_migration.py checks that the two agree.
    from math import sqrt

    if total == 0:
        return {"successes": 0, "total": 0, "rate": 0.0, "lower": 0.0, "upper": 0.0}
    rate = successes / total
    denominator = 1 + (z * z) / total
    centre = (rate + (z * z) / (2 * total)) / denominator
    margin = z * sqrt((rate * (1 - rate) / total) + (z * z) / (4 * total * total)) / denominator
    return {"successes": successes, "total": total, "rate": rate, "lower": max(0.0, centre - margin), "upper": min(1.0, centre + margin)}


def _totals(report: dict) -> dict:
    tables = report["tables"].values()
    migrated = sum(table["citations"]["migrated"] for table in tables)
    already = sum(table["citations"]["already_migrated"] for table in tables)
    unresolved = sum(table["citations"]["legacy_unresolved"] for table in tables)
    legacy = migrated + already + unresolved
    native = sum(table["citations"]["native_v2"] + table["citations"]["native_unresolved"] for table in tables)
    interval = wilson_interval(unresolved, legacy) if legacy else None
    return {
        "legacy_citations": legacy,
        "migrated": migrated,
        "already_migrated": already,
        "legacy_unresolved": unresolved,
        "unresolved_share": round(unresolved / legacy, 6) if legacy else None,
        "unresolved_share_wilson95": [round(interval["lower"], 6), round(interval["upper"], 6)] if interval else None,
        "native_citations": native,
        "native_unresolved": sum(table["citations"]["native_unresolved"] for table in tables),
        "exact_match_regressions": sum(table["citations"]["exact_match_regressions"] for table in tables),
        "rows_skipped_non_canonical": sum(table["rows_skipped_non_canonical"] for table in tables),
    }


def _share_limit(rule: Mapping[str, Any], key: str) -> float | None:
    value = rule.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"legacy_citations.{key} must be null or a number in [0, 1]")
    return float(value)


def _threshold(report: dict, package: ConfigPackage, mode: str) -> dict:
    """The D-30 comparison (plan Phase 2 L: "stop if unresolved citations exceed the OPEN DECISION threshold").

    Every limit comes from the configuration package (legacy_citations), so ratifying D-30 is a configuration change:
    - native: the share of Phase 2 citations that do not resolve may not exceed max_unresolved_share_native (0.0);
    - legacy: when max_unresolved_share_legacy is a number, the unresolved share of legacy citations may not exceed
      it, measured by legacy_share_statistic ("point": the observed share; "wilson95_upper": its Wilson 95% upper
      bound); null leaves the share reported and labelled but not gated (D-30 open).
    """
    rule = package.legacy_citations
    totals = report["totals"]
    stop_reasons = []
    native_limit = _share_limit(rule, "max_unresolved_share_native")
    native_limit = 0.0 if native_limit is None else native_limit
    native_share = totals["native_unresolved"] / totals["native_citations"] if totals["native_citations"] else 0.0
    if totals["native_unresolved"] > 0 and native_share > native_limit:
        stop_reasons.append(
            f"a citation created by the Phase 2 pipeline does not resolve (D-30: native share {native_share:.6f} "
            f"exceeds {native_limit})"
        )
    legacy_limit = _share_limit(rule, "max_unresolved_share_legacy")
    statistic = rule.get("legacy_share_statistic", "point")
    if statistic not in {"point", "wilson95_upper"}:
        raise ValueError("legacy_citations.legacy_share_statistic must be 'point' or 'wilson95_upper'")
    observed = None
    if totals["legacy_citations"]:
        observed = totals["unresolved_share"] if statistic == "point" else totals["unresolved_share_wilson95"][1]
    if legacy_limit is not None and observed is not None and observed > legacy_limit:
        stop_reasons.append(f"legacy unresolved share {observed} ({statistic}) exceeds the D-30 legacy threshold {legacy_limit}")
    if rule.get("stop_on_exact_match_regression", True) and totals["exact_match_regressions"] > 0:
        stop_reasons.append("a previously exact-match citation would become or has become unresolved (D-30, D10)")
    if mode == "apply" and rule.get("stop_on_non_canonical_row_in_apply", True) and totals["rows_skipped_non_canonical"] > 0:
        stop_reasons.append("rows whose stored JSON is not canonical were skipped, so the run is not fully reversible")
    return {
        "decision": rule.get("decision", "D-30"),
        "status": rule.get("status", "provisional"),
        "max_unresolved_share_native": native_limit,
        "native_unresolved_share": round(native_share, 6),
        "max_unresolved_share_legacy": legacy_limit,
        "legacy_share_statistic": statistic,
        "legacy_share_observed": observed,
        "legacy_gated": legacy_limit is not None,
        "result": "stop" if stop_reasons else "pass",
        "stop_reasons": stop_reasons,
    }
