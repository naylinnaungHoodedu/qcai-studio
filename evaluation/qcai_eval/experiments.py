"""The E2, E3 and E4 designs and their registered families (plan task 5 "E1-E4 per Section 15"; VBT RevB Sec. VIII-D,
X-A, Table I; spec 4.14).

Each design plans its requests from the run spec's `design` block, runs them through the runner's responder seam as E1
does (stub, recorded; live refused), and computes its registered family with Holm from the responses. Nothing here
pins a model: the verifier panel, both E3 designs' generator and E4's four models and prices are the spec's (D-07 pins
them for a real run; until then only synthetic, stub or recorded runs exist, and E1-E4 runs stay confirmatory only).
A live run or a run over research data runs the registered protocol (`REGISTERED_DESIGN`, the hypotheses' `resamples`;
`departures`); a synthetic run may depart, and its record names each departure and files its family as
`departs_from_registration`.

- **E2** (verifier reliability; H2a-c). The verification set is every labelled claim of a pinned E1 responses file
  (generator family named) and, optionally, of a pinned E4 responses file (the generator of each line is its model,
  whose family the verifier list gives). Each verifier verifies every claim generated outside its own family (`verify`
  requests); the panel is the three verifiers outside the E1 generator's family, formed afterwards by rule (1oo3, 2oo3,
  3oo3 and a two-coin Dawid-Skene posterior) on identical claims. H2a: claim-level F1 of 2oo3 minus the best single
  member's, a one-sided cluster BCa bootstrap over items; H2b: DR = P_all / (m1 m2 m3) on erroneous claims, the
  one-sided cluster percentile lower bound against 1; H2c: the paired AUC bootstrap of the panel against Group B novice
  trust ratings, computed only from a pinned ratings file (none exists before IRB approval, D-08).
- **E3** (adaptation invariance; H3a-b). Every live S7 (stratum G) item at the three levels under two designs: two-pass
  (one `two-pass-evidential` request, then a `two-pass` presentation request per level, each sent with the evidential
  response's locked claims) and single-pass (`single-pass` per level), plus single-pass repeated at one fixed level.
  v_q = 1 when the claim set or the cited span set differs across the levels (eq. 18), compared exactly (PD-75; the
  paper's bidirectional entailment with human checks on disagreements is DI-148, and the record lists the items whose
  sets differ). H3a: exact McNemar of v_q two-pass vs single-pass, paired by item; H3b: Friedman's test of a
  presentation feature across the levels under two-pass.
- **E4** (model comparison and ranking replay; H4a-b). All four models answer every unit in GATE and VLOOP; a response's
  cost is its logged input and output units at the model's input and output list prices (the local model's prices
  are a stand-in for measured energy plus amortized hardware, which the record reports separately; DI-148), and the
  latency a response records is reported as median and 95th percentile. The replay resamples items, then draws seeded
  streams from them (`statistics.two_level_bootstrap_share_le_zero`, one replicate per stream), with one model's
  first-pass error rate in one topic raised by resampling its own failed responses from a request on, and replays eight
  routing policies: the Phase 9 controller with and without hysteresis, static-best, round-robin, cheapest-eligible,
  epsilon-greedy, a LinUCB-style bandit and threshold escalation. H4a: the share of streams in which the controller's
  verified quality per price is at most the larger of static-best's and round-robin's, with the 95% percentile interval
  of that difference; the controller's detection, false alarms and switches are reported under MR-2's and MR-3's
  counting rules as figures, not outcomes. H4b: exact McNemar of the local model's and the pilot-selected commercial
  model's item-level error on answerable items in GATE, and the paired TOST of their expert EQC ratings from a pinned
  ratings file (reported inconclusive: ICC(2,k) and Cronbach's alpha are not implemented, DI-138). Each hypothesis waits
  (`awaiting_labels`) only for the labels it reads: H4a every model's GATE and VLOOP responses, H4b the two GATE cells.

The engineering parameters no plan text fixes are provisional (PD-75; `evaluation/config/harness_parameters_v1.json`
`designs`). Outcomes are reported by the PI, never asserted by the harness (invariant 9).
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _dt
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from . import inputs, statistics, ulqs
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


PRICE_MAX = Fraction(10 ** 6)  # USD per unit: keeps the replay's cost units inside the controller's exact arithmetic


def _number(value: Any, *, decimal: bool = False) -> Fraction | None:
    """A rational string the computation can use: Fraction-readable and float-representable (finite once converted, so
    that '1e400' is refused here, not an OverflowError or an infinite figure after the run). With `decimal`, a value the
    computation reads with Decimal: it must also be Decimal-readable and finite there ('1/2' is refused, not a
    decimal.InvalidOperation after the run)."""
    if not isinstance(value, str):
        return None
    try:
        if decimal and not Decimal(value).is_finite():
            return None
        number = Fraction(value)
        return number if isfinite(float(number)) else None
    except (ValueError, ArithmeticError):
        return None


def _decimal(value: Any, *, positive: bool = False, unit: bool = False, low: Fraction | None = None,
             high: Fraction | None = None) -> bool:
    """A Decimal-readable, float-representable string (`_number` with `decimal`). `positive`: above 0 and still above 0
    as a float ('1e-400' underflows to 0.0 and is refused, never a division by a zero cost); `unit`: in (0, 1); `low`,
    `high`: in [low, high]."""
    number = _number(value, decimal=True)
    if number is None:
        return False
    return ((not positive or (number > 0 and float(number) > 0)) and (not unit or 0 < number < 1)
            and (low is None or number >= low) and (high is None or number <= high))


def _rational(value: Any, low: Fraction, high: Fraction | None = None) -> bool:
    """A float-representable rational string (`_number`) in [low, high] (high None: no upper bound)."""
    number = _number(value)
    if number is None:
        return False
    return number >= low and (high is None or number <= high)


def _day(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


PRICE_KEYS = ("price_per_input_unit", "price_per_output_unit")


def _later_price_ok(value: Any) -> bool:
    """A model's optional later list price: {"from": "YYYY-MM-DD", "price_per_input_unit", "price_per_output_unit"},
    positive decimals up to PRICE_MAX (`_price_ok`; VBT RevB Sec. VIII-D: "at both Gemini prices if runs straddle 1 January
    2027")."""
    if value is None:
        return True
    return (isinstance(value, Mapping) and set(value) == {"from", *PRICE_KEYS} and _day(value.get("from"))
            and all(_price_ok(value.get(key)) for key in PRICE_KEYS))


def _price_ok(value: Any) -> bool:
    """A list price per unit, read with Decimal by the computation: a positive decimal (positive as a float too) of at
    most PRICE_MAX, so that the replay's cost units (the cost in thousandths of a USD) stay inside the ranking
    controller's exact arithmetic (34 digits, quantum 1e-18): "1e306" is refused here, never a decimal.InvalidOperation
    after the run."""
    return _decimal(value, positive=True, high=PRICE_MAX)


def _local_cost_ok(value: Any) -> bool:
    """The local model's measured cost of the run, when the operator supplies it: {"energy", "amortized_hardware"}, each a
    non-negative decimal in USD, read with Decimal (VBT RevB Sec. VIII-D: "local cost is reported separately as measured energy plus
    amortized hardware")."""
    if value is None:
        return True
    return (isinstance(value, Mapping) and set(value) == {"energy", "amortized_hardware"}
            and all(_decimal(value.get(key), low=Fraction(0)) for key in ("energy", "amortized_hardware")))


def _model_ok(entry: Any) -> bool:
    return (isinstance(entry, Mapping) and isinstance(entry.get("model_id"), str) and bool(MODEL_ID.match(entry["model_id"]))
            and isinstance(entry.get("family"), str) and bool(entry["family"]) and isinstance(entry.get("local"), bool)
            and all(_price_ok(entry.get(key)) for key in PRICE_KEYS) and _later_price_ok(entry.get("later_price")))


def shape_refusals(experiment: str, design: Any) -> list[str]:
    """The `design` block's shape (exit 2, the field named): every nested value the planner and the computation read, so
    that a malformed value is refused before anything runs, never a traceback after the run completed."""
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
        if "dawid_skene_iterations" in design and not _positive_int(design["dawid_skene_iterations"]):
            reasons.append("design.dawid_skene_iterations")
    elif experiment == "E3":
        from .ablation import ARM_IDS

        if "arm" in design and design["arm"] not in ARM_IDS:
            reasons.append("design.arm")
        if "fixed_level" in design and design["fixed_level"] not in ulqs.REPLAY_LEVELS:
            reasons.append("design.fixed_level")
        if "repeats" in design and not _positive_int(design["repeats"], 2):
            reasons.append("design.repeats")
        if "h3b_feature" in design and design["h3b_feature"] not in FEATURES:
            reasons.append("design.h3b_feature")
    elif experiment == "E4":
        models = design.get("models")
        if not isinstance(models, list) or not all(_model_ok(entry) for entry in models):
            reasons.append("design.models")
        if not isinstance(design.get("pilot_commercial"), str):
            reasons.append("design.pilot_commercial")
        for key in ("streams", "stream_length", "commissioning_items"):
            if key in design and not _positive_int(design[key]):
                reasons.append(f"design.{key}")
        if "min_stream_items" in design:  # the streams' floor is the harness parameters' (PD-75), never the spec's
            reasons.append("design.min_stream_items")
        if "epsilon" in design and not _rational(design["epsilon"], Fraction(0), Fraction(1)):
            reasons.append("design.epsilon")
        if "linucb_alpha" in design and not _rational(design["linucb_alpha"], Fraction(0)):
            reasons.append("design.linucb_alpha")
        if not _local_cost_ok(design.get("local_cost")):
            reasons.append("design.local_cost")
        shift = design.get("shift")
        if (not isinstance(shift, Mapping) or not isinstance(shift.get("model"), str) or not isinstance(shift.get("topic"), str)
                or ("at" in shift and not _positive_int(shift["at"], 0)) or ("points" in shift and not _decimal(shift["points"], unit=True))):
            reasons.append("design.shift")
    return reasons


# The protocol values the registration fixes: the analysis plan's per-hypothesis `resamples` (H2a, H2b 10,000), and VBT
# RevB Sec. VIII-D's E3 "Single-pass generation is also repeated three times at one fixed level" and E4 "1,000 seeded
# streams of 2,000 requests ... At request 1,000, one model's first-pass error rate in one topic is raised by ten
# percentage points" (plan 6.5 Table XVII "1,000 replay streams"). `harness_parameters_v1.json` `designs` holds the same
# values as the defaults (PD-75; a test keeps them equal). E4's `commissioning_items` is not registered: the paper's 80
# commissioning items ("the 30-item pilot plus the golden set (80 items)", VBT RevB Sec. VII) are not ULQS items, and the
# harness's hold-out of run items in their place is an engineering stand-in (PD-75, DI-148) whose cost, the items the
# streams lose, is bounded by the streams' floor (`min_stream_items`, `stream_floor_refusals`).
REGISTERED_DESIGN = {"E3": {"repeats": 3}, "E4": {"streams": 1000, "stream_length": 2000, "shift.at": 1000, "shift.points": "0.10"}}


def departures(experiment: str, design: Mapping[str, Any], family: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each effective design value that differs from the registered protocol (`REGISTERED_DESIGN` and the hypotheses'
    registered `resamples`), as {field, registered, effective} (with the hypothesis for a resamples departure). The
    planner refuses a departure in a live run or a run over non-synthetic data (`design_departs_from_registration:<field>`,
    exit 2); a synthetic run may depart, and its record names every departure (`pins.design.departures`) and files its
    family as `protocol: departs_from_registration`, never as the registered result."""
    found: list[dict[str, Any]] = []
    if design.get("resamples") is not None:
        for hypothesis in family.get("hypotheses") or []:
            if hypothesis.get("resamples") is not None and int(design["resamples"]) != int(hypothesis["resamples"]):
                found.append({"field": "design.resamples", "hypothesis": hypothesis["id"], "registered": int(hypothesis["resamples"]),
                              "effective": int(design["resamples"])})
    for field, registered in REGISTERED_DESIGN.get(experiment, {}).items():
        value = design["shift"][field.split(".", 1)[1]] if field.startswith("shift.") else design[field]
        same = Fraction(value) == Fraction(registered) if field == "shift.points" else value == registered
        if not same:
            found.append({"field": f"design.{field}", "registered": registered, "effective": value})
    return found


DEFAULTED = {"E2": ("dawid_skene_iterations",), "E3": ("arm", "fixed_level", "repeats", "h3b_feature"),
             "E4": ("streams", "stream_length", "epsilon", "linucb_alpha", "commissioning_items", "shift.at", "shift.points")}


def defaults_taken(experiment: str, design: Mapping[str, Any]) -> list[str]:
    """The design fields the spec leaves to `harness_parameters_v1.json` `designs` (`effective_design` fills them); the
    record's `pins.harness_parameters.used_for` names `designs` when there is any."""
    taken = []
    for field in DEFAULTED.get(experiment, ()):
        if field.startswith("shift."):
            shift = design.get("shift")
            if not isinstance(shift, Mapping) or field.split(".", 1)[1] not in shift:
                taken.append(field)
        elif field not in design:
            taken.append(field)
    return taken


def effective_design(experiment: str, design: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The design block with the provisional defaults (`harness_parameters_v1.json` `designs`, PD-75) filled in."""
    defaults = (parameters.get("designs") or {}).get(experiment) or {}
    effective = json.loads(json.dumps(design))
    if experiment == "E3":
        for key in ("arm", "fixed_level", "repeats", "h3b_feature"):
            effective.setdefault(key, defaults[key])
    elif experiment == "E4":
        for key in ("streams", "stream_length", "epsilon", "linucb_alpha", "commissioning_items"):
            effective.setdefault(key, defaults[key])
        effective["shift"] = {"at": defaults["shift_at"], "points": defaults["shift_points"], **effective["shift"]}
        effective["min_stream_items"] = defaults["min_stream_items"]  # always the harness parameters' (shape_refusals)
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
    except inputs.InputInvalid:  # a value no step can compute with (NaN, an infinity, 1e400, 10**400): invalid content
        raise DesignRefused(3, [f"{kind}_invalid"]) from None
    except (OSError, ValueError):
        raise DesignRefused(3, [f"{kind}_unreadable"]) from None
    if not all(isinstance(line, Mapping) for line in lines):
        raise DesignRefused(3, [f"{kind}_invalid"])
    return lines


def _line_ok(line: Mapping[str, Any]) -> bool:
    """A responses line's shape as the verification set reads it: an integer replicate, a string outcome and arm, a
    string or null unit and cell, and a list of claim objects, each with a string `claim_id`, a string or null `label`
    and a list of string `cited` pointers (absent: none)."""
    replicate, claims = line.get("replicate"), line.get("claims")
    if not isinstance(replicate, int) or isinstance(replicate, bool) or not isinstance(line.get("outcome"), str):
        return False
    if not isinstance(line.get("arm"), str) or not isinstance(line.get("unit"), (str, type(None))) or not isinstance(line.get("cell"), (str, type(None))):
        return False
    if claims is None:
        return True
    return isinstance(claims, list) and all(
        isinstance(claim, Mapping) and isinstance(claim.get("claim_id"), str) and isinstance(claim.get("label"), (str, type(None)))
        and isinstance(claim.get("cited", []), list) and all(isinstance(pointer, str) for pointer in claim.get("cited", []))
        for claim in claims)


def _claims_of(lines: Sequence[Mapping[str, Any]], *, live: set[str], family_of: Callable[[Mapping[str, Any]], str | None], source: str,
               kind: str) -> list[Claim]:
    claims = []
    for line in lines:
        if not isinstance(line.get("item_id"), str) or line["item_id"] not in live or not isinstance(line.get("request_key"), str):
            raise DesignRefused(3, [f"{kind}_items"])
        if not _line_ok(line):
            raise DesignRefused(3, [f"{kind}_invalid"])
        if line.get("replicate") != 1 or line.get("outcome") != "answered":
            continue
        family = family_of(line)
        if family is None:
            raise DesignRefused(3, [f"{kind}_generator_unknown"])
        for claim in line.get("claims") or []:
            if claim.get("label") is None:
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
                                   and _finite_value(row.get("value"))
                                   and set(row) == {"rating", "source_request_key", "value"} for row in rows):
            raise DesignRefused(3, ["ratings_invalid"])
        loaded["ratings"] = rows
    return loaded


def _finite_value(value: Any) -> bool:
    """A rating's value: a JSON number (not a bool) that converts to a finite float; a huge integer (an OverflowError in
    float()), NaN or Infinity is refused as ratings_invalid, never a traceback in the statistics after the run."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


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
                    epsilon=design["epsilon"], linucb_alpha=design["linucb_alpha"], commissioning_items=design["commissioning_items"],
                    min_stream_items=design["min_stream_items"],
                    policies=list(POLICIES),
                    local_cost=design.get("local_cost"))
    pins["resamples"] = design.get("resamples")
    pins["ratings"] = None if design.get("ratings") is None else {"sha256": design["ratings"]["sha256"]}
    pins["departures"] = list(loaded.get("departures") or [])
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


SET_RULE = "claim-or-span-set-differs-v1"  # exact claim-id and cited-span sets (PD-75), standing in for entailment (DI-148)


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
        # VBT RevB Sec. VIII-D compares claim sets "by bidirectional entailment with human checks on disagreements"; the
        # harness compares claim ids and cited spans exactly (PD-75), and lists the items whose sets differ for that check
        # (the entailment checker and the human checks are DI-148).
        "claim_set_comparison": {"rule": SET_RULE, "stands_in_for": "bidirectional entailment of claim sets with human checks on "
                                                                     "disagreements (VBT RevB Sec. VIII-D; DI-148)",
                                 "human_checks": "awaiting_human_checks",
                                 "disagreements": {role: sorted(item for item, value in values.items() if value)
                                                   for role, values in violations.items()}},
        "two_pass_lock_kept": {"items": len(violations["two-pass"]), "kept": lock_kept},
        "presentation_features": {name: {"items": len(values)} for name, values in sorted(features.items())},
    }
    variance = {"single-pass": {"fixed_level": design["fixed_level"], "repeats": int(design["repeats"]),
                                "violations": statistics.wilson_interval(sum(repeats.values()), len(repeats)),
                                "rule": SET_RULE}}
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
    cost: float        # its logged input and output units at the model's input and output list prices
    first_cost: float  # the first pass's cost, priced the same way


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


