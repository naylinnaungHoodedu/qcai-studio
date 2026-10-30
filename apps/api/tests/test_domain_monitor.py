"""The domain-registration and TLS expiry monitor, offline (plan task 1.12). Real runs: the scheduled workflow."""

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import sys
import threading

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("domain_monitor", REPO_ROOT / "scripts" / "domain_monitor.py")
monitor = importlib.util.module_from_spec(_spec)
sys.modules["domain_monitor"] = monitor  # dataclasses looks the module up while building its classes
_spec.loader.exec_module(monitor)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
BOOTSTRAP = {
    "services": [
        [["com", "net"], ["https://rdap.example-com.test/"]],
        [["academy", "agency"], ["http://insecure.test/", "https://rdap.identitydigital.services/rdap"]],
    ]
}
RDAP_DOCUMENT = {
    "objectClassName": "domain",
    "ldhName": "qantumlearn.academy",
    "status": ["client delete prohibited", "client transfer prohibited"],
    "events": [
        {"eventAction": "registration", "eventDate": "2026-03-27T05:16:30Z"},
        {"eventAction": "expiration", "eventDate": "2027-03-27T05:16:30Z"},
        {"eventAction": "last update of RDAP database", "eventDate": "2026-10-30T11:00:00Z"},
    ],
    "entities": [
        {"roles": ["registrant"], "handle": "REDACTED"},
        {"roles": ["registrar"], "handle": "895", "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Squarespace Domains II LLC"]]]},
    ],
}
CERTIFICATE = {
    "subject": ((("commonName", "qantumlearn.academy"),),),
    "issuer": ((("countryName", "US"),), (("organizationName", "Google Trust Services"),), (("commonName", "WR3"),)),
    "notBefore": "Sep  9 03:10:24 2026 GMT",
    "notAfter": "Dec  8 04:01:56 2026 GMT",
    "subjectAltName": (("DNS", "qantumlearn.academy"),),
}


def test_the_rdap_server_comes_from_the_iana_bootstrap_https_entry():
    assert monitor.rdap_base_url(BOOTSTRAP, "qantumlearn.academy") == "https://rdap.identitydigital.services/rdap/"
    with pytest.raises(LookupError):
        monitor.rdap_base_url(BOOTSTRAP, "example.org")


def test_the_registration_record_reads_expiry_status_and_registrar():
    record = monitor.parse_rdap(RDAP_DOCUMENT, "qantumlearn.academy", NOW)

    assert (record.expires_utc, record.registered_utc, record.days_left) == ("2027-03-27T05:16:30Z", "2026-03-27T05:16:30Z", 147)
    assert record.registrar == "Squarespace Domains II LLC"
    assert record.status == ["client delete prohibited", "client transfer prohibited"]


def test_a_record_without_an_expiration_event_is_an_error():
    document = {**RDAP_DOCUMENT, "events": [{"eventAction": "registration", "eventDate": "2026-03-27T05:16:30Z"}]}

    assert monitor.parse_rdap(document, "qantumlearn.academy", NOW).error == "The RDAP record has no expiration event."


def test_the_tls_record_reads_issuer_names_and_expiry():
    record = monitor.tls_record("qantumlearn.academy", CERTIFICATE, NOW)

    assert record.issuer == "Google Trust Services / WR3"
    assert (record.subject, record.names) == ("qantumlearn.academy", ["qantumlearn.academy"])
    assert (record.not_after_utc, record.days_left) == ("2026-12-08T04:01:56Z", 38)


@pytest.mark.parametrize(
    ("domain_days", "tls_days", "expected"),
    [(60, 21, 0), (147, 21, 1), (400, 21, 1), (60, 38, 1), (60, 37, 0)],
    ids=["below-thresholds", "registration-at-threshold", "registration-high-threshold", "tls-at-threshold", "tls-below"],
)
def test_alerts_fire_at_or_within_each_threshold(domain_days, tls_days, expected):
    domain = monitor.parse_rdap(RDAP_DOCUMENT, "qantumlearn.academy", NOW)
    certificate = monitor.tls_record("qantumlearn.academy", CERTIFICATE, NOW)

    assert len(monitor.alerts_for(domain, [certificate], domain_days, tls_days)) == expected


def test_a_check_that_cannot_run_is_an_alert():
    domain = monitor.DomainRecord(domain="qantumlearn.academy", error="URLError: timed out")
    certificate = monitor.TlsRecord(host="www.qantumlearn.academy", error="gaierror: getaddrinfo failed")

    alerts = monitor.alerts_for(domain, [certificate], 60, 21)

    assert len(alerts) == 2
    assert "could not be checked" in alerts[0] and "could not be checked" in alerts[1]


def test_a_certificate_that_fails_verification_is_an_alert(tmp_path):
    # A local TLS server with a self-signed certificate: the check must refuse it, not record it.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_path, key_path = tmp_path / "server.pem", tmp_path / "server.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate_path, key_path)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve_once() -> None:
        connection, _ = listener.accept()
        try:
            with server_context.wrap_socket(connection, server_side=True):
                pass
        except (ssl.SSLError, OSError):
            pass

    server = threading.Thread(target=serve_once, daemon=True)
    server.start()
    record = monitor.check_tls("127.0.0.1", NOW, port=port)
    server.join(timeout=10)
    listener.close()

    assert record.error is not None and "CERTIFICATE_VERIFY_FAILED" in record.error
    domain = monitor.parse_rdap(RDAP_DOCUMENT, "qantumlearn.academy", NOW)
    assert monitor.alerts_for(domain, [record], 60, 21) == [f"127.0.0.1: TLS certificate could not be checked ({record.error})"]


def _offline(monkeypatch):
    monkeypatch.setattr(monitor, "check_domain", lambda domain, now: monitor.parse_rdap(RDAP_DOCUMENT, domain, NOW))
    monkeypatch.setattr(monitor, "check_tls", lambda host, now: monitor.tls_record(host, CERTIFICATE, NOW))


def test_a_run_below_the_thresholds_exits_0_and_writes_the_record_and_summary(monkeypatch, tmp_path):
    _offline(monkeypatch)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    record = tmp_path / "record.json"

    code = monitor.main(["--domain", "qantumlearn.academy", "--host", "qantumlearn.academy", "--json", str(record)])

    assert code == 0
    report = json.loads(record.read_text(encoding="utf-8"))
    assert report["alerts"] == [] and report["domain"]["days_left"] == 147
    assert "No alerts." in summary.read_text(encoding="utf-8")


def test_a_run_with_a_high_threshold_proves_the_alert_fires(monkeypatch, tmp_path, capsys):
    # The readiness assessment's validation: set the threshold high and the run must fail with an alert.
    _offline(monkeypatch)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    code = monitor.main(["--domain", "qantumlearn.academy", "--host", "qantumlearn.academy", "--domain-alert-days", "400"])

    assert code == 1
    assert "::error title=Domain or TLS expiry::qantumlearn.academy: registration expires 2027-03-27T05:16:30Z, in 147 days" in capsys.readouterr().err


def test_the_workflow_runs_daily_with_read_only_rights_and_no_inline_inputs():
    workflow = (REPO_ROOT / ".github" / "workflows" / "domain-monitor.yml").read_text(encoding="utf-8")

    assert 'cron: "17 6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "permissions:\n  contents: read" in workflow.replace("\r\n", "\n")
    run_block = workflow.split("run: >-", 1)[1].split("- name:", 1)[0]
    assert "${{" not in run_block, "dispatch inputs must reach the shell through env, not inline"
    assert "--host qantumlearn.academy" in run_block and "--host api.qantumlearn.academy" in run_block
