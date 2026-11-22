"""The shipped non-development learner answer bodies, by sha256 (Phase 5 spec 12.2; design E12; plan D-05 freeze).

Run: python scripts/capture_public_payloads.py --write apps/api/tests/data/phase4_public_payloads_v1.json
     python scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json

Outside development every learner-facing answer body must equal Phase 4's for the same inputs. The golden was written
on the Phase 4 application tree (main 98f7cc4), before any Phase 5 application change. For every query of the public
score-floor fixture (apps/api/tests/data/score_floor_queries.json: 174 in-domain, 100 off-topic and 24 stopword-only
queries) and two configurations, it records the sha256 of the canonical JSON of:
  qa     QAEngine.ask(query), the legacy guard included (the POST /qa/ask body);
  tutor  TutorOrchestrator.chat(...) on an in-memory SQLite database with a fresh uuid4 demo learner, its thread_id
         and turn_id replaced by fixed placeholders (the POST /assistant/chat body, the legacy guard included).
Configurations:
  governed      ENVIRONMENT=production, governance on, the repository manifest (D-31: nothing approved, so every
                answer abstains)
  all_approved  the same settings with a temporary manifest approving every public-plane, bound item
No body is stored (bodies hold corpus text), only hashes. --check recomputes on the current tree and exits 1 on any
difference; it writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import os  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

QUERIES_PATH = API_ROOT / "tests" / "data" / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
DEFAULT_GOLDEN = API_ROOT / "tests" / "data" / "phase4_public_payloads_v1.json"
CAPTURED_ON_APP_TREE = "98f7cc4"
CONFIGURATIONS = ("governed", "all_approved")
SURFACES = ("qa", "tutor")
PLACEHOLDERS = {"thread_id": "thread-placeholder", "turn_id": "turn-placeholder"}
EXIT_DIFFERENT = 1


def queries() -> list[str]:
    data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    return [item["query"] for item in data["in_domain"]] + list(data["off_topic"]) + list(data["stopword_only"])


def body_sha256(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _settings(manifest: Path):
    from app.core.config import Settings

    return Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"],
                    corpus_manifest_path=str(manifest))


def _capture(settings, items: list[str]) -> list[dict]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.auth import AuthUser
    from app.core.db import Base
    from app.schemas import AssistantChatRequest
    from app.services.content_assembler import CourseStore
    from app.services.qa_engine import QAEngine
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.teaching_assistant import TeachingAssistantService
    from app.services.tutor_orchestrator import TutorOrchestrator

    store = CourseStore(settings)
    engine = RetrievalEngine(store, settings)
    qa = QAEngine(engine, settings)
    tutor = TutorOrchestrator(TeachingAssistantService(engine, settings), settings)
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    rows: list[dict] = []
    try:
        Base.metadata.create_all(bind=database)
        sessions = sessionmaker(bind=database, autoflush=False, expire_on_commit=False)
        for index, query in enumerate(items):
            rows.append({"surface": "qa", "query_index": index, "sha256": body_sha256(json.loads(qa.ask(query).model_dump_json()))})
            learner = AuthUser(user_id=f"guest-{uuid4()}", email=None, role="learner")
            with sessions() as db:
                response = tutor.chat(db, learner, AssistantChatRequest(message=query))
                db.rollback()
            body = json.loads(response.model_dump_json())
            for key, placeholder in PLACEHOLDERS.items():
                if key in body:
                    body[key] = placeholder
            rows.append({"surface": "tutor", "query_index": index, "sha256": body_sha256(body)})
    finally:
        database.dispose()
    return rows


def compute(items: list[str] | None = None) -> dict:
    from app.core.manifest_v2 import with_all_public_approved

    items = queries() if items is None else items
    configurations: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory(prefix="qcai-public-payloads-") as temp:
        approved = Path(temp) / "manifest.json"
        approved.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
        for name, manifest in (("governed", REPO_MANIFEST), ("all_approved", approved)):
            configurations[name] = _capture(_settings(manifest), items)
    return {"golden": "qcai-public-payloads", "format_version": 1, "captured_on_app_tree": CAPTURED_ON_APP_TREE,
            "queries": {"path": QUERIES_PATH.relative_to(REPO_ROOT).as_posix(), "count": len(items)},
            "configurations": configurations}


def differences(committed: dict, fresh: dict) -> list[str]:
    problems = []
    for name in CONFIGURATIONS:
        old = {(row["surface"], row["query_index"]): row["sha256"] for row in committed.get("configurations", {}).get(name, [])}
        new = {(row["surface"], row["query_index"]): row["sha256"] for row in fresh["configurations"][name]}
        if set(old) != set(new):
            problems.append(f"{name}: the captured (surface, query) set differs")
        problems.extend(f"{name}: {surface} body of query {index} differs from Phase 4's"
                        for (surface, index), digest in sorted(new.items()) if old.get((surface, index)) not in (None, digest))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    fresh = compute()
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: {sum(len(rows) for rows in fresh['configurations'].values())} body hashes")
        return 0
    committed = json.loads(args.check.read_text(encoding="utf-8"))
    problems = differences(committed, fresh)
    if problems:
        for problem in problems[:20]:
            print(problem, file=sys.stderr)
        print(f"public payload check failed: {len(problems)} difference(s) from the Phase 4 golden", file=sys.stderr)
        return EXIT_DIFFERENT
    print(f"public payloads equal the Phase 4 golden: {sum(len(rows) for rows in fresh['configurations'].values())} bodies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
