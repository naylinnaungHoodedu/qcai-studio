"""The E2, E3 and E4 designs and their registered families (plan task 5 "E1-E4 per Section 15"; VBT RevB Sec. VIII-D,
X-A, Table I; spec 4.14).

Each design plans its requests from the run spec's `design` block, runs them through the runner's responder seam as E1
does (stub, recorded; live refused), and computes its registered family with Holm from the responses. Nothing here
pins a model: the verifier panel, both E3 designs' generator and E4's four models and prices are the spec's (D-07 pins
them for a real run; until then only synthetic, stub or recorded runs exist, and E1-E4 runs stay confirmatory only).

- **E2** (verifier reliability; H2a-c). The verification set is every labelled claim of a pinned E1 responses file
  (generator family named) and, optionally, of a pinned E4 responses file (the generator of each line is its model,
  whose family the verifier list gives). Each verifier verifies every claim generated outside its own family (`verify`
  requests); the panel is the three verifiers outside the E1 generator's family, formed afterwards by rule (1oo3, 2oo3,
  3oo3 and a two-coin Dawid-Skene posterior) on identical claims. H2a: claim-level F1 of 2oo3 minus the best single
  member's, a one-sided cluster BCa bootstrap over items; H2b: DR = P_all / (m1 m2 m3) on erroneous claims, the
  one-sided cluster percentile lower bound against 1; H2c: the paired AUC bootstrap of the panel against Group B novice
  trust ratings, computed only from a pinned ratings file (none exists before IRB approval, D-08).
- **E3** (adaptation invariance; H3a-b). Every live S7 (stratum G) item at the three levels under two designs: two-pass
  (one `two-pass-evidential` request, then a `two-pass` presentation request per level) and single-pass (`single-pass`
  per level), plus single-pass repeated at one fixed level. v_q = 1 when the claim set or the cited span set differs
  across the levels (eq. 18). H3a: exact McNemar of v_q two-pass vs single-pass, paired by item; H3b: Friedman's test of
  a presentation feature across the levels under two-pass.
- **E4** (model comparison and ranking replay; H4a-b). All four models answer every unit in GATE and VLOOP. The replay
  resamples items, then draws seeded streams from them (`statistics.two_level_bootstrap_share_le_zero`, one replicate
  per stream), with one model's first-pass error rate in one topic raised by resampling its own failed responses from a
  request on, and replays eight routing policies: the Phase 9 controller with and without hysteresis, static-best,
  round-robin, cheapest-eligible, epsilon-greedy, a LinUCB-style bandit and threshold escalation. H4a: the share of
  streams in which the controller's verified quality per price unit is at most the larger of static-best's and
  round-robin's; H4b: exact McNemar of the local model's and the pilot-selected commercial model's item-level error on
  answerable items in GATE, and the paired TOST of their expert EQC ratings from a pinned ratings file (reported
  inconclusive: ICC(2,k) and Cronbach's alpha are not implemented, DI-138).

The engineering parameters no plan text fixes are provisional (PD-75; `evaluation/config/harness_parameters_v1.json`
`designs`). Outcomes are reported by the PI, never asserted by the harness (invariant 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from math import sqrt
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from . import statistics, ulqs
from .canonical import canonical_sha256, hashed_hex, lf_sha256, read_jsonl

PROVISIONAL_DEFAULTS = ("PD-75",)
DESIGN_EXPERIMENTS = ("E2", "E3", "E4")
ERROR_LABELS = frozenset({"fabricated", "attribution_error"})
ROLES = ("answer", "verify", "two-pass-evidential", "two-pass", "single-pass")
VERDICTS = ("pass", "object")
FEATURES = ("fk_grade", "guiding_questions", "prerequisite_recaps", "length")
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.+:-]{0,63}$")
POLICIES = ("controller", "controller-no-hysteresis", "static-best", "round-robin", "cheapest-eligible", "epsilon-greedy", "linucb",
            "threshold-escalation")
# The hypotheses each design computes, with the registered test each must carry (the planner refuses any other family).
COMPUTED = {
    "E1": {"H1a": "mcnemar_exact", "H1b": "mcnemar_exact", "H1c": "paired_bootstrap_one_sided"},
    "E2": {"H2a": "cluster_bootstrap_bca_one_sided", "H2b": "cluster_bootstrap_lower_bound", "H2c": "paired_bootstrap_auc_one_sided"},
    "E3": {"H3a": "mcnemar_exact", "H3b": "friedman"},
    "E4": {"H4a": "two_level_bootstrap_share_le_zero", "H4b": "mcnemar_exact+paired_tost"},
}


class DesignRefused(Exception):
    def __init__(self, code: int, reasons: Sequence[str]) -> None:
        super().__init__(", ".join(reasons))
        self.code = code
        self.reasons = list(reasons)


@dataclass(frozen=True)
class Claim:
    """One verification-set claim: its source response, the claim, its gold label and its generator's family."""

    key: str
    source_request_key: str
    arm: str
    item_id: str
    unit: str | None
    claim_id: str
    label: str
    family: str
    source: str
    cited: tuple[str, ...]


# ------------------------------------------------------------------------------------------------------------ planning


def family_refusals(experiment: str, family: Mapping[str, Any], selected: Sequence[str]) -> list[str]:
    """`analysis_plan_invalid:<experiment>` unless every hypothesis of the experiment's family is one the design computes,
    under the registered test it computes, and (E1) compares two of the selected arms; checked before anything runs, so a
    plans file that validates but registers another test never ends a completed run in a traceback."""
    expected = COMPUTED.get(experiment, {})
    hypotheses = family.get("hypotheses") if isinstance(family, Mapping) else None
    if not isinstance(hypotheses, list) or not hypotheses:
        return [f"analysis_plan_invalid:{experiment}"]
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping) or expected.get(hypothesis.get("id")) != hypothesis.get("test"):
            return [f"analysis_plan_invalid:{experiment}"]
        if experiment == "E1":
            comparison = hypothesis.get("comparison")
            if (not isinstance(comparison, list) or len(comparison) != 2 or len(set(comparison)) != 2
                    or any(arm not in selected for arm in comparison)):
                return [f"analysis_plan_invalid:{experiment}"]
    return []


def _ref(value: Any) -> bool:
    return isinstance(value, Mapping) and isinstance(value.get("path"), str) and bool(value["path"]) and isinstance(value.get("sha256"), str)


