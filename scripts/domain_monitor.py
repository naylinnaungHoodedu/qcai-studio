"""Domain-registration and TLS-certificate expiry monitor (plan task 1.12, R-34, E-34, Q-21).

Reads the domain's expiry from its registry over RDAP (the server is found through IANA's bootstrap file)
and each host's TLS certificate (issuer and expiry, after normal chain verification). It prints a JSON
record, adds a summary to a GitHub Actions run, and exits 1 when the domain or any certificate is within
its alert threshold or cannot be checked, so a scheduled run turns red and GitHub notifies.

Run: python scripts/domain_monitor.py --domain qantumlearn.academy \
         --host qantumlearn.academy --host api.qantumlearn.academy [--domain-alert-days 60] \
         [--tls-alert-days 21] [--json record.json]

Standard library only, so the workflow needs no installs.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import urllib.request

IANA_DNS_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
DEFAULT_DOMAIN_ALERT_DAYS = 60
DEFAULT_TLS_ALERT_DAYS = 21
_TIMEOUT_SECONDS = 20
_USER_AGENT = "qcai-domain-monitor/1 (+https://qantumlearn.academy)"


@dataclass
class DomainRecord:
    domain: str
    rdap_url: str | None = None
    expires_utc: str | None = None
    registered_utc: str | None = None
    status: list[str] = field(default_factory=list)
    registrar: str | None = None
    days_left: int | None = None
    error: str | None = None


@dataclass
class TlsRecord:
    host: str
    issuer: str | None = None
    subject: str | None = None
    names: list[str] = field(default_factory=list)
    not_before_utc: str | None = None
    not_after_utc: str | None = None
    days_left: int | None = None
    error: str | None = None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _days_left(expires: datetime, now: datetime) -> int:
    return int((expires - now).total_seconds() // 86400)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/rdap+json, application/json", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def rdap_base_url(bootstrap: dict, domain: str) -> str:
    """The registry's RDAP base URL for this domain's top-level domain, from IANA's bootstrap file."""
    tld = domain.rstrip(".").rsplit(".", 1)[-1].lower()
    for tlds, urls in bootstrap.get("services", []):
        if tld in (entry.lower() for entry in tlds):
            https = [url for url in urls if url.startswith("https://")]
            if https:
                return https[0] if https[0].endswith("/") else https[0] + "/"
    raise LookupError(f"No RDAP service is registered for .{tld}")


def _registrar(document: dict) -> str | None:
    for entity in document.get("entities", []):
        if "registrar" not in entity.get("roles", []):
            continue
        for item in (entity.get("vcardArray") or [None, []])[1]:
            if item and item[0] == "fn":
                return str(item[3])
        return entity.get("handle")
    return None


def parse_rdap(document: dict, domain: str, now: datetime, rdap_url: str | None = None) -> DomainRecord:
    events = {event.get("eventAction"): event.get("eventDate") for event in document.get("events", [])}
    record = DomainRecord(domain=domain, rdap_url=rdap_url, status=list(document.get("status", [])), registrar=_registrar(document))
    if events.get("registration"):
        record.registered_utc = _iso(_parse_time(events["registration"]))
    if not events.get("expiration"):
        record.error = "The RDAP record has no expiration event."
        return record
    expires = _parse_time(events["expiration"])
    record.expires_utc = _iso(expires)
    record.days_left = _days_left(expires, now)
    return record


def check_domain(domain: str, now: datetime) -> DomainRecord:
    try:
        url = rdap_base_url(_get_json(IANA_DNS_BOOTSTRAP), domain) + f"domain/{domain}"
        return parse_rdap(_get_json(url), domain, now, rdap_url=url)
    except Exception as error:  # Any failure is reported, and counts as an alert.
        return DomainRecord(domain=domain, error=f"{type(error).__name__}: {error}")


def _name(parts) -> str | None:
    fields = {key: value for part in parts or () for key, value in part}
    return fields.get("organizationName") or fields.get("commonName")


