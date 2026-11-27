"""Synthetic builders for tests, fixtures and CI (spec 3.15, 7.1). Every text is invented; `license_class` is synthetic.

Nothing here derives from a ULQS item, a licensed volume or a course document. The committed fixtures
(`evaluation/fixtures/synthetic_ulqs_v1.jsonl`, `synthetic_evidence_catalog_v1.jsonl`) are `synthetic_dataset(SMALL)` and
its catalog; tests build larger sets (the 160-item AC-10-1 set) in their own temporary directory.
"""

from __future__ import annotations

import json
from math import ceil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256, dumps_line, dumps_record, lf_sha256, write_lf
from .planes import PINNED_PACKAGE, PINNED_PACKAGE_VERSION
from .pointers import content_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_VERSION = "SYNTHETIC-CORPUS-v1"
SMALL = {"A": 2, "B": 2, "C": 2, "D": 2, "E": 2, "F": 2, "G": 2}
PAPER_TARGETS = {"A": 40, "B": 25, "C": 20, "D": 15, "E": 15, "F": 20, "G": 25}
SENTINEL = "sentinel orchid lantern 7f3a9c must never reach a log"
CREATED = "2026-11-24T00:00:00Z"
FIXTURES = REPO_ROOT / "evaluation" / "fixtures"
ITEMS_FIXTURE = FIXTURES / "synthetic_ulqs_v1.jsonl"
CATALOG_FIXTURE = FIXTURES / "synthetic_evidence_catalog_v1.jsonl"
RECORDED_FIXTURE = FIXTURES / "recorded_responses_synthetic_v1.jsonl"
CONTAMINATION_FIXTURE = FIXTURES / "contamination_synthetic_v1.json"
PACKAGE_PATH = PINNED_PACKAGE  # planes.PINNED_PACKAGE, the one place the pinned package is named
ARMS_PATH = "evaluation/config/arms_v1.json"
PLANS_PATH = "evaluation/config/analysis_plans_v1.json"
# An invented verifier-model id for the agent re-check in tests; the committed freeze rules pin no model (DI-142).
SYNTHETIC_AGENT_MODEL = "SYN-VERIFIER-1"


def pointer(page: int, entry: int) -> str:
    return f"EV-SYN-p{page:03d}-{entry:02d}"


def _negative() -> dict[str, Any]:
    return {"corpus_version": CORPUS_VERSION, "sections_searched": ["invented section index"], "queries": ["invented query"],
            "methods": ["lexical_bm25", "regex"], "verdict": "none_found", "verified_utc": CREATED,
            "limitations": "synthetic negative-evidence record"}


