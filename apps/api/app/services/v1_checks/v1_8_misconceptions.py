"""V1.8, the misconception library (rule misconception-all-terms-v1; plan Phase 4 D: "misconception library match",
EHMF C, "flag, queue V3"; plan 7.2 "V1.8 match --> V3"; Phase 4 spec 4.9 and conflict 12).

The library is versioned and content-hashed: inline in configuration packages v3 to v5 (`v1.v1_8.library`, library v0,
whose sha256 is the canonical sha256 of the library object without its sha256 field) and, from package v6 (Phase 7), the
library v1 file config_package/misconceptions/v1.json that `v1.v1_8.library` pins (ehmf.library; checked at load). Q-14
(the seed list, A-18) is unavailable, so the library ships empty: V1.8 then passes every claim. An entry matches a claim when every one of its
terms (at least two; lowercase, sorted, unique) is a token of the claim (negation cues and numbers count as tokens). A
match flags the claim (never hard), which withholds it before Phase 5 (13.6) and gives it a V3 intent
(v1_8_misconception). Tests pass a fixture library to the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.tutor_pipeline.contracts import CheckResult, LockedClaimSet
from app.services.v1_checks.lexicon import tokens
from app.services.v1_checks.results import make_result

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


@dataclass(frozen=True)
class MisconceptionEntry:
    entry_id: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class MisconceptionLibrary:
    version: str
    sha256: str
    entries: tuple[MisconceptionEntry, ...]
    # Phase 7: an unavailable library is an EHMF detector down under EHMF=on (ehmf.detectors; spec 4.3).
    available: bool = True


def load_library(package: "ConfigPackage") -> MisconceptionLibrary:
    """The package's library (its sha256 was checked when the package loaded)."""
    if package.v1 is None:
        raise ValueError("the configuration package has no v1 block")
    v1 = package.v1
    return MisconceptionLibrary(
        version=v1.library_version,
        sha256=v1.library_sha256,
        entries=tuple(MisconceptionEntry(entry_id=entry.entry_id, terms=entry.terms) for entry in v1.library_entries),
    )


def matches(text: str, entry: MisconceptionEntry) -> bool:
    found = set(tokens(text))
    return all(term in found for term in entry.terms)


def check_v1_8(locked: LockedClaimSet, library: MisconceptionLibrary, *, attempt: int) -> tuple[CheckResult, ...]:
    return tuple(
        make_result("V1.8", "pre_render", attempt,
                    "misconception_match" if any(matches(claim.text, entry) for entry in library.entries) else "no_match",
                    claim_id=claim.claim_id)
        for claim in locked.claims
    )