def tls_record(host: str, certificate: dict, now: datetime) -> TlsRecord:
    """A record from `SSLSocket.getpeercert()` output."""
    not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate["notAfter"]), UTC)
    not_before = datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate["notBefore"]), UTC)
    issuer_fields = {key: value for part in certificate.get("issuer", ()) for key, value in part}
    issuer = " / ".join(value for value in (issuer_fields.get("organizationName"), issuer_fields.get("commonName")) if value)
    return TlsRecord(
        host=host,
        issuer=issuer or None,
        subject=_name(certificate.get("subject")),
        names=[value for kind, value in certificate.get("subjectAltName", ()) if kind == "DNS"],
        not_before_utc=_iso(not_before),
        not_after_utc=_iso(not_after),
        days_left=_days_left(not_after, now),
    )


def check_tls(host: str, now: datetime, port: int = 443) -> TlsRecord:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=_TIMEOUT_SECONDS) as raw:
            with context.wrap_socket(raw, server_hostname=host) as connection:
                return tls_record(host, connection.getpeercert(), now)
    except Exception as error:  # Includes a chain or name that fails verification.
        return TlsRecord(host=host, error=f"{type(error).__name__}: {error}")


def alerts_for(domain: DomainRecord, certificates: list[TlsRecord], domain_alert_days: int, tls_alert_days: int) -> list[str]:
    alerts = []
    if domain.error:
        alerts.append(f"{domain.domain}: registration could not be checked ({domain.error})")
    elif domain.days_left is not None and domain.days_left <= domain_alert_days:
        alerts.append(f"{domain.domain}: registration expires {domain.expires_utc}, in {domain.days_left} days (alert at {domain_alert_days})")
    for certificate in certificates:
        if certificate.error:
            alerts.append(f"{certificate.host}: TLS certificate could not be checked ({certificate.error})")
        elif certificate.days_left is not None and certificate.days_left <= tls_alert_days:
            alerts.append(
                f"{certificate.host}: TLS certificate expires {certificate.not_after_utc}, in {certificate.days_left} days (alert at {tls_alert_days})"
            )
    return alerts


def summary_markdown(report: dict) -> str:
    domain = report["domain"]
    lines = [
        "## Domain and TLS expiry",
        "",
        f"Checked {report['checked_utc']}. Alert thresholds: registration {report['domain_alert_days']} days, TLS {report['tls_alert_days']} days.",
        "",
        "| Item | Expires (UTC) | Days left | Detail |",
        "|---|---|---|---|",
        f"| Registration `{domain['domain']}` | {domain['expires_utc'] or '-'} | {domain['days_left'] if domain['days_left'] is not None else '-'} | {domain['error'] or ', '.join(domain['status']) or '-'} |",
    ]
    for certificate in report["tls"]:
        detail = certificate["error"] or f"issuer {certificate['issuer']}"
        days = certificate["days_left"] if certificate["days_left"] is not None else "-"
        lines.append(f"| TLS `{certificate['host']}` | {certificate['not_after_utc'] or '-'} | {days} | {detail} |")
    lines += ["", "**Alerts:**" if report["alerts"] else "No alerts."]
    lines += [f"- {alert}" for alert in report["alerts"]]
    return "\n".join(lines) + "\n"


def build_report(domain: str, hosts: list[str], domain_alert_days: int, tls_alert_days: int, now: datetime) -> dict:
    domain_record = check_domain(domain, now)
    certificates = [check_tls(host, now) for host in hosts]
    return {
        "checked_utc": _iso(now),
        "domain_alert_days": domain_alert_days,
        "tls_alert_days": tls_alert_days,
        "domain": asdict(domain_record),
        "tls": [asdict(certificate) for certificate in certificates],
        "alerts": alerts_for(domain_record, certificates, domain_alert_days, tls_alert_days),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--host", action="append", default=[], help="a host whose TLS certificate is checked (repeatable)")
    parser.add_argument("--domain-alert-days", type=int, default=DEFAULT_DOMAIN_ALERT_DAYS)
    parser.add_argument("--tls-alert-days", type=int, default=DEFAULT_TLS_ALERT_DAYS)
    parser.add_argument("--json", type=Path, help="also write the record to this file")
    args = parser.parse_args(argv)

    report = build_report(args.domain, args.host, args.domain_alert_days, args.tls_alert_days, datetime.now(UTC))
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(summary_markdown(report))
    for alert in report["alerts"]:
        print(f"::error title=Domain or TLS expiry::{alert}", file=sys.stderr)
    return 1 if report["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
