"""Phase 3: the three-plan replay record's provenance check survives the project's squash merge (AC-3-2; spec 7.17).

G1  no file that runs or checks the replay record asks git about history (a real squash-merged main that keeps the
    branch's objects passes the committed-record check in test_phase3_acceptance.py). The scan leaves this module out,
    because it names what it looks for, so nothing that runs or checks the record belongs here.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import ast
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SELF = Path(__file__).resolve()


# =============================================================================================================== G1


# Git questions about history: an ancestry or reachability test, a walk of the commit graph, or a log. The record's
# check must not depend on them, because the project squash-merges (18.8 F2, 18.9 G1).
HISTORY_TOKENS = ("merge-base", "is-ancestor", "rev-list", "--contains", "name-rev", "--first-parent", "reflog", "git log")
HISTORY_SUBCOMMANDS = {"merge-base", "rev-list", "log", "name-rev", "describe", "reflog", "show-branch", "cherry", "branch", "for-each-ref"}
# The one function allowed to ask: it builds the squash-merged fixture and proves that the fixture holds the condition
# under which the 18.7 E3 rule failed.
FIXTURE_BUILDER = ("apps/api/tests/test_phase3_acceptance.py", "_squash_merged_main")
RECORD_CHECKS = ("_check_committed_replay_record", "test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1")


def _replay_checkers() -> list[Path]:
    """Every code or CI file that runs or checks the three-plan replay record (this file aside)."""
    found = []
    for base, patterns in ((REPO_ROOT / "scripts", ("*.py",)), (API_ROOT / "tests", ("*.py",)), (REPO_ROOT / "evaluation", ("*.py",)),
                           (REPO_ROOT / ".github", ("*.yml", "*.yaml"))):
        for pattern in patterns:
            for path in base.rglob(pattern):
                if path.resolve() == SELF or "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if "three_plan_replay" in text or "replay_tutor_plans" in text:
                    found.append(path)
    return sorted(found)


def _git_subcommand(call: ast.Call) -> str | None:
    """The git subcommand a call runs, when it is visible: subprocess-style ["git", "<sub>", ...] or a helper called
    git, _git or ok whose first argument is the subcommand."""
    for argument in call.args[:1]:
        if isinstance(argument, (ast.List, ast.Tuple)) and len(argument.elts) >= 2:
            first, second = argument.elts[:2]
            if isinstance(first, ast.Constant) and first.value == "git" and isinstance(second, ast.Constant):
                return str(second.value)
    name = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else None
    if name in {"git", "_git", "ok"} and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _history_questions(text: str, relative: str) -> list[str]:
    """Where a file asks git about history: a history token in a string (any file) or, in Python, a visible git call
    with a history subcommand. The fixture builder is exempt."""
    if not relative.endswith(".py"):
        return [f"{relative}: {token}" for token in HISTORY_TOKENS if token in text]
    hits = []
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (relative, node.name) == FIXTURE_BUILDER:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                hits += [f"{relative}:{inner.lineno}: {token!r}" for token in HISTORY_TOKENS if token in inner.value]
            if isinstance(inner, ast.Call) and _git_subcommand(inner) in HISTORY_SUBCOMMANDS:
                hits.append(f"{relative}:{inner.lineno}: git {_git_subcommand(inner)}")
    return hits


def _function(path: Path, name: str) -> ast.FunctionDef:
    return next(node for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef) and node.name == name)


def _called(function: ast.FunctionDef) -> set[str]:
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                owner = node.func.value.id if isinstance(node.func.value, ast.Name) else "?"
                names.add(f"{owner}.{node.func.attr}")
    return names


def test_g1_no_file_that_runs_or_checks_the_replay_record_asks_git_about_history():
    checkers = _replay_checkers()
    relative = {path.relative_to(REPO_ROOT).as_posix() for path in checkers}
    # The scan is not vacuous: the script, the acceptance tests and CI are the record's checkers.
    assert {"scripts/replay_tutor_plans.py", "apps/api/tests/test_phase3_acceptance.py", ".github/workflows/ci.yml"} <= relative, relative
    assert [hit for path in checkers for hit in _history_questions(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix())] == []
    # The exemption is not stale: the fixture builder exists and is what asks the ancestry question.
    builder = _function(REPO_ROOT / FIXTURE_BUILDER[0], FIXTURE_BUILDER[1])
    assert any(isinstance(node, ast.Call) and _git_subcommand(node) == "merge-base" for node in ast.walk(builder))
    # Neither the committed-record check nor the AC-3-2 record test calls a process runner itself; the squash-merge
    # test runs the former inside a squash-merged repository. (Corrected in 18.10 H4: this comment said both "run no
    # process at all", but this AST scan sees only direct calls, and the AC-3-2 test's compute() ran git rev-parse and
    # git status for the informational commit. That test now supplies its own commit and refuses every process while
    # it runs (refuse_processes), so the property holds at run time; test_phase3_docs.py's test_h4_* proves both halves.)
    acceptance = REPO_ROOT / "apps" / "api" / "tests" / "test_phase3_acceptance.py"
    for name in RECORD_CHECKS:
        called = _called(_function(acceptance, name))
        assert not {call for call in called if call.startswith(("subprocess.", "os.system", "os.popen")) or call in {"_git", "git", "ok"}}, (name, called)
    record_test = _function(acceptance, RECORD_CHECKS[1])
    assert "refuse_processes" in _called(record_test)
    assert any(isinstance(node, ast.keyword) and node.arg == "commit_source" for node in ast.walk(record_test))
    squash_test = _function(acceptance, "test_ac_3_2_the_committed_record_check_passes_on_a_squash_merged_main_that_keeps_the_branch_objects")
    assert {"_squash_merged_main", "_check_committed_replay_record"} <= _called(squash_test)
    # The script asks git only which HEAD it runs on and whether the tree is clean (the informational commit), and only
    # through _git.
    script = REPO_ROOT / "scripts" / "replay_tutor_plans.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    subcommands = {_git_subcommand(node) for node in ast.walk(tree) if isinstance(node, ast.Call) and _git_subcommand(node)}
    assert subcommands == {"rev-parse", "status"}, subcommands
    runners = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
               and any(call.startswith(("subprocess.", "os.system", "os.popen")) for call in _called(node))]
    assert runners == ["_git"], runners


def test_g1_the_history_scan_catches_the_18_7_e3_rule_and_its_variants():
    # The scan catches the rule this round guards against (18.7 E3, as it stood in the AC-3-2 test) and the other
    # forms an ancestry or log question could take, in the test, the script or CI; and it exempts only the builder.
    e3_rule = (
        "def test_ac_3_2_record():\n"
        "    completed = subprocess.run([\"git\", \"merge-base\", \"--is-ancestor\", commit, \"HEAD\"], cwd=REPO_ROOT,\n"
        "                               capture_output=True, text=True)\n"
        "    if completed.returncode == 128:\n"
        "        pytest.skip(\"the record's commit is not in this clone\")\n"
        "    assert completed.returncode == 0\n"
    )
    for relative, source in (
        ("apps/api/tests/test_phase3_acceptance.py", e3_rule),
        ("scripts/replay_tutor_plans.py", 'def check(commit):\n    return _git("merge-base", "--is-ancestor", commit, "HEAD")\n'),
        ("scripts/replay_tutor_plans.py", 'def check():\n    return subprocess.run(["git", "log", "--format=%H"], cwd=REPO_ROOT)\n'),
        ("scripts/replay_tutor_plans.py", 'def check(commit):\n    return _git("rev-list", commit)\n'),
        ("apps/api/tests/test_phase3_acceptance.py", 'def check(commit):\n    os.system("git branch --contains " + commit)\n'),
        (".github/workflows/ci.yml", "      - run: git merge-base --is-ancestor HEAD origin/main\n"),
    ):
        assert _history_questions(source, relative), source
    builder = e3_rule.replace("def test_ac_3_2_record", f"def {FIXTURE_BUILDER[1]}")
    assert _history_questions(builder, FIXTURE_BUILDER[0]) == []
    assert _history_questions(builder, "scripts/replay_tutor_plans.py")
