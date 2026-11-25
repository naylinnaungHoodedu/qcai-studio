"""Phase 10: fingerprint families, the scanner's targets and its self-test (spec 3.14, 4.8; AC-10-4, AC-10-6; PD-71)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

import pytest

from evaluation.qcai_eval import contamination, synthetic
import scan_guard

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
    # In process, the guard both conftests install (apps/api/tests/scan_guard.py) fails any test whose repository target
    # would list the real checkout through the real git_files, however the call is made: a literal argv, an argv built
    # elsewhere, a direct repository_target call.
    module = scanner()
    assert getattr(contamination.repository_target, scan_guard.GUARD_MARKER, False)
    base = ["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE)]
    for call in (lambda: module.main(base + ["--repo"]), lambda: contamination.repository_target(REPO_ROOT, [])):
        with pytest.raises(pytest.fail.Exception, match="whole tracked tree"):
            call()
    # A subprocess is outside the process: no test may run the script with --repo in one.
    sources = [*(REPO_ROOT / "evaluation" / "tests").glob("test_*.py"), *(REPO_ROOT / "apps" / "api" / "tests").glob("test_*.py")]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name == sys._getframe().f_code.co_name:
                continue  # (this guard's own text names what it refuses)
            body = ast.get_source_segment(text, node)
            spawns = any(name in body for name in ("subprocess", "Popen", "os.system", "check_call", "check_output"))
            assert not (spawns and "scan_research_logs" in body and '"--repo"' in body), (path.name, node.name)


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


def _builder():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_licensed_fingerprints as builder

    return builder


def _access(path):
    return [(line["action"], line["artifact_kind"], line["artifact_sha256"]) for line in
            (json.loads(text) for text in path.read_text(encoding="utf-8").splitlines())]


def test_the_builder_refuses_a_missing_or_invalid_input_with_a_documented_code_and_logs_what_it_read(tmp_path, monkeypatch, capsys):
    from evaluation.qcai_eval import ulqs
    from evaluation.qcai_eval.canonical import lf_sha256

    builder = _builder()
    text = tmp_path / "licensed.txt"
    text.write_text(fixture()["licensed_passages"][0], encoding="utf-8")
    items = synthetic.write_jsonl(tmp_path / "items.jsonl", synthetic.synthetic_dataset({"A": 1}))
    access = tmp_path / "access.jsonl"
    monkeypatch.setenv("SALT_FOR_TEST", "ab" * 32)

    def run(licensed, ulqs_path):
        if access.exists():
            access.unlink()
        return builder.main(["--licensed-text", str(licensed), "--ulqs", str(ulqs_path), "--set-id", "t", "--output-licensed",
                             str(tmp_path / "l.json"), "--output-ulqs", str(tmp_path / "u.json"), "--salt-env", "SALT_FOR_TEST",
                             "--access-log", str(access), "--actor-role", "MLE"])

    assert run(tmp_path / "absent.txt", items) == 2 and not access.exists()          # a licensed text that is not there
    assert run(text, tmp_path / "absent.jsonl") == 2                                   # a ULQS file that is not there
    assert [entry[:2] for entry in _access(access)] == [("read", "licensed_text")]
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json\n", encoding="utf-8")
    assert run(text, broken) == 4                                                       # not JSON lines
    assert _access(access)[1] == ("read", "ulqs_items", lf_sha256(broken))
    invalid_items = synthetic.synthetic_dataset({"A": 1})
    invalid_items[0]["stratum"] = "Q"
    invalid = synthetic.write_jsonl(tmp_path / "invalid.jsonl", invalid_items)
    assert run(text, invalid) == 4 and not (tmp_path / "u.json").exists()             # fails ulqs.validate_dataset
    assert _access(access)[1] == ("read", "ulqs_items", ulqs.dataset_sha256(invalid_items))
    err = capsys.readouterr().err
    assert "Traceback" not in err and "exit 4" in err
    assert run(text, items) == 0 and [entry[:2] for entry in _access(access)] == [
        ("read", "licensed_text"), ("read", "ulqs_items"), ("write", "fingerprints"), ("write", "fingerprints")]


def test_the_scanner_logs_research_fingerprints_targets_and_its_report(tmp_path, monkeypatch, capsys):
    from evaluation.qcai_eval.canonical import canonical_sha256, lf_sha256

    builder, module = _builder(), scanner()
    text = tmp_path / "licensed.txt"
    text.write_text(fixture()["licensed_passages"][0], encoding="utf-8")
    items = synthetic.write_jsonl(tmp_path / "items.jsonl", synthetic.synthetic_dataset({"A": 1}))
    monkeypatch.setenv("SALT_FOR_TEST", "ab" * 32)
    licensed, ulqs_set = tmp_path / "l.json", tmp_path / "u.json"
    assert builder.main(["--licensed-text", str(text), "--ulqs", str(items), "--set-id", "research-t1", "--output-licensed", str(licensed),
                         "--output-ulqs", str(ulqs_set), "--salt-env", "SALT_FOR_TEST", "--access-log", str(tmp_path / "b.jsonl"),
                         "--actor-role", "MLE"]) == 0
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "payload_log.jsonl").write_text("{}\n", encoding="utf-8")
    (run / "responses.jsonl").write_text("{}\n", encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "p.txt").write_text("an invented prompt\n", encoding="utf-8")
    access, report = tmp_path / "access.jsonl", tmp_path / "scan.json"
    base = ["--fingerprints", str(licensed), "--ulqs-fingerprints", str(ulqs_set), "--research-logs", str(run), "--path", str(prompts),
            "--require-zero", "--report", str(report)]
    # Research fingerprints are research-plane material: the scan needs the access log and the role.
    assert module.main(base) == 2 and module.main(base + ["--access-log", str(access)]) == 2 and not access.exists()
    assert module.main(base + ["--access-log", str(REPO_ROOT / "docs" / "access.jsonl"), "--actor-role", "MLE"]) == 2
    assert module.main(base + ["--access-log", str(access), "--actor-role", "MLE"]) == 0
    logged = _access(access)
    assert [entry[:2] for entry in logged] == [("read", "fingerprints"), ("read", "fingerprints"), ("read", "scan_target"),
                                               ("read", "run_output"), ("write", "scan_report")]
    built = [entry[2] for entry in _access(tmp_path / "b.jsonl") if entry[0] == "write"]
    assert [entry[2] for entry in logged[:2]] == built  # the same digests the builder logged when it wrote them
    assert logged[4][2] == lf_sha256(report)
    payload_sha = __import__("hashlib").sha256((run / "payload_log.jsonl").read_bytes()).hexdigest()
    assert logged[3][2] == canonical_sha256([["payload_log.jsonl", payload_sha]])  # responses.jsonl is not read
    # A fingerprint file that does not parse is logged as read (by its LF sha256) before the scan refuses it.
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    access.unlink()
    assert module.main(["--fingerprints", str(broken), "--research-logs", str(run), "--access-log", str(access), "--actor-role", "MLE"]) == 2
    assert _access(access) == [("read", "fingerprints", lf_sha256(broken))]
    assert not (REPO_ROOT / "docs" / "access.jsonl").exists()
