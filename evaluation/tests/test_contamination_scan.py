"""Phase 10: fingerprint families, the scanner's targets and its self-test (spec 3.14, 4.8; AC-10-4, AC-10-6; PD-71)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
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
    assert frozenset(module.TEXT_EXTENSIONS) <= contamination.TEXT_EXTENSIONS  # at least every suffix scan_boundary scans
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


def _raise(error):
    def read():
        raise error
    return read


def test_binary_files_are_not_text_and_large_or_unreadable_files_are_excluded(tmp_path):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    passage = fixture()["licensed_passages"][2]
    read_png = []
    entries = [("image.png", lambda: read_png.append(1) or passage.encode()), ("data.bin", lambda: b"\x00" + passage.encode()),
               ("latin.dat", lambda: passage.encode("utf-16")), ("big.txt", _raise(contamination.TooLarge("big.txt"))),
               ("gone.md", _raise(OSError("gone")))]
    result = contamination.scan_files(entries, sets)
    assert result["scanned"] == 0 and read_png == []
    assert result["excluded"] == [{"path": "big.txt", "reason": "too_large"}, {"path": "gone.md", "reason": "unreadable"}]


TEXT_NAMES = ("docs/uml/flow.puml", "apps/api/Dockerfile", ".gitignore", ".dockerignore", "infra/hydrate.sh", "alembic/script.py.mako",
              "README", "LICENSE", "notes.tex", "page.rst", "corpus/x.mp4.sha256", "unknown.suffix")


@pytest.mark.parametrize("name", TEXT_NAMES)
def test_a_text_file_of_any_suffix_is_scanned(name):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    passage = fixture()["licensed_passages"][0]
    result = contamination.scan_files([(name, lambda: f"# {passage}\n".encode())], sets)
    assert result["scanned"] == 1 and [hit["path"] for hit in result["files_with_hits"]] == [name]


def test_environment_files_are_read_only_when_asked(tmp_path):
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    passage = fixture()["licensed_passages"][0]
    read = []
    entries = [("apps/api/.env.example", lambda: read.append(1) or f"X={passage}\n".encode())]
    result = contamination.scan_files(entries, sets)
    assert read == [] and result["scanned"] == 0 and result["files_with_hits"] == []
    assert result["excluded"] == [{"path": "apps/api/.env.example", "reason": contamination.ENV_EXCLUSION}]
    result = contamination.scan_files(entries, sets, include_env=True)
    assert read == [1] and [hit["path"] for hit in result["files_with_hits"]] == ["apps/api/.env.example"]
    # The planted file is the test's own (tmp_path), never a workstation .env file.
    (tmp_path / ".env.example").write_text(f"X={passage}\n", encoding="utf-8")
    module = scanner()
    argv = ["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(tmp_path)]
    assert module.main(argv) == 0 and module.main(argv + ["--include-env-files"]) == 1


def test_require_zero_fails_on_incomplete_coverage(tmp_path, monkeypatch):
    module = scanner()
    base = ["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE)]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert module.main(base + ["--path", str(empty)]) == 0
    assert module.main(base + ["--path", str(empty), "--require-zero"]) == 1
    full = tmp_path / "full"
    full.mkdir()
    (full / "a.txt").write_text("nothing licensed here", encoding="utf-8")
    (full / "b.txt").write_text("x" * 64, encoding="utf-8")
    assert module.main(base + ["--path", str(full), "--require-zero"]) == 0
    monkeypatch.setattr(contamination, "MAX_SCAN_BYTES", 32)
    assert module.main(base + ["--path", str(full)]) == 0
    assert module.main(base + ["--path", str(full), "--require-zero"]) == 1


def test_the_report_names_each_set_s_kind_and_the_ulqs_set_s_dataset():
    items = synthetic.synthetic_dataset({"A": 1})
    ulqs_set = contamination.set_from_payload(contamination.build_ulqs(items, SALT, set_id="u"))
    licensed = contamination.set_from_payload(contamination.build_licensed(["x"], SALT, set_id="l"))
    from evaluation.qcai_eval import ulqs

    report = contamination.report([], [licensed, ulqs_set])
    assert report["fingerprint_sets"] == [{"id": "l", "kind": "licensed", "dataset_content_sha256": None},
                                          {"id": "u", "kind": "ulqs", "dataset_content_sha256": ulqs.dataset_content_sha256(items)}]


def test_ci_scans_the_whole_tracked_tree_once_with_the_env_templates_and_require_zero():
    # AC-10-4 over the whole tracked tree is CI's own step (api-and-evaluation): every text file whatever its suffix, the
    # tracked .env.example templates included, under --require-zero. No test repeats that scan (it took about 37 s); the
    # tests scan the Phase 10 records and synthetic directories through the same script.
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    steps = [line.strip() for line in ci.splitlines() if "scan_research_logs.py" in line and "--repo" in line]
    assert steps == ["- run: python scripts/scan_research_logs.py --synthetic-fixture evaluation/fixtures/contamination_synthetic_v1.json "
                     "--repo --include-env-files --require-zero --report \"$RUNNER_TEMP/research-log-scan.json\""]
    job = ci.split("\n  api-and-evaluation:\n", 1)[1].split("\n  api-image-boundary-scan:\n", 1)[0]
    assert steps[0] in job
    sources = [*(REPO_ROOT / "evaluation" / "tests").glob("test_*.py"), *(REPO_ROOT / "apps" / "api" / "tests").glob("test_*.py")]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.get_source_segment(text, node)
            calls = [call for call in re.findall(r"main\(\[[^\]]*\"--repo\"[^\]]*\]", body) if "--synthetic-fixture" in call]
            # A test may use the repository target only over a list it supplies (git_files replaced), never the whole tree.
            assert not calls or 'setattr(contamination, "git_files"' in body, (path.name, node.name)


def test_an_env_template_s_content_never_reaches_the_output_the_report_or_an_error(tmp_path, capsys, monkeypatch):
    # CI's --repo step reads the tracked .env.example templates. The scanner reports paths, counts and set ids only: a
    # sentinel planted in a temporary env template (never a workstation file) appears in no output, report or error.
    sentinel = "SENTINEL-" + "7f3a9c" * 6
    passage = fixture()["licensed_passages"][0]
    root = tmp_path / "tree"
    (root / "apps" / "api").mkdir(parents=True)
    (root / ".env.example").write_text(f"SECRET_VALUE={sentinel}\n", encoding="utf-8")
    (root / "apps" / "api" / ".env.example").write_text(f"NOTE={sentinel} {passage}\n", encoding="utf-8")
    (root / ".env.local.example.yaml").write_text(f"key: {sentinel}\n", encoding="utf-8")
    module = scanner()
    report = tmp_path / "report.json"
    argv = ["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(root), "--include-env-files", "--require-zero",
            "--report", str(report)]
    assert module.main(argv) == 1  # the planted passage is a match, named by path
    out = capsys.readouterr()
    result = report.read_text(encoding="utf-8")
    assert "apps/api/.env.example" in result and json.loads(result)["matches_total"] >= 1
    monkeypatch.setattr(contamination, "MAX_SCAN_BYTES", 8)  # every template now too large: excluded by path and reason
    assert module.main(argv) == 1
    later = capsys.readouterr()
    too_large = report.read_text(encoding="utf-8")
    assert {entry["reason"] for entry in json.loads(too_large)["targets"][0]["excluded"]} == {"too_large"}
    for text in (out.out, out.err, result, later.out, later.err, too_large):
        assert sentinel not in text and passage not in text and "SECRET_VALUE" not in text


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
            "--output-ulqs", str(tmp_path / "u.json"), "--salt-env", "SALT_FOR_TEST", "--access-log", str(tmp_path / "access.jsonl"),
            "--actor-role", "MLE"]
    assert builder.main(args) == 3 and not (tmp_path / "l.json").exists()
    monkeypatch.setenv("SALT_FOR_TEST", "not hex")
    assert builder.main(args) == 3
    monkeypatch.setenv("SALT_FOR_TEST", "ab" * 32)
    assert builder.main(args) == 0 and (tmp_path / "l.json").exists()
