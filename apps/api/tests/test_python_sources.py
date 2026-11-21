"""Every Python source in the repository compiles without a SyntaxWarning.

A SyntaxWarning (an invalid escape sequence such as "\\u" in a non-raw string, an "is" comparison with a literal) is
printed once, when the file is first compiled, and never fails anything by itself; a cached bytecode file hides it on
every later run. apps/api/pytest.ini turns the warning into an error for whatever the run compiles, and this test
compiles every source, so a new one fails the suite wherever it is.
"""

from __future__ import annotations

from pathlib import Path
import warnings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Not repository sources: installed packages, caches and build output.
SKIPPED_PARTS = {".git", "__pycache__", "node_modules", ".next", ".venv", "venv", "dist"}


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
