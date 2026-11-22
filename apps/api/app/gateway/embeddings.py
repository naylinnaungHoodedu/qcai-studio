"""The gateway's embedding egress (plan 7.1 "The gateway MUST be the sole holder of provider credentials [Risk R-06]";
7.6 "Provider keys stay in the gateway"; D-23; Phase 5 spec 4.19).

The Phase 2 semantic backend (retrieval_engine.PineconeSemanticBackend) embeds its index entries and its queries
through this module only, so no module outside app.gateway reads OPENAI_API_KEY or calls an embedding provider (no
Settings field holds the key). embedding_problem(settings, package) names why no provider embedder may run, the first
check that fails giving the reason:
  egress_not_opted_in   the environment's MODEL_EGRESS_PROVIDERS does not name openai-embeddings (D-23, PD-22)
  provider_open         D-12 or D-07 is open or Q-09 is unresolved (the loader's rule for every non-fake member), or
                        Q-15's payload review is pending: a query embedding sends the learner's query text, which the
                        payload register lists, and the register's owner review precedes every non-fake adapter (DI-71)
  unpinned              OPENAI_EMBEDDING_MODEL with OPENAI_EMBEDDING_MODEL_VERSION fails pinned-version-v1 (D-07's rule)
  no_budget             the registry's daily budget is 0 (every budget outside development, while A-15 is open)
  gateway_stopped       the process gateway is stopped (a stop guard, or the shared stop, 4.5)
  not_configured        OPENAI_API_KEY is not set in the process environment (the gateway's SecretStore)
With the shipped package D-07, D-12, Q-09 and Q-15 are open, so once an environment opts in the reason is provider_open
and no embedding call is possible anywhere. embedder_for builds the embedder when there is no problem.

OpenAIEmbeddingAdapter, like HttpJsonAdapter, is exercised only through httpx.MockTransport. It posts {model, input,
encoding_format} to the embeddings endpoint (https, no query): the key is read from the SecretStore per call,
registered with the log redaction (owner gateway) and sent only as Authorization: Bearer. Each request reserves
EMBEDDING_COST_UNITS from the process gateway's daily budget; a refusal stops the gateway (budget_breach), and a
stopped gateway refuses every embedding call. Timeouts, transport errors and 429/500/502/503/504 are retried at most
EMBEDDING_MAX_RETRIES times. Every failure raises EmbeddingError(kind, status) after its except block, so its
__cause__ and __context__ are None and no httpx object (whose request holds the headers) is reachable from it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import time
from typing import TYPE_CHECKING, Any, Protocol

from app.gateway.adapters import RETRY_STATUSES
from app.gateway.egress import egress_allowed

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

EMBEDDINGS_PROVIDER = "openai-embeddings"
EMBEDDINGS_SECRET_REF = "OPENAI_API_KEY"
EMBEDDINGS_ENDPOINT = "https://api.openai.com/v1/embeddings"
EMBEDDING_TIMEOUT_MS = 10000
EMBEDDING_MAX_RETRIES = 2
EMBEDDING_BATCH = 256
EMBEDDING_COST_UNITS = 1
EMBEDDING_PROBLEMS = ("egress_not_opted_in", "provider_open", "unpinned", "no_budget", "gateway_stopped", "not_configured")
EMBEDDING_ERROR_KINDS = ("http_status", "timeout", "transport", "invalid_output", "no_key", "stopped", "budget")


class EmbeddingError(RuntimeError):
    def __init__(self, kind: str, status: int | None = None) -> None:
        self.kind, self.status = kind, status
        super().__init__(f"embedding call failed: {kind}" + (f" ({status})" if status is not None else ""))


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def providers_open(package: "ConfigPackage") -> bool:
    """D-12 or D-07 open, Q-09 unresolved, or Q-15's payload review pending; a decision the package does not hold counts
    as open (fail closed)."""
    decisions = package.owner_decisions or {}

    def state(name: str) -> Any:
        entry = decisions.get(name)
        return entry.get("state") if isinstance(entry, dict) else "missing"

    return (state("D-12") in ("open", "missing") or state("D-07") in ("open", "missing")
            or state("Q-09") in ("unresolved", "missing") or state("Q-15") != "reviewed")


def embedding_problem(settings: "Settings", package: "ConfigPackage", *, secret_store=None, gateway=None) -> str | None:
    """Why no provider embedder may run (the module docstring's order), or None."""
    from app.gateway.pinning import pin_problem
    from app.gateway.registry import registry_name
    from app.gateway.secrets import EnvironmentSecretStore

    if not egress_allowed(settings, EMBEDDINGS_PROVIDER):
        return "egress_not_opted_in"
    if package.gateway is None or providers_open(package):
        return "provider_open"
    if pin_problem(settings.openai_embedding_model, settings.openai_embedding_model_version) is not None:
        return "unpinned"
    if package.gateway.daily_units.get(registry_name(settings, package.gateway.registries), 0) == 0:
        return "no_budget"
    if gateway is None:
        from app.gateway.gateway import get_gateway

        gateway = get_gateway()
    gateway.refresh()
    if gateway.state == "stopped":
        return "gateway_stopped"
    store = secret_store if secret_store is not None else EnvironmentSecretStore()
    if not store.get(EMBEDDINGS_SECRET_REF):
        return "not_configured"
    return None


def embedder_for(settings: "Settings", package: "ConfigPackage", *, secret_store=None, gateway=None, transport=None) -> "OpenAIEmbeddingAdapter | None":
    """The provider embedder when embedding_problem finds no problem, else None."""
    from app.gateway.secrets import EnvironmentSecretStore

    store = secret_store if secret_store is not None else EnvironmentSecretStore()
    if embedding_problem(settings, package, secret_store=store, gateway=gateway) is not None:
        return None
    return OpenAIEmbeddingAdapter(settings.openai_embedding_model, settings.openai_embedding_model_version, secret_store=store,
                                  gateway=gateway, transport=transport)


class OpenAIEmbeddingAdapter:
    """The gateway's one embedding adapter (tests: httpx.MockTransport only; no shipped configuration reaches it)."""

    def __init__(self, model_id: str, model_version: str | None, *, secret_store, gateway=None, transport=None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.provider = EMBEDDINGS_PROVIDER
        self.model_id, self.model_version = model_id, model_version
        self._secret_store = secret_store
        self._gateway = gateway
        self._transport = transport
        self._sleep = sleep

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        items = [str(text) for text in texts]
        for start in range(0, len(items), EMBEDDING_BATCH):
            vectors.extend(self._post(items[start:start + EMBEDDING_BATCH]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._post([str(text)])[0]

    def _gateway_or_process(self):
        if self._gateway is not None:
            return self._gateway
        from app.gateway.gateway import get_gateway

        return get_gateway()

    def _headers(self) -> dict[str, str]:
        key = self._secret_store.get(EMBEDDINGS_SECRET_REF)
        if not key:
            raise EmbeddingError("no_key")
        from app.core.log_redaction import install_log_redaction

        install_log_redaction([key], owner="gateway")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _reserve(self) -> None:
        gateway = self._gateway_or_process()
        gateway.check_secret_flag()
        if gateway.state == "stopped":
            raise EmbeddingError("stopped")
        if not gateway.budget.reserve(EMBEDDING_COST_UNITS):
            gateway.stop("budget_breach")
            raise EmbeddingError("budget")

    def _post(self, texts: list[str]) -> list[list[float]]:
        import httpx

        if not texts:
            return []
        self._reserve()
        body = {"model": self.model_id, "input": texts, "encoding_format": "float"}
        failure: tuple[str, int | None] = ("transport", None)
        for attempt in range(1 + EMBEDDING_MAX_RETRIES):
            if attempt:
                self._sleep(0.05 * 2 ** (attempt - 1))
            kind = status = None
            payload = None
            headers = self._headers()
            try:
                with httpx.Client(timeout=EMBEDDING_TIMEOUT_MS / 1000.0, transport=self._transport) as client:
                    response = client.post(EMBEDDINGS_ENDPOINT, headers=headers, json=body)
                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        kind = "invalid_output"
                else:
                    kind = "http_status"
            except httpx.TimeoutException:
                kind = "timeout"
            except httpx.TransportError:
                kind = "transport"
            except httpx.DecodingError:
                kind = "invalid_output"
            except httpx.HTTPError:
                kind = "transport"
            del headers
            if kind is None:
                vectors = _vectors(payload, len(texts))
                if vectors is None:
                    raise EmbeddingError("invalid_output")
                return vectors
            failure = (kind, status)
            retryable = kind in ("timeout", "transport") or (kind == "http_status" and status in RETRY_STATUSES)
            if not retryable:
                break
        raise EmbeddingError(failure[0], failure[1])


def _vectors(payload: Any, count: int) -> list[list[float]] | None:
    """The reply's vectors in input order: {"data": [{"index": i, "embedding": [float, ...]}, ...]}, one per input."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != count:
        return None
    by_index: dict[int, list[float]] = {}
    for item in data:
        index = item.get("index") if isinstance(item, dict) else None
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if type(index) is not int or not isinstance(embedding, list) or not embedding:
            return None
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in embedding):
            return None
        by_index[index] = [float(value) for value in embedding]
    if sorted(by_index) != list(range(count)):
        return None
    return [by_index[index] for index in range(count)]
