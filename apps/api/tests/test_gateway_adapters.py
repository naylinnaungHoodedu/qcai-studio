"""Phase 5 model adapters (plan Phase 5 E1, tasks 5.10 and 5.12; AC-5-9; R-06; Phase 5 spec 3.1, 4.3). The HTTP adapter
runs only over httpx.MockTransport: no test touches the network."""

from __future__ import annotations

import json

import httpx
import pytest

from app.gateway.adapters import AdapterError, FakeAdapter, HttpJsonAdapter, claim_text_sha256, project_verdict
from app.gateway.contracts import VerdictInstructions, VerdictRequest, VerdictSpan
from app.services.v2_panel.rules import verifier_prompt_hash
from v1_fakes import InjectedClock
from v2_fakes import FakeSecretStore, fake_spec, fresh_gateway

SPAN = "span-" + "a" * 64
OTHER = "span-" + "b" * 64
KEY = "test-provider-key-0123456789"


def request(claim: str = "Routing control keeps compiled circuits within the device topology.",
            span_text: str = "In practice, routing control keeps compiled circuits within the device topology. It runs at each step.") -> VerdictRequest:
    return VerdictRequest(claim_text=claim, span=VerdictSpan(span_id=SPAN, text=span_text),
                          instructions=VerdictInstructions(prompt_hash=verifier_prompt_hash(), tool_contract_version="mcp-tools-v1"))


def http_spec(**overrides):
    options = dict(provider="test-provider", endpoint="https://verifier.invalid/v1/verdicts", auth_header="authorization-bearer",
                   secret_ref="TEST_PROVIDER_KEY", max_retries=2)
    options.update(overrides)
    return fake_spec("test-family", **options)


def test_the_fake_rule_supports_a_verbatim_claim_and_objects_to_anything_else():
    adapter = FakeAdapter(fake_spec("fake-alpha"))
    assert adapter.verify(request())["verdict"] == "SUPPORTED"
    folded = adapter.verify(request(claim="ROUTING   control keeps compiled circuits within the device topology."))
    assert folded["verdict"] == "SUPPORTED" and folded["ehmf_type"] is None
    other = adapter.verify(request(claim="Routing control is never needed."))
    assert (other["verdict"], other["ehmf_type"]) == ("NOT_ENOUGH_INFO", "B")
    assert adapter.align(None) == {"rating": 4, "leakage": False} and adapter.calls == 4
    with pytest.raises(ValueError):
        FakeAdapter(http_spec())


def test_a_scripted_table_down_and_late_fakes():
    claim = request().claim_text
    adapter = FakeAdapter(fake_spec("fake-beta"), script={(claim_text_sha256(claim), SPAN): ("CONTRADICTED", "A")})
    assert adapter.verify(request())["verdict"] == "CONTRADICTED"
    everywhere = FakeAdapter(fake_spec("fake-beta"), script={"*": ("NOT_ENOUGH_INFO", "C")})
    assert everywhere.verify(request())["ehmf_type"] == "C"
    erroring = FakeAdapter(fake_spec("fake-beta"), script={"*": "error"})
    with pytest.raises(AdapterError):
        erroring.verify(request())
    down = FakeAdapter(fake_spec("fake-gamma"), down=True)
    assert not down.available()
    with pytest.raises(AdapterError):
        down.verify(request())


def test_a_late_fake_is_a_timeout_at_the_gateway(monkeypatch):
    from app.gateway import policy

    monkeypatch.setattr(policy.PayloadPolicy, "check", lambda self, request, context: None)
    clock = InjectedClock()
    late = FakeAdapter(fake_spec("fake-delta", timeout_ms=50), late_ms=80, clock=clock)
    gateway = fresh_gateway(adapters={"fake-delta-v1": late}, clock=clock)
    with pytest.raises(AdapterError) as excinfo:
        gateway.verify(late.spec, request(), context=None)
    assert excinfo.value.kind == "timeout" and late.calls == 1
    in_time = FakeAdapter(fake_spec("fake-alpha", timeout_ms=50), late_ms=10, clock=clock)
    assert fresh_gateway(adapters={"fake-alpha-v1": in_time}, clock=clock).verify(in_time.spec, request(), context=None).verdict == "SUPPORTED"