def synthetic_item(stratum: str, number: int, *, page: int, status: str = "candidate", human_reviewed: bool = False,
                   item_kind: str | None = "instructional", bloom: str = "understand", **overrides: Any) -> dict[str, Any]:
    item_id = f"SYN-{stratum}-{number:03d}"
    item: dict[str, Any] = {
        "item_id": item_id, "schema_version": "1.1", "dataset_version": "ULQS-v1.0", "corpus_version": CORPUS_VERSION,
        "status": status, "stratum": stratum, "corpus_scope": ["synthetic"], "topic": f"invented topic {stratum.lower()}",
        "concepts": [f"invented concept {number}"], "difficulty": "easy", "bloom": bloom, "retrieval_type": "single_span",
        "question": f"Invented harness question {number} of stratum {stratum} about the Quillfen archive?", "weight": 1.0,
        "leakage_risk": "low", "license_class": "synthetic",
        "quality_scores": {"retrieval_difficulty": 1, "grounding_difficulty": 1, "citation_difficulty": 1, "abstention_difficulty": 1,
                           "educational_value": 2},
        "provenance": {"created_utc": CREATED, "author": "RL"},
        "validation": {"citation_resolved": True, "evidence_verified": True, "duplicate_checked": True, "human_reviewed": human_reviewed},
        "item_kind": item_kind, "split": None,
    }

    def answer(record: dict[str, Any], owner: str, pointers: list[str]) -> None:
        record["evidence_ids"] = pointers
        record["atomic_claims"] = [{"claim_id": f"{owner}-c{index}", "text": f"Invented claim {index} of {owner.lower()}.",
                                    "evidence_ids": [ptr]} for index, ptr in enumerate(pointers, start=1)]
        record["gold_answer"] = f"Invented gold answer for {owner.lower()}."

    def abstain(record: dict[str, Any], owner: str) -> None:
        record["negative_evidence"] = _negative()
        record["abstention_rationale"] = f"Invented abstention rationale for {owner.lower()}."

    if stratum in ("A", "B"):
        item["expected_behavior"] = "answer"
        item["retrieval_type"] = "single_span" if stratum == "A" else "multi_span"
        answer(item, item_id, [pointer(page, 1)] if stratum == "A" else [pointer(page, 1), pointer(page, 2)])
    elif stratum in ("C", "E") or (stratum == "D" and number % 2 == 1):
        item["expected_behavior"] = "abstain"
        item["retrieval_type"] = "negative_evidence"
        abstain(item, item_id)
    elif stratum == "D":
        item["expected_behavior"] = "answer"
        answer(item, item_id, [pointer(page, 1)])
    elif stratum == "F":
        item["retrieval_type"] = "multi_turn"
        first = {"turn_id": f"{item_id}-t1", "user_utterance": "Invented opening turn.", "resolved_query": "Invented resolved query one.",
                 "expected_behavior": "answer"}
        answer(first, first["turn_id"], [pointer(page, 1)])
        second = {"turn_id": f"{item_id}-t2", "user_utterance": "Invented follow-up turn.", "resolved_query": "Invented resolved query two.",
                  "expected_behavior": "abstain"}
        abstain(second, second["turn_id"])
        item["conversation"] = [first, second]
    elif stratum == "G":
        answer(item, item_id, [pointer(page, 1)])
        del item["gold_answer"]
        item["base_question"] = f"Invented base question {number} about the Quillfen archive?"
        item["replays"] = [{"level": level, "gold_answer": f"Invented {level} answer.", "presentation_notes": f"Invented {level} notes."}
                           for level in ("beginner", "intermediate", "advanced")]
        item["invariance_checked"] = True
    item.update(overrides)
    return item


