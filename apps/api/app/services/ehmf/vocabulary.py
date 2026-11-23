"""The EHMF vocabulary (plan Phase 7 D task 1; plan 6.3; plan Phase 4 D table; Phase 7 spec 3.1).

The only definition of the five error-handling-and-mitigation-framework types and their subtypes: every other module
imports them from here (a guard test scans the application for another definition). Standard library only, so the
record contracts and the configuration-package loader can import it.
  A  a claim that contradicts or is not supported by its sources (revise or abstain)
  B  a citation fault: B1 an unresolvable or invented citation (final, never repaired), B2 a real span that does not
     support the claim (re-cite or abstain)
  C  a misconception or a misleading analogy (bind the step or label the analogy)
  D  a conflict between sources, or content the sources did not state (precedence plus disclosure)
  E  a presentation fault (regenerate the pedagogical pass)
The plan's weights (plan 6.3 "A=1.0, B=1.0, C=0.6, D=0.6, E=0.4"; plan Phase 7 A "D 0.6 (0 when disclosed)") are
configuration (package v6 ehmf.weights); PLAN_WEIGHTS holds them as decimal strings only so that the loader can bind the
package's values to them while the PI's decision is open (PD-41).
"""

from __future__ import annotations

EHMF_VERSION = "ehmf-v1"
EHMF_TYPES = ("A", "B", "C", "D", "E")                      # plan E-87; the only value tuple of the five types
SUBTYPES = {"B": ("B1", "B2")}                              # B1 unresolvable or invented citation; B2 a real span that does not support the claim
FINDING_TYPES = ("A", "B1", "B2", "C", "D", "E")
TYPE_OF = {"A": "A", "B1": "B", "B2": "B", "C": "C", "D": "D", "E": "E"}
PRIMARY_ORDER = ("B1", "A", "B2", "D", "C", "E")            # tie-break among equal weights (most severe first)
PLAN_TYPES_BY_CHECK = {"V1.1": ("B",), "V1.2": ("A", "B"), "V1.3": ("A", "B", "C"), "V1.4": ("D", "E"), "V1.5": ("A",),
                       "V1.6": ("E",), "V1.7": ("D",), "V1.8": ("C",), "V1.9": ("E",)}     # plan Phase 4 D table (verbatim)
PLAN_WEIGHTS = {"A": "1.0", "B": "1.0", "C": "0.6", "D": "0.6", "D_disclosed": "0", "E": "0.4"}   # plan L1504, L682 (decimal strings: Fraction(value) is exact)
ROUTING_VERSION = "ehmf-routing-v1"
MITIGATIONS = {"A": "revise_or_abstain", "B1": "final", "B2": "recite_or_abstain", "C": "bind_step_or_label_analogy",
               "D": "precedence_plus_disclosure", "E": "regenerate_pedagogical_pass"}   # plan task 1
OWNERS = {"A": "ml_engineer", "B1": "ml_engineer", "B2": "ml_engineer", "C": "content_owner", "D": "content_owner", "E": "ml_engineer"}
TELEMETRY = {name: f"ehmf.type.{name}" for name in FINDING_TYPES}
DETECTOR_KINDS = ("deterministic", "checker", "library", "panel", "alignment")
EHMF_FIRST_MAJOR = 6                                        # the first package with an ehmf block (renumbered with E16)
PRE_PHASE_7 = "pre-phase-7"                                 # plan G
PRECEDENCE_RULE = "precedence-v1"
DISCLOSURE_TEMPLATE = "conflict-disclosure-v2"
LIBRARY_SCHEMA = "misconception-library-v1"
GOLDEN_SET_VERSION = "golden-set-v1"
STOP_RULE = "rising-ab-after-config-change-v1"
PENALTY_RULE = "span-penalty-rank-v1"
EHMF_DETECTOR_DOWN = "ehmf_detector_down"
EHMF_SET_CHANGED = "ehmf_set_changed"
