from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db_models import PublicWebVital, SupportRequest
from app.main import app


client = TestClient(app)
TRUSTED_ORIGIN = "http://localhost:3000"


def test_support_request_records_structured_ticket():
    email = f"support-{uuid4().hex[:8]}@qcai.local"
    response = client.post(
        "/support/requests",
        headers={"origin": TRUSTED_ORIGIN, "user-agent": "pytest-support"},
        json={
            "name": "Audit Reviewer",
            "email": email,
            "organization": "Codex Creator Challenge",
            "request_type": "partnership",
            "page_url": "https://qantumlearn.academy/support",
            "message": "Requesting a structured partner review path and expected timeline for evaluation.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "received"
    assert payload["ticket_id"].startswith("SUP-")
    assert "business days" in payload["response_target"]

    with SessionLocal() as db:
        support_request = db.scalars(select(SupportRequest).where(SupportRequest.email == email)).first()
        assert support_request is not None
        assert support_request.request_type == "partnership"
        assert support_request.requester_origin == TRUSTED_ORIGIN


def test_support_request_requires_trusted_origin():
    response = client.post(
        "/support/requests",
        headers={"origin": "https://untrusted.example"},
        json={
            "name": "Audit Reviewer",
            "email": f"blocked-{uuid4().hex[:8]}@qcai.local",
            "request_type": "product",
            "message": "This request should be rejected because it does not come from a trusted origin.",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Untrusted request origin."


def test_public_web_vitals_accepts_same_origin_samples_without_auth():
    metric_id = f"vital-{uuid4()}"
    response = client.post(
        "/analytics/public-web-vitals",
        headers={"origin": TRUSTED_ORIGIN, "user-agent": "pytest-vitals"},
        json={
            "metric_id": metric_id,
            "metric_name": "LCP",
            "path": "/support",
            "value": 1820.4,
            "delta": 125.0,
            "rating": "good",
            "navigation_type": "navigate",
            "connection_type": "4g",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    with SessionLocal() as db:
        sample = db.scalars(select(PublicWebVital).where(PublicWebVital.metric_id == metric_id)).first()
        assert sample is not None
        assert sample.metric_name == "LCP"
        assert sample.path == "/support"
        assert sample.rating == "good"


def test_public_web_vitals_summary_reports_recent_metrics():
    metric_prefix = uuid4().hex[:8]
    for value, rating in ((1450.0, "good"), (2650.0, "needs-improvement")):
        response = client.post(
            "/analytics/public-web-vitals",
            headers={"origin": TRUSTED_ORIGIN},
            json={
                "metric_id": f"{metric_prefix}-{value}",
                "metric_name": "LCP",
                "path": "/modules",
                "value": value,
                "delta": 0,
                "rating": rating,
                "navigation_type": "navigate",
            },
        )
        assert response.status_code == 200

    summary_response = client.get("/analytics/public-web-vitals/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["status"] == "ok"
    assert summary["total_samples"] >= 2
    assert "/modules" in summary["monitored_paths"]
    lcp = next(item for item in summary["metrics"] if item["metric_name"] == "LCP")
    assert lcp["sample_count"] >= 2
    assert lcp["p75_value"] >= 1450.0
    assert lcp["good_rate_percent"] <= 100.0


def test_public_web_vitals_is_idempotent_by_metric_id():
    metric_id = f"vital-{uuid4()}"
    payload = {
        "metric_id": metric_id,
        "metric_name": "LCP",
        "path": "/support",
        "value": 1820.4,
        "delta": 125.0,
        "rating": "good",
        "navigation_type": "navigate",
        "connection_type": "4g",
    }

    first = client.post(
        "/analytics/public-web-vitals",
        headers={"origin": TRUSTED_ORIGIN, "user-agent": "pytest-vitals"},
        json=payload,
    )
    second = client.post(
        "/analytics/public-web-vitals",
        headers={"origin": TRUSTED_ORIGIN, "user-agent": "pytest-vitals"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200

    with SessionLocal() as db:
        stored = db.scalars(select(PublicWebVital).where(PublicWebVital.metric_id == metric_id)).all()
        assert len(stored) == 1