def _units(response: Mapping[str, Any]) -> tuple[int, int]:
    """A response's logged (input, output) usage units; a value that is not a non-negative integer counts 0."""
    usage = response.get("usage") if isinstance(response.get("usage"), Mapping) else {}
    values = [usage.get(key, 0) for key in ("input_units", "output_units")]
    inputs, outputs = (value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0 for value in values)
    return inputs, outputs


def _cost(response: Mapping[str, Any], price: tuple[float, float]) -> float:
    """Logged usage at the list prices (VBT RevB Sec. VIII-D: "Cost is computed from logged tokens at the list prices";
    Table XIV prices input and output tokens separately): input units times the input price plus output units times the
    output price. A response that logged no usage is priced as one input and one output unit (PD-75), so that no
    delivered response is free."""
    inputs, outputs = _units(response)
    if inputs + outputs == 0:
        inputs = outputs = 1
    return inputs * price[0] + outputs * price[1]


def prices_of(design: Mapping[str, Any], *, later: bool = False) -> dict[str, tuple[float, float]]:
    """Each model's (input, output) price per unit: the list prices in force at the run's start, or with `later` each
    model's later list price where it has one."""
    prices = {}
    for entry in design["models"]:
        source = (entry.get("later_price") or entry) if later else entry
        prices[entry["model_id"]] = (float(Decimal(source["price_per_input_unit"])), float(Decimal(source["price_per_output_unit"])))
    return prices