def _positive_int(value: Any, low: int = 1) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _decimal(value: Any, *, positive: bool = False, unit: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    try:
        number = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return False
    return (not positive or number > 0) and (not unit or 0 < number < 1)


def _later_price_ok(value: Any) -> bool:
    """A model's optional later list price: {"from": "YYYY-MM-DD", "price_per_unit": a positive decimal} (VBT RevB Sec.
    VIII-D: "at both Gemini prices if runs straddle 1 January 2027")."""
    if value is None:
        return True
    if not isinstance(value, Mapping) or set(value) != {"from", "price_per_unit"} or not _decimal(value.get("price_per_unit"), positive=True):
        return False
    try:
        import datetime

        datetime.date.fromisoformat(value["from"])
    except (TypeError, ValueError):
        return False
    return isinstance(value["from"], str) and len(value["from"]) == 10


def shape_refusals(experiment: str, design: Any) -> list[str]:
    """The `design` block's shape (exit 2, the field named): every nested value the planner reads."""
    if not isinstance(design, Mapping):
        return ["design"]
    reasons = []
    if "resamples" in design and not _positive_int(design["resamples"]):
        reasons.append("design.resamples")
    if design.get("ratings") is not None and not _ref(design["ratings"]):
        reasons.append("design.ratings")
    if experiment == "E2":
        if not _ref(design.get("verification_set")) or not isinstance(design["verification_set"].get("generator_family"), str):
            reasons.append("design.verification_set")
        if design.get("e4_responses") is not None and not _ref(design["e4_responses"]):
            reasons.append("design.e4_responses")
        verifiers = design.get("verifiers")
        if (not isinstance(verifiers, list) or not all(isinstance(entry, Mapping) and isinstance(entry.get("model_id"), str)
                                                        and MODEL_ID.match(entry["model_id"]) and isinstance(entry.get("family"), str)
                                                        and entry["family"] for entry in verifiers)):
            reasons.append("design.verifiers")
    elif experiment == "E3":
        if "fixed_level" in design and design["fixed_level"] not in ulqs.REPLAY_LEVELS:
            reasons.append("design.fixed_level")
        if "repeats" in design and not _positive_int(design["repeats"], 2):
            reasons.append("design.repeats")
    elif experiment == "E4":
        models = design.get("models")
        if (not isinstance(models, list) or not all(
                isinstance(entry, Mapping) and isinstance(entry.get("model_id"), str) and MODEL_ID.match(entry["model_id"])
                and isinstance(entry.get("family"), str) and entry["family"] and _decimal(entry.get("price_per_unit"), positive=True)
                and isinstance(entry.get("local"), bool) and _later_price_ok(entry.get("later_price")) for entry in models)):
            reasons.append("design.models")
        if not isinstance(design.get("pilot_commercial"), str):
            reasons.append("design.pilot_commercial")
        for key in ("streams", "stream_length"):
            if key in design and not _positive_int(design[key]):
                reasons.append(f"design.{key}")
        shift = design.get("shift")
        if (not isinstance(shift, Mapping) or not isinstance(shift.get("model"), str) or not isinstance(shift.get("topic"), str)
                or ("at" in shift and not _positive_int(shift["at"], 0)) or ("points" in shift and not _decimal(shift["points"], unit=True))):
            reasons.append("design.shift")
    return reasons


def effective_design(experiment: str, design: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The design block with the provisional defaults (`harness_parameters_v1.json` `designs`, PD-75) filled in."""
    defaults = (parameters.get("designs") or {}).get(experiment) or {}
    effective = json.loads(json.dumps(design))
    if experiment == "E3":
        for key in ("arm", "fixed_level", "repeats", "h3b_feature"):
            effective.setdefault(key, defaults[key])
    elif experiment == "E4":
        for key in ("streams", "stream_length", "epsilon", "linucb_alpha"):
            effective.setdefault(key, defaults[key])
        effective["shift"] = {"at": defaults["shift_at"], "points": defaults["shift_points"], **effective["shift"]}
    elif experiment == "E2":
        effective.setdefault("dawid_skene_iterations", defaults["dawid_skene_iterations"])
    return effective


def _read_lines(reference: Mapping[str, Any], repo_root: Path, kind: str, note: Callable[[str, str | None], None]) -> list[dict]:
    path = Path(reference["path"])
    path = path if path.is_absolute() else Path(repo_root) / path
    try:
        sha = lf_sha256(path)
    except (OSError, ValueError):
        note(kind, None)
        raise DesignRefused(3, [f"{kind}_unreadable"]) from None
    note(kind, sha)
    if sha != reference.get("sha256"):
        raise DesignRefused(6, [f"{kind}_sha256"])
    try:
        lines = read_jsonl(path)
    except (OSError, ValueError):
        raise DesignRefused(3, [f"{kind}_unreadable"]) from None
    if not all(isinstance(line, Mapping) for line in lines):
        raise DesignRefused(3, [f"{kind}_invalid"])
    return lines


def _claims_of(lines: Sequence[Mapping[str, Any]], *, live: set[str], family_of: Callable[[Mapping[str, Any]], str | None], source: str,
               kind: str) -> list[Claim]:
    claims = []
    for line in lines:
        if line.get("item_id") not in live or not isinstance(line.get("request_key"), str):
            raise DesignRefused(3, [f"{kind}_items"])
        if line.get("replicate") != 1 or line.get("outcome") != "answered":
            continue
        family = family_of(line)
        if family is None:
            raise DesignRefused(3, [f"{kind}_generator_unknown"])
        for claim in line.get("claims") or []:
            if not isinstance(claim, Mapping) or claim.get("label") is None:
                continue  # only labelled claims enter the verification set
            key = canonical_sha256({"source": source, "request_key": line["request_key"], "claim_id": claim.get("claim_id")})
            claims.append(Claim(key=key, source_request_key=line["request_key"], arm=str(line.get("arm")), item_id=line["item_id"],
                                unit=line.get("unit"), claim_id=str(claim.get("claim_id")), label=str(claim["label"]), family=family,
                                source=source, cited=tuple(sorted(str(pointer) for pointer in claim.get("cited") or []))))
    return claims


def load_design(experiment: str, spec: Mapping[str, Any], items: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
                repo_root: Path, note: Callable[[str, str | None], None]) -> dict[str, Any]:
    """The checked, effective design and the inputs it reads (the verification sets and the ratings, each logged as read),
    or DesignRefused (exit 2 a design that cannot run, 3 an unreadable or foreign input, 6 a sha256 mismatch)."""
    design = effective_design(experiment, spec["design"], parameters)
    live = {item["item_id"] for item in items if item.get("status") != "retired"}
    loaded: dict[str, Any] = {"design": design, "claims": [], "ratings": None}
    if experiment == "E2":
        verifiers = design["verifiers"]
        ids = [entry["model_id"] for entry in verifiers]
        generator = design["verification_set"]["generator_family"]
        panel = [entry for entry in verifiers if entry["family"] != generator]
        if (len(set(ids)) != len(ids) or len(panel) != 3 or len({entry["family"] for entry in panel}) != 3):
            raise DesignRefused(2, ["e2_panel_invalid"])  # a blind three-family panel without the generator's family
        lines = _read_lines(design["verification_set"], repo_root, "verification_set", note)
        claims = _claims_of(lines, live=live, family_of=lambda line: generator, source="E1", kind="verification_set")
        if design.get("e4_responses") is not None:
            families = {entry["model_id"]: entry["family"] for entry in verifiers}
            e4_lines = _read_lines(design["e4_responses"], repo_root, "e4_responses", note)
            claims += _claims_of(e4_lines, live=live, family_of=lambda line: families.get(line.get("cell")), source="E4",
                                 kind="e4_responses")
        if not claims:
            raise DesignRefused(2, ["verification_set_empty"])
        loaded["claims"] = sorted(claims, key=lambda claim: (claim.source, claim.item_id, claim.unit or "", claim.arm, claim.claim_id,
                                                             claim.source_request_key))
        loaded["panel"] = sorted(entry["model_id"] for entry in panel)
    elif experiment == "E3":
        if not any(item.get("stratum") == "G" and item["item_id"] in live for item in items):
            raise DesignRefused(2, ["e3_no_s7_items"])
    elif experiment == "E4":
        models = design["models"]
        ids = [entry["model_id"] for entry in models]
        locals_ = [entry for entry in models if entry["local"]]
        pilot = {entry["model_id"]: entry for entry in models}.get(design["pilot_commercial"])
        if len(models) != 4 or len(set(ids)) != 4 or len(locals_) != 1 or pilot is None or pilot["local"]:
            raise DesignRefused(2, ["e4_models_invalid"])  # four models, one local, the pilot-selected commercial one named
        topics = {item.get("topic") for item in items if item["item_id"] in live}
        if design["shift"]["model"] not in ids or design["shift"]["topic"] not in topics:
            raise DesignRefused(2, ["e4_shift_invalid"])
    if design.get("ratings") is not None:
        rows = _read_lines(design["ratings"], repo_root, "ratings", note)
        kind = {"E2": "novice-trust", "E4": "eqc"}.get(experiment)
        if kind is None or not all(row.get("rating") == kind and isinstance(row.get("source_request_key"), str)
                                   and isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool)
                                   and set(row) == {"rating", "source_request_key", "value"} for row in rows):
            raise DesignRefused(3, ["ratings_invalid"])
        loaded["ratings"] = rows
    return loaded


def design_pins(experiment: str, loaded: Mapping[str, Any]) -> dict[str, Any]:
    design = loaded["design"]
    pins: dict[str, Any] = {"experiment": experiment}
    if experiment == "E2":
        pins.update(verification_set={"sha256": design["verification_set"]["sha256"], "generator_family": design["verification_set"]["generator_family"]},
                    e4_responses=None if design.get("e4_responses") is None else {"sha256": design["e4_responses"]["sha256"]},
                    verifiers=[{"model_id": entry["model_id"], "family": entry["family"]} for entry in design["verifiers"]],
                    panel=loaded["panel"], claims=len(loaded["claims"]), dawid_skene_iterations=design["dawid_skene_iterations"])
    elif experiment == "E3":
        pins.update({key: design[key] for key in ("arm", "fixed_level", "repeats", "h3b_feature")})
    elif experiment == "E4":
        pins.update(models=[dict(entry) for entry in design["models"]], pilot_commercial=design["pilot_commercial"],
                    streams=design["streams"], stream_length=design["stream_length"], shift=dict(design["shift"]),
                    epsilon=design["epsilon"], linucb_alpha=design["linucb_alpha"], policies=list(POLICIES))
    pins["resamples"] = design.get("resamples")
    pins["ratings"] = None if design.get("ratings") is None else {"sha256": design["ratings"]["sha256"]}
    return pins


def design_request_key(*, role: str, arm_config_sha256: str, item_id: str, unit: str | None, replicate: int, package_sha256: str,
                       prompt_version: str, evidence: Sequence[str], cell: str | None, subject: str | None = None) -> str:
    """A design request's key: E1's composition plus its role, its cell (the verifier or the model) and, for a
    verification, the claim it verifies; no run id."""
    return canonical_sha256({"arm_config": arm_config_sha256, "item_id": item_id, "unit": unit, "replicate": replicate,
                             "package": package_sha256, "prompt_version": prompt_version, "evidence": sorted(evidence), "role": role,
                             "cell": cell, "subject": subject})


def design_seed(run_id: str, arm: str, item_id: str, replicate: int, role: str, cell: str | None, subject: str | None) -> str:
    """The seed rule's design form: sha256(run_id, arm, item_id, replicate, role, cell, unit or claim), first 16 hex."""
    return hashed_hex(run_id, arm, item_id, str(replicate), role, cell or "-", subject or "-")[:16]


# ------------------------------------------------------------------------------------------------------------ metrics helpers


def _done(response: Mapping[str, Any]) -> bool:
    return response.get("outcome") != "provider_failure"


def _has_error(response: Mapping[str, Any]) -> bool:
    return any(isinstance(claim, Mapping) and claim.get("label") in ERROR_LABELS for claim in response.get("claims") or [])


def answerable_item_errors(pairs: Sequence[tuple[Any, Mapping[str, Any]]], select: Callable[[Any], bool]) -> dict[str, int]:
    """H1a's endpoint (VBT RevB Table I: "Share of answerable items whose response contains at least one fabricated or
    attribution-error claim (an abstention scores as no error ...)"), per item: over the item's answerable units (gold
    `answer`) of the selected requests, replicate 1, provider failures excluded, 1 when any has a Fabricated or
    Attribution-error claim; items with no such unit are absent."""
    errors: dict[str, int] = {}
    for request, response in pairs:
        if not select(request) or request.replicate != 1 or request.gold != "answer" or not _done(response):
            continue
        errors[request.item_id] = max(errors.get(request.item_id, 0), int(_has_error(response)))
    return errors


def paired_by_item(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, Any]:
    items = sorted(set(left) & set(right))
    return {**statistics.mcnemar_exact([bool(left[item]) for item in items], [bool(right[item]) for item in items]), "items": len(items)}


def _holm(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    tested = {name: value["p_value"] for name, value in results.items() if isinstance(value.get("p_value"), (int, float))
              and value.get("enters_holm", True)}
    return statistics.holm(tested) if tested else {}


def _labels_pending(pairs: Sequence[tuple[Any, Mapping[str, Any]]]) -> bool:
    return any(isinstance(claim, Mapping) and claim.get("label") is None
               for _request, response in pairs if _done(response) for claim in response.get("claims") or [])


def _resamples(plan: Any, hypothesis: Mapping[str, Any]) -> int:
    design = plan.extra["design"]["design"]
    if design.get("resamples") is not None:
        return int(design["resamples"])
    return int(hypothesis.get("resamples") or (plan.spec.get("bootstrap") or {}).get("resamples", 1000))


def _hypotheses(plan: Any) -> dict[str, Mapping[str, Any]]:
    family = plan.extra["analysis_plans"]["families"][plan.spec["experiment"]]
    return {hypothesis["id"]: hypothesis for hypothesis in family["hypotheses"]}


def _seed(plan: Any, name: str) -> str:
    return hashed_hex(plan.spec["run_id"], "registered", name)


def _f1(rows: Sequence[tuple[bool, bool]]) -> float:
    tp = sum(1 for gold, flagged in rows if gold and flagged)
    fp = sum(1 for gold, flagged in rows if not gold and flagged)
    fn = sum(1 for gold, flagged in rows if gold and not flagged)
    return 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)


def _classification(rows: Sequence[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for gold, flagged in rows if gold and flagged)
    fp = sum(1 for gold, flagged in rows if not gold and flagged)
    fn = sum(1 for gold, flagged in rows if gold and not flagged)
    return {"claims": len(rows), "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": None if tp + fp == 0 else tp / (tp + fp), "recall": None if tp + fn == 0 else tp / (tp + fn), "F1": _f1(rows)}


# ------------------------------------------------------------------------------------------------------------ E2


def _vote(flags: Sequence[bool], needed: int) -> bool:
    return sum(flags) >= needed


def dawid_skene(rows: Sequence[Sequence[bool]], iterations: int) -> list[float]:
    """The two-coin Dawid-Skene posterior P(erroneous | verdicts) per claim (each verifier a sensitivity and a
    specificity, one prevalence), from the 2oo3 vote, `iterations` EM steps, clipped to (1e-6, 1 - 1e-6)."""
    if not rows:
        return []
    k = len(rows[0])
    posterior = [1.0 if _vote(row, 2) else 0.0 for row in rows]
    clip = lambda value: min(max(value, 1e-6), 1 - 1e-6)  # noqa: E731
    for _step in range(iterations):
        mass = sum(posterior)
        prevalence = clip(mass / len(rows))
        sensitivity = [clip(sum(p for p, row in zip(posterior, rows) if row[j]) / mass) if mass else 0.5 for j in range(k)]
        negatives = len(rows) - mass
        specificity = [clip(sum(1 - p for p, row in zip(posterior, rows) if not row[j]) / negatives) if negatives else 0.5
                       for j in range(k)]
        updated = []
        for row in rows:
            positive, negative = prevalence, 1 - prevalence
            for j, flag in enumerate(row):
                positive *= sensitivity[j] if flag else 1 - sensitivity[j]
                negative *= (1 - specificity[j]) if flag else specificity[j]
            updated.append(positive / (positive + negative))
        posterior = updated
    return posterior


def _dr(clusters: Sequence[Sequence[tuple[bool, tuple[bool, ...]]]]) -> float:
    """DR = P_all / (m1 m2 m3) over the erroneous claims of the clusters; -inf when undefined (no erroneous claim or a
    member that never misses), which a one-sided bootstrap counts at or below the margin (conservative)."""
    misses = [tuple(not flag for flag in flags) for cluster in clusters for gold, flags in cluster if gold]
    if not misses:
        return float("-inf")
    k = len(misses[0])
    rates = [sum(row[j] for row in misses) / len(misses) for j in range(k)]
    product = 1.0
    for rate in rates:
        product *= rate
    if product == 0:
        return float("-inf")
    return (sum(1 for row in misses if all(row)) / len(misses)) / product


def compute_e2(plan: Any, responses: Sequence[Mapping[str, Any]]) -> tuple[dict, dict]:
    loaded = plan.extra["design"]
    claims = {claim.key: claim for claim in loaded["claims"]}
    panel = loaded["panel"]
    verdicts: dict[str, dict[str, bool]] = {}
    invalid = failures = 0
    for request, response in zip(plan.requests, responses):
        if request.replicate != 1:
            continue
        if not _done(response):
            failures += 1
            continue
        if response.get("verdict") not in VERDICTS:
            invalid += 1
            continue
        verdicts.setdefault(request.subject, {})[request.cell] = response["verdict"] == "object"
    metrics: dict[str, Any] = {"verification_set": {"claims": len(claims), "erroneous": sum(c.label in ERROR_LABELS for c in claims.values()),
                                                    "by_source": {source: sum(c.source == source for c in claims.values()) for source in ("E1", "E4")}},
                               "provider_failures_excluded": failures, "invalid_verdicts_excluded": invalid, "verifiers": {}}
    for verifier in sorted({request.cell for request in plan.requests}):
        rows = [(claims[key].label in ERROR_LABELS, flags[verifier]) for key, flags in sorted(verdicts.items()) if verifier in flags]
        metrics["verifiers"][verifier] = _classification(rows)
    complete = [(claims[key], tuple(flags[member] for member in panel)) for key, flags in sorted(verdicts.items())
                if claims[key].source == "E1" and all(member in flags for member in panel)]
    gold = [claim.label in ERROR_LABELS for claim, _flags in complete]
    rules = {f"{needed}oo3": [_vote(flags, needed) for _claim, flags in complete] for needed in (1, 2, 3)}
    posterior = dawid_skene([flags for _claim, flags in complete], int(loaded["design"]["dawid_skene_iterations"]))
    rules["dawid-skene"] = [value > 0.5 for value in posterior]
    metrics["panel"] = {"members": panel, "claims": len(complete),
                        "rules": {name: _classification(list(zip(gold, flagged))) for name, flagged in rules.items()}}
    erroneous = [flags for (claim, flags) in complete if claim.label in ERROR_LABELS]
    if erroneous:
        m = [sum(not row[j] for row in erroneous) / len(erroneous) for j in range(3)]
        observed = {name: sum(1 for claim_flags, flagged in zip(complete, rules[name]) if claim_flags[0].label in ERROR_LABELS and not flagged)
                    / len(erroneous) for name in ("1oo3", "2oo3", "3oo3")}
        product = m[0] * m[1] * m[2]
        metrics["panel"]["misses"] = {
            "member_miss_rates": dict(zip(panel, m)), "observed": observed,
            "predicted_independent": {"1oo3": product, "2oo3": m[0] * m[1] + m[0] * m[2] + m[1] * m[2] - 2 * product,
                                      "3oo3": 1 - (1 - m[0]) * (1 - m[1]) * (1 - m[2])},
            "DR": None if product == 0 else observed["1oo3"] / product}
    hypotheses = _hypotheses(plan)
    by_item: dict[str, list[tuple[bool, tuple[bool, ...]]]] = {}
    for claim, flags in complete:
        by_item.setdefault(claim.item_id, []).append((claim.label in ERROR_LABELS, flags))
    clusters = [rows for _item, rows in sorted(by_item.items())]
    results: dict[str, Any] = {}
    for name, hypothesis in hypotheses.items():
        base = {"endpoint": hypothesis["endpoint"], "test": hypothesis["test"]}
        if name == "H2a":
            def advantage(chosen: list) -> float:
                rows = [row for cluster in chosen for row in cluster]
                singles = [_f1([(gold_, flags[j]) for gold_, flags in rows]) for j in range(3)]
                return _f1([(gold_, _vote(flags, 2)) for gold_, flags in rows]) - max(singles)

            results[name] = _guarded(base, lambda: statistics.cluster_bootstrap_bca_one_sided(
                clusters, advantage, resamples=_resamples(plan, hypothesis), seed=_seed(plan, name), margin=hypothesis["margin"]))
        elif name == "H2b":
            estimate = _dr(clusters) if clusters else float("-inf")
            if estimate == float("-inf"):
                results[name] = {**base, "status": "undefined", "reason": "no erroneous claim, or a panel member that never misses"}
            else:
                results[name] = _guarded(base, lambda: statistics.cluster_bootstrap_lower_bound(
                    clusters, _dr, resamples=_resamples(plan, hypothesis), seed=_seed(plan, name), margin=hypothesis["margin"]))
        elif name == "H2c":
            results[name] = _h2c(plan, base, complete, hypothesis)
    return metrics, {"family": "E2", "correction": "holm", "hypotheses": results, "holm": _holm(results),
                     "note": "the registered E2 family; V-3, V-4's n_eff, UE-1 and UE-3 are reported without a family test (criteria_only; DI-138)"}


def _guarded(base: Mapping[str, Any], compute: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    """A bootstrap whose statistic is undefined on this data (too few clusters, a degenerate BCa) is reported as such."""
    try:
        return {**base, **compute()}
    except ValueError as error:
        return {**base, "status": "undefined", "reason": str(error)}


def _h2c(plan: Any, base: Mapping[str, Any], complete: Sequence[tuple[Claim, tuple[bool, ...]]], hypothesis: Mapping[str, Any]) -> dict:
    ratings = plan.extra["design"]["ratings"]
    if ratings is None:
        return {**base, "status": "awaiting_ratings", "needs": "Group B novice trust ratings (participant data after IRB approval, D-08)"}
    by_response: dict[str, list[tuple[bool, float]]] = {}
    for claim, flags in complete:
        by_response.setdefault(claim.source_request_key, []).append((claim.label in ERROR_LABELS, sum(flags) / 3))
    trust: dict[str, list[float]] = {}
    for row in ratings:
        trust.setdefault(row["source_request_key"], []).append(float(row["value"]))
    keys = sorted(set(by_response) & set(trust))
    labels = [any(gold for gold, _share in by_response[key]) for key in keys]
    panel = [max(share for _gold, share in by_response[key]) for key in keys]
    novices = [-(sum(trust[key]) / len(trust[key])) for key in keys]  # lower trust ranks a response as more likely erroneous
    return _guarded({**base, "responses": len(keys)}, lambda: statistics.paired_bootstrap_auc_one_sided(
        labels, panel, novices, resamples=_resamples(plan, hypothesis), seed=_seed(plan, "H2c"), margin=hypothesis["margin"]))


# ------------------------------------------------------------------------------------------------------------ E3


def _set_of(response: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    claims = [claim for claim in response.get("claims") or [] if isinstance(claim, Mapping)]
    return (tuple(sorted(str(claim.get("claim_id")) for claim in claims)),
            tuple(sorted({str(pointer) for claim in claims for pointer in claim.get("cited") or []})))


def compute_e3(plan: Any, responses: Sequence[Mapping[str, Any]]) -> tuple[dict, dict, dict]:
    design = plan.extra["design"]["design"]
    cells: dict[tuple[str, str, str | None, int], Mapping[str, Any]] = {}
    for request, response in zip(plan.requests, responses):
        cells[(request.item_id, request.role, request.unit, request.replicate)] = response
    items = sorted({request.item_id for request in plan.requests})
    violations: dict[str, dict[str, int]] = {"two-pass": {}, "single-pass": {}}
    excluded = {"two-pass": 0, "single-pass": 0}
    lock_kept = 0
    features: dict[str, dict[str, list[float]]] = {}
    for item in items:
        for role in ("two-pass", "single-pass"):
            level_responses = [cells.get((item, role, level, 1)) for level in ulqs.REPLAY_LEVELS]
            locked = cells.get((item, "two-pass-evidential", None, 1)) if role == "two-pass" else None
            if any(response is None or not _done(response) for response in level_responses) or (role == "two-pass" and (locked is None or not _done(locked))):
                excluded[role] += 1
                continue
            sets = [_set_of(response) for response in level_responses]
            violations[role][item] = int(len(set(sets)) > 1)
            if role == "two-pass":
                lock_kept += int(all(entry == _set_of(locked) for entry in sets))
                values = [response.get("features") for response in level_responses]
                if all(isinstance(value, Mapping) for value in values):
                    for name in FEATURES:
                        if all(isinstance(value.get(name), (int, float)) and not isinstance(value.get(name), bool) for value in values):
                            features.setdefault(name, {})[item] = [float(value[name]) for value in values]
    repeats = {}
    for item in items:
        runs = [cells.get((item, "single-pass", design["fixed_level"], replicate)) for replicate in range(1, int(design["repeats"]) + 1)]
        if all(response is not None and _done(response) for response in runs):
            repeats[item] = int(len({_set_of(response) for response in runs}) > 1)
    metrics = {
        "items": len(items),
        "IV": {role: {**statistics.wilson_interval(sum(values.values()), len(values)), "excluded_items": excluded[role]}
               for role, values in violations.items()},
        "two_pass_lock_kept": {"items": len(violations["two-pass"]), "kept": lock_kept},
        "presentation_features": {name: {"items": len(values)} for name, values in sorted(features.items())},
    }
    variance = {"single-pass": {"fixed_level": design["fixed_level"], "repeats": int(design["repeats"]),
                                "violations": statistics.wilson_interval(sum(repeats.values()), len(repeats)),
                                "rule": "claim-or-span-set-differs-v1"}}
    hypotheses = _hypotheses(plan)
    results: dict[str, Any] = {}
    for name, hypothesis in hypotheses.items():
        base = {"endpoint": hypothesis["endpoint"], "comparison": list(hypothesis["comparison"]), "test": hypothesis["test"]}
        if name == "H3a":
            results[name] = {**base, **paired_by_item(violations["two-pass"], violations["single-pass"])}
        elif name == "H3b":
            values = features.get(design["h3b_feature"], {})
            exploratory = {}
            for feature, rows in sorted(features.items()):
                if feature != design["h3b_feature"]:
                    exploratory[feature] = _guarded({}, lambda rows=rows: statistics.friedman([rows[item] for item in sorted(rows)]))
            results[name] = {**_guarded({**base, "feature": design["h3b_feature"]},
                                        lambda: statistics.friedman([values[item] for item in sorted(values)])),
                             "other_features_exploratory": exploratory}
    return metrics, {"family": "E3", "correction": "holm", "hypotheses": results, "holm": _holm(results),
                     "note": "the registered E3 family; H3b enters Holm through the pinned feature's Friedman test (PD-75)"}, variance


# ------------------------------------------------------------------------------------------------------------ E4


def _uniform(seed: str, *parts: Any) -> float:
    digest = hashlib.sha256("\x1f".join([seed, *(str(part) for part in parts)]).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64


def _index(seed: str, n: int, *parts: Any) -> int:
    digest = hashlib.sha256("\x1f".join([seed, *(str(part) for part in parts)]).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % n


@dataclass(frozen=True)
class Outcome:
    y: int             # 1 when the first pass (GATE) is clean
    quality: float     # the delivered (VLOOP) response's verified quality
    cost: float        # its usage units times the model's price per unit
    first_cost: float  # the first pass's usage units times the price


def _quality(response: Mapping[str, Any], gold: str, weights: Mapping[str, Any] | None) -> float:
    """Verified quality of a delivered response: eq. (8) over its `signals` with the pinned package's weights when the
    responder supplies them (`app.services.ranking.quality`), else 1 for an answer without an error claim to an
    answerable unit and 0 otherwise (an abstention delivers nothing)."""
    signals = response.get("signals")
    if isinstance(signals, Mapping) and weights is not None:
        from app.services.ranking.numeric import D
        from app.services.ranking.quality import quality

        return float(quality(signals, {name: D(value) for name, value in weights.items()}))
    return float(response.get("outcome") == "answered" and gold == "answer" and not _has_error(response))


def _usage(response: Mapping[str, Any]) -> int:
    usage = response.get("usage") or {}
    return int(usage.get("input_units", 0)) + int(usage.get("output_units", 0))


def _replay_population(plan: Any, responses: Sequence[Mapping[str, Any]], *, later: bool = False):
    """The units every model has a verified outcome for, each model's outcome on each, and the prices: the list prices in
    force at the run's start, or with `later` each model's later list price where it has one."""
    design = plan.extra["design"]["design"]
    prices = {entry["model_id"]: float(Decimal((entry.get("later_price") or entry)["price_per_unit"] if later else entry["price_per_unit"]))
              for entry in design["models"]}
    weights = ((plan.package_raw.get("ranking") or {}).get("quality") or {}).get("weights")
    grid: dict[tuple[str, str | None], dict[str, dict[str, Mapping]]] = {}
    meta: dict[tuple[str, str | None], tuple[str, str]] = {}
    topics = {item["item_id"]: item.get("topic") for item in plan.items}
    for request, response in zip(plan.requests, responses):
        if request.replicate != 1:
            continue
        grid.setdefault((request.item_id, request.unit), {}).setdefault(request.cell, {})[request.arm] = (response, request)
        meta[(request.item_id, request.unit)] = (topics.get(request.item_id), request.gold)
    population = {}
    excluded = 0
    for unit, by_model in sorted(grid.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")):
        if set(by_model) != set(prices) or any(set(arms) != {"GATE", "VLOOP"} or not all(_done(r) for r, _q in arms.values())
                                               for arms in by_model.values()):
            excluded += 1
            continue
        outcomes = {}
        for model, arms in by_model.items():
            gate, gate_request = arms["GATE"]
            vloop, vloop_request = arms["VLOOP"]
            first_error = _has_error(gate) or (gate_request.gold == "abstain" and gate.get("outcome") == "answered")
            outcomes[model] = Outcome(y=int(not first_error), quality=_quality(vloop, vloop_request.gold, weights),
                                      cost=max(_usage(vloop), 1) * prices[model], first_cost=max(_usage(gate), 1) * prices[model])
        population[unit] = {"topic": meta[unit][0], "outcomes": outcomes}
    return population, excluded, prices


class _Controller:
    """The Phase 9 ranking controller as a routing policy: each request is routed to Algorithm 1's choice for its context
    (`app.services.ranking.selection.select` on the controller's state), then its verified outcome is applied as an
    `outcome` input (`controller.apply_in_place`); a fallback abstains. Without hysteresis, the promotion margin delta is 0
    and one batch suffices (n_d = 1)."""

    def __init__(self, block: Mapping[str, Any], models: Sequence[Mapping[str, Any]], *, hysteresis: bool) -> None:
        from app.services.ranking.controller import apply_in_place
        from app.services.ranking.state import canonical, empty_state, params_of, sha256_hex

        self._apply = apply_in_place
        block = json.loads(json.dumps(block))
        if not hysteresis:
            block["promotion"] = {**block["promotion"], "delta": "0", "n_d": 1}
        self.state = empty_state()
        self.seq = 0
        self.alarms: list[tuple[int, str]] = []
        self.params_of = params_of
        self._input("config", {"package_version": "e4-replay", "package_sha256": "0" * 64, "parameters_sha256": sha256_hex(canonical(block)),
                               "parameters": block})
        for entry in models:
            self._input("model_seen", {"model": {"adapter_id": entry["model_id"], "family": entry["family"], "provider": entry["family"],
                                                 "model_id": entry["model_id"], "model_version": "e4", "cost_units_per_call":
                                                 int(Decimal(entry["price_per_unit"]) * 1000)}})
        self._input("availability", {"models": {entry["model_id"]: None for entry in models}})
        for entry in models:  # the Phase 9 synthetic commissioning prior (PD-75)
            self._input("commission", {"adapter_id": entry["model_id"], "version": "e4", "clean": 40, "failed": 0, "generated": 40,
                                       "mean_q": "0.9", "run_sha256": "0" * 64})
        self.clusters = set(self.params_of(self.state).clusters)

    def _input(self, kind: str, payload: Mapping[str, Any]) -> list:
        self.seq += 1
        return self._apply(self.state, {"seq": self.seq, "kind": kind, "payload": payload})

    def context(self, topic: str | None) -> dict[str, Any]:
        return {"cluster": topic if topic in self.clusters else "unscoped", "task_type": "explanation", "tier": 2}

    def choose(self, t: int, topic: str | None) -> str | None:
        from app.services.ranking.selection import ensure_models, select
        from app.services.ranking.types import Context

        params = self.params_of(self.state)
        key = Context(**self.context(topic)).key()
        ensure_models(self.state, params, key)
        decision, _u = select(self.state, params, key, ledger_seq=t + 1)
        return decision.model if decision.kind != "fallback" else None

    def observe(self, t: int, topic: str | None, model: str, outcome: Outcome) -> None:
        derived = self._input("outcome", {"ledger_seq": t + 1, "created_at": "2026-11-23T00:00:00.000000Z", "model": model,
                                          "context": self.context(topic), "y": outcome.y,
                                          "signals": {"V": format(outcome.quality, ".6f"), "S": None, "K": None, "H": "0", "F": None},
                                          "cost_units": int(round(outcome.cost * 1000)), "latency_ms": None, "tier_source": "v2"})
        self.alarms += [(t, payload["stream"]) for kind, payload in derived if kind == "alarm"]


def _replay_stream(plan: Any, population: Mapping, units: Sequence, prices: Mapping[str, float], seed: str) -> dict[str, Any]:
    """One stream: `stream_length` requests drawn (seeded) from `units`, the injected shift, and every policy replayed."""
    design = plan.extra["design"]["design"]
    models = sorted(prices)
    length = int(design["stream_length"])
    shift = design["shift"]
    shift_model, shift_topic, shift_at = shift["model"], shift["topic"], int(shift["at"])
    in_topic = [unit for unit in sorted(population, key=lambda u: (u[0], u[1] or "")) if population[unit]["topic"] == shift_topic]
    failed = [unit for unit in in_topic if population[unit]["outcomes"][shift_model].y == 0]
    base_error = (len(failed) / len(in_topic)) if in_topic else 1.0
    rate = min(1.0, float(Fraction(shift["points"])) / (1 - base_error)) if failed and base_error < 1 else 0.0
    stream = []
    for t in range(length):
        unit = units[_index(seed, len(units), "request", t)]
        outcomes = dict(population[unit]["outcomes"])
        shifted = (t >= shift_at and population[unit]["topic"] == shift_topic and rate > 0 and outcomes[shift_model].y == 1
                   and _uniform(seed, "shift", t) < rate)
        if shifted:
            outcomes[shift_model] = population[failed[_index(seed, len(failed), "failed", t)]]["outcomes"][shift_model]
        stream.append((unit, population[unit]["topic"], outcomes))
    pool = {}
    for unit in units:
        for model in models:
            entry = pool.setdefault(model, [0.0, 0.0])
            entry[0] += population[unit]["outcomes"][model].quality
            entry[1] += population[unit]["outcomes"][model].cost
    static_best = min(models, key=lambda model: (-(pool[model][0] / pool[model][1]), model))
    cheapest = min(models, key=lambda model: (prices[model], model))
    by_price = sorted(models, key=lambda model: (prices[model], model))
    epsilon = float(Fraction(design["epsilon"]))
    alpha = float(Fraction(design["linucb_alpha"]))
    results: dict[str, dict[str, Any]] = {}
    block = plan.package_raw.get("ranking")
    for policy in POLICIES:
        quality = cost = 0.0
        delay = None
        degraded_seen = 0
        controller = None
        if policy.startswith("controller"):
            if not isinstance(block, Mapping):
                results[policy] = {"status": "no_ranking_block"}
                continue
            controller = _Controller(block, plan.extra["design"]["design"]["models"], hysteresis=policy == "controller")
        means: dict[str, list[float]] = {model: [0.0, 0.0] for model in models}
        arms: dict[tuple[str, str | None], list[float]] = {}
        for t, (unit, topic, outcomes) in enumerate(stream):
            spent = 0.0
            if controller is not None:
                model = controller.choose(t, topic)
                if model is None:
                    continue
                controller.observe(t, topic, model, outcomes[model])
                if t >= shift_at and model == shift_model and topic == shift_topic:
                    degraded_seen += 1
                if delay is None and any(at >= shift_at and _stream_model(stream_name) == shift_model for at, stream_name in controller.alarms):
                    delay = degraded_seen
            elif policy == "static-best":
                model = static_best
            elif policy == "round-robin":
                model = models[t % len(models)]
            elif policy == "cheapest-eligible":
                model = cheapest
            elif policy == "epsilon-greedy":
                untried = [name for name in models if means[name][1] == 0]
                if untried:
                    model = untried[0]
                elif _uniform(seed, policy, t) < epsilon:
                    model = models[_index(seed, len(models), policy, "explore", t)]
                else:
                    model = min(models, key=lambda name: (-(means[name][0] / means[name][1]), name))
            elif policy == "linucb":
                def upper(name: str) -> float:
                    count, total = arms.get((name, topic), [0.0, 0.0])
                    return total / (1 + count) + alpha * sqrt(1 / (1 + count))

                model = min(models, key=lambda name: (-upper(name), name))
            else:  # threshold escalation: cheapest first, escalating while the first pass fails verification
                for model in by_price:
                    if outcomes[model].y == 1 or model == by_price[-1]:
                        break
                    spent += outcomes[model].first_cost
            outcome = outcomes[model]
            quality += outcome.quality
            cost += outcome.cost + spent
            reward = outcome.quality / outcome.cost
            means[model][0] += reward
            means[model][1] += 1
            entry = arms.setdefault((model, topic), [0.0, 0.0])
            entry[0] += 1
            entry[1] += reward
        results[policy] = {"verified_quality": quality, "cost": cost, "quality_per_price": None if cost == 0 else quality / cost}
        if controller is not None:
            results[policy].update(detection_delay=delay, switches=int(controller.state["counts"]["switches"]),
                                   alarms=int(controller.state["counts"]["alarms"]))
    return {"policies": results, "static_best": static_best, "shift_rate": rate}


def _stream_model(stream: str) -> str | None:
    """The model a Phase 9 CUSUM stream belongs to (`model:<id>` or `model-cluster:<id>:<cluster>`)."""
    parts = stream.split(":")
    return parts[1] if len(parts) >= 2 and parts[0] in ("model", "model-cluster") else None


def _h4a_difference(result: Mapping[str, Any]) -> float:
    policies = result["policies"]
    values = [policies.get(name, {}).get("quality_per_price") for name in ("controller", "static-best", "round-robin")]
    if any(value is None for value in values):
        return float("-inf")
    return values[0] - max(values[1], values[2])


def compute_e4(plan: Any, responses: Sequence[Mapping[str, Any]]) -> tuple[dict, dict, dict]:
    design = plan.extra["design"]["design"]
    pairs = list(zip(plan.requests, responses))
    models = [entry["model_id"] for entry in design["models"]]
    metrics: dict[str, Any] = {"cells": {}}
    for model in models:
        for arm in ("GATE", "VLOOP"):
            rows = [(request, response) for request, response in pairs if request.cell == model and request.arm == arm and request.replicate == 1]
            done = [(request, response) for request, response in rows if _done(response)]
            errors = answerable_item_errors(rows, lambda request: True)
            metrics["cells"][f"{model}|{arm}"] = {
                "units": len(rows), "provider_failures_excluded": len(rows) - len(done),
                "item_error_answerable": statistics.wilson_interval(sum(errors.values()), len(errors)),
                "answer_rate": statistics.wilson_interval(sum(1 for request, response in done if request.gold == "answer"
                                                              and response.get("outcome") == "answered"),
                                                          sum(1 for request, _response in done if request.gold == "answer"))}
    variance = _cell_replicate_variance(plan, pairs)
    if _labels_pending(pairs):
        return {**metrics, "status": "awaiting_labels"}, {"family": "E4", "status": "awaiting_labels"}, variance
    population, excluded, prices = _replay_population(plan, responses)
    metrics["replay"] = {"units": len(population), "excluded_units": excluded}
    hypotheses = _hypotheses(plan)
    results: dict[str, Any] = {}
    local = next(entry["model_id"] for entry in design["models"] if entry["local"])
    for name, hypothesis in hypotheses.items():
        base = {"endpoint": hypothesis["endpoint"], "comparison": list(hypothesis["comparison"]), "test": hypothesis["test"]}
        if name == "H4a":
            results[name] = {**base, **_h4a(plan, population, prices, hypothesis), "margin": hypothesis["margin"]}
            later = {entry["model_id"]: entry["later_price"] for entry in design["models"] if entry.get("later_price")}
            if later:
                # "at both Gemini prices if runs straddle 1 January 2027": the replay again at the later list prices,
                # reported beside the registered result and not entering Holm.
                later_population, _excluded, later_prices = _replay_population(plan, responses, later=True)
                results[name]["at_later_prices"] = {"later_price": later, "enters_holm": False,
                                                    **_h4a(plan, later_population, later_prices, hypothesis)}
        elif name == "H4b":
            left = answerable_item_errors(pairs, lambda request: request.cell == local and request.arm == "GATE")
            right = answerable_item_errors(pairs, lambda request: request.cell == design["pilot_commercial"] and request.arm == "GATE")
            results[name] = {**base, "local": local, "commercial": design["pilot_commercial"], **paired_by_item(left, right),
                             "tost": _h4b_tost(plan, pairs, local, hypothesis)}
    return metrics, {"family": "E4", "correction": "holm", "hypotheses": results, "holm": _holm(results),
                     "note": "the registered E4 family; H4b enters Holm through its exact McNemar test, and its TOST only when the "
                             "EQC reliability condition can be judged (ICC(2,k) and Cronbach's alpha are not implemented, DI-138); "
                             "MR-2, MR-3 and LQ-2 are reported without a family test (criteria_only)"}, variance


def _h4a(plan: Any, population: Mapping, prices: Mapping[str, float], hypothesis: Mapping[str, Any]) -> dict[str, Any]:
    design = plan.extra["design"]["design"]
    if not population:
        return {"status": "undefined", "reason": "no unit has a verified outcome for every model"}
    groups: dict[str, list] = {}
    for unit in population:
        groups.setdefault(unit[0], []).append(unit)
    ordered = [sorted(groups[item], key=lambda unit: unit[1] or "") for item in sorted(groups)]
    seed = _seed(plan, "H4a")
    streams: list[dict[str, Any]] = []

    def difference(chosen: list, replicate: int | None) -> float:
        units = [unit for group in chosen for unit in group]
        result = _replay_stream(plan, population, units, prices, f"{seed}\x1fstream\x1f{'estimate' if replicate is None else replicate}")
        if replicate is not None:
            streams.append(result)
        return _h4a_difference(result)

    share = statistics.two_level_bootstrap_share_le_zero(ordered, difference, resamples=int(design["streams"]), seed=seed, indexed=True)
    summary: dict[str, Any] = {}
    for policy in POLICIES:
        values = sorted(result["policies"][policy]["quality_per_price"] for result in streams
                        if result["policies"].get(policy, {}).get("quality_per_price") is not None)
        if values:
            summary[policy] = {"mean": sum(values) / len(values), "interval_95": [values[int(0.025 * len(values))],
                                                                                   values[min(len(values) - 1, int(0.975 * len(values)))]]}
    delays = [result["policies"]["controller"].get("detection_delay") for result in streams if "controller" in result["policies"]]
    detected = [delay for delay in delays if delay is not None]
    return {**share, "streams": len(streams), "stream_length": int(design["stream_length"]), "quality_per_price": summary,
            "detection": {"streams": len(delays), "detected": len(detected), "within_100": sum(1 for delay in detected if delay <= 100),
                          "median_delay": sorted(detected)[len(detected) // 2] if detected else None}}


def _h4b_tost(plan: Any, pairs: Sequence, local: str, hypothesis: Mapping[str, Any]) -> dict[str, Any]:
    ratings = plan.extra["design"]["ratings"]
    if ratings is None:
        return {"status": "awaiting_ratings", "needs": "expert EQC ratings (six scales, two raters) of the VLOOP responses"}
    values: dict[str, list[float]] = {}
    for row in ratings:
        values.setdefault(row["source_request_key"], []).append(float(row["value"]))
    design = plan.extra["design"]["design"]
    by_unit: dict[tuple, dict[str, float]] = {}
    for request, _response in pairs:
        if request.arm == "VLOOP" and request.replicate == 1 and request.request_key in values:
            scores = values[request.request_key]
            by_unit.setdefault((request.item_id, request.unit), {})[request.cell] = sum(scores) / len(scores)
    units = sorted((unit for unit, cells in by_unit.items() if local in cells and design["pilot_commercial"] in cells),
                   key=lambda unit: (unit[0], unit[1] or ""))
    result = _guarded({"pairs": len(units)}, lambda: statistics.paired_tost([by_unit[unit][local] for unit in units],
                                                                            [by_unit[unit][design["pilot_commercial"]] for unit in units],
                                                                            margin=hypothesis["margin"]))
    return {**result, "confirmatory": "inconclusive", "reason": "ICC(2,k) and Cronbach's alpha are not implemented (DI-138)",
            "enters_holm": False}


def _cell_replicate_variance(plan: Any, pairs: Sequence) -> dict[str, Any]:
    from .runner import subsample

    sampled = set(subsample(plan.items, plan.pins["replicates"]))
    variance: dict[str, Any] = {}
    if not sampled:
        return variance
    for model in sorted({request.cell for request, _response in pairs}):
        for arm in ("GATE", "VLOOP"):
            by_replicate: dict[int, list[int]] = {}
            for request, response in pairs:
                if request.cell == model and request.arm == arm and request.item_id in sampled and _done(response):
                    by_replicate.setdefault(request.replicate, []).append(int(_has_error(response) or (
                        request.gold == "abstain" and response.get("outcome") == "answered")))
            rates = [sum(values) / len(values) for _replicate, values in sorted(by_replicate.items())]
            variance[f"{model}|{arm}"] = {"er_by_replicate": rates, "variance": statistics.sample_variance(rates), "rule": "sample-variance-v1"}
    return variance


def _verifier_replicate_variance(plan: Any, responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_cell: dict[str, dict[int, list[int]]] = {}
    for request, response in zip(plan.requests, responses):
        if _done(response) and response.get("verdict") in VERDICTS:
            by_cell.setdefault(request.cell, {}).setdefault(request.replicate, []).append(int(response["verdict"] == "object"))
    variance = {}
    for cell, by_replicate in sorted(by_cell.items()):
        if len(by_replicate) < 2:
            continue
        rates = [sum(values) / len(values) for _replicate, values in sorted(by_replicate.items())]
        variance[cell] = {"objection_rate_by_replicate": rates, "variance": statistics.sample_variance(rates), "rule": "sample-variance-v1"}
    return variance


def finite(value: Any) -> Any:
    """`value` with every infinite or NaN float (an undefined replicate or estimate) as null, so the record stays JSON."""
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Mapping):
        return {key: finite(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(entry) for entry in value]
    return value


def compute(plan: Any, responses: Sequence[Mapping[str, Any]]) -> tuple[dict, dict, dict]:
    """(metrics, registered tests, replicate variance) of a design run."""
    experiment = plan.spec["experiment"]
    if experiment == "E2":
        metrics, registered = compute_e2(plan, responses)
        result = (metrics, registered, _verifier_replicate_variance(plan, responses))
    elif experiment == "E3":
        result = compute_e3(plan, responses)
    else:
        result = compute_e4(plan, responses)
    return tuple(finite(part) for part in result)  # type: ignore[return-value]


# ------------------------------------------------------------------------------------------------------------ stub


def stub_verdict(prefix: bytes, request: Any) -> dict[str, Any]:
    """`stub-responder-v1` for a verification: b = sha256(prefix + request_key); an erroneous claim (gold label Fabricated
    or Attribution error) is objected to when b[0] < 200, any other when b[0] < 20 (synthetic accuracy by construction)."""
    digest = hashlib.sha256(prefix + request.request_key.encode("utf-8")).digest()
    objects = digest[0] < (200 if request.claim_label in ERROR_LABELS else 20)
    return {"outcome": "answered", "verdict": "object" if objects else "pass", "claims": [], "text": "stub:" + request.request_key[:16],
            "usage": {"input_units": 1, "output_units": 1}, "model_id": None}


def stub_generation(prefix: bytes, request: Any) -> dict[str, Any]:
    """`stub-responder-v1` for an E3 generation, the same rule for both designs and every level (no design effect by
    construction): answers when b[0] < 240; each gold claim kept unless b[1 + i] % 8 == 0, citing the unit's evidence;
    presentation features from b[20..23]."""
    digest = hashlib.sha256(prefix + request.request_key.encode("utf-8")).digest()
    text = "stub:" + request.request_key[:16]
    usage = {"input_units": 1, "output_units": 1}
    if digest[0] >= 240:
        return {"outcome": "abstained", "claims": [], "text": text, "usage": usage, "model_id": None}
    claims = [{"claim_id": claim_id, "cited": list(request.evidence), "label": "supported", "ehmf_type": None}
              for index, claim_id in enumerate(request.gold_claims) if digest[1 + index % 19] % 8]
    features = {"fk_grade": 4 + digest[20] % 9, "guiding_questions": digest[21] % 3, "prerequisite_recaps": digest[22] % 2,
                "length": 60 + digest[23]}
    return {"outcome": "answered", "claims": claims, "features": features, "text": text, "usage": usage, "model_id": None}


def stub_dispatch(prefix: bytes, request: Any, answer: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    role = getattr(request, "role", "answer")
    if role == "verify":
        return stub_verdict(prefix, request)
    if role in ("two-pass-evidential", "two-pass", "single-pass"):
        return stub_generation(prefix, request)
    return answer(prefix, request, **kwargs)

