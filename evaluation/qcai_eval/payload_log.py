"""Provider payload logs: pointers, hashes and sizes only, never span or item text (spec 3.11, 4.11; AC-10-6; PD-72).

Each line has exactly `LOG_KEYS`; every string value matches an id, hex, enumeration or null pattern, so there is no field
a text could travel in. `validate_log_record` runs before every write, and a violation aborts the run (exit 3).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

PROVISIONAL_DEFAULTS = ("PD-72",)  # Phase 10 spec 12.1; ratified under DI-140

LOG_FORMAT = "payload-log-v1"
LOG_KEYS = frozenset({"log", "purpose", "run_id", "request_key", "arm", "item_id", "unit", "replicate", "seed_hex", "prompt_version",
                      "prompt_sha256", "prompt_bytes", "evidence", "response_sha256", "response_bytes", "outcome", "failure_reason",
                      "attempts", "model_id", "cost_units", "role", "cell"})
EVIDENCE_KEYS = frozenset({"pointer", "content_sha256", "bytes"})
ID = r"^[a-z0-9][a-z0-9.+:-]{0,63}$"
PATTERNS = {
    "log": re.compile(rf"^{LOG_FORMAT}$"),
    "purpose": re.compile(r"^(exploratory|confirmatory)$"),
    "run_id": re.compile(ID),
    "request_key": re.compile(r"^[0-9a-f]{64}$"),
    "arm": re.compile(r"^(NR|LEX|SEM|GATE|GATE\+SV|GATE\+V1|VLOOP)$"),
    "item_id": re.compile(r"^(ULQS|SYN)-[A-G]-[0-9]{3,}$"),
    "unit": re.compile(r"^((ULQS|SYN)-F-[0-9]{3,}-t[0-9]+|beginner|intermediate|advanced)$"),
    "seed_hex": re.compile(r"^[0-9a-f]{16}$"),
    "prompt_version": re.compile(ID),
    "prompt_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "response_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "outcome": re.compile(r"^(answered|abstained|provider_failure)$"),
    "failure_reason": re.compile(r"^(timeout|rate_limited|server_error|refused_payload|recorded_missing)$"),
    "model_id": re.compile(ID),
    "role": re.compile(r"^(answer|verify|two-pass-evidential|two-pass|single-pass)$"),
    "cell": re.compile(ID),
}
NULLABLE = frozenset({"unit", "response_sha256", "failure_reason", "model_id", "cell"})
INTEGERS = ("replicate", "prompt_bytes", "response_bytes", "attempts", "cost_units")
POINTER = re.compile(r"^(EV-(2025|2026|IND|SYN)-p[0-9]{3}-[0-9]{2}|span-[0-9a-f]{64})$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PayloadLogViolation(ValueError):
    """A payload-log record outside the whitelist (the message names the key, never the value)."""


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_log_record(record: Mapping[str, Any]) -> None:
    if set(record) != LOG_KEYS:
        raise PayloadLogViolation(f"keys differ: {sorted(set(record) ^ LOG_KEYS)}")
    for key, pattern in PATTERNS.items():
        value = record[key]
        if value is None and key in NULLABLE:
            continue
        if not isinstance(value, str) or not pattern.match(value):
            raise PayloadLogViolation(f"{key}: not an id, hex or enumeration value")
    for key in INTEGERS:
        if not _integer(record[key]) or record[key] < 0:
            raise PayloadLogViolation(f"{key}: not a non-negative integer")
    if not isinstance(record["evidence"], list):
        raise PayloadLogViolation("evidence: not a list")
    for index, entry in enumerate(record["evidence"]):
        if not isinstance(entry, Mapping) or set(entry) != EVIDENCE_KEYS:
            raise PayloadLogViolation(f"evidence[{index}]: keys differ")
        if not isinstance(entry["pointer"], str) or not POINTER.match(entry["pointer"]):
            raise PayloadLogViolation(f"evidence[{index}].pointer: not a pointer")
        if not isinstance(entry["content_sha256"], str) or not HEX64.match(entry["content_sha256"]):
            raise PayloadLogViolation(f"evidence[{index}].content_sha256: not hex")
        if not _integer(entry["bytes"]) or entry["bytes"] < 1:
            raise PayloadLogViolation(f"evidence[{index}].bytes: not a positive integer")


def log_record(request: Any, response: Mapping[str, Any], *, run_id: str, purpose: str, prompt_version: str, prompt_bytes: bytes,
               resolver: Any) -> dict[str, Any]:
    evidence = []
    for pointer in request.evidence:
        evidence.append({"pointer": pointer, "content_sha256": resolver.content_hash(pointer), "bytes": resolver.byte_length(pointer)})
    text = response.get("text")
    encoded = text.encode("utf-8") if isinstance(text, str) else None
    usage = response.get("usage") or {}
    return {
        "log": LOG_FORMAT,
        "purpose": purpose,
        "run_id": run_id,
        "request_key": request.request_key,
        "arm": request.arm,
        "item_id": request.item_id,
        "unit": request.unit,
        "replicate": request.replicate,
        "seed_hex": request.seed_hex,
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "evidence": evidence,
        "response_sha256": None if encoded is None else hashlib.sha256(encoded).hexdigest(),
        "response_bytes": 0 if encoded is None else len(encoded),
        "outcome": response["outcome"],
        "failure_reason": response.get("failure_reason"),
        "attempts": len(response.get("attempts", [])),
        "model_id": response.get("model_id"),
        "cost_units": int(usage.get("input_units", 0)) + int(usage.get("output_units", 0)),
        "role": getattr(request, "role", "answer"),
        "cell": getattr(request, "cell", None),
    }