def _replay_population(plan: Any, responses: Sequence[Mapping[str, Any]], *, later: bool = False):
    """The units every model has a verified outcome for, each model's outcome on each, and the prices (`prices_of`)."""
    design = plan.extra["design"]["design"]
    prices = prices_of(design, later=later)
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
                                      cost=_cost(vloop, prices[model]), first_cost=_cost(gate, prices[model]))
        population[unit] = {"topic": meta[unit][0], "outcomes": outcomes}
    return population, excluded, prices


# The fields of a package's `ranking` block the E4 replay reads (`_quality`, `_Controller`, and through its `config` input
# `app.services.ranking.state.Params`), each with the shape it is read in. `ranking_problem` checks them before any request.
_RANKING_DECIMALS = (("trust", "gamma"), ("trust", "quantile"), ("quality", "eta"), ("quality", "initial_qbar"),
                     ("selection", "eps_s"), ("promotion", "delta"), ("cusum", "p0"), ("cusum", "p1"), ("cusum", "h"),
                     ("recommission", "deflation"), ("recommission", "uncommissioned_prior", "alpha"),
                     ("recommission", "uncommissioned_prior", "beta"), ("penalties", "lambda_u"), ("penalties", "lambda_l"))
_RANKING_COUNTS = (("promotion", "n_d"), ("micro_batch", "responses"), ("micro_batch", "seconds"))
_RANKING_FLAGS = (("tier_permissions", "B_tier_1_when_no_A"), ("selection", "first_incumbent_is_switch"))
_RANKING_WEIGHTS = ("V", "S", "K", "F")  # app.services.ranking.quality.SIGNAL_NAMES: eq. (8) reads a weight for each
_RANKING_RATINGS = ("A", "B", "C")
_RANKING_TIERS = ("A", "B", "C", "D")
_ABSENT = object()


