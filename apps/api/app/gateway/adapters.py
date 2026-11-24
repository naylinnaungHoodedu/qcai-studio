"""Model adapters (plan Phase 5 E1; tasks 5.10 caps, 5.12 keys and redaction; AC-5-9; R-06; Phase 5 spec 3.1, 4.3).

ModelAdapter: spec, available(), verify(request) -> dict and align(request) -> dict, the provider's output before
projection. The gateway projects it onto the verdict keys and validates it (project_verdict, project_alignment):
any other key, a rationale included, is dropped; a missing key, a wrong type or a span id other than the request's
is AdapterError(kind="invalid_output").

FakeAdapter is the development and test family (rule verbatim-support-v1): a claim is SUPPORTED iff its NFKC-casefolded,
whitespace-collapsed text lies inside the same fold of the span text, else NOT_ENOUGH_INFO with EHMF B; an alignment
item gets rating 4 and no leakage. It makes no network call. down, script (claim text sha256 and span id, or "*", to a
verdict and EHMF type, or "error"), late_ms (advancing an injected clock) and calls serve fault injection; it keeps
the requests it was given only when built with record=True (a test's choice), so a long-running process holds none.

HttpJsonAdapter is provider-neutral and exercised only through httpx.MockTransport; no shipped registry can hold it (the
loader refuses a non-fake member while D-12, D-07 or Q-09 is open or the Q-15 review is pending). Its endpoint is https with no query, userinfo or fragment (keys
and parameters never travel in the URL); the key is read from the secret store per call and travels only in a header
(Authorization: Bearer or x-api-key). The body is {model, model_version, max_tokens, instructions, input}: the fixed
instruction text of the request's prompt id (the text whose hash the request carries; a request naming another hash
is refused, invalid_request) and the request contract. Timeouts, transport errors and 429/500/502/503/504 are retried
at most caps.max_retries times, a 4xx other than 429 never; a body the client cannot decode is invalid_output and any
other httpx error is transport. Before each retry it calls the gateway's reserve_retry hook, which reserves one more
call's cost from the daily budget; a refused reservation sends nothing more and is budget, on which the gateway stops
(budget_breach) unless the budget's store failed (the member is then only unavailable). The reply's usage.cost_units must be a non-negative integer no larger than the call's
reservation (spec.cost_units_per_call), else cost_overrun, on which the gateway stops (budget_breach). Every failure
raises AdapterError(adapter_id, kind, status) after its except block, so the error's __cause__ and __context__ are None
and no httpx object (whose request holds the headers) is reachable from it; its text names the adapter, the kind and
the status only. The adapter never logs.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import time
from typing import Any, Protocol
from urllib.parse import urlsplit
import unicodedata

from pydantic import ValidationError

from app.gateway.contracts import ALIGNMENT_KEYS, VERDICT_KEYS, AdapterVerdict, AlignmentRequest, AlignmentVerdict, VerdictRequest
from app.gateway.registry import AdapterSpec
from app.services.v2_panel import rules

WIRED_FAKE_RULES = frozenset({"verbatim-support-v1"})
# Package v7 (Phase 9 spec 4.12): the one fake generate rule, the extractive clone (app.services.ranking.generators), which
# runs only for development shadow generation (RANKING_SHADOW_GENERATION) and makes no gateway or network call.
WIRED_FAKE_GENERATE_RULES = frozenset({"extractive-clone-v1"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# "error" is the gateway's kind for an adapter that raised anything but an AdapterError.
ERROR_KINDS = ("http_status", "timeout", "transport", "invalid_output", "invalid_request", "cost_overrun", "budget", "no_key", "down",
               "scripted", "error")
# The fixed instruction text of each prompt id and the hash that names it (Phase 5 spec 4.7; E-97).
INSTRUCTIONS = {
    rules.VERIFIER_PROMPT_ID: (rules.VERIFIER_INSTRUCTIONS, rules.verifier_prompt_hash),
    rules.ALIGNMENT_PROMPT_ID: (rules.ALIGNMENT_INSTRUCTIONS, rules.alignment_prompt_hash),
}


class AdapterError(RuntimeError):
    def __init__(self, adapter_id: str, kind: str, status: int | None = None) -> None:
        self.adapter_id, self.kind, self.status = adapter_id, kind, status
        super().__init__(f"adapter {adapter_id} failed: {kind}" + (f" ({status})" if status is not None else ""))


class ModelAdapter(Protocol):
    spec: AdapterSpec

    def available(self) -> bool: ...

    def verify(self, request: VerdictRequest) -> dict: ...

    def align(self, request: AlignmentRequest) -> dict: ...


def fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def claim_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_verdict(raw: Any, request: VerdictRequest, adapter_id: str) -> AdapterVerdict:
    if not isinstance(raw, dict) or not all(key in raw for key in VERDICT_KEYS):
        raise AdapterError(adapter_id, "invalid_output")
    try:
        verdict = AdapterVerdict.model_validate({key: raw[key] for key in VERDICT_KEYS})
    except ValidationError:
        verdict = None
    if verdict is None or verdict.span_id != request.span.span_id:
        raise AdapterError(adapter_id, "invalid_output")
    return verdict


def project_alignment(raw: Any, adapter_id: str) -> AlignmentVerdict:
    if not isinstance(raw, dict) or not all(key in raw for key in ALIGNMENT_KEYS):
        raise AdapterError(adapter_id, "invalid_output")
    try:
        verdict = AlignmentVerdict.model_validate({key: raw[key] for key in ALIGNMENT_KEYS})
    except ValidationError:
        verdict = None
    if verdict is None:
        raise AdapterError(adapter_id, "invalid_output")
    return verdict


class FakeAdapter:
    """A deterministic fake family member; no network call."""

    def __init__(self, spec: AdapterSpec, *, script: dict | None = None, down: bool = False, late_ms: float = 0.0,
                 clock: Any = None, alignment: dict | None = None, record: bool = False) -> None:
        if spec.provider != "fake" or spec.fake_rule not in WIRED_FAKE_RULES:
            raise ValueError(f"adapter {spec.adapter_id} is not a wired fake")
        self.spec = spec
        self.script = dict(script or {})
        self.down = down
        self.late_ms = late_ms
        self.clock = clock
        self.alignment = dict(alignment or {"rating": 4, "leakage": False})
        self.calls = 0
        # The process gateway caches one adapter per id for the life of the process: it keeps no request unless asked.
        self.record = record
        self.requests: list = []

    def _keep(self, request: Any) -> None:
        if self.record:
            self.requests.append(request)

    def available(self) -> bool:
        return not self.down

    def _tick(self) -> None:
        self.calls += 1
        if self.late_ms and self.clock is not None:
            self.clock.now += self.late_ms / 1000.0
        if self.down:
            raise AdapterError(self.spec.adapter_id, "down")

    def verify(self, request: VerdictRequest) -> dict:
        self._tick()
        self._keep(request)
        key = (claim_text_sha256(request.claim_text), request.span.span_id)
        scripted = self.script.get(key, self.script.get("*"))
        if scripted == "error":
            raise AdapterError(self.spec.adapter_id, "scripted")
        if scripted is not None:
            verdict, ehmf = scripted
            return {"verdict": verdict, "ehmf_type": ehmf, "span_id": request.span.span_id, "rationale": "scripted"}
        supported = fold(request.claim_text) in fold(request.span.text)
        return {"verdict": "SUPPORTED" if supported else "NOT_ENOUGH_INFO", "ehmf_type": None if supported else "B",
                "span_id": request.span.span_id}

    def align(self, request: AlignmentRequest) -> dict:
        self._tick()
        self._keep(request)
        return dict(self.alignment)


class HttpJsonAdapter:
    """A provider-neutral JSON-over-HTTPS adapter (tests: httpx.MockTransport only; never in a shipped registry)."""

    def __init__(self, spec: AdapterSpec, *, secret_store, transport=None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        parts = urlsplit(spec.endpoint or "")
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.username or parts.password or "@" in parts.netloc:
            raise ValueError("an adapter endpoint is https with no query, userinfo or fragment: keys and parameters never travel in the URL")
        if spec.auth_header not in ("authorization-bearer", "x-api-key") or not spec.secret_ref:
            raise ValueError("an HTTP adapter names its auth header and its secret reference")
        self.spec = spec
        self._secret_store = secret_store
        self._transport = transport
        self._sleep = sleep
        self._clock = clock

    def available(self) -> bool:
        return True

    def verify(self, request: VerdictRequest, *, reserve_retry: Callable[[], bool] | None = None) -> dict:
        return self._post(request, reserve_retry)

    def align(self, request: AlignmentRequest, *, reserve_retry: Callable[[], bool] | None = None) -> dict:
        return self._post(request, reserve_retry)

    def _headers(self) -> dict[str, str]:
        key = self._secret_store.get(self.spec.secret_ref)
        if not key:
            raise AdapterError(self.spec.adapter_id, "no_key")
        from app.core.log_redaction import install_log_redaction

        install_log_redaction([key], owner="gateway")
        if self.spec.auth_header == "authorization-bearer":
            return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        return {"x-api-key": key, "Content-Type": "application/json"}

    def _post(self, request, reserve_retry: Callable[[], bool] | None = None) -> dict:
        """One call: up to 1 + caps.max_retries attempts; each retry is reserved through reserve_retry first (the gateway's
        hook; a direct call without it, as in the adapter's own tests, reserves nothing)."""
        import httpx

        spec = self.spec
        text, hashed = INSTRUCTIONS[request.instructions.prompt_id]
        if request.instructions.prompt_hash != hashed():
            raise AdapterError(spec.adapter_id, "invalid_request")
        body = {"model": spec.model_id, "model_version": spec.model_version, "max_tokens": spec.caps.max_tokens,
                "instructions": text, "input": request.model_dump(mode="json")}
        attempts = 1 + spec.caps.max_retries
        failure: tuple[str, int | None] = ("transport", None)
        for attempt in range(attempts):
            if attempt:
                if reserve_retry is not None and not reserve_retry():
                    failure = ("budget", None)
                    break
                self._sleep(0.05 * 2 ** (attempt - 1))
            kind = status = None
            payload = None
            headers = self._headers()
            try:
                with httpx.Client(timeout=spec.caps.timeout_ms / 1000.0, transport=self._transport) as client:
                    response = client.post(spec.endpoint, headers=headers, json=body)
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
                kind = "invalid_output"  # a body the client cannot decode (a bad content encoding)
            except httpx.HTTPError:
                kind = "transport"       # any other client error (too many redirects, ...)
            del headers
            if kind is None:
                output = payload.get("output") if isinstance(payload, dict) else None
                usage = payload.get("usage") if isinstance(payload, dict) else None
                cost = usage.get("cost_units") if isinstance(usage, dict) else None
                if not isinstance(output, dict) or type(cost) is not int or cost < 0:
                    raise AdapterError(spec.adapter_id, "invalid_output")
                if cost > spec.cost_units_per_call:
                    raise AdapterError(spec.adapter_id, "cost_overrun")
                return output
            failure = (kind, status)
            retryable = kind in ("timeout", "transport") or (kind == "http_status" and status in RETRY_STATUSES)
            if not retryable:
                break
        raise AdapterError(spec.adapter_id, failure[0], failure[1])
