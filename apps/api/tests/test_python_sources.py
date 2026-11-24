"""The repository's Python sources: each compiles without a SyntaxWarning, and no test reads outside the repository.

A SyntaxWarning (an invalid escape sequence such as "\\u" in a non-raw string, an "is" comparison with a literal) is
printed once, when the file is first compiled, and never fails anything by itself; a cached bytecode file hides it on
every later run. apps/api/pytest.ini turns the warning into an error for whatever the run compiles, and this module
compiles every source, so a new one fails the suite wherever it is.

A test that reads a file outside the checkout (the evidence package or the plan beside it on the workstation) tests
nothing in CI, whose checkout holds neither, and breaks the suite whenever those records change. The evidence package
checks its own records (its 00_meta/check_records.py).

A test that reads rows of the append-only security-event table from a select with no ORDER BY gets them in an
undefined order: one row (.first(), or Session.scalar) is then any matching row, and several (.all(), list(), a loop)
come in any order. PostgreSQL returns rows in physical order, and the suite under psycopg read two lockout events out
of order. The scan reads a select bound to a name through that name's assignments; .one() needs no order.

A test that creates a SQLAlchemy engine and never disposes it leaves its pooled database connection for the garbage
collector to close at an arbitrary point in a later test (a ResourceWarning run of the suite found such leaks). The
scan follows an engine a helper returns to each call of the helper, which must dispose it in turn.

No test touches the network (Phase 5 spec 13.2): conftest.py installs network_guard before the application is imported,
and a test here shows it refuses a non-loopback connect or name lookup before any packet and lets loopback through.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import warnings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Not repository sources: installed packages, caches and build output.
SKIPPED_PARTS = {".git", "__pycache__", "node_modules", ".next", ".venv", "venv", "dist"}
TEST_ROOTS = (REPO_ROOT / "apps" / "api" / "tests", REPO_ROOT / "evaluation" / "tests")
# Names of what lies beside the checkout on the workstation: the evidence packages, the plan, the private research data
# folder (the ULQS working files, Phase 10 spec R-25) and the paper's folder.
OUTSIDE_NAMES = ("BEP-2-12", "BEP-1", "BEP-0", "QC_AI_Studio_Ultimate_Software_Upgrade_Plan", "Working_Data", "Verify_Before_You_Teach")


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
                   'register = Path(r"D:\\QC_AI_Studio\\BEP-2-12")\n', 'ITEMS = Path("../Working_Data/items.jsonl")\n',
                   'ITEMS = Path(r"D:\\QC_AI_Studio\\Working_Data\\items.jsonl")\n', 'PAPER = Path("../Verify_Before_You_Teach/paper.pdf")\n'):
        assert _outside_reads(source, "sample.py", 3), source
    assert _outside_reads('REPO_ROOT = Path(__file__).resolve().parents[3]\nAPI_ROOT = REPO_ROOT / "apps" / "api"\n', "sample.py", 3) == []
    assert _outside_reads('"""The score floor, approved as P1-D-04 (BEP-1)."""\n', "sample.py", 3) == []


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    scope = parents.get(node)
    while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scope = parents.get(scope)
    return scope


def _assigned_values(scope: ast.AST) -> dict[str, list[ast.expr]]:
    """Every value assigned to a plain name in scope (a function, or the module): `query = select(...)`, `query =
    query.where(...)`."""
    values: dict[str, list[ast.expr]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values.setdefault(node.targets[0].id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            values.setdefault(node.target.id, []).append(node.value)
    return values


def _expanded(expr: ast.expr, values: dict[str, list[ast.expr]], seen: tuple[str, ...] = ()) -> str:
    """The text of expr, followed by the text of every value its names were assigned in the same scope, so a select bound
    to a name first (`query = select(...)`; `db.scalars(query)`) is read as the select it names."""
    parts = [ast.unparse(expr)]
    for used in sorted({node.id for node in ast.walk(expr) if isinstance(node, ast.Name)} - set(seen)):
        parts += [_expanded(value, values, (*seen, used)) for value in values.get(used, [])]
    return " ".join(parts)


# Session methods that run a select, and the Result methods after which the row order cannot matter (at most one row,
# or an error).
_ROW_READS = {"scalars", "execute", "scalar"}
_ORDER_FREE = {"one", "one_or_none", "scalar_one", "scalar_one_or_none"}


def _unordered_event_reads(source: str, name: str, *, several: bool = False) -> list[str]:
    """Where a module reads security events from a select of SecurityEvent rows that has no ORDER BY: one event
    (`.first()` on the result, or Session.scalar), or, with several=True, more than one (`.all()`, list(), iteration,
    any other use of the result). A select bound to a name is read through the name's assignments in the same function
    (or the module); `.one()` and its kin need no order."""
    tree = ast.parse(source)
    parents = _parents(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ROW_READS and node.args):
            continue
        scope = _enclosing_function(node, parents) or tree
        query = _expanded(node.args[0], _assigned_values(scope))
        if not re.search(r"\bselect\(SecurityEvent\b", query) or "order_by" in query:
            continue
        consumer = parents.get(node)
        taken = consumer.attr if isinstance(consumer, ast.Attribute) and isinstance(parents.get(consumer), ast.Call) else None
        if taken in _ORDER_FREE:
            continue
        one = node.func.attr == "scalar" or taken == "first"
        if one != several:
            found.append(f"{name}:{node.lineno}: {query[:80]}")
    return found


def _test_modules() -> list[Path]:
    return [path for root in TEST_ROOTS for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts]


def test_no_test_reads_one_security_event_without_an_order():
    paths = _test_modules()
    found = [problem for path in paths for problem in _unordered_event_reads(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix())]
    assert len(paths) > 50 and found == []


def test_no_test_reads_several_security_events_without_an_order():
    # The same order rule for a read of several events: a test that compares them in turn (as the lockout test once
    # did) gets them in physical order under PostgreSQL.
    paths = _test_modules()
    found = [problem for path in paths
             for problem in _unordered_event_reads(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix(), several=True)]
    assert len(paths) > 50 and found == []


def test_the_event_order_scan_catches_an_unordered_read_and_accepts_an_ordered_one():
    one = (
        'event = db.scalars(select(SecurityEvent).where(SecurityEvent.event_type == "authz.denied")).first()\n',
        "event = db.scalar(select(SecurityEvent).where(SecurityEvent.seq > start))\n",
        "def test_a(db):\n    query = select(SecurityEvent).where(SecurityEvent.seq > 0)\n    event = db.scalars(query).first()\n",
    )
    several = (
        # The lockout test before 669510a: two events, compared in order, from a select with no ORDER BY.
        "def test_b(db, start):\n    lockouts = list(\n        db.scalars(\n            select(SecurityEvent)\n"
        "            .where(SecurityEvent.seq > start, SecurityEvent.event_type == \"auth.lockout\")\n        )\n    )\n"
        "    assert [event.outcome for event in lockouts] == [\"warning\", \"denied\"]\n",
        "events = db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start)).all()\n",
        "def test_c(db):\n    query = select(SecurityEvent)\n    query = query.where(SecurityEvent.seq > 0)\n    rows = db.execute(query).scalars().all()\n",
    )
    for source in one:
        assert _unordered_event_reads(source, "sample.py"), source
        assert _unordered_event_reads(source, "sample.py", several=True) == [], source
    for source in several:
        assert _unordered_event_reads(source, "sample.py", several=True), source
        assert _unordered_event_reads(source, "sample.py") == [], source
    ordered = (
        "events = db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start).order_by(SecurityEvent.seq)).all()\n",
        "start = db.scalar(select(SecurityEvent.seq).order_by(SecurityEvent.seq.desc()).limit(1)) or 0\n",
        "start = db.scalar(select(func.max(SecurityEvent.seq))) or 0\n",
        'row = db.scalars(select(UserAccount).where(UserAccount.email == email)).first()\n',
        "def test_d(db):\n    query = select(SecurityEvent).order_by(SecurityEvent.seq)\n    query = query.where(SecurityEvent.seq > 0)\n"
        "    return list(db.scalars(query))\n",
        "stored = db.scalars(select(SecurityEvent).where(SecurityEvent.seq == seq)).one()\n",
    )
    for source in ordered:
        assert _unordered_event_reads(source, "sample.py") == [] and _unordered_event_reads(source, "sample.py", several=True) == [], source


def _calls_on(function: ast.AST, receiver: str, method: str) -> bool:
    """Whether function holds `receiver.method(...)`, receiver an expression's text (`engine`, `pair[1]`)."""
    return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == method
               and ast.unparse(call.func.value) == receiver for call in ast.walk(function))


