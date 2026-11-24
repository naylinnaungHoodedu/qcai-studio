"""Synthetic builders for tests, fixtures and CI (spec 3.15, 7.1). Every text is invented; `license_class` is synthetic.

Nothing here derives from a ULQS item, a licensed volume or a course document. The committed fixtures
(`evaluation/fixtures/synthetic_ulqs_v1.jsonl`, `synthetic_evidence_catalog_v1.jsonl`) are `synthetic_dataset(SMALL)` and
its catalog; tests build larger sets (the 160-item AC-10-1 set) in their own temporary directory.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256, dumps_line, dumps_record, lf_sha256, write_lf
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
PACKAGE_PATH = "apps/api/app/config_package/v7.json"
ARMS_PATH = "evaluation/config/arms_v1.json"
PLANS_PATH = "evaluation/config/analysis_plans_v1.json"


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


def synthetic_dataset(counts: Mapping[str, int] = SMALL, **kwargs: Any) -> list[dict[str, Any]]:
    items, page = [], 1
    for stratum in ("A", "B", "C", "D", "E", "F", "G"):
        for number in range(1, counts.get(stratum, 0) + 1):
            items.append(synthetic_item(stratum, number, page=page, **kwargs))
            page += 1
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


def freeze_record(path: Path, *, dataset_sha256: str, passed: bool = True, **overrides: Any) -> dict[str, str]:
    value = {"record": "ulqs-freeze-record-v1", "dataset_sha256": dataset_sha256, "dataset_content_sha256": "0" * 64,
             "rules_sha256": "0" * 64, "agreement_sha256": "0" * 64, "passed": passed, "failures": [] if passed else ["alpha_below_floor"]}
    value.update(overrides)
    return _write_record(path, value)


def pass_scan(path: Path) -> dict[str, str]:
    return _write_record(path, {"report": "qcai-research-log-scan", "format_version": 1, "fingerprint_sets": [], "targets": [],
                                "matches_total": 0, "result": "pass"})


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
        "package": {"path": PACKAGE_PATH, "sha256": _json_sha(absolute(PACKAGE_PATH)), "package_version": "7.0.0"},
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
