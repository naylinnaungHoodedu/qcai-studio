"""Contexts c = (topic cluster, task type, tier) (plan Phase 9 task 1, B "topic clusters ... OPEN DECISION"; spec 4.2; PD-50).

cluster-module-v1: the module slugs (MODULE_BLUEPRINTS) of the lessons each retrieval.evidence span is bound to; the one
module common to every evidence span, else "unscoped" (several or none, no evidence, or a record of another corpus
version than the store's). The ledger records no lesson, so the cluster is derived from fields every record carries
(spec conflict 3) and frozen into the outcome event: the replay never needs the store.
tier-source-v1: the V2 claim tier; else V1.6 (not_assessment gives default_tier, any other code assessment_tier); else
default_tier. tier-1-quiz-item-v1: the assessment tier is a quiz item, every other tier an explanation (the other four
task types are reserved values).
"""

from __future__ import annotations

from typing import Any

from app.services.ranking.vocabulary import UNSCOPED


def span_modules(store: Any) -> dict[str, frozenset[str]]:
    """span id -> the module slugs of the lessons the span is bound to (built once per scan)."""
    lesson_module = {}
    for module in store.modules.values():
        for lesson in module.lesson_slugs:
            lesson_module[lesson] = module.slug
    out = {}
    for entry in store.chunks:
        out[entry.span_id] = frozenset(lesson_module[lesson] for lesson in entry.lesson_slugs if lesson in lesson_module)
    return out


def cluster_for(entry: Any, modules: dict[str, frozenset[str]], corpus_version: str | None) -> str:
    retrieval = getattr(entry, "retrieval", None)
    evidence = getattr(retrieval, "evidence", ()) if retrieval is not None else ()
    if not evidence or (corpus_version is not None and retrieval.corpus_version != corpus_version):
        return UNSCOPED
    common: frozenset[str] | None = None
    for span in evidence:
        found = modules.get(span.span_id, frozenset())
        common = found if common is None else common & found
    if common is not None and len(common) == 1:
        return next(iter(common))
    return UNSCOPED


def tier_for(entry: Any, package: Any) -> tuple[int, str]:
    v2 = package.v2
    verification = getattr(entry, "verification", None)
    for verdict in getattr(verification, "verdicts", ()) or ():
        claim_v2 = getattr(verdict, "v2", None)
        if claim_v2 is not None:
            return int(claim_v2.tier), "v2"
    for check in getattr(verification, "checks", ()) or ():
        if check.check_id == "V1.6":
            return (int(v2.default_tier) if check.reason_code == "not_assessment" else int(v2.assessment_tier)), "v1_6"
    return int(v2.default_tier), "default"


def task_type_for(tier: int, package: Any) -> str:
    return "quiz_item" if int(tier) == int(package.v2.assessment_tier) else "explanation"