def _registries(tree: ast.Module) -> set[str]:
    """Module-level names an autouse fixture empties and disposes (`_BUILT`, whose entries the fixture disposes after
    each test): an engine appended to one is disposed by that fixture's teardown."""
    names = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
             for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        autouse = any(isinstance(decorator, ast.Call) and "fixture" in ast.unparse(decorator.func)
                      and any(keyword.arg == "autouse" and getattr(keyword.value, "value", False) is True for keyword in decorator.keywords)
                      for decorator in node.decorator_list)
        if autouse and ".dispose()" in ast.unparse(node):
            found |= {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and item.id in names}
    return found


_MISSING = object()


def _undisposed_engines(source: str, name: str) -> list[str]:
    """Where a test module creates a SQLAlchemy engine it never disposes. An engine bound to a name in a function must be
    disposed in that function (a fixture's teardown counts), or appended to a module list that an autouse fixture
    disposes after each test, or returned. A function that returns an engine (alone, or at one position of a tuple) is
    a helper, and every call of a helper must bind the engine it returns to a name that the calling function disposes
    in turn (or registers, or returns, which makes the caller a helper too). A module-level engine may only lend its
    dialect (it never connects). Any other use, such as an engine passed straight to create_all or a helper's engine
    discarded, leaves its pooled connection for the garbage collector to close at an arbitrary later point, in whatever
    test is running then."""
    tree = ast.parse(source)
    parents = _parents(tree)
    registries = _registries(tree)
    found: list[str] = []
    helpers: dict[str, int | None] = {}

    def returned_at(function: ast.AST, bound: str):
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id == bound:
                return None
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                for index, item in enumerate(node.value.elts):
                    if isinstance(item, ast.Name) and item.id == bound:
                        return index
        return _MISSING

    def registered(function: ast.AST, bound: str) -> bool:
        return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "append"
                   and ast.unparse(call.func.value) in registries
                   and any(isinstance(item, ast.Name) and item.id == bound for arg in call.args for item in ast.walk(arg))
                   for call in ast.walk(function))

    def judge(bound: str, function, lineno: int, what: str) -> None:
        if _calls_on(function, bound, "dispose") or registered(function, bound):
            return
        position = returned_at(function, bound)
        if position is not _MISSING:
            helpers.setdefault(function.name, position)
            return
        found.append(f"{name}:{lineno}: {what} {bound} is never disposed in {function.name}")

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "create_engine"):
            continue
        parent, function = parents[node], _enclosing_function(node, parents)
        if function is None:
            if not (isinstance(parent, ast.Attribute) and parent.attr == "dialect"):
                found.append(f"{name}:{node.lineno}: a module-level engine")
            continue
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
            judge(parent.targets[0].id, function, node.lineno, "the engine")
        elif isinstance(parent, ast.Return):
            helpers.setdefault(function.name, None)
        elif isinstance(parent, ast.Tuple) and isinstance(parents.get(parent), ast.Return):
            helpers.setdefault(function.name, parent.elts.index(node))
        else:
            found.append(f"{name}:{node.lineno}: an engine used without a name in {function.name}")

    checked: set[str] = set()
    while set(helpers) - checked:
        helper = sorted(set(helpers) - checked)[0]
        checked.add(helper)
        position = helpers[helper]
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == helper):
                continue
            parent, function = parents[call], _enclosing_function(call, parents)
            what = f"the engine {helper} returns,"
            if function is None:
                found.append(f"{name}:{call.lineno}: {helper} is called at module level")
            elif isinstance(parent, ast.Return):
                helpers.setdefault(function.name, position)
            elif isinstance(parent, ast.Assign) and len(parent.targets) == 1:
                target = parent.targets[0]
                if position is None and isinstance(target, ast.Name):
                    judge(target.id, function, call.lineno, what)
                elif position is not None and isinstance(target, ast.Tuple) and isinstance(target.elts[position], ast.Name):
                    judge(target.elts[position].id, function, call.lineno, what)
                elif position is not None and isinstance(target, ast.Name):
                    if not (_calls_on(function, f"{target.id}[{position}]", "dispose") or returned_at(function, target.id) is not _MISSING):
                        found.append(f"{name}:{call.lineno}: {what} {target.id}[{position}] is never disposed in {function.name}")
                    elif returned_at(function, target.id) is not _MISSING:
                        helpers.setdefault(function.name, position)
                else:
                    found.append(f"{name}:{call.lineno}: {what} is not bound to a name in {function.name}")
            else:
                found.append(f"{name}:{call.lineno}: {what} is used without a name in {function.name}")
    return found


