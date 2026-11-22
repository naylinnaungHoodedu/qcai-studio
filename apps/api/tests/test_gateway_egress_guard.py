"""Phase 5 egress guard: only the gateway makes model egress (plan Phase 5 E1; plan 7.1 "The gateway MUST be the sole
holder of provider credentials"; R-06; Phase 5 spec 13.2, conflicts 1, 10 and 29).

Two AST rules over the repository's code:
  import rule      no module of the API image (apps/api/app) outside app/gateway/ imports a provider SDK or an HTTP client,
                   with one recorded allow-list entry: the vector index client of the Phase 2 semantic backend
                   (app/services/retrieval_engine.py: pinecone), reached only with an embedder the gateway gives (its
                   embedding egress and key are app/gateway/embeddings.py's)
  host-string rule in the Python files under apps/api/app, scripts, evaluation (its tests included) and tools outside
                   app/gateway/, no string literal names a model provider's host; apps/api/tests, apps/frontend, infra
                   and every non-Python file are not scanned
Each rule is shown catching a sample, and passing urllib.parse, langchain_text_splitters, the scripts' non-model
urllib.request and the word "coherence".
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps" / "api" / "app"
GATEWAY_ROOT = APP_ROOT / "gateway"
EGRESS_MODULES = ("httpx", "requests", "aiohttp", "urllib.request", "urllib3", "http.client", "google.auth", "openai", "anthropic",
                  "google.generativeai", "google.genai", "vertexai", "langchain_openai", "langchain_anthropic", "langchain_google",
                  "cohere", "mistralai", "pinecone")
ALLOWED_IMPORTS = {"app/services/retrieval_engine.py": {"pinecone"}}
PROVIDER_HOSTS = ("generativelanguage.googleapis.com", "aiplatform.googleapis.com", "api.openai.com", "openai.azure.com",
                  "api.anthropic.com", "api.cohere.ai", "api.cohere.com", "api.mistral.ai", "api-inference.huggingface.co", "bedrock-runtime")
HOST_ROOTS = (APP_ROOT, REPO_ROOT / "scripts", REPO_ROOT / "evaluation", REPO_ROOT / "tools")
SKIPPED = {"__pycache__", "node_modules", ".venv", "venv"}


def _egress(module: str) -> str | None:
    for name in EGRESS_MODULES:
        if module == name or module.startswith(name + ".") or (name == "langchain_google" and module.startswith("langchain_google")):
            return name
    return None


def import_problems(source: str, relative: str) -> list[str]:
    allowed = ALLOWED_IMPORTS.get(relative, set())
    problems = []
    for node in ast.walk(ast.parse(source)):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for module in modules:
            name = _egress(module)
            if name and name not in allowed:
                problems.append(f"{relative}: imports {module}")
    return sorted(set(problems))


def host_problems(source: str, relative: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            problems.extend(f"{relative}: names {host}" for host in PROVIDER_HOSTS if host in lowered)
    return problems


def _sources(root: Path):
    for path in sorted(root.rglob("*.py")):
        if SKIPPED & set(path.parts) or path.is_relative_to(GATEWAY_ROOT):
            continue
        yield path


def scan() -> list[str]:
    problems = []
    for path in _sources(APP_ROOT):
        problems.extend(import_problems(path.read_text(encoding="utf-8"), path.relative_to(APP_ROOT.parent).as_posix()))
    for root in HOST_ROOTS:
        if root.exists():
            for path in _sources(root):
                problems.extend(host_problems(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix()))
    return problems


def test_only_the_gateway_imports_a_model_client_or_names_a_provider_host():
    assert scan() == []


def test_the_scanner_catches_each_rule_s_sample_and_passes_what_is_not_egress():
    for sample in ("import httpx", "import requests", "from urllib.request import urlopen", "import http.client", "from google.auth import default",
                   "import google.auth", "from openai import OpenAI", "import anthropic", "from google import genai", "import vertexai",
                   "from langchain_google_vertexai import X", "from langchain_openai import OpenAIEmbeddings", "import mistralai"):
        assert import_problems(sample, "app/services/x.py"), sample
    assert import_problems("import google.genai", "app/services/x.py")
    for passing in ("from urllib.parse import urlsplit", "import langchain_text_splitters", "import socket", "import json"):
        assert import_problems(passing, "app/services/x.py") == [], passing
    assert import_problems("from pinecone import Pinecone", "app/services/retrieval_engine.py") == []
    assert import_problems("from langchain_openai import OpenAIEmbeddings", "app/services/retrieval_engine.py")
    assert import_problems("import httpx", "app/services/retrieval_engine.py")
    for host in PROVIDER_HOSTS:
        assert host_problems(f"URL = 'https://{host}/v1'", "scripts/x.py"), host
    assert host_problems("WORD = 'coherence'; OTHER = 'https://example.invalid/api'", "scripts/x.py") == []
    # The two scripts' non-model egress (the deployment record and the domain monitor) is outside the import rule.
    for script in ("deployment_record.py", "domain_monitor.py"):
        assert host_problems((REPO_ROOT / "scripts" / script).read_text(encoding="utf-8"), f"scripts/{script}") == []


def test_the_allow_list_is_the_one_recorded_exception():
    # The vector index client only: the embedding egress, its key and its D-23 opt-in are the gateway's (spec 4.19).
    assert ALLOWED_IMPORTS == {"app/services/retrieval_engine.py": {"pinecone"}}
    source = (APP_ROOT / "services" / "retrieval_engine.py").read_text(encoding="utf-8")
    assert "from pinecone import Pinecone" in source and "langchain_openai" not in source and "openai_api_key" not in source
    assert "from app.gateway.embeddings import embedding_problem" in source and "embedder_for" in source