def test_output_is_projected_onto_the_verdict_keys_and_a_wrong_span_or_shape_is_invalid():
    verdict = project_verdict({"verdict": "SUPPORTED", "ehmf_type": None, "span_id": SPAN, "rationale": "x" * 50}, request(), "a")
    assert verdict.model_dump() == {"verdict": "SUPPORTED", "ehmf_type": None, "span_id": SPAN}
    for raw in ({"verdict": "SUPPORTED", "ehmf_type": None, "span_id": OTHER}, {"verdict": "SUPPORTED", "span_id": SPAN},
                {"verdict": "MAYBE", "ehmf_type": None, "span_id": SPAN}, {"verdict": "CONTRADICTED", "ehmf_type": None, "span_id": SPAN}, []):
        with pytest.raises(AdapterError) as excinfo:
            project_verdict(raw, request(), "a")
        assert excinfo.value.kind == "invalid_output"


def _transport(responses: list, seen: list):
    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        item = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler)


def test_the_http_adapter_sends_the_key_in_a_header_with_its_caps_and_returns_the_output():
    seen: list = []
    body = {"output": {"verdict": "SUPPORTED", "ehmf_type": None, "span_id": SPAN, "rationale": "dropped"}, "usage": {"cost_units": 1}}
    adapter = HttpJsonAdapter(http_spec(), secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": KEY}),
                              transport=_transport([httpx.Response(200, json=body)], seen), sleep=lambda seconds: None)
    output = adapter.verify(request())
    assert project_verdict(output, request(), "test-family-v1").verdict == "SUPPORTED"
    sent = seen[0]
    assert sent.headers["authorization"] == f"Bearer {KEY}" and not sent.url.query and KEY not in str(sent.url)
    payload = json.loads(sent.content)
    assert payload["max_tokens"] == 256 and payload["model"] == "test-family-verifier" and payload["input"]["item"] == "claim"
    header = HttpJsonAdapter(http_spec(auth_header="x-api-key"), secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": KEY}),
                             transport=_transport([httpx.Response(200, json=body)], seen), sleep=lambda seconds: None)
    header.verify(request())
    assert seen[-1].headers["x-api-key"] == KEY and "authorization" not in seen[-1].headers
    assert not any(KEY in repr(value) for value in vars(adapter).values())  # no attribute holds the key


@pytest.mark.parametrize("responses, kind, attempts", [
    ([httpx.Response(500)] * 5, "http_status", 3),
    ([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"output": {}, "usage": {"cost_units": 1}})], None, 3),
    ([httpx.Response(401)] * 5, "http_status", 1),
    ([httpx.Response(404)] * 5, "http_status", 1),
    ([httpx.ReadTimeout("slow")] * 5, "timeout", 3),
    ([httpx.ConnectError("refused")] * 5, "transport", 3),
    ([httpx.Response(200, content=b"not json")] * 5, "invalid_output", 1),
    ([httpx.Response(200, json={"output": {}})] * 5, "invalid_output", 1),
])
def test_retries_are_bounded_and_every_failure_is_raised_with_no_cause_or_context(responses, kind, attempts):
    seen: list = []
    sleeps: list = []
    adapter = HttpJsonAdapter(http_spec(), secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": KEY}), transport=_transport(responses, seen),
                              sleep=sleeps.append)
    if kind is None:
        assert adapter.verify(request()) == {}
    else:
        with pytest.raises(AdapterError) as excinfo:
            adapter.verify(request())
        error = excinfo.value
        assert error.kind == kind and error.__cause__ is None and error.__context__ is None
        assert KEY not in str(error) and KEY not in repr(error) and "Bearer" not in str(error) and "verifier.invalid" not in str(error)
    assert len(seen) == attempts and len(sleeps) == attempts - 1


def test_no_key_and_an_endpoint_with_a_query_userinfo_fragment_or_plain_http_are_refused():
    seen: list = []
    adapter = HttpJsonAdapter(http_spec(), secret_store=FakeSecretStore({}), transport=_transport([httpx.Response(200)], seen))
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify(request())
    assert excinfo.value.kind == "no_key" and seen == []
    for endpoint in ("https://verifier.invalid/v1?key=abc", "https://user:pass@verifier.invalid/v1", "https://verifier.invalid/v1#x",
                     "http://verifier.invalid/v1"):
        with pytest.raises(ValueError, match="never travel in the URL"):
            HttpJsonAdapter(http_spec(endpoint=endpoint), secret_store=FakeSecretStore({}))