def synthetic_dataset(counts: Mapping[str, int] = SMALL, *, splits: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
    """The synthetic items at `counts`; with `splits`, each carries its `ulqs-split-v1` split (a set meant to freeze)."""
    from .ulqs import assign_splits

    items, page = [], 1
    for stratum in ("A", "B", "C", "D", "E", "F", "G"):
        for number in range(1, counts.get(stratum, 0) + 1):
            items.append(synthetic_item(stratum, number, page=page, **kwargs))
            page += 1
    if splits:
        assigned = assign_splits(items)
        for item in items:
            item["split"] = assigned[item["item_id"]]
    return items


def all_pointers(items: Sequence[Mapping[str, Any]]) -> list[str]:
    from .ulqs import pointers_of

    return sorted({ptr for item in items for _path, ptr in pointers_of(item)})


def evidence_text(ptr: str) -> str:
    return f"Synthetic evidence sentence {ptr.lower()} from the invented Quillfen archive."


def synthetic_catalog(items: Sequence[Mapping[str, Any]], *, with_text: bool = True) -> list[dict[str, Any]]:
    lines = []
    for ptr in all_pointers(items):
        text = evidence_text(ptr)
        page = int(ptr.split("-p")[1][:3])
        line = {"evidence_id": ptr, "document_id": f"syn-doc-{ptr.lower()}", "volume": "synthetic", "page": page, "char_start": 0,
                "char_end": len(text), "byte_length": len(text.encode("utf-8")), "content_sha256": content_sha256(text),
                "corpus_version": CORPUS_VERSION}
        if with_text:
            line["text"] = text
        lines.append(line)
    return lines


def corpus_text(items: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {f"syn-doc-{ptr.lower()}": evidence_text(ptr) for ptr in all_pointers(items)}


def rc1_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Synthetic items reshaped as rc1 records (schema 1.0, licensed class, EV-2026 pointers); every M5 field appears
    (the migrator's input in the tests)."""
    volume = "qcai" + "_2026"
    reshaped = []
    for index, item in enumerate(json.loads(json.dumps(items))):
        text = json.dumps(item).replace("SYN-", "ULQS-").replace("EV-ULQS-", "EV-2026-")
        rc1 = json.loads(text)
        for key in ("dataset_version", "item_kind", "split"):
            rc1.pop(key, None)
        rc1["validation"].pop("human_reviewed")
        rc1.update(schema_version="1.0", license_class="private_eval_full_span", corpus_version="QCAI-CORPUS-2030-01-01",
                   corpus_scope=[volume], status="candidate")
        rc1["provenance"] = {"created_utc": "2030-01-01T00:00:00Z", "author": SENTINEL,
                             "migrated_from": "invented-v0", "migration_disposition": "convert" if index % 2 else "revise",
                             "note": "invented note"}
        rc1["question"] = f"{rc1['question']} {SENTINEL}"
        if index == 0:
            rc1["reasoning_chain"] = ["invented step one", "invented step two"]
            rc1["notes"] = "invented notes"
        for block in [rc1] + rc1.get("conversation", []):
            if "negative_evidence" in block:
                block["negative_evidence"]["corpus_version"] = "QCAI-CORPUS-2030-01-01"
        reshaped.append(rc1)
    return reshaped


def write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> Path:
    write_lf(Path(path), "".join(dumps_line(record) for record in records))
    return Path(path)


def synthetic_ratings(items: Sequence[Mapping[str, Any]], *, rubric_sha256: str, share: str = "1/4", disagree: int = 0) -> list[dict]:
    """R1 labels every rated unit; R2 labels every unit of ceil(n_s * share) items per stratum; R2 disagrees on `disagree` units."""
    from fractions import Fraction

    from .ulqs import STRATA, rated_units

    ratings: list[dict] = []
    fraction = Fraction(share)
    disagreements = disagree
    for letter in STRATA:
        members = [item for item in items if item.get("stratum") == letter and item.get("status") != "retired"]
        doubled = {item["item_id"] for item in members[: ceil(len(members) * fraction)]}
        for item in members:
            for index, unit in enumerate(rated_units(item)):
                abstention = unit.endswith("-abstention")
                if abstention:
                    label = "supported_abstention" if index % 3 else "unsupported_abstention"
                else:
                    label = "supported" if (len(ratings) % 4) else "unsupported_but_true"
                base = {"item_id": item["item_id"], "unit_id": unit, "ehmf_type": None, "round": "main", "rubric_sha256": rubric_sha256}
                ratings.append({**base, "rater": "R1", "label": label})
                if item["item_id"] in doubled:
                    second = label
                    if disagreements > 0:
                        disagreements -= 1
                        second = ("unsupported_abstention" if label == "supported_abstention" else "supported_abstention") if abstention \
                            else ("fabricated" if label != "fabricated" else "supported")
                    ratings.append({**base, "rater": "R2", "label": second})
    return ratings


def record_ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": lf_sha256(path)}


def _write_record(path: Path, value: Mapping[str, Any]) -> dict[str, str]:
    write_lf(Path(path), dumps_record(value))
    return record_ref(Path(path))


def irb_record(path: Path, **overrides: Any) -> dict[str, str]:
    value = {"record": "irb-approval-v1", "protocol_number": "SYN-IRB-0001", "determination": "approved", "approval_date": "2026-11-01",
             "expiry_date": "2027-11-01", "letter_sha256": "0" * 64}
    value.update(overrides)
    return _write_record(path, value)


def osf_record(path: Path, *, analysis_plan_sha256: str, **overrides: Any) -> dict[str, str]:
    value = {"record": "osf-registration-v1", "doi": "10.17605/OSF.IO/SYN0001", "registered_date": "2026-11-02",
             "analysis_plan_sha256": analysis_plan_sha256}
    value.update(overrides)
    return _write_record(path, value)


def agent_check(items: Sequence[Mapping[str, Any]], **overrides: Any) -> dict[str, Any]:
    """An `ulqs-agent-check-v1` record for `items` (VBT RevB p. 15): the synthetic agent checked every live item, and its
    one disagreement was adjudicated by a rater who did not review that item. `checked_items` binds each live item's
    content as checked; no item changed unless `items_changed_after_flag` or `items_changed_without_flag` is
    overridden. The counts are invented."""
    from .ulqs import item_content_sha256

    value = {"record": "ulqs-agent-check-v1",
             "checked_items": {item["item_id"]: item_content_sha256(item) for item in items if item.get("status") != "retired"},
             "agent_model_id": SYNTHETIC_AGENT_MODEL, "model_chosen_before_check": True, "verdict_schema": "v2",
             "report_sha256": "a" * 64, "items_checked": sum(1 for item in items if item.get("status") != "retired"),
             "disagreements": 1, "disagreements_adjudicated": 1, "adjudicated_by_non_reviewer": True,
             "agent_detected_defects": 1, "agent_false_alarms": 0, "agent_missed_defects": 0, "items_changed_after_flag": [],
             "items_changed_without_flag": []}
    value.update(overrides)
    return value


def freeze_record(path: Path, *, dataset_sha256: str, passed: bool = True, **overrides: Any) -> dict[str, str]:
    value = {"record": "ulqs-freeze-record-v1", "dataset_sha256": dataset_sha256, "dataset_content_sha256": "0" * 64,
             "rules_sha256": "0" * 64, "agreement_sha256": "0" * 64, "agent_check_sha256": "0" * 64,
             "agent_report_sha256": "a" * 64, "agent_model_id": SYNTHETIC_AGENT_MODEL, "agent_detected_defects": 0, "agent_false_alarms": 0, "agent_missed_defects": 0,
             "disagreements_adjudicated": 0, "items_changed_after_flag": [], "items_changed_without_flag": [], "passed": passed,
             "failures": [] if passed else ["alpha_below_floor"]}
    value.update(overrides)
    return _write_record(path, value)


def provider_terms_record(path: Path, **overrides: Any) -> dict[str, str]:
    value = {"record": "provider-terms-v1", "provider_id": "SYN-PROVIDER-1", "recorded_date": "2026-11-01", "retention_recorded": True,
             "training_recorded": True, "publication_recorded": True, "terms_sha256": "0" * 64}
    value.update(overrides)
    return _write_record(path, value)


def licence_ruling_record(path: Path, **overrides: Any) -> dict[str, str]:
    value = {"record": "licence-ruling-v1", "determination": "permits", "ruling_date": "2026-11-01", "letter_sha256": "0" * 64}
    value.update(overrides)
    return _write_record(path, value)


def research_use_record(path: Path, **overrides: Any) -> dict[str, str]:
    value = {"record": "research-use-confirmation-v1", "confirmation": "confirmed", "confirmed_date": "2026-11-01",
             "letter_sha256": "0" * 64}
    value.update(overrides)
    return _write_record(path, value)


def decided_package(directory: Path, **changes: Any) -> dict[str, str]:
    """A copy of the pinned package (with its sha256 sidecar) in `directory` whose owner decisions D-07, D-08, D-12 and D-14
    read `decided` and whose semantic backend is on: the state a live or non-synthetic run needs, which no committed
    package has. The runner judges decisions only from a committed package (`governance.committed_package_sha256s`), so a
    test that needs this copy judged as decided also replaces that function (`commit_for_test`). For tests only; returns
    the spec's `package` block."""
    import json

    raw = json.loads((REPO_ROOT / PACKAGE_PATH).read_text(encoding="utf-8"))
    for name in ("D-07", "D-08", "D-12", "D-14"):
        raw.setdefault("owner_decisions", {}).setdefault(name, {})["state"] = "decided"
    raw.setdefault("semantic", {})["enabled_by_default"] = True
    raw.update(changes)
    path = Path(directory) / "package-decided.json"
    write_lf(path, dumps_record(raw))
    sha = canonical_sha256(raw)
    write_lf(path.with_name(path.name + ".sha256"), sha + "\n")
    return {"path": str(path), "sha256": sha, "package_version": raw.get("package_version")}


def commit_for_test(monkeypatch: Any, package: Mapping[str, Any]) -> None:
    """Make the runner judge `package` (a `decided_package` block) as a committed package, through pytest's `monkeypatch`.
    The only way to do so: no script or CLI path reaches it."""
    from . import governance

    committed = governance.committed_package_sha256s
    monkeypatch.setattr(governance, "committed_package_sha256s", lambda: committed() | {package["sha256"]})


def pass_scan(path: Path, *, dataset_content_sha256: str, corpus_version: str = CORPUS_VERSION, **overrides: Any) -> dict[str, str]:
    """A pre-run scan report shaped like one that passes the gate (governance.scan_refusals): a licensed and a ULQS set
    with research ids and non-empty sizes, the ULQS set bound to the items and the licensed set to the items and their
    corpus version, a repository and a research-logs target that each scanned a file. Its counts are invented; tests
    pass `overrides` to break one condition at a time."""
    value = {"report": "qcai-research-log-scan", "format_version": 1,
             "fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": dataset_content_sha256,
                                   "corpus_version": corpus_version, "shingle_words": 12, "fingerprints": 40, "exact": 0},
                                  {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": dataset_content_sha256,
                                   "corpus_version": None, "shingle_words": 6, "fingerprints": 30, "exact": 5}],
             "targets": [{"target": "repository", "root": ".", "files": 3, "scanned": 2, "excluded": [], "files_with_hits": []},
                         {"target": "research-logs", "root": "prior-run", "files": 4, "scanned": 3, "excluded": [],
                          "files_with_hits": []}],
             "matches_total": 0, "incomplete_targets": [], "result": "pass"}
    value.update(overrides)
    return _write_record(path, value)


def _json_sha(path: Path) -> str:
    import json

    return canonical_sha256(json.loads(Path(path).read_text(encoding="utf-8")))


def spec_dict(*, items_path: Path | str, catalog_path: Path | str | None, run_id: str = "synthetic-stub-v1", mode: str = "stub",
              purpose: str = "exploratory", experiment: str = "harness-check", repo_root: Path = REPO_ROOT,
              replicates: Mapping[str, Any] | None = None, responder: Mapping[str, Any] | None = None,
              arms_path: str | Path = ARMS_PATH, selected: Sequence[str] | None = None, family: str = "E1",
              **extra: Any) -> dict[str, Any]:
    from .canonical import read_jsonl
    from .pointers import EvidenceCatalog
    from .ulqs import dataset_sha256

    def absolute(value: str | Path) -> Path:
        value = Path(value)
        return value if value.is_absolute() else Path(repo_root) / value

    items = read_jsonl(absolute(items_path))
    spec: dict[str, Any] = {
        "run_spec": "ulqs-run-spec-v1", "run_id": run_id, "mode": mode, "purpose": purpose, "experiment": experiment,
        "created_at": CREATED,
        "package": {"path": PACKAGE_PATH, "sha256": _json_sha(absolute(PACKAGE_PATH)), "package_version": PINNED_PACKAGE_VERSION},
        "items": {"path": Path(items_path).as_posix(), "sha256": dataset_sha256(items), "count": len(items), "required_state": "any"},
        "evidence_catalog": None if catalog_path is None else {
            "path": Path(catalog_path).as_posix(), "sha256": EvidenceCatalog.load(absolute(catalog_path)).sha256},
        "arms": {"path": Path(arms_path).as_posix(), "sha256": _json_sha(absolute(arms_path)),
                 "selected": list(selected) if selected else ["NR", "LEX", "SEM", "GATE", "GATE+SV", "GATE+V1", "VLOOP"]},
        "analysis_plan": {"path": PLANS_PATH, "sha256": _json_sha(absolute(PLANS_PATH)), "family": family},
        "seeds": {"rule": "sha256-run-arm-item-replicate-v1"},
        "replicates": dict(replicates) if replicates is not None else {
            "default": 1, "subsample": {"stratum": "A", "size": 2, "replicates": 3, "rule": "sha256-order-v1"}},
        "responder": dict(responder) if responder is not None else {"rule": "stub-responder-v1"},
        "labels": None,
        "bootstrap": {"resamples": 1000, "rule": "hash-resample-v1", "level": "0.95"},
        "retries": 3,
        "governance": {"irb_record": None, "osf_record": None},
        "freeze_record": None, "pre_run_scan": None, "provider_terms": None, "licence_ruling": None, "research_use_confirmation": None,
    }
    spec.update(extra)
    return spec


def write_spec(path: Path, **kwargs: Any) -> Path:
    write_lf(Path(path), dumps_record(spec_dict(**kwargs)))
    return Path(path)


def write_fixture_set(directory: Path, counts: Mapping[str, int] = SMALL, **kwargs: Any) -> tuple[Path, Path, list[dict]]:
    """Items and their catalog written to `directory` (a test's tmp_path)."""
    items = synthetic_dataset(counts, **kwargs)
    items_path = write_jsonl(Path(directory) / "items.jsonl", items)
    catalog_path = write_jsonl(Path(directory) / "catalog.jsonl", synthetic_catalog(items))
    return items_path, catalog_path, items
