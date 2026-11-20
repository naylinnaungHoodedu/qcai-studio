"""Calibrate the bm25f-v1 abstention floor and margin on public-corpus items only (plan Phase 2 task 2.6).

Run: python scripts/calibrate_abstention.py --write docs/evaluation/phase2/calibration_record_v1.json [--update-package]
     python scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json

Inputs (public only; anything under lqs/ is refused, and no learner record, tutor turn or rating is read):
- apps/api/tests/data/phase2_calibration_queries.json: the pre-registered BEP-1 strata with cal/conf folds
  ("sha256(query) first hex digit even -> cal, odd -> conf") and hold-out B;
- apps/api/tests/data/score_floor_queries.json: the AC-2-4/AC-2-5 fixture;
- MODULE_BLUEPRINTS learner questions, each labelled with its own lesson.
Two index configurations: the governed build as configured (D-31: authored spans only) and every public-plane,
bound item approved (a temporary manifest). The baseline is the frozen pre-migration search
(app.services.retrieval_legacy_p1) in the same run (AC-2-5).

Selection (spec 3.14): a floor is feasible on the cal fold when no oos_general or stop_only cal query keeps a
result and recall@5 (cal in-domain, and learner questions) is not below the legacy recall. Per configuration take
the contiguous feasible interval from the lowest feasible floor; intersect; floor = midpoint rounded down to 0.05,
margin = upper end - floor rounded down to 0.05. Confirm on the conf fold, hold-out B and the AC fixture; any
failure, or an empty intersection, is a stop (plan Phase 2 L): exit 3, package unchanged. The values stay
provisional until Phase 4 and are not final before the E1 freeze.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import UTC, datetime

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import Settings  # noqa: E402
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package  # noqa: E402
from app.core.corpus_governance import get_corpus_registry  # noqa: E402
from app.core.manifest_v2 import dumps_manifest, with_all_public_approved  # noqa: E402
from app.services.content_assembler import MODULE_BLUEPRINTS, CourseStore, _module_lessons  # noqa: E402
from app.services.retrieval_legacy_p1 import LEGACY_ALGORITHM, build_legacy_chunks, legacy_search  # noqa: E402
from evaluation.qcai_eval.statistics import wilson_interval  # noqa: E402

DATA = API_ROOT / "tests" / "data"
CALIBRATION_FIXTURE = DATA / "phase2_calibration_queries.json"
AC_FIXTURE = DATA / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
DEFAULT_RECORD = REPO_ROOT / "docs" / "evaluation" / "phase2" / "calibration_record_v1.json"
GRID_START, GRID_STEP, GRID_POINTS = 0.0, 0.05, 401  # 0.00 .. 20.00
IN_DOMAIN_STRATA = ("in_suggested", "in_flashcard", "in_short", "in_paraphrase", "in_multi", "in_quiz")
GATED_OOS = ("oos_general", "stop_only")
HOLDOUT_OOS = ("holdout_oos", "holdout_stop")
STRESS_SUFFIXES = (" noise model", " for optimization")
EXIT_STOP = 3


def _refuse_lqs(path: Path) -> None:
    resolved = path.resolve()
    if "lqs" in resolved.relative_to(REPO_ROOT).parts if resolved.is_relative_to(REPO_ROOT) else "lqs" in resolved.parts:
        raise SystemExit(f"refused: {path} is under lqs/; ULQS items MUST NOT be used for calibration (plan 11.3)")


def _canonical_file_sha(path: Path) -> str:
    return canonical_sha256(json.loads(path.read_text(encoding="utf-8")))


def learner_questions() -> list[dict]:
    return [
        {"query": question, "expected": [lesson["slug"]]}
        for blueprint in MODULE_BLUEPRINTS
        for lesson in _module_lessons(blueprint)
        for question in lesson["learner_questions"]
    ]


LESSON_ORDER = [lesson["slug"] for blueprint in MODULE_BLUEPRINTS for lesson in _module_lessons(blueprint)]


def floor_value(index: int) -> float:
    return round(GRID_START + index * GRID_STEP, 2)


class Configuration:
    """One index configuration: the bm25f-v1 eligible lists, the p1-floor span index and the frozen legacy search."""

    def __init__(self, name: str, description: str, settings: Settings, queries: list[str], *, legacy_all_assets: bool = False):
        self.name = name
        self.description = description
        bm25 = CourseStore(settings.model_copy(update={"retrieval_gate": "bm25f-v1"}))
        p1 = CourseStore(settings.model_copy(update={"retrieval_gate": "p1-floor"}))
        # The pre-migration code served every approved asset, the 2026 video included (it had no Q-10 binding).
        registry = get_corpus_registry(settings)
        documents = [path for path in settings.source_documents if registry.is_public_asset(path.name) or legacy_all_assets]
        videos = [path for path in settings.source_videos if registry.is_public_asset(path.name) or legacy_all_assets]
        chunks = build_legacy_chunks(settings, documents, videos)
        self.index_version = bm25.index_version
        self.p1_index_version = p1.index_version
        self.entries = len(bm25.chunks)
        self.corpus_version = bm25.corpus_version
        self.eligible = {
            query: [(item.score, item.entry.lesson_slugs, item.entry.item_kind) for item in bm25.index.eligible_unfloored(query)]
            for query in queries
        }
        self.p1 = {query: [(r.lesson_slug, r.source_kind) for r in p1.search(query, top_k=5)] for query in queries}
        self.p1_lessons = {
            query: [tuple(r.lesson_slugs) for r in p1.search(query, top_k=5)] for query in queries
        }
        self.legacy = {query: [(r.lesson_slug, r.source_kind, r.score) for r in legacy_search(chunks, query, top_k=5)] for query in queries}
        self.legacy_exact = {query: [(r.lesson_slug, r.score, r.excerpt) for r in legacy_search(chunks, query, top_k=8)] for query in queries}
        self.p1_exact = {query: [(r.lesson_slug, r.score, r.excerpt) for r in p1.search(query, top_k=8)] for query in queries}

    # bm25f-v1 at a floor
    def survivors(self, query: str, floor: float) -> list[tuple]:
        return [item for item in self.eligible[query] if item[0] >= floor - 1e-12]

    def recall(self, items: list[dict], floor: float, *, slot_equal: bool = False) -> int:
        hits = 0
        for item in items:
            top = self.survivors(item["query"], floor)[:5]
            if slot_equal:
                lessons: list[str] = []
                for _, slugs, _ in top:
                    lessons.extend(sorted(slugs, key=LESSON_ORDER.index))
                found = set(lessons[:5])
            else:
                found = {slug for _, slugs, _ in top for slug in slugs}
            hits += bool(set(item["expected"]) & found)
        return hits

    def with_results(self, items: list[dict], floor: float) -> int:
        return sum(1 for item in items if self.survivors(item["query"], floor))

    def answered(self, items: list[dict], floor: float) -> int:
        return sum(1 for item in items if any(kind == "document" for _, _, kind in self.survivors(item["query"], floor)[:4]))

    # the frozen pre-migration search
    def legacy_recall(self, items: list[dict]) -> int:
        return sum(bool(set(item["expected"]) & {slug for slug, _, _ in self.legacy[item["query"]]}) for item in items)

    def legacy_with_results(self, items: list[dict]) -> int:
        return sum(1 for item in items if self.legacy[item["query"]])

    def legacy_answered(self, items: list[dict]) -> int:
        return sum(1 for item in items if any(kind == "document" for _, kind, _ in self.legacy[item["query"]][:4]))

    # p1-floor over the span index (what ships outside development)
    def p1_recall(self, items: list[dict]) -> int:
        return sum(bool(set(item["expected"]) & {slug for slugs in self.p1_lessons[item["query"]] for slug in slugs}) for item in items)

    def p1_with_results(self, items: list[dict]) -> int:
        return sum(1 for item in items if self.p1[item["query"]])

    def p1_answered(self, items: list[dict]) -> int:
        return sum(1 for item in items if any(kind == "document" for _, kind in self.p1[item["query"]][:4]))


def _items(fixture: dict, *, fold: str | None = None, strata: tuple[str, ...] | None = None) -> list[dict]:
    return [
        item
        for item in fixture["items"]
        if (fold is None or item["fold"] == fold) and (strata is None or item["stratum"] in strata)
    ]


def compute(workdir: Path) -> dict:
    package = get_config_package(Settings())
    fixture = json.loads(CALIBRATION_FIXTURE.read_text(encoding="utf-8"))
    ac = json.loads(AC_FIXTURE.read_text(encoding="utf-8"))
    lq = learner_questions()
    ac_in = [{"query": item["query"], "expected": item["expected_lessons"]} for item in ac["in_domain"]]
    ac_oos = [{"query": query, "expected": []} for query in ac["off_topic"] + ac["stopword_only"]]
    stress = {suffix: [{"query": item["query"] + suffix, "expected": []} for item in ac_oos] for suffix in STRESS_SUFFIXES}
    queries = sorted({
        *(item["query"] for item in fixture["items"]),
        *(item["query"] for item in ac_in + ac_oos + lq),
        *(item["query"] for items in stress.values() for item in items),
    })

    manifest = json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    approved_path = workdir / "all_public_approved_manifest.json"
    approved_path.write_text(dumps_manifest(with_all_public_approved(manifest)), encoding="utf-8")
    base = {"environment": "production", "enforce_corpus_governance": True}
    configurations = [
        Configuration(
            "governed_as_configured",
            "committed manifest, D-31: zero approved; authored spans only",
            Settings(**base, corpus_manifest_path=str(REPO_MANIFEST)),
            queries,
        ),
        Configuration(
            "all_public_approved",
            "every public-plane bound item approved (temporary manifest, never committed)",
            Settings(**base, corpus_manifest_path=str(approved_path)),
            queries,
            legacy_all_assets=True,
        ),
    ]

    cal_in = _items(fixture, fold="cal", strata=IN_DOMAIN_STRATA)
    cal_oos = _items(fixture, fold="cal", strata=GATED_OOS)
    conf_in = _items(fixture, fold="conf", strata=IN_DOMAIN_STRATA)
    conf_oos = _items(fixture, fold="conf", strata=GATED_OOS)
    hold_in = _items(fixture, strata=("holdout_in",))
    hold_oos = _items(fixture, strata=HOLDOUT_OOS)
    all_in = _items(fixture, strata=IN_DOMAIN_STRATA) + hold_in

    record_configurations = []
    windows = []
    for config in configurations:
        legacy = {
            "cal": config.legacy_recall(cal_in),
            "conf": config.legacy_recall(conf_in),
            "holdout": config.legacy_recall(hold_in),
            "all": config.legacy_recall(ac_in),
        }
        legacy_lq = config.legacy_recall(lq)
        sweep = []
        feasible = []
        for index in range(GRID_POINTS):
            floor = floor_value(index)
            cal_leaks = config.with_results(cal_oos, floor)
            cal_recall = config.recall(cal_in, floor)
            lq_recall = config.recall(lq, floor)
            ok = cal_leaks == 0 and cal_recall >= legacy["cal"] and lq_recall >= legacy_lq
            feasible.append(ok)
            sweep.append({"floor": floor, "cal": {"oos_with_results": cal_leaks, "recall_at_5": cal_recall},
                          "learner_questions_recall_at_5": lq_recall, "feasible": ok})
        window = None
        if any(feasible):
            low = feasible.index(True)
            high = low
            while high + 1 < GRID_POINTS and feasible[high + 1]:
                high += 1
            window = (low, high)
        windows.append(window)
        record_configurations.append({
            "name": config.name,
            "description": config.description,
            "corpus_version": config.corpus_version,
            "index_version": config.index_version,
            "entries": config.entries,
            "legacy": {"algorithm": LEGACY_ALGORITHM, "recall_at_5": legacy, "learner_questions_recall_at_5": legacy_lq},
            "p1_floor_on_span_index": {
                "index_version": config.p1_index_version,
                "recall_at_5_all": config.p1_recall(ac_in),
                "learner_questions_recall_at_5": config.p1_recall(lq),
                "equals_legacy_per_query": all(config.p1_exact[item["query"]] == config.legacy_exact[item["query"]] for item in ac_in + lq + ac_oos),
                "strata_with_results": {stratum: config.p1_with_results(_items(fixture, strata=(stratum,)))
                                        for stratum in ("oos_general", "stop_only", "oos_lexical", "near_miss")},
            },
            "sweep": sweep,
            "feasible_window_cal": [floor_value(window[0]), floor_value(window[1])] if window else None,
        })

    selection = {
        "rule": ("feasible on the cal fold (no oos_general/stop_only result; recall >= legacy) and on the learner questions; "
                 "floor = midpoint of the intersection, rounded down to 0.05; margin = upper end - floor, rounded down to 0.05"),
        "intersected_window": None,
        "floor": None,
        "margin": None,
    }
    result = "stop"
    confirmation: dict = {}
    reported: dict = {}
    answer_rate: dict = {}
    fragility: list[str] = []
    stress_results: dict = {}
    if all(windows):
        low = max(window[0] for window in windows)
        high = min(window[1] for window in windows)
        if low <= high:
            floor_index = (low + high) // 2
            margin_index = high - floor_index
            floor, margin = floor_value(floor_index), floor_value(margin_index)
            selection.update({"intersected_window": [floor_value(low), floor_value(high)], "floor": floor, "margin": margin})
            checks = []
            conf_block, hold_block, ac_block = {}, {}, {"ac_2_4_oos_with_results": {}, "ac_2_5_recall": {}, "ac_2_5_legacy": {}}
            for config, record in zip(configurations, record_configurations):
                legacy = record["legacy"]["recall_at_5"]
                conf_block[config.name] = {"recall_at_5": config.recall(conf_in, floor), "legacy": legacy["conf"],
                                           "oos_with_results": config.with_results(conf_oos, floor)}
                hold_block[config.name] = {"recall_at_5": config.recall(hold_in, floor), "legacy": legacy["holdout"],
                                           "oos_with_results": config.with_results(hold_oos, floor)}
                ac_block["ac_2_4_oos_with_results"][config.name] = config.with_results(ac_oos, floor)
                ac_block["ac_2_5_recall"][config.name] = config.recall(ac_in, floor)
                ac_block["ac_2_5_legacy"][config.name] = legacy["all"]
                ac_block.setdefault("ac_2_5_recall_slot_equal", {})[config.name] = config.recall(ac_in, floor, slot_equal=True)
                ac_block.setdefault("learner_questions_recall_at_5", {})[config.name] = config.recall(lq, floor)
                ac_block.setdefault("learner_questions_slot_equal", {})[config.name] = config.recall(lq, floor, slot_equal=True)
                ac_block.setdefault("learner_questions_legacy", {})[config.name] = record["legacy"]["learner_questions_recall_at_5"]
                checks += [
                    conf_block[config.name]["oos_with_results"] == 0,
                    conf_block[config.name]["recall_at_5"] >= legacy["conf"],
                    hold_block[config.name]["oos_with_results"] == 0,
                    hold_block[config.name]["recall_at_5"] >= legacy["holdout"],
                    ac_block["ac_2_4_oos_with_results"][config.name] == 0,
                    ac_block["ac_2_5_recall"][config.name] >= legacy["all"],
                    ac_block["learner_questions_recall_at_5"][config.name] >= record["legacy"]["learner_questions_recall_at_5"],
                ]
                for label, value, baseline in (
                    ("AC fixture recall_at_5", ac_block["ac_2_5_recall"][config.name], legacy["all"]),
                    ("learner_questions recall_at_5", ac_block["learner_questions_recall_at_5"][config.name], record["legacy"]["learner_questions_recall_at_5"]),
                    ("conf fold recall_at_5", conf_block[config.name]["recall_at_5"], legacy["conf"]),
                    ("hold-out B recall_at_5", hold_block[config.name]["recall_at_5"], legacy["holdout"]),
                ):
                    if value == baseline:
                        fragility.append(f"{config.name} {label} {value} = legacy {baseline} (zero slack)")
                if ac_block["learner_questions_slot_equal"][config.name] < record["legacy"]["learner_questions_recall_at_5"]:
                    fragility.append(f"{config.name} learner_questions slot-equal recall_at_5 {ac_block['learner_questions_slot_equal'][config.name]} "
                                     f"< legacy {record['legacy']['learner_questions_recall_at_5']} (informational metric)")
            result = "pass" if all(checks) else "stop"
            confirmation = {"conf_fold": conf_block, "holdout_b": hold_block, "ac_fixture": ac_block, "result": result}
            for stratum in ("near_miss", "oos_lexical"):
                items = _items(fixture, strata=(stratum,))
                reported[stratum] = {
                    "queries": len(items),
                    "bm25": {config.name: config.with_results(items, floor) for config in configurations},
                    "p1_floor_span_index": {config.name: config.p1_with_results(items) for config in configurations},
                    "legacy_p1": {config.name: config.legacy_with_results(items) for config in configurations},
                }
            multi = _items(fixture, strata=("in_multi",))
            reported["in_multi_recall_at_5"] = {
                "queries": len(multi),
                "bm25": {config.name: config.recall(multi, floor) for config in configurations},
                "legacy_p1": {config.name: config.legacy_recall(multi) for config in configurations},
            }
            reported["in_domain_with_results"] = {
                "queries": len(ac_in),
                "bm25": {config.name: config.with_results(ac_in, floor) for config in configurations},
                "p1_floor_span_index": {config.name: config.p1_with_results(ac_in) for config in configurations},
            }
            reported["regression_vs_p1"] = any(
                reported[stratum]["bm25"][config.name] > reported[stratum]["legacy_p1"][config.name]
                for stratum in ("near_miss", "oos_lexical")
                for config in configurations
            )
            for suffix, items in stress.items():
                stress_results[suffix.strip()] = {
                    "queries": len(items),
                    "bm25": {config.name: config.with_results(items, floor) for config in configurations},
                    "bm25_at_window_top": {config.name: config.with_results(items, floor_value(high)) for config in configurations},
                    "p1_floor_span_index": {config.name: config.p1_with_results(items) for config in configurations},
                }
            approved = configurations[1]
            bm25_answered = approved.answered(ac_in, floor)
            p1_answered = approved.p1_answered(ac_in)
            legacy_answered = approved.legacy_answered(ac_in)
            total = len(ac_in)
            answer_rate = {
                "phase0_proxy": {"value": f"{total}/{total}", "rate": 1.0,
                                 "source": "BEP-1/27_score_floor/PROPOSAL.md section 3 (b3d6808c, before the floor)"},
                "bm25": f"{bm25_answered}/{total}",
                "p1_floor_span_index": f"{p1_answered}/{total}",
                "legacy_p1": f"{legacy_answered}/{total}",
                "wilson95": {
                    "bm25": [round(wilson_interval(bm25_answered, total)["lower"], 4), round(wilson_interval(bm25_answered, total)["upper"], 4)],
                    "p1_floor_span_index": [round(wilson_interval(p1_answered, total)["lower"], 4), round(wilson_interval(p1_answered, total)["upper"], 4)],
                },
                "within_5_points": {
                    "bm25": bm25_answered / total >= 0.95,
                    "p1_floor_span_index": p1_answered / total >= 0.95,
                    "legacy_p1": legacy_answered / total >= 0.95,
                },
            }
    return {
        "record": "qcai-abstention-calibration",
        "format_version": 1,
        # Phase 3 spec 5.3: the record names the package it was calibrated with (v2 keeps v1's calibration).
        "config_package_version": package.abstention.calibrated_with_package_version or package.package_version,
        "retrieval_sha256": package.retrieval_sha256,
        "corpus_version": configurations[0].corpus_version,
        "span_scheme": package.span_scheme,
        "public_corpus_only": True,
        "excluded_sources": ["private plane", "lqs/ (ULQS)", "learner records, tutor turns, ratings"],
        "datasets": {
            "fixture": {
                "path": CALIBRATION_FIXTURE.relative_to(REPO_ROOT).as_posix(),
                "sha256": _canonical_file_sha(CALIBRATION_FIXTURE),
                "sources": fixture["sources"],
                "fold_rule": fixture["fold_rule"],
                "strata": {stratum: sum(1 for item in fixture["items"] if item["stratum"] == stratum)
                           for stratum in sorted({item["stratum"] for item in fixture["items"]})},
            },
            "ac_fixture": {
                "path": AC_FIXTURE.relative_to(REPO_ROOT).as_posix(),
                "sha256": _canonical_file_sha(AC_FIXTURE),
                "note": "AC-2-4/AC-2-5 fixture (Phase 1); equals the union of the gated strata and hold-out B",
            },
            "learner_questions": {"source": "MODULE_BLUEPRINTS learner_questions, label = own lesson", "count": len(lq)},
        },
        "metric_definitions": {
            "recall_at_5": "expected lesson in the union of lesson_slugs of the top 5 survivors (BEP-1 definition, generalised)",
            "recall_at_5_slot_equal": "expected lesson among the first 5 (span, lesson) pairs, lessons expanded in blueprint order (informational)",
            "answer_rate": "share of in-domain queries with >= 1 document span among the top 4 survivors (all-approved configuration)",
        },
        "grid": {"start": GRID_START, "stop": floor_value(GRID_POINTS - 1), "step": GRID_STEP},
        "configurations": record_configurations,
        "selection": selection,
        "confirmation": confirmation,
        "reported_strata_vs_p1": reported,
        "stress_probes": {"note": "informational; each off-topic AC-fixture question plus a course phrase", "results": stress_results},
        "answer_rate": answer_rate,
        "fragility": fragility,
        "provisional": True,
        "provisional_until": "Phase 4",
        "not_final_before": "E1 freeze (plan Phase 2 H)",
        "shipping_gate": {"outside_development": "p1-floor", "switch_requires": "D-05 remediation approval (R-15)"},
        "limitations": [
            "coverage-v1 and the framing stopwords (define, definition, term, terms, word, words) were designed after inspecting leaks on the whole repository fixture, including the conf fold and hold-out B; AC-2-4 on it is design-set evidence",
            "near_miss and oos_lexical were not used in design; see reported_strata_vs_p1 for bm25f-v1 against the Phase 1 floor",
            "learner questions appear verbatim in authored spans (circular for the governed configuration)",
            "no ULQS calibration split yet (Phase 4)",
            "the Phase 0 answer rate is a proxy measured at b3d6808c before the floor",
        ],
        "result": result,
    }


def _strip_volatile(record: dict) -> dict:
    stripped = copy.deepcopy(record)
    for key in ("created_at", "commit"):
        stripped.pop(key, None)
    return stripped


def build_record() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        record = compute(Path(tmp))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip() or "unknown"
    return {"record": record["record"], "format_version": record["format_version"],
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": commit,
            **{key: value for key, value in record.items() if key not in {"record", "format_version"}}}


def update_package(record: dict, record_sha: str, package_path: Path = DEFAULT_PACKAGE_PATH) -> str:
    from scripts.config_package import write_package

    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["abstention"]["floor"] = record["selection"]["floor"]
    payload["abstention"]["margin"] = record["selection"]["margin"]
    payload["abstention"]["calibration_record_sha256"] = record_sha
    return write_package(package_path, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--update-package", action="store_true")
    args = parser.parse_args(argv)
    for path in (CALIBRATION_FIXTURE, AC_FIXTURE):
        _refuse_lqs(path)
    target = args.write or args.check
    _refuse_lqs(target)
    if args.write:
        record = build_record()
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        record_sha = canonical_sha256(json.loads(args.write.read_text(encoding="utf-8")))
        selection = record["selection"]
        print(f"wrote {args.write}: result {record['result']}, floor {selection['floor']}, margin {selection['margin']}, sha256 {record_sha}")
        if record["result"] != "pass":
            print("stop condition (plan Phase 2 L): the package is unchanged", file=sys.stderr)
            return EXIT_STOP
        if args.update_package:
            digest = update_package(record, record_sha)
            print(f"updated the configuration package: sha256 {digest}")
        return 0
    committed = json.loads(args.check.read_text(encoding="utf-8"))
    fresh = build_record()
    problems = []
    if _strip_volatile(committed) != _strip_volatile(fresh):
        differing = sorted(key for key in set(committed) | set(fresh) if key not in {"created_at", "commit"} and committed.get(key) != fresh.get(key))
        problems.append(f"the record differs from a fresh computation in: {', '.join(differing)}")
    package = get_config_package(Settings())
    if (package.abstention.floor, package.abstention.margin) != (committed["selection"]["floor"], committed["selection"]["margin"]):
        problems.append("the package floor and margin differ from the record's selection")
    if package.abstention.calibration_record_sha256 != canonical_sha256(committed):
        problems.append("the package's calibration_record_sha256 does not match the record")
    if problems:
        print("calibration check failed:\n" + "\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
        return 1
    if committed["result"] != "pass":
        print("the committed record is a stop", file=sys.stderr)
        return EXIT_STOP
    print(f"calibration record is current: floor {committed['selection']['floor']}, margin {committed['selection']['margin']} (provisional until Phase 4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
