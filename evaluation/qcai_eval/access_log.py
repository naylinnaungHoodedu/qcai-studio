"""The research-plane access log (`access-log-v1`; spec 3.11; PD-72): roles, actions and artifact hashes, no names, no text.

Lines are appended, never rewritten. The runner, the migrator, the validator and the fingerprint builder require
`--access-log PATH` whenever their inputs are not all synthetic, and the research-log scanner whenever it reads research
fingerprints; with it, the actor's role (`--actor-role`, the migrator's `--author-role`). Each of these five scripts logs
every research-plane input as soon as it is read, before any check that can refuse, and every artifact it writes; the
runner also logs the run's start and its outcome (completed, interrupted or refused), so a run that ended early still
leaves its reads in the log.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .canonical import dumps_line

PROVISIONAL_DEFAULTS = ("PD-72",)
ROLES = ("PI", "MLE", "DS", "RL", "RV")
ACTIONS = ("read", "write", "run", "export")
KINDS = ("ulqs_items", "evidence_catalog", "corpus_text", "ratings", "licensed_text", "fingerprints", "agreement_record",
         "freeze_record", "scan_report", "scan_target", "run_spec", "recording", "run_output", "irb_record", "osf_record",
         "governance_record", "agent_check_record")
OUTCOMES = ("started", "completed", "interrupted", "refused")


def append(path: Path, *, actor_role: str, action: str, artifact_kind: str, artifact_sha256: str, purpose: str,
           run_id: str | None = None, outcome: str | None = None) -> None:
    if actor_role not in ROLES or action not in ACTIONS or artifact_kind not in KINDS:
        raise ValueError("access log: role, action or artifact kind outside the vocabulary")
    if (outcome is None) != (action != "run") or (outcome is not None and outcome not in OUTCOMES):
        raise ValueError("access log: a run line carries an outcome, and only a run line does")
    line = {"log": "access-log-v1", "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "actor_role": actor_role,
            "action": action, "artifact_kind": artifact_kind, "artifact_sha256": artifact_sha256, "purpose": purpose}
    if run_id is not None:
        line["run_id"] = run_id
    if outcome is not None:
        line["outcome"] = outcome
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps_line(line))
