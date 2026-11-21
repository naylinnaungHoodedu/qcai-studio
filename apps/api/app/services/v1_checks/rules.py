"""The rule ids and fixed constants of the V1 checks (plan Phase 4 D; Phase 4 spec 4.1).

Every numeric literal the V1 checks use, other than 0, 1 and -1, lives in this module (an AST test scans
v1_checks/*.py). Thresholds, bands and lexicon lists are configuration values (configuration package v3 `v1`,
R-46), read through V1Params; what is here is the rule vocabulary itself, and v1_rules_hash pins it in the package
(`v1.rules_hash`), so a rule changed under its old id is a package_check failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.config_package import canonical_sha256
from app.services.claim_gate import SUBSET_CHECK_RULE

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage, V1Params

RULES_VERSION = "v1-checks-v1"
RULE_IDS: dict[str, str] = {
    "V1.1": "span-resolution-current-v1",
    "V1.2": "binding-polarity-v1",
    "V1.3": "entailment-interface-v1",
    "V1.4": SUBSET_CHECK_RULE,
    "V1.5": "gate-decision-margin-v2",
    "V1.6": "keyed-answer-containment-v1",
    "V1.6-omit": "keyed-answer-socratic-omit-v1",
    "V1.7": "conflict-version-polarity-v1",
    "V1.8": "misconception-all-terms-v1",
    "V1.9": "schema-forbid-v1",
    "V1.9-band": "fk-grade-segments-v1",
}
# The polarity sub-rule of V1.2 (E-27: the legacy gate's stopwords stripped negation; this rule never does).
POLARITY_RULE = "quantity-negation-polarity-v1"
# V1.6's assessment-context rule (a hyphenated item id in the turn, or prompt similarity).
ASSESSMENT_RULE = "prompt-containment-or-jaccard-v1"
# Plan 18.4 D-20, applied as its own text while the decision is open (PD-13).
D20_RULE = "withhold-all-flagged-v1"
# Flesch-Kincaid grade: 0.39 * words per sentence + 11.8 * syllables per word - 15.59.
FK = (0.39, 11.8, 15.59)
SYLLABLE_RULE = "vowel-groups-silent-e-v1"
WORD_PATTERN = r"[a-z0-9]+(?:['’][a-z]+)?"
QUANTITY_PATTERN = r"(?<![\w.])(?P<number>\d+(?:[.,]\d+)*)(?:\s*(?P<unit>%|[a-zµμ]+))?"
ALPHA_PATTERN = r"[A-Za-z]+"
KEY_STRIP_PATTERN = r"[^\w\s]"
VOWEL_GROUP_PATTERN = r"[aeiouy]+"
SILENT_E_EXCEPTIONS = ("le", "ee")
# D-21 is open: no checker hosting exists, so the only checker that can be wired is the NullChecker ("none").
WIRED_CHECKERS = frozenset({"none"})
NULL_CHECKER_ID = "none"
# A short key ("b", "3", "yes") designates a choice by letter or position; it is matched only as that choice's text.
CHOICE_LETTERS = ("a", "b", "c", "d")
CHOICE_DIGITS = ("1", "2", "3", "4")
# The plan's regeneration bound (plan Phase 4 D "regen <= 2"; 7.2 "regenerate (<= 2)") caps attempts at three.
MAX_ATTEMPTS = 3
MAX_VERDICTS = 20
MAX_DISCLOSED_CONFLICTS = 20
MAX_CONFLICT_SPANS = 12
# V1.7 compares the parity of two sentences' negation-cue counts ("not ... not" reads as no negation), pair by pair.
PARITY = 2
PAIR = 2
# Units and rounding of what V1 records and logs (not thresholds).
MS_PER_S = 1000.0
SCORE_DIGITS = 3
RATE_DIGITS = 6
# The in-process V1 latency histogram (V1_METRICS) and the nearest-rank p95 window (plan Phase 4 I).
LATENCY_BUCKETS_MS = (1, 2, 5, 10, 20, 50, 100, 250, 500, 1000)
LATENCY_WINDOW = 1024
P95 = 0.95
# v1_checks/package_check.py sits this many directories below the repository root (the fixture file's base).
REPOSITORY_DEPTH = 5


def lexicon_payload(v1: "V1Params") -> dict[str, Any]:
    lexicon = v1.lexicon
    return {
        "negation_cues": sorted(lexicon.negation_cues),
        "negation_suffixes": list(lexicon.negation_suffixes),
        "number_words": sorted(lexicon.number_words),
        "units": sorted(lexicon.units),
        "min_alignment_term_chars": lexicon.min_alignment_term_chars,
    }


def v1_rules_hash_for(v1: "V1Params") -> str:
    """The hash of the rule vocabulary and the package's lexicon: what v1.rules_hash must equal."""
    return canonical_sha256(
        {
            "rule_ids": RULE_IDS,
            "polarity": POLARITY_RULE,
            "assessment": ASSESSMENT_RULE,
            "d20": D20_RULE,
            "fk": list(FK),
            "patterns": [WORD_PATTERN, QUANTITY_PATTERN, ALPHA_PATTERN, KEY_STRIP_PATTERN],
            "lexicon": lexicon_payload(v1),
            "syllables": [SYLLABLE_RULE, VOWEL_GROUP_PATTERN, list(SILENT_E_EXCEPTIONS)],
        }
    )


def v1_rules_hash(package: "ConfigPackage") -> str:
    if package.v1 is None:
        raise ValueError("the configuration package has no v1 block (package v3 is required)")
    return v1_rules_hash_for(package.v1)
