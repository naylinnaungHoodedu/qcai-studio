"""The repository's Python sources: each compiles without a SyntaxWarning, and no test reads outside the repository.

A SyntaxWarning (an invalid escape sequence such as "\\u" in a non-raw string, an "is" comparison with a literal) is
printed once, when the file is first compiled, and never fails anything by itself; a cached bytecode file hides it on
every later run. apps/api/pytest.ini turns the warning into an error for whatever the run compiles, and this module
compiles every source, so a new one fails the suite wherever it is.

A test that reads a file outside the checkout (the evidence package or the plan beside it on the workstation) tests
nothing in CI, whose checkout holds neither, and breaks the suite whenever those records change. The evidence package
checks its own records (its 00_meta/check_records.py).
"""

from __future__ import annotations

import ast
from pathlib import Path
import warnings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Not repository sources: installed packages, caches and build output.
SKIPPED_PARTS = {".git", "__pycache__", "node_modules", ".next", ".venv", "venv", "dist"}
TEST_ROOTS = (REPO_ROOT / "apps" / "api" / "tests", REPO_ROOT / "evaluation" / "tests")
# Names of what lies beside the checkout on the workstation: the evidence packages and the plan.
OUTSIDE_NAMES = ("BEP-2-12", "BEP-1", "BEP-0", "QC_AI_Studio_Ultimate_Software_Upgrade_Plan")


def _sources() -> list[Path]:
    return sorted(path for path in REPO_ROOT.rglob("*.py") if not SKIPPED_PARTS & set(path.relative_to(REPO_ROOT).parts))


def _syntax_warnings(source: bytes, name: str) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        try:
            compile(source, name, "exec", dont_inherit=True)
        except SyntaxError as error:  # a SyntaxWarning raised as an error arrives as SyntaxError
            return [f"{name}:{error.lineno}: {error.msg}"]
    return []


def test_no_python_source_raises_a_syntax_warning():
    sources = _sources()
    # Not vacuous: the application, its tests, the scripts and the evaluation package are all scanned.
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in sources}
    for expected in ("apps/api/app/main.py", "apps/api/tests/test_malformed_input.py", "scripts/config_package.py", "evaluation/tests/test_evaluators.py"):
        assert expected in scanned, expected
    found = [problem for path in sources for problem in _syntax_warnings(path.read_bytes(), path.relative_to(REPO_ROOT).as_posix())]
    assert found == []


def test_the_scan_catches_an_invalid_escape_sequence():
    (problem,) = _syntax_warnings(b'body = b"\\ud800"\n', "sample.py")
    assert problem.startswith("sample.py:1: ") and "invalid escape sequence" in problem
    assert _syntax_warnings(b'body = rb"\\ud800"\n', "sample.py") == []


def _names_a_path_outside(value: str) -> bool:
    """A string that is, or holds after a path separator, the name of what lies beside the checkout. A docstring that
    cites a record ("approved as P1-D-04 (BEP-1)") names no path."""
    return any(value.startswith(outside) or f"/{outside}" in value or f"\\{outside}" in value for outside in OUTSIDE_NAMES)


def _outside_reads(source: str, name: str, depth: int) -> list[str]:
    """Where a test module reaches outside the checkout: a string naming what lies beside it, the parent of the
    repository root (`REPO_ROOT.parent`), or `parents[n]` of a path past the root (depth is the module's own)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _names_a_path_outside(node.value):
            found.append(f"{name}:{node.lineno}: names {node.value[:60]!r}")
        if isinstance(node, ast.Attribute) and node.attr in {"parent", "parents"} and isinstance(node.value, ast.Name) and node.value.id == "REPO_ROOT":
            found.append(f"{name}:{node.lineno}: REPO_ROOT.{node.attr}")
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int) and node.slice.value > depth):
            found.append(f"{name}:{node.lineno}: parents[{node.slice.value}]")
    return found


def test_no_test_reads_outside_the_repository():
    found, scanned = [], 0
    for root in TEST_ROOTS:
        depth = len(root.relative_to(REPO_ROOT).parts)  # parents[depth] of a module in root is the repository root
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve() or "__pycache__" in path.parts:
                continue  # this module names what it looks for
            scanned += 1
            found += _outside_reads(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix(), depth)
    assert scanned > 50 and found == []


def test_the_outside_read_scan_catches_each_way_a_test_reached_the_evidence_package():
    for source in ('BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"\n', 'PLAN = REPO_ROOT.parent / "QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt"\n',
                   'ROOT = REPO_ROOT.parents[0]\n', 'ROOT = Path(__file__).resolve().parents[4]\n', 'register = Path("../BEP-2-12/00_meta")\n',
                   'register = Path(r"D:\\QC_AI_Studio\\BEP-2-12")\n'):
        assert _outside_reads(source, "sample.py", 3), source
    assert _outside_reads('REPO_ROOT = Path(__file__).resolve().parents[3]\nAPI_ROOT = REPO_ROOT / "apps" / "api"\n', "sample.py", 3) == []
    assert _outside_reads('"""The score floor, approved as P1-D-04 (BEP-1)."""\n', "sample.py", 3) == []