def test_every_engine_a_test_creates_is_disposed():
    paths = _test_modules()
    found = [problem for path in paths for problem in _undisposed_engines(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix())]
    assert len(paths) > 50 and found == []


def test_the_engine_scan_catches_an_undisposed_engine_and_accepts_a_disposed_one():
    leaking = (
        "def test_a(url):\n    Base.metadata.create_all(create_engine(url))\n",
        "def test_b(url):\n    engine = create_engine(url)\n    engine.connect()\n",
        "ENGINE = create_engine('sqlite://')\n",
        # A helper's engine that one caller disposes and another never does: each call site is judged on its own.
        "def fresh(url):\n    return create_engine(url)\n\ndef test_a(url):\n    engine = fresh(url)\n    engine.dispose()\n\n"
        "def test_b(url):\n    engine = fresh(url)\n    engine.connect()\n",
        "def fresh_sessions(url):\n    engine = create_engine(url)\n    return sessionmaker(bind=engine), engine\n\n"
        "def test_c(url):\n    factory, engine = fresh_sessions(url)\n    factory().close()\n",
        "def fresh_sessions(url):\n    engine = create_engine(url)\n    return sessionmaker(bind=engine), engine\n\n"
        "def test_d(url):\n    factory, _ = fresh_sessions(url)\n",
        "def fresh(url):\n    return create_engine(url)\n\ndef test_e(url):\n    Base.metadata.create_all(fresh(url))\n",
        # A helper of a helper: its callers are judged too.
        "def fresh(url):\n    return create_engine(url)\n\ndef appender(url):\n    engine = fresh(url)\n    return engine\n\n"
        "def test_f(url):\n    engine = appender(url)\n",
    )
    for source in leaking:
        assert _undisposed_engines(source, "sample.py"), source
    disposed = (
        "def test_a(url):\n    engine = create_engine(url)\n    try:\n        engine.connect()\n    finally:\n        engine.dispose()\n",
        "def _helper(url):\n    return create_engine(url)\n\ndef test_b(url):\n    engine = _helper(url)\n    engine.dispose()\n",
        "DIALECT = create_engine('postgresql+pg8000://', creator=lambda: None).dialect\n",
        "def fresh_sessions(url):\n    engine = create_engine(url)\n    return sessionmaker(bind=engine), engine\n\n"
        "def appender(url):\n    factory, engine = fresh_sessions(url)\n    return factory, engine\n\n"
        "def test_c(url):\n    factory, engine = appender(url)\n    try:\n        factory().close()\n    finally:\n        engine.dispose()\n",
        "@pytest.fixture\ndef isolated(url):\n    engine = fresh(url)\n    yield engine\n    engine.dispose()\n\ndef fresh(url):\n    return create_engine(url)\n",
        "_BUILT = []\n\n@pytest.fixture(autouse=True)\ndef _close():\n    yield\n    while _BUILT:\n        _BUILT.pop().dispose()\n\n"
        "def pooled():\n    engine = create_engine('sqlite://')\n    _BUILT.append(engine)\n    return engine\n\ndef test_d():\n    engine = pooled()\n",
    )
    for source in disposed:
        assert _undisposed_engines(source, "sample.py") == [], source


