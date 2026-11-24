"""Phase 10: fingerprint families, the scanner's targets and its self-test (spec 3.14, 4.8; AC-10-4, AC-10-6; PD-71)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from evaluation.qcai_eval import contamination, synthetic

REPO_ROOT = Path(__file__).resolve().parents[2]
SALT = bytes(range(32))


def fixture():
    return json.loads(synthetic.CONTAMINATION_FIXTURE.read_text(encoding="utf-8"))


def scan_boundary():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scan_boundary as module

    return module


def scanner():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scan_research_logs as module

    return module


def test_the_shingles_and_normalisation_equal_scan_boundary_s():
    module = scan_boundary()
    text = fixture()["licensed_passages"][0] + " Ünïcode ＦＵＬＬＷＩＤＴＨ under_score"
    assert contamination.normalized_words(text) == module.normalized_words(text)
    assert contamination.fingerprint_shingles(text, SALT, 12) == module.fingerprint_shingles(text, SALT, 12)
    assert contamination.TEXT_EXTENSIONS == frozenset(module.TEXT_EXTENSIONS)
    assert contamination.MAX_SCAN_BYTES == module.MAX_SCAN_BYTES
    assert contamination.LICENSED_FORMAT == module.FINGERPRINT_FORMAT


def test_scan_boundary_reads_the_licensed_format(tmp_path):
    payload = contamination.build_licensed(fixture()["licensed_passages"], SALT, set_id="t")
    path = tmp_path / "f.private.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = scan_boundary().load_fingerprints(path)
    assert loaded["n"] == 12 and loaded["set"] == frozenset(payload["fingerprints"]) and loaded["id"] == "t"


def test_the_ulqs_exact_family_finds_a_short_text_the_shingles_miss():
    question = fixture()["ulqs_texts"][0]
    built = contamination.set_from_payload(contamination.build_ulqs([{"question": question}], SALT, set_id="u"))
    assert len(contamination.normalized_words(question)) < 12
    assert contamination.scan_text(f"log line\n{question}\n", [built])["ulqs"] >= 1
    assert contamination.scan_text(json.dumps({"field": question}), [built])["ulqs"] >= 1
    assert contamination.scan_text("Why do glassblowers?", [built])["ulqs"] == 0
    assert contamination.exact_fingerprint("two words", SALT) is None


def test_ulqs_texts_cover_every_free_text_field():
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    texts = [text for item in items for text in contamination.ulqs_texts(item)]
    for item in items:
        assert item["question"] in texts
        for claim in item.get("atomic_claims", []):
            assert claim["text"] in texts
        for turn in item.get("conversation", []):
            assert turn["user_utterance"] in texts and turn["resolved_query"] in texts
        for replay in item.get("replays", []):
            assert replay["gold_answer"] in texts
        if "negative_evidence" in item:
            assert item["negative_evidence"]["queries"][0] in texts


def test_the_research_log_target_excludes_only_responses_jsonl(tmp_path):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    passage = fixture()["licensed_passages"][1]
    for name in ("payload_log.jsonl", "run_events.jsonl", "run_record.json", "responses.jsonl", "notes.txt"):
        (tmp_path / name).write_text(json.dumps({"text": passage}) + "\n", encoding="utf-8")
    # A run record that names payload_log.jsonl as research data widens nothing.
    (tmp_path / "run_record.json").write_text(json.dumps({"research_data": ["payload_log.jsonl"], "text": passage}), encoding="utf-8")
    target = contamination.research_logs_target(tmp_path, sets, label="run")
    assert sorted(hit["path"] for hit in target["files_with_hits"]) == ["notes.txt", "payload_log.jsonl", "run_events.jsonl", "run_record.json"]
    assert target["excluded"] == [{"path": "responses.jsonl", "reason": "research data (model outputs)"}]
    assert contamination.RESEARCH_DATA_FILES == frozenset({"responses.jsonl"})


def test_unknown_extensions_are_not_text_and_large_files_are_excluded(tmp_path):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    passage = fixture()["licensed_passages"][2]
    (tmp_path / "data.bin").write_text(passage, encoding="utf-8")
    result = contamination.scan_files([("data.bin", lambda: passage.encode()), ("big.txt", lambda: None)], sets)
    assert result["scanned"] == 0 and result["excluded"] == [{"path": "big.txt", "reason": "too_large"}]


def test_the_repository_target_reads_git_ls_files_only(tmp_path, monkeypatch):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    seen = []
    monkeypatch.setattr(contamination, "git_files", lambda root: seen.append(root) or ["README.md"])
    target = contamination.repository_target(REPO_ROOT, sets)
    assert seen == [REPO_ROOT] and target["files"] == 1 and target["target"] == "repository"


def test_the_self_test_passes_and_fails_when_the_scanner_is_broken(monkeypatch, capsys):
    module = scanner()
    assert module.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--self-test"]) == 0
    monkeypatch.setattr(contamination, "scan_text", lambda text, sets: {"licensed": 0, "ulqs": 0})
    assert module.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--self-test"]) == 1
    monkeypatch.undo()
    monkeypatch.setattr(contamination, "RESEARCH_DATA_FILES", frozenset())
    assert module.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--self-test"]) == 1


def test_a_salt_shorter_than_32_bytes_is_refused_by_the_builder(tmp_path, monkeypatch):
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_licensed_fingerprints as builder

    text = tmp_path / "licensed.txt"
    text.write_text(fixture()["licensed_passages"][0], encoding="utf-8")
    items = synthetic.write_jsonl(tmp_path / "items.jsonl", synthetic.synthetic_dataset({"A": 1}))
    monkeypatch.setenv("SALT_FOR_TEST", "ab" * 16)
    args = ["--licensed-text", str(text), "--ulqs", str(items), "--set-id", "t", "--output-licensed", str(tmp_path / "l.json"),
            "--output-ulqs", str(tmp_path / "u.json"), "--salt-env", "SALT_FOR_TEST", "--access-log", str(tmp_path / "access.jsonl")]
    assert builder.main(args) == 3 and not (tmp_path / "l.json").exists()
    monkeypatch.setenv("SALT_FOR_TEST", "not hex")
    assert builder.main(args) == 3
    monkeypatch.setenv("SALT_FOR_TEST", "ab" * 32)
    assert builder.main(args) == 0 and (tmp_path / "l.json").exists()
