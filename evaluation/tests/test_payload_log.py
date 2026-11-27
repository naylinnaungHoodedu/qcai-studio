"""Phase 10: the payload-log whitelist (spec 3.11, 4.11; AC-10-6; PD-72)."""

from __future__ import annotations

import copy

import pytest

from evaluation.qcai_eval import synthetic
from evaluation.qcai_eval.payload_log import EVIDENCE_KEYS, LOG_KEYS, PayloadLogViolation, log_record, validate_log_record
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver
from evaluation.qcai_eval.runner import Request


def good_record(evidence=("EV-SYN-p001-01",), unit=None):
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    resolver = PointerResolver(catalog=EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items)))
    request = Request(request_key="a" * 64, arm="NR" if not evidence else "GATE", item_id="SYN-A-001", unit=unit, turn_depth=None,
                      replicate=1, seed_hex="b" * 16, evidence=tuple(evidence), gold="answer", gold_claims=("SYN-A-001-c1",))
    response = {"outcome": "answered", "failure_reason": None, "attempts": [{"status": "ok"}], "claims": [], "text": "stub:x",
                "usage": {"input_units": 1, "output_units": 1}, "model_id": None}
    return log_record(request, response, run_id="synthetic-stub-v1", purpose="exploratory", prompt_version="e1-prompt-v1",
                      prompt_bytes=b"{}", resolver=resolver)


def test_a_record_has_exactly_the_whitelisted_keys_and_validates():
    record = good_record()
    assert set(record) == LOG_KEYS and set(record["evidence"][0]) == EVIDENCE_KEYS
    assert isinstance(record["evidence"][0]["bytes"], int) and record["evidence"][0]["bytes"] > 0
    validate_log_record(record)


def test_nr_logs_empty_evidence():
    record = good_record(evidence=())
    assert record["evidence"] == []
    validate_log_record(record)


@pytest.mark.parametrize("key", sorted(LOG_KEYS))
def test_a_free_text_value_in_any_field_is_refused(key):
    record = good_record()
    record[key] = synthetic.SENTINEL
    with pytest.raises(PayloadLogViolation) as raised:
        validate_log_record(record)
    assert synthetic.SENTINEL not in str(raised.value)


def test_an_extra_key_or_evidence_text_is_refused():
    record = good_record()
    record["prompt"] = synthetic.SENTINEL
    with pytest.raises(PayloadLogViolation, match="keys differ"):
        validate_log_record(record)
    record = good_record()
    record["evidence"][0]["text"] = synthetic.SENTINEL
    with pytest.raises(PayloadLogViolation, match="evidence"):
        validate_log_record(record)
    record = good_record()
    record["evidence"][0]["bytes"] = "57"
    with pytest.raises(PayloadLogViolation, match="bytes"):
        validate_log_record(record)
    record = good_record()
    record["attempts"] = True
    with pytest.raises(PayloadLogViolation, match="attempts"):
        validate_log_record(record)


@pytest.mark.parametrize(("unit", "ok"), [(None, True), ("SYN-F-001-t2", True), ("advanced", True), ("expert", False),
                                          ("SYN-A-001-t1", False)])
def test_unit_patterns(unit, ok):
    record = good_record(unit=unit)
    if ok:
        validate_log_record(record)
    else:
        with pytest.raises(PayloadLogViolation, match="unit"):
            validate_log_record(copy.deepcopy(record))