def _ranking_at(block: Mapping[str, Any], path: Sequence[str]) -> Any:
    node: Any = block
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return _ABSENT
        node = node[key]
    return node


def _ranking_decimal(value: Any) -> bool:
    """A finite decimal as the ranking arithmetic reads it (`app.services.ranking.numeric.D`): a string or an integer,
    never a float or a bool."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return False
    try:
        return Decimal(value).is_finite()
    except (ArithmeticError, ValueError):
        return False


def ranking_problem(block: Any) -> str | None:
    """The first field of a package's `ranking` block that is not shaped as the E4 replay reads it, as `ranking` or
    `ranking.<dotted field>`, or None: the block is absent, null (E4's controller policies then report
    `no_ranking_block`) or an object whose decimal fields are finite decimal strings or integers, whose counts are
    positive integers, whose flags are booleans, whose `quality.weights` give a decimal for each of V, S, K and F (the
    four eq. (8) weights non-negative with a positive sum, so that eq. (8) is a weighted mean) and `ratings` one for each
    of A, B and C, whose `tier_permissions` A-D are lists of integers, whose `seed` is a string
    and whose `contexts.clusters` is a list of strings (each read as a context's cluster). The arithmetic a value takes
    part in is checked by `ranking_replay_problem` when an E4 run is planned."""
    if block is None:
        return None
    if not isinstance(block, Mapping):
        return "ranking"
    for path in _RANKING_DECIMALS:
        if not _ranking_decimal(_ranking_at(block, path)):
            return "ranking." + ".".join(path)
    for path in _RANKING_COUNTS:
        value = _ranking_at(block, path)
        if type(value) is not int or value < 1:
            return "ranking." + ".".join(path)
    for path in _RANKING_FLAGS:
        if not isinstance(_ranking_at(block, path), bool):
            return "ranking." + ".".join(path)
    for name, required in (("quality.weights", _RANKING_WEIGHTS), ("ratings", _RANKING_RATINGS)):
        values = _ranking_at(block, name.split("."))
        if not isinstance(values, Mapping) or not set(required) <= set(values) \
                or not all(isinstance(key, str) and _ranking_decimal(value) for key, value in values.items()):
            return f"ranking.{name}"
    weights = [Decimal(block["quality"]["weights"][name]) for name in _RANKING_WEIGHTS]
    if any(weight < 0 for weight in weights) or not any(weight > 0 for weight in weights):
        return "ranking.quality.weights"
    for tier in _RANKING_TIERS:
        value = _ranking_at(block, ("tier_permissions", tier))
        if not isinstance(value, list) or not all(type(entry) is int for entry in value):
            return f"ranking.tier_permissions.{tier}"
    if not isinstance(block.get("seed"), str):
        return "ranking.seed"
    clusters = _ranking_at(block, ("contexts", "clusters"))
    if not isinstance(clusters, list) or not all(isinstance(entry, str) for entry in clusters):
        return "ranking.contexts.clusters"
    return None


class _Controller:
    """The Phase 9 ranking controller as a routing policy: each request is routed to Algorithm 1's choice for its context
    (`app.services.ranking.selection.select` on the controller's state), then its verified outcome is applied as an
    `outcome` input (`controller.apply_in_place`); a fallback abstains. Without hysteresis, the promotion margin delta is 0
    and one batch suffices (n_d = 1). Each model is commissioned from its own outcomes on the commissioning items
    (`commission`: {model: {clean, failed, generated, mean_q}}, `commissioning`; VBT RevB Sec. VII: "Posteriors start from
    commissioning: alpha0 = 1 + clean responses and beta0 = 1 + failed ones"). It records every alarm (request index, CUSUM
    stream) and every incumbent switch (request index, context key, count)."""

    def __init__(self, block: Mapping[str, Any], models: Sequence[Mapping[str, Any]], *, hysteresis: bool,
                 commission: Mapping[str, Mapping[str, Any]]) -> None:
        from app.services.ranking.controller import apply_in_place
        from app.services.ranking.state import canonical, empty_state, params_of, sha256_hex

        self._apply = apply_in_place
        block = json.loads(json.dumps(block))
        if not hysteresis:
            block["promotion"] = {**block["promotion"], "delta": "0", "n_d": 1}
        self.state = empty_state()
        self.seq = 0
        self.alarms: list[tuple[int, str]] = []
        self.switches: list[tuple[int, str, int]] = []
        self.params_of = params_of
        self._input("config", {"package_version": "e4-replay", "package_sha256": "0" * 64, "parameters_sha256": sha256_hex(canonical(block)),
                               "parameters": block})
        for entry in models:  # cost units per call: one input and one output unit at the list prices, in thousandths
            per_call = (Decimal(entry["price_per_input_unit"]) + Decimal(entry["price_per_output_unit"])) * 1000
            self._input("model_seen", {"model": {"adapter_id": entry["model_id"], "family": entry["family"], "provider": entry["family"],
                                                 "model_id": entry["model_id"], "model_version": "e4", "cost_units_per_call": int(per_call)}})
        self._input("availability", {"models": {entry["model_id"]: None for entry in models}})
        for entry in models:  # each model's own commissioning outcomes, on items disjoint from the stream's
            record = commission[entry["model_id"]]
            self._input("commission", {"adapter_id": entry["model_id"], "version": "e4", "clean": int(record["clean"]),
                                       "failed": int(record["failed"]), "generated": int(record["generated"]),
                                       "mean_q": str(record["mean_q"]), "run_sha256": "0" * 64})
        self.clusters = set(self.params_of(self.state).clusters)

    def _input(self, kind: str, payload: Mapping[str, Any]) -> list:
        self.seq += 1
        return self._apply(self.state, {"seq": self.seq, "kind": kind, "payload": payload})

    def context(self, topic: str | None) -> dict[str, Any]:
        return {"cluster": topic if topic in self.clusters else "unscoped", "task_type": "explanation", "tier": 2}

    def key(self, topic: str | None) -> str:
        from app.services.ranking.types import Context

        return Context(**self.context(topic)).key()

    def eligible(self, topic: str | None) -> tuple[str, ...]:
        """The models eligible to generate in the request's context (Phase 9 `selection.eligible_set`: rating and tier)."""
        from app.services.ranking.selection import eligible_set, ensure_models

        params = self.params_of(self.state)
        key = self.key(topic)
        ensure_models(self.state, params, key)
        return eligible_set(self.state, params, key)

    def choose(self, t: int, topic: str | None) -> str | None:
        from app.services.ranking.selection import ensure_models, select

        params = self.params_of(self.state)
        key = self.key(topic)
        ensure_models(self.state, params, key)
        decision, _u = select(self.state, params, key, ledger_seq=t + 1)
        return decision.model if decision.kind != "fallback" else None

    def observe(self, t: int, topic: str | None, model: str, outcome: Outcome) -> None:
        before = int(self.state["counts"]["switches"])
        derived = self._input("outcome", {"ledger_seq": t + 1, "created_at": "2026-11-23T00:00:00.000000Z", "model": model,
                                          "context": self.context(topic), "y": outcome.y,
                                          "signals": {"V": format(outcome.quality, ".6f"), "S": None, "K": None, "H": "0", "F": None},
                                          "cost_units": int(round(outcome.cost * 1000)), "latency_ms": None, "tier_source": "v2"})
        self.alarms += [(t, payload["stream"]) for kind, payload in derived if kind == "alarm"]
        switched = int(self.state["counts"]["switches"]) - before  # an outcome input changes only its own context
        if switched:
            self.switches.append((t, self.key(topic), switched))


def ranking_replay_problem(block: Any, models: Sequence[Mapping[str, Any]]) -> str | None:
    """`ranking_problem`, then, for a ranking object, a dry run of the replay's controller policies on it before any
    request is sent: both controllers (`_Controller`, with and without hysteresis) are built over the design's models,
    each commissioned from one clean and one failed response, and route and learn from one outcome in every context
    (each cluster and the unscoped one); and eq. (8) (`_quality`, which the replay applies to each VLOOP response's own
    signals) is computed over the block's weights for every subset of the signals V, S, K and F, each at 0 and at 1 (a
    response's signals are decimals in [0, 1], `providers.response_problem`). A block whose values the ranking arithmetic
    refuses is `ranking`, so that no E4 run sends a request whose replay would then fail."""
    problem = ranking_problem(block)
    if problem is not None or block is None:
        return problem
    commission = {entry["model_id"]: {"clean": 1, "failed": 1, "generated": 2, "mean_q": "0.5"} for entry in models}
    try:
        for hysteresis in (True, False):
            controller = _Controller(block, models, hysteresis=hysteresis, commission=commission)
            for t, topic in enumerate([*sorted(controller.clusters), None]):
                controller.eligible(topic)
                model = controller.choose(t, topic)
                if model is not None:
                    controller.observe(t, topic, model, Outcome(y=t % 2, quality=0.5, cost=1.0, first_cost=1.0))
        weights = block["quality"]["weights"]
        for mask in range(1, 1 << len(_RANKING_WEIGHTS)):
            for value in ("0", "1"):
                signals = {name: value if mask >> index & 1 else None for index, name in enumerate(_RANKING_WEIGHTS)}
                _quality({"signals": {**signals, "H": "0"}}, "answer", weights)
    except (ArithmeticError, LookupError, TypeError, ValueError, AttributeError):
        return "ranking"
    return None


REPLAY_REFUSED = ("the ranking arithmetic refused eq. (8) on a VLOOP response's signals with the package's weights, so the "
                  "replay has no population")
DETECTION_RULE = ("MR-2's counting (plan 15.1): the degraded model's responses in the shifted topic, from the shift to the first "
                  "alarm on that model's CUSUM stream for the topic's context (model-cluster); every alarm before the shift is a "
                  "false alarm")
SWITCH_RULE = ("MR-3's counting (plan 15.1): incumbent switches per context per 1,000 drift-free requests, the requests before "
               "the shift")
CRITERION_NOTE = "figures under the criterion's counting rule, not its outcome: MR-2 and MR-3 are criteria_only and reported by the PI (DI-138)"


SHIFT_NOT_INJECTED = {
    "topic_absent": "the shift topic has no unit in the streams' population, so no shift is injected",
    "no_failed_outcome": "the shift model has no failed first pass in the shift topic among the streams' population, so it has no "
                         "failed outcome to inject",
    "no_clean_outcome": "the shift model fails every first pass in the shift topic among the streams' population, so its error "
                        "rate cannot be raised",
    "zero_points": "the shift raises the error rate by zero points",
}


def shift_injection(design: Mapping[str, Any], population: Mapping) -> tuple[list, float, str | None]:
    """(the shift model's failed units in the shift topic, the rate at which a clean outcome of it there is replaced by one
    of them, the reason no shift is injected or None). The rate is points / (1 - base error), capped at 1; it is 0, with
    the reason (`SHIFT_NOT_INJECTED`), when the topic has no unit in `population`, the model has no failed or no clean
    first pass there, or the points are zero."""
    shift = design["shift"]
    in_topic = [unit for unit in sorted(population, key=lambda u: (u[0], u[1] or "")) if population[unit]["topic"] == shift["topic"]]
    failed = [unit for unit in in_topic if population[unit]["outcomes"][shift["model"]].y == 0]
    points = Fraction(shift["points"])
    reason = ("topic_absent" if not in_topic else "no_failed_outcome" if not failed else
              "no_clean_outcome" if len(failed) == len(in_topic) else "zero_points" if points == 0 else None)
    if reason is not None:
        return failed, 0.0, reason
    return failed, min(1.0, float(points) / (1 - len(failed) / len(in_topic))), None


def _replay_stream(plan: Any, population: Mapping, units: Sequence, models: Sequence[str], seed: str, *,
                   commission: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """One stream: `stream_length` requests drawn (seeded) from `units`, the injected shift, and every policy replayed.
    `commission` is each model's commissioning record (`commissioning`), read by the controller and by cheapest-eligible's
    eligibility."""
    design = plan.extra["design"]["design"]
    models = sorted(models)
    length = int(design["stream_length"])
    shift = design["shift"]
    shift_model, shift_topic, shift_at = shift["model"], shift["topic"], int(shift["at"])
    failed, rate, _reason = shift_injection(design, population)
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
    by_cost = sorted(models, key=lambda model: (pool[model][1], model))  # the pool's cost at the list prices, cheapest first
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
            controller = _Controller(block, plan.extra["design"]["design"]["models"], hysteresis=policy == "controller",
                                     commission=commission)
            affected = f"model-cluster:{shift_model}:{controller.context(shift_topic)['cluster']}"
            drift_free: dict[str, int] = {}
        commissioned = None
        if policy == "cheapest-eligible":
            # VBT RevB Sec. VII: a model below rating B is "ineligible to generate"; the baseline routes to the cheapest
            # model the commissioned controller holds eligible in the request's context, and abstains (a fallback, as the
            # controller does) when none is. Its eligibility is the commissioning's: the baseline does not learn.
            if not isinstance(block, Mapping):
                results[policy] = {"status": "no_ranking_block"}
                continue
            commissioned = _Controller(block, plan.extra["design"]["design"]["models"], hysteresis=True, commission=commission)
        means: dict[str, list[float]] = {model: [0.0, 0.0] for model in models}
        arms: dict[tuple[str, str | None], list[float]] = {}
        for t, (unit, topic, outcomes) in enumerate(stream):
            spent = 0.0
            if controller is not None:
                if t < shift_at:
                    drift_free[controller.key(topic)] = drift_free.get(controller.key(topic), 0) + 1
                model = controller.choose(t, topic)
                if model is None:
                    continue
                controller.observe(t, topic, model, outcomes[model])
                if t >= shift_at and model == shift_model and topic == shift_topic:
                    degraded_seen += 1
                if delay is None and any(at >= shift_at and stream_name == affected for at, stream_name in controller.alarms):
                    delay = degraded_seen
            elif policy == "static-best":
                model = static_best
            elif policy == "round-robin":
                model = models[t % len(models)]
            elif policy == "cheapest-eligible":
                eligible = set(commissioned.eligible(topic))
                model = next((name for name in by_cost if name in eligible), None)
                if model is None:
                    continue
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
                for model in by_cost:
                    if outcomes[model].y == 1 or model == by_cost[-1]:
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
            before_shift: dict[str, int] = {}
            for at, key, count in controller.switches:
                if at < shift_at:
                    before_shift[key] = before_shift.get(key, 0) + count
            results[policy].update(
                detection_delay=delay, false_alarms=sum(1 for at, _stream in controller.alarms if at < shift_at),
                switches=int(controller.state["counts"]["switches"]), alarms=int(controller.state["counts"]["alarms"]),
                switches_per_1000_drift_free={key: 1000 * before_shift.get(key, 0) / count for key, count in sorted(drift_free.items())})
    return {"policies": results, "static_best": static_best, "shift_rate": rate}


COMMISSIONING_RULE = ("commissioning-holdout-v1: the first `commissioning_items` replay items in sha256(seed, item) order are held "
                      "out with all their units; each model is commissioned from its own outcomes on them (clean: first pass "
                      "clean, failed: not, mean_q: the mean delivered quality), and the streams draw only the other items")
COMMISSIONING_STAND_IN = ("VBT RevB Sec. VII: \"Commissioning therefore uses the 30-item pilot plus the golden set (80 items)\"; "
                          "\"In the replay, commissioning and evaluation use disjoint items.\" No pilot or golden-set responses of "
                          "the four models exist, so the harness holds out run items instead, and the streams lose those items "
                          "(DI-148)")
STREAM_FLOOR_RULE = ("the streams keep at least `min_stream_items` items after the hold-out (120, the smallest ULQS AC-10-1 admits: "
                     "\"120-200 items across S1-S7\", VBT RevB p. 15, Sec. VIII-B; PD-75): a live run or a run over research data whose live "
                     "items less `commissioning_items` fall below it is refused (`e4_stream_items_below_floor`), and a replay "
                     "whose streams' population falls below it is flagged (`below_floor`)")


def stream_floor_refusals(design: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> list[str]:
    """`e4_stream_items_below_floor` when the live items left for the streams after the `commissioning_items` hold-out are
    fewer than `min_stream_items` (STREAM_FLOOR_RULE); the planner applies it to a live run or a run over research data."""
    live = sum(1 for item in items if item.get("status") != "retired")
    return ["e4_stream_items_below_floor"] if live - int(design["commissioning_items"]) < int(design["min_stream_items"]) else []


def commissioning_split(plan: Any, population: Mapping) -> tuple[dict, dict]:
    """(the held-out commissioning units, the streams' population): the first `commissioning_items` items of the population
    in sha256(seed, item) order, with all their units, are held out (COMMISSIONING_RULE), so that commissioning and
    evaluation use disjoint items."""
    count = int(plan.extra["design"]["design"]["commissioning_items"])
    seed = _seed(plan, "E4-commissioning")
    items = sorted({unit[0] for unit in population}, key=lambda item: (hashed_hex(seed, item), item))
    held = set(items[:count])
    return ({unit: value for unit, value in population.items() if unit[0] in held},
            {unit: value for unit, value in population.items() if unit[0] not in held})


def commissioning(held_out: Mapping, models: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Each model's commissioning record from its own outcomes on the held-out units: {clean, failed, generated, mean_q},
    the Phase 9 `commission` input (alpha0 = 1 + clean, beta0 = 1 + failed, the quality estimate mean_q)."""
    records = {}
    for model in models:
        outcomes = [held_out[unit]["outcomes"][model] for unit in sorted(held_out, key=lambda u: (u[0], u[1] or ""))]
        clean = sum(outcome.y for outcome in outcomes)
        mean = sum(outcome.quality for outcome in outcomes) / len(outcomes) if outcomes else 0.0
        records[model] = {"clean": clean, "failed": len(outcomes) - clean, "generated": len(outcomes), "mean_q": format(mean, ".6f")}
    return records


def _h4a_difference(result: Mapping[str, Any]) -> float:
    """H4a's statistic on one stream: the controller's verified quality per price minus the larger of static-best's and
    round-robin's (-inf when one of them delivered at no cost, which the one-sided share counts at or below 0)."""
    policies = result["policies"]
    values = [policies.get(name, {}).get("quality_per_price") for name in ("controller", "static-best", "round-robin")]
    if any(value is None for value in values):
        return float("-inf")
    return values[0] - max(values[1], values[2])


def _pending(pairs: Sequence[tuple[Any, Mapping[str, Any]]], select: Callable[[Any], bool]) -> bool:
    """Whether a completed replicate-1 response the selection covers holds a claim without a human label."""
    return _labels_pending([(request, response) for request, response in pairs if request.replicate == 1 and select(request)])


def _percentiles(values: Sequence[int]) -> dict[str, Any]:
    """The median (the mean of the two middle values for an even count) and the nearest-rank 95th percentile."""
    ordered = sorted(values)
    n = len(ordered)
    middle = n // 2
    median = ordered[middle] if n % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {"n": n, "median": median, "p95": ordered[max(0, -(-95 * n // 100) - 1)], "rule": "median-and-nearest-rank-p95-v1"}


def _latency(rows: Sequence[tuple[Any, Mapping[str, Any]]]) -> dict[str, Any]:
    """VBT RevB Sec. VIII-D: "Latency is recorded as time to first token and total time (median and 95th percentile)",
    from each completed response's `latency` {first_token_ms, total_ms} (non-negative integers, first token not after
    the total); a response without one is counted as not recorded."""
    first, total = [], []
    for _request, response in rows:
        value = response.get("latency")
        if (isinstance(value, Mapping) and set(value) == {"first_token_ms", "total_ms"}
                and all(isinstance(value[key], int) and not isinstance(value[key], bool) and value[key] >= 0 for key in value)
                and value["first_token_ms"] <= value["total_ms"]):
            first.append(value["first_token_ms"])
            total.append(value["total_ms"])
    if not first:
        return {"status": "not_recorded", "responses": len(rows)}
    return {"time_to_first_token_ms": _percentiles(first), "total_time_ms": _percentiles(total), "not_recorded": len(rows) - len(first)}


def compute_e4(plan: Any, responses: Sequence[Mapping[str, Any]]) -> tuple[dict, dict, dict]:
    design = plan.extra["design"]["design"]
    pairs = list(zip(plan.requests, responses))
    models = [entry["model_id"] for entry in design["models"]]
    local = next(entry["model_id"] for entry in design["models"] if entry["local"])
    prices = prices_of(design)
    metrics: dict[str, Any] = {"cells": {}, "cost": {}, "latency": {}}
    for model in models:
        for arm in ("GATE", "VLOOP"):
            rows = [(request, response) for request, response in pairs if request.cell == model and request.arm == arm and request.replicate == 1]
            done = [(request, response) for request, response in rows if _done(response)]
            metrics["latency"][f"{model}|{arm}"] = _latency(done)
            if _labels_pending(done):
                metrics["cells"][f"{model}|{arm}"] = {"status": "awaiting_labels", "units": len(rows)}
                continue
            errors = answerable_item_errors(rows, lambda request: True)
            metrics["cells"][f"{model}|{arm}"] = {
                "units": len(rows), "provider_failures_excluded": len(rows) - len(done),
                "item_error_answerable": statistics.wilson_interval(sum(errors.values()), len(errors)),
                "answer_rate": statistics.wilson_interval(sum(1 for request, response in done if request.gold == "answer"
                                                              and response.get("outcome") == "answered"),
                                                          sum(1 for request, _response in done if request.gold == "answer"))}
        done = [response for request, response in pairs if request.cell == model and request.replicate == 1 and _done(response)]
        units = [_units(response) for response in done]
        cost = {"responses": len(done), "input_units": sum(i for i, _o in units), "output_units": sum(o for _i, o in units),
                "cost": sum(_cost(response, prices[model]) for response in done)}
        if model == local:
            # "local cost is reported separately as measured energy plus amortized hardware" (VBT RevB Sec. VIII-D): the
            # replay prices the local model by its spec-stated per-unit stand-in (PD-75); the measured cost is the
            # operator's `local_cost`, when supplied (DI-148).
            measured = design.get("local_cost")
            cost.update(basis="per-unit stand-in for measured energy plus amortized hardware (PD-75)",
                        measured={"status": "not_measured", "needs": "measured energy plus amortized hardware (DI-148)"} if measured is None
                        else {"energy": measured["energy"], "amortized_hardware": measured["amortized_hardware"],
                              "total": str(Decimal(measured["energy"]) + Decimal(measured["amortized_hardware"]))})
            metrics["local_cost"] = {"model": local, **cost}
        else:
            metrics["cost"][model] = {**cost, "basis": "logged input and output units at the list prices"}
    variance = _cell_replicate_variance(plan, pairs)
    hypotheses = _hypotheses(plan)
    results: dict[str, Any] = {}
    replay_pending = _pending(pairs, lambda request: True)  # H4a replays every model's GATE and VLOOP responses
    replay_refused = None
    if not replay_pending:
        try:
            population, excluded, prices = _replay_population(plan, responses)
            metrics["replay"] = {"units": len(population), "excluded_units": excluded}
        except ArithmeticError as error:
            # `ranking_replay_problem` refuses, before any request, a ranking block whose eq. (8) arithmetic fails on
            # signals in [0, 1]; should a response's quality still be refused here, the replay is reported undefined,
            # never the last-resort exit 10.
            replay_refused = {"status": "undefined", "reason": REPLAY_REFUSED, "error": type(error).__name__}
            metrics["replay"] = replay_refused
    else:
        metrics["replay"] = {"status": "awaiting_labels"}
    for name, hypothesis in hypotheses.items():
        base = {"endpoint": hypothesis["endpoint"], "comparison": list(hypothesis["comparison"]), "test": hypothesis["test"]}
        if name == "H4a":
            if replay_pending:
                results[name] = {**base, "status": "awaiting_labels", "needs": "every model's GATE and VLOOP responses labelled (replicate 1)"}
                continue
            if replay_refused is not None:
                results[name] = {**base, **replay_refused}
                continue
            results[name] = {**base, **_h4a(plan, population, prices, hypothesis), "margin": hypothesis["margin"]}
            later = {entry["model_id"]: entry["later_price"] for entry in design["models"] if entry.get("later_price")}
            if later:
                # "at both Gemini prices if runs straddle 1 January 2027": the replay again at the later list prices,
                # reported beside the registered result and not entering Holm.
                later_population, _excluded, later_prices = _replay_population(plan, responses, later=True)  # same qualities
                results[name]["at_later_prices"] = {"later_price": later, "enters_holm": False,
                                                    **_h4a(plan, later_population, later_prices, hypothesis)}
        elif name == "H4b":
            # H4b reads only the GATE responses of the local and the pilot-selected commercial model (VBT RevB Sec. VIII-D:
            # "Human claim labels for E4 cover at least the GATE responses of the local model and of the pilot-selected
            # commercial model, which H4b's error-rate comparison needs").
            compared = (local, design["pilot_commercial"])
            if _pending(pairs, lambda request: request.arm == "GATE" and request.cell in compared):
                results[name] = {**base, "status": "awaiting_labels", "needs": "the GATE responses of the local and the pilot-selected "
                                                                                 "commercial model labelled (replicate 1)"}
                continue
            left = answerable_item_errors(pairs, lambda request: request.cell == local and request.arm == "GATE")
            right = answerable_item_errors(pairs, lambda request: request.cell == design["pilot_commercial"] and request.arm == "GATE")
            results[name] = {**base, "local": local, "commercial": design["pilot_commercial"], **paired_by_item(left, right),
                             "tost": _h4b_tost(plan, pairs, local, hypothesis)}
    return metrics, {"family": "E4", "correction": "holm", "hypotheses": results, "holm": _holm(results),
                     "note": "the registered E4 family; H4b enters Holm through its exact McNemar test, and its TOST only when the "
                             "EQC reliability condition can be judged (ICC(2,k) and Cronbach's alpha are not implemented, DI-138); "
                             "MR-2, MR-3 and LQ-2 are reported without a family test (criteria_only)"}, variance


def _h4a(plan: Any, population: Mapping, prices: Mapping[str, tuple[float, float]], hypothesis: Mapping[str, Any]) -> dict[str, Any]:
    design = plan.extra["design"]["design"]
    if not population:
        return {"status": "undefined", "reason": "no unit has a verified outcome for every model"}
    held_out, population = commissioning_split(plan, population)
    commission = commissioning(held_out, sorted(prices))
    stream_items = len({unit[0] for unit in population})
    record = {"items": len({unit[0] for unit in held_out}), "units": len(held_out), "rule": COMMISSIONING_RULE,
              "stands_in_for": COMMISSIONING_STAND_IN, "models": commission, "stream_items": stream_items,
              "min_stream_items": int(design["min_stream_items"]), "below_floor": stream_items < int(design["min_stream_items"]),
              "floor_rule": STREAM_FLOOR_RULE}
    if not population:
        return {"status": "undefined", "reason": "no item is left for the streams after the commissioning items are held out",
                "commissioning": record}
    _failed, shift_rate, not_injected = shift_injection(design, population)
    shift = {"model": design["shift"]["model"], "topic": design["shift"]["topic"], "at": int(design["shift"]["at"]),
             "points": design["shift"]["points"], "rate": shift_rate}
    if not_injected is not None:
        # MR-2's figures need the injected degradation: without it every stream would read "not detected" as if the
        # controller had missed a real shift, so H4a is undefined and names why.
        return {"status": "undefined", "reason": SHIFT_NOT_INJECTED[not_injected], "shift_not_injected": not_injected,
                "shift": shift, "commissioning": record}
    groups: dict[str, list] = {}
    for unit in population:
        groups.setdefault(unit[0], []).append(unit)
    ordered = [sorted(groups[item], key=lambda unit: unit[1] or "") for item in sorted(groups)]
    seed = _seed(plan, "H4a")
    streams: list[dict[str, Any]] = []

    def difference(chosen: list, replicate: int | None) -> float:
        units = [unit for group in chosen for unit in group]
        result = _replay_stream(plan, population, units, sorted(prices), f"{seed}\x1fstream\x1f{'estimate' if replicate is None else replicate}",
                                commission=commission)
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
    runs = [result["policies"]["controller"] for result in streams if "detection_delay" in result["policies"].get("controller", {})]
    delays = [run["detection_delay"] for run in runs]
    detected = [delay for delay in delays if delay is not None]
    worst = [max(run["switches_per_1000_drift_free"].values()) for run in runs if run["switches_per_1000_drift_free"]]
    return {**share, "difference_interval_95": share["interval_95"], "streams": len(streams), "stream_length": int(design["stream_length"]),
            "commissioning": record, "quality_per_price": summary, "shift": shift,
            "detection": {"streams": len(runs), "shift_rate": shift_rate, "detected": len(detected), "within_100": sum(1 for delay in detected if delay <= 100),
                          "median_delay": sorted(detected)[len(detected) // 2] if detected else None,
                          "streams_with_false_alarms": sum(1 for run in runs if run["false_alarms"]), "rule": DETECTION_RULE,
                          "criterion": CRITERION_NOTE},
            "switches": {"streams": len(worst), "max_per_context_per_1000_drift_free": max(worst) if worst else None,
                         "streams_at_most_2": sum(1 for value in worst if value <= 2), "rule": SWITCH_RULE, "criterion": CRITERION_NOTE}}


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
            rows = [(request, response) for request, response in pairs
                    if request.cell == model and request.arm == arm and request.item_id in sampled and _done(response)]
            if _labels_pending(rows):
                variance[f"{model}|{arm}"] = {"status": "awaiting_labels"}
                continue
            by_replicate: dict[int, list[int]] = {}
            for request, response in rows:
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
    """(metrics, registered tests, replicate variance) of a design run. The family names its protocol: `registered`, or
    `departs_from_registration` with the departures (`departures`: the design's, `pins.design.departures`, then the
    execution protocol's, `pins.execution.departures`; only a synthetic run may depart), and the hypotheses
    still waiting for an input (`pending`), whose p-values Holm has not yet seen."""
    experiment = plan.spec["experiment"]
    if experiment == "E2":
        metrics, registered = compute_e2(plan, responses)
        result = (metrics, registered, _verifier_replicate_variance(plan, responses))
    else:
        result = compute_e3(plan, responses) if experiment == "E3" else compute_e4(plan, responses)
    registered = result[1]
    found = list(plan.extra["design"].get("departures") or []) + list((plan.pins.get("execution") or {}).get("departures") or [])
    registered["protocol"] = "departs_from_registration" if found else "registered"
    registered["departures"] = found
    registered["pending"] = sorted(name for name, value in registered["hypotheses"].items()
                                   if str(value.get("status", "")).startswith("awaiting_"))
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
    """`stub-responder-v1` for an E3 generation. The evidential pass and each single-pass generation answer when b[0] <
    240, keeping each gold claim unless b[1 + i] % 8 == 0, citing the unit's evidence; a two-pass presentation pass
    answers with exactly the locked claims it was sent (`request.locked`), as the two-pass design reuses them at every
    level. Presentation features come from b[20..23]."""
    digest = hashlib.sha256(prefix + request.request_key.encode("utf-8")).digest()
    text = "stub:" + request.request_key[:16]
    usage = {"input_units": 1, "output_units": 1}
    features = {"fk_grade": 4 + digest[20] % 9, "guiding_questions": digest[21] % 3, "prerequisite_recaps": digest[22] % 2,
                "length": 60 + digest[23]}
    if getattr(request, "role", None) == "two-pass":
        claims = [{"claim_id": claim_id, "cited": list(cited), "label": "supported", "ehmf_type": None}
                  for claim_id, cited in getattr(request, "locked", ())]
        return {"outcome": "answered", "claims": claims, "features": features, "text": text, "usage": usage, "model_id": None}
    if digest[0] >= 240:
        return {"outcome": "abstained", "claims": [], "text": text, "usage": usage, "model_id": None}
    claims = [{"claim_id": claim_id, "cited": list(request.evidence), "label": "supported", "ehmf_type": None}
              for index, claim_id in enumerate(request.gold_claims) if digest[1 + index % 19] % 8]
    return {"outcome": "answered", "claims": claims, "features": features, "text": text, "usage": usage, "model_id": None}


def stub_dispatch(prefix: bytes, request: Any, answer: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    role = getattr(request, "role", "answer")
    if role == "verify":
        return stub_verdict(prefix, request)
    if role in ("two-pass-evidential", "two-pass", "single-pass"):
        return stub_generation(prefix, request)
    return answer(prefix, request, **kwargs)

