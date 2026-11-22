"""The gateway's embedding egress (plan 7.1 "The gateway MUST be the sole holder of provider credentials [Risk R-06]";
7.6 "Provider keys stay in the gateway"; plan H "Only public-corpus spans leave the platform"; D-23; Phase 5 spec 4.19).

The Phase 2 semantic backend (retrieval_engine.PineconeSemanticBackend) embeds its index entries and its queries
through this module only, so no module outside app.gateway reads OPENAI_API_KEY or calls an embedding provider (no
Settings field holds the key). Its parameters are package v4's gateway.embeddings entry (app.gateway.registry.
EmbeddingSpec, provisional, PD-26): the model id and pinned version (null while no model is chosen), the caps
(max_items per request, max_input_chars per input, timeout_ms, max_retries) and cost_units_per_item.
embedding_problem(settings, package) names why no provider embedder may run, the first check that fails giving the
reason:
  egress_not_opted_in   the environment's MODEL_EGRESS_PROVIDERS does not name openai-embeddings (D-23, PD-22)
  provider_open         D-12 or D-07 is open, Q-09 is unresolved or Q-15's payload review is pending (the loader's rule
                        for every non-fake member, app.gateway.registry.providers_open)
  unpinned              gateway.embeddings names no pinned model (D-07's rule; the loader refuses an unpinned one)
  no_budget             the registry's daily budget is 0 (every budget outside development, while A-15 is open)
  gateway_stopped       the process gateway is stopped (a stop guard, or the shared stop, 4.5)
  not_configured        OPENAI_API_KEY is not set in the process environment (the gateway's SecretStore)
  learner_text          the semantic backend embeds every query, and a query embedding sends the learner's query text,
                        which plan H never lets leave (PayloadPolicy.check_embedding refuses it)
So embedding_problem never returns None and embedder_for never builds an embedder: with the shipped package the reason
is provider_open once an environment opts in, and learner_text would remain once every other check passed.

OpenAIEmbeddingAdapter, like HttpJsonAdapter, is exercised only through httpx.MockTransport. A request runs: the shared
stop (gateway.refresh, so a stop another instance wrote is adopted before every request), the secret flag, the stop,
the payload policy (PayloadPolicy.check_embedding: a query item is refused; each document item must be the excerpt of
an index entry of the adapter's store whose span is public and quotable; a violation stops the gateway), the caps (more
than max_items inputs or an input over max_input_chars is invalid_request, before anything is sent), then up to
1 + max_retries attempts. Each attempt first reserves len(inputs) * cost_units_per_item from the process gateway's daily
budget: a refusal stops the gateway (budget_breach), and a budget store that cannot be read or written is
budget_unavailable (nothing is sent, no stop). It posts {model, input, encoding_format} to the embeddings endpoint
(https, no query): the key is read from the SecretStore per attempt, registered with the log redaction (owner gateway)
and sent only as Authorization: Bearer. Timeouts, transport errors and 429/500/502/503/504 are retried. Every failure
raises EmbeddingError(kind, status) after its except block, so its __cause__ and __context__ are None and no httpx
object (whose request holds the headers) is reachable from it.
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
    from app.gateway.registry import EmbeddingSpec

EMBEDDINGS_PROVIDER = "openai-embeddings"
EMBEDDINGS_SECRET_REF = "OPENAI_API_KEY"
EMBEDDINGS_ENDPOINT = "https://api.openai.com/v1/embeddings"
EMBEDDING_PROBLEMS = ("egress_not_opted_in", "provider_open", "unpinned", "no_budget", "gateway_stopped", "not_configured", "learner_text")
EMBEDDING_ERROR_KINDS = ("http_status", "timeout", "transport", "invalid_output", "invalid_request", "no_key", "stopped", "budget",
                         "budget_unavailable", "payload_violation")


class EmbeddingError(RuntimeError):
    def __init__(self, kind: str, status: int | None = None) -> None:
        self.kind, self.status = kind, status
        super().__init__(f"embedding call failed: {kind}" + (f" ({status})" if status is not None else ""))


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def providers_open(package: "ConfigPackage") -> bool:
    """The package's provider gates (app.gateway.registry.providers_open), the loader's rule for every non-fake member."""
    from app.gateway.registry import providers_open as gates_open

    return gates_open(package.owner_decisions)


def embedding_problem(settings: "Settings", package: "ConfigPackage", *, secret_store=None, gateway=None) -> str | None:
    """Why no provider embedder may run (the module docstring's order); learner_text, plan H's bar, is the last check."""
    from app.gateway.pinning import pin_problem
    from app.gateway.registry import registry_name
    from app.gateway.secrets import EnvironmentSecretStore

    if not egress_allowed(settings, EMBEDDINGS_PROVIDER):
        return "egress_not_opted_in"
    spec = package.gateway.embeddings if package.gateway is not None else None
    if spec is None or providers_open(package):
        return "provider_open"
    if spec.model_id is None or pin_problem(spec.model_id, spec.model_version) is not None:
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
    return "learner_text"


def embedder_for(settings: "Settings", package: "ConfigPackage", *, store: Any = None, secret_store=None, gateway=None,
                 transport=None) -> "OpenAIEmbeddingAdapter | None":
    """The provider embedder when embedding_problem finds no problem, else None. While plan H holds it always finds one
    (learner_text at the latest), so no provider embedder is built."""
    from app.gateway.secrets import EnvironmentSecretStore

    secrets = secret_store if secret_store is not None else EnvironmentSecretStore()
    if embedding_problem(settings, package, secret_store=secrets, gateway=gateway) is not None:
        return None
    return OpenAIEmbeddingAdapter(package.gateway.embeddings, store=store, secret_store=secrets, gateway=gateway, transport=transport)


class OpenAIEmbeddingAdapter:
    """The gateway's one embedding adapter (tests: httpx.MockTransport only; no shipped configuration reaches it)."""

    def __init__(self, spec: "EmbeddingSpec", *, store: Any, secret_store, gateway=None, transport=None, corpus_registry: Any = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if spec.model_id is None or spec.model_version is None:
            raise ValueError("the embedding adapter needs a pinned model (gateway.embeddings)")
        self.provider = EMBEDDINGS_PROVIDER
        self.spec = spec
        self.model_id, self.model_version = spec.model_id, spec.model_version
        self._store = store
        self._corpus_registry = corpus_registry
        self._secret_store = secret_store
        self._gateway = gateway
        self._transport = transport
        self._sleep = sleep

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        items = [str(text) for text in texts]
        batch = self.spec.caps.max_items
        for start in range(0, len(items), batch):
            vectors.extend(self._post(items[start:start + batch], purpose="documents"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._post([str(text)], purpose="query")[0]

    def _gateway_or_process(self):
        if self._gateway is not None:
            return self._gateway
        from app.gateway.gateway import get_gateway

        return get_gateway()

    def _context(self):
        if self._store is None:
            return None
        from app.gateway.policy import PolicyContext

        registry = self._corpus_registry
        if registry is None:
            from app.services.span_resolver import SpanResolver

            registry = SpanResolver(self._store).registry
        return PolicyContext(store=self._store, corpus_registry=registry)

    def _headers(self) -> dict[str, str]:
        key = self._secret_store.get(EMBEDDINGS_SECRET_REF)
        if not key:
            raise EmbeddingError("no_key")
        from app.core.log_redaction import install_log_redaction

        install_log_redaction([key], owner="gateway")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _admit(self, texts: list[str], purpose: str) -> None:
        """The checks before any attempt: the shared stop, the secret flag, the stop, the payload policy and the caps."""
        from app.gateway.policy import PayloadViolation

        gateway = self._gateway_or_process()
        gateway.refresh()
        gateway.check_secret_flag()
        if gateway.state == "stopped":
            raise EmbeddingError("stopped")
        try:
            gateway.policy.check_embedding(texts, purpose=purpose, context=self._context())
        except PayloadViolation:
            violation = True
        else:
            violation = False
        if violation:
            gateway.stop("payload_violation")
            raise EmbeddingError("payload_violation")
        caps = self.spec.caps
        if len(texts) > caps.max_items or any(len(text) > caps.max_input_chars for text in texts):
            raise EmbeddingError("invalid_request")

    def _reserve(self, count: int) -> None:
        """One attempt's reservation: count inputs at cost_units_per_item each."""
        gateway = self._gateway_or_process()
        try:
            granted = gateway.budget.reserve(count * self.spec.cost_units_per_item)
        except Exception:  # noqa: BLE001 - an unwritable budget store sends nothing and does not stop the gateway
            granted = None
        if granted is None:
            from app.gateway.gateway import budget_unavailable

            budget_unavailable()
            raise EmbeddingError("budget_unavailable")
        if not granted:
            gateway.stop("budget_breach")
            raise EmbeddingError("budget")

    def _post(self, texts: list[str], *, purpose: str) -> list[list[float]]:
        import httpx

        if not texts:
            return []
        self._admit(texts, purpose)
        caps = self.spec.caps
        body = {"model": self.model_id, "input": texts, "encoding_format": "float"}
        failure: tuple[str, int | None] = ("transport", None)
        for attempt in range(1 + caps.max_retries):
            if attempt:
                self._sleep(0.05 * 2 ** (attempt - 1))
            self._reserve(len(texts))
            kind = status = None
            payload = None
            headers = self._headers()
            try:
                with httpx.Client(timeout=caps.timeout_ms / 1000.0, transport=self._transport) as client:
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
