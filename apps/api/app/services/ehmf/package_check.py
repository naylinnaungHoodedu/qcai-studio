"""The start-up and CI check of package v6's ehmf block (Phase 7 spec 4.13).

check_ehmf_package(structural=False) runs at start-up (main._check_ehmf_package): the routing table and its sha256
against the code, the weights against the plan, the correction bound, the stop and penalty structure and the library
file's hash. It never reads docs/ or apps/api/tests/ (the image holds neither). structural=True (tests and
scripts/config_package.py --check) also checks the golden-set file's sha256 and item count, that the routing document
exists, and the library rules with the development store.
"""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
from typing import Any

from app.services.ehmf.vocabulary import EHMF_TYPES, PLAN_WEIGHTS


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def check_ehmf_package(package: Any, *, structural: bool = False, store: Any = None) -> list[str]:
    from app.core.config_package import canonical_sha256
    from app.services.ehmf.library import read_library_file
    from app.services.ehmf.routing import routing_sha256, routing_table

    ehmf = package.ehmf
    if ehmf is None:
        return []
    problems: list[str] = []
    if dict(ehmf.routing_table) != routing_table() or ehmf.routing_sha256 != routing_sha256():
        problems.append("ehmf.routing differs from the code's routing table ehmf-routing-v1")
    decisions = package.owner_decisions
    if (decisions.get("EHMF-WEIGHTS") or {}).get("state") == "open":
        if any(ehmf.weights[key] != Fraction(PLAN_WEIGHTS[key]) for key in EHMF_TYPES) or ehmf.weights["D_disclosed"] != 0:
            problems.append("ehmf.weights differ from the plan's 6.3 weights while EHMF-WEIGHTS is open (PD-41)")
    if ehmf.max_cycles != 2:
        problems.append("the correction bound is two cycles (plan Phase 7 D task 4)")
    if ehmf.stop_min_claims > ehmf.stop_window_claims or ehmf.stop_rise <= 1:
        problems.append("ehmf.stop windows or rise are malformed")
    if set(ehmf.penalty_registries) != {"default", "development", "production", "staging"}:
        problems.append("ehmf.retrieval_penalty names development, staging, production and default")
    raw_pin = ((package.raw.get("v1") or {}).get("v1_8") or {}).get("library") or {}
    library_path = Path(package.path).resolve().parent / str(raw_pin.get("path", ""))
    if not library_path.parent.is_dir():
        library_path = Path(__file__).resolve().parents[2] / "config_package" / str(raw_pin.get("path", ""))
    shipped = library_path.resolve().parent == (Path(__file__).resolve().parents[2] / "config_package" / "misconceptions").resolve()
    _library, library_faults = read_library_file(library_path, expected_sha256=str(raw_pin.get("sha256", "")), shipped=shipped)
    problems.extend(library_faults)
    if not structural:
        return problems
    root = _repository_root()
    golden_path = root / ehmf.golden_set_path
    try:
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"the golden set at {ehmf.golden_set_path} could not be read: {exc}")
    else:
        if canonical_sha256(golden) != ehmf.golden_set_sha256:
            problems.append("ehmf.golden_set.sha256 differs from the golden set file's canonical sha256 (rerun the golden set)")
        if len(golden.get("items", ())) != ehmf.golden_set_items:
            problems.append("ehmf.golden_set.items differs from the golden set file's item count")
    doc = (package.raw.get("ehmf") or {}).get("routing", {}).get("doc", "")
    if not (root / doc).is_file():
        problems.append(f"the routing document {doc} is missing (plan Phase 7 F \"Routing spec\")")
    if store is None:
        try:
            from app.services.store import get_course_store

            store = get_course_store()
        except Exception:  # noqa: BLE001 - without a store the span rules cannot run; the structural rules above did
            store = None
    if store is not None and _library is not None:
        from app.services.ehmf.library import library_problems

        problems.extend(library_problems(_library.raw, store=store, shipped=shipped,
                                         max_chars=ehmf.library_paraphrase_max_chars,
                                         max_shared_words=ehmf.library_paraphrase_max_shared_words))
    return problems
