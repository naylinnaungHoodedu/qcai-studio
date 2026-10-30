"""Machine-generated deployment record (plan task 1.9, AC-1-7).

AC-1-7: "A committed deployment record names digest and commit; /health returns that commit." For each
Cloud Run service this reads which revisions serve traffic and their image digests (read-only `gcloud`
describes) and the public /health, then checks that:
  - traffic is pinned to named revisions (no "latest revision" routing);
  - every serving revision's image digest is recorded;
  - /health reports the expected commit.
It writes the record (JSON) either way, lists any failure, and exits 1 if a check fails. A passing record is
committed by pull request (infra/cloudrun/deployment.md).

Run: python scripts/deployment_record.py --commit <40-char commit> [--write deploy/records]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

DEFAULT_PROJECT = "naylinnaung"
DEFAULT_REGION = "us-central1"
DEFAULT_SERVICES = ("qcai-api=https://api.qantumlearn.academy", "qcai-frontend=https://qantumlearn.academy")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r".+@sha256:[0-9a-f]{64}")
_TIMEOUT_SECONDS = 20


def gcloud_json(arguments: list[str]) -> dict:
    # Resolved to a full path: on Windows gcloud is a .cmd file, which a bare name does not find.
    completed = subprocess.run(
        [shutil.which("gcloud") or "gcloud", *arguments], capture_output=True, text=True, timeout=120, check=True
    )
    return json.loads(completed.stdout)


def describe_service(service: str, project: str, region: str) -> dict:
    return gcloud_json(
        ["run", "services", "describe", service, "--project", project, "--region", region,
         "--format=json(metadata.name,status.url,status.traffic)"]
    )


def describe_revision(revision: str, project: str, region: str) -> dict:
    return gcloud_json(
        ["run", "revisions", "describe", revision, "--project", project, "--region", region,
         "--format=json(metadata.name,metadata.creationTimestamp,status.imageDigest)"]
    )


def fetch_health(base_url: str) -> dict:
    request = urllib.request.Request(base_url.rstrip("/") + "/health", headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # Reported in the record; a missing commit fails the check.
        return {"error": f"{type(error).__name__}: {error}"}


def service_entry(name: str, public_url: str, service: dict, revisions: dict[str, dict], health: dict, commit: str) -> dict:
    """The record for one service, from `describe_service`, `describe_revision` per serving revision, and /health."""
    traffic = []
    for route in service.get("status", {}).get("traffic", []):
        revision_name = route.get("revisionName")
        revision = revisions.get(revision_name, {})
        traffic.append(
            {
                "revision": revision_name,
                "percent": int(route.get("percent") or 0),
                "latest_revision": bool(route.get("latestRevision")),
                "tag": route.get("tag"),
                "image_digest": revision.get("status", {}).get("imageDigest"),
                "created_utc": revision.get("metadata", {}).get("creationTimestamp"),
            }
        )
    serving = [route for route in traffic if route["percent"] > 0]
    problems = []
    if not serving:
        problems.append("no revision serves traffic")
    if any(route["latest_revision"] for route in serving):
        problems.append("traffic follows the latest revision instead of a named one")
    for route in serving:
        if not route["image_digest"] or not DIGEST_PATTERN.fullmatch(route["image_digest"]):
            problems.append(f"no image digest recorded for {route['revision']}")
    reported = health.get("commit")
    if health.get("error"):
        problems.append(f"/health could not be read ({health['error']})")
    elif reported != commit:
        problems.append(f"/health reports commit {reported!r}, expected {commit}")
    return {
        "service": name,
        "public_url": public_url,
        "run_url": service.get("status", {}).get("url"),
        "traffic": traffic,
        "health": health,
        "problems": problems,
    }


def build_record(commit: str, project: str, region: str, services: list[tuple[str, str]], now: datetime) -> dict:
    entries = []
    for name, public_url in services:
        service = describe_service(name, project, region)
        revisions = {
            route["revisionName"]: describe_revision(route["revisionName"], project, region)
            for route in service.get("status", {}).get("traffic", [])
            if route.get("revisionName") and int(route.get("percent") or 0) > 0
        }
        entries.append(service_entry(name, public_url, service, revisions, fetch_health(public_url), commit))
    return {
        "recorded_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "project": project,
        "region": region,
        "services": entries,
        "ok": all(not entry["problems"] for entry in entries),
    }


def _service_pair(value: str) -> tuple[str, str]:
    name, separator, url = value.partition("=")
    if not separator or not name or not url.startswith("https://"):
        raise argparse.ArgumentTypeError("expected SERVICE=https://public.host")
    return name, url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", required=True, help="the full commit the services should be serving")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--service", action="append", type=_service_pair, help="SERVICE=https://public.host (repeatable)")
    parser.add_argument("--write", type=Path, help="directory to write <recorded_utc>.json into")
    args = parser.parse_args(argv)
    if not COMMIT_PATTERN.fullmatch(args.commit):
        parser.error("--commit must be a full 40-character commit")
    services = args.service or [_service_pair(value) for value in DEFAULT_SERVICES]

    record = build_record(args.commit, args.project, args.region, services, datetime.now(UTC))
    text = json.dumps(record, indent=2, sort_keys=True)
    print(text)
    if args.write:
        args.write.mkdir(parents=True, exist_ok=True)
        (args.write / f"{record['recorded_utc'].replace(':', '')}.json").write_text(text + "\n", encoding="utf-8")
    for entry in record["services"]:
        for problem in entry["problems"]:
            print(f"{entry['service']}: {problem}", file=sys.stderr)
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