def test_the_network_guard_refuses_a_non_loopback_socket_and_allows_loopback():
    import socket

    import pytest

    import network_guard

    assert network_guard._installed  # conftest installed it before the application was imported
    for attempt in (lambda: socket.create_connection(("203.0.113.1", 9), timeout=0.01),
                    lambda: socket.getaddrinfo("example.com", 443)):
        with pytest.raises(network_guard.NetworkBlocked):
            attempt()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(network_guard.NetworkBlocked):
            probe.connect(("203.0.113.1", 9))
        with pytest.raises(network_guard.NetworkBlocked):
            probe.connect_ex(("203.0.113.1", 9))
    finally:
        probe.close()
    blocked = network_guard.take_blocked()
    assert len(blocked) == 4 and all("203.0.113.1" in item or "example.com" in item for item in blocked)
    # Loopback passes through: a listener on 127.0.0.1 accepts a connect, and the local names resolve.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), timeout=2)
        client.close()
    finally:
        server.close()
    assert socket.getaddrinfo("localhost", 80) and socket.getaddrinfo("127.0.0.1", 80)
    if socket.has_ipv6:
        assert network_guard._is_local("::1") and network_guard._is_local("[::1]")
    assert not network_guard._is_local("2001:db8::1") and not network_guard._is_local("api.example.org")
    assert network_guard.take_blocked() == []
