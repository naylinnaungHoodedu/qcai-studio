"""Deploy one commit's image to Cloud Run by digest and pin traffic to that revision (plan task 1.9, AC-1-7).

Without --execute this only prints the plan; it may still resolve the digest, which is a read. With --execute
it makes Cloud Run writes, which need the Platform Owner's approval and a D-05 release approval.

1. resolve <registry>/<service>:<commit> to its digest (or take --digest);
2. gcloud run deploy <service> --image <registry>/<service>@sha256:... --no-traffic --tag c-<commit[:12]>;
3. check that the new revision's tagged URL reports the commit on /health (--no-pin stops here, for checks on
   the tagged URL before any traffic moves);
4. gcloud run services update-traffic <service> --to-revisions <revision>=100: a named revision, so traffic
   no longer follows "latest";
5. then run scripts/deployment_record.py --commit <commit> --write deploy/records and commit that record by PR.

Rollback: gcloud run services update-traffic <service> --to-revisions <previous revision>=100
(infra/cloudrun/deployment.md).

Run: python scripts/deploy_by_digest.py --service qcai-api --commit <40-char commit> [--execute]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deployment_record import COMMIT_PATTERN, DEFAULT_PROJECT, DEFAULT_REGION, fetch_health  # noqa: E402

REGISTRY = "us-central1-docker.pkg.dev/{project}/qcai-repo"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
# NAME=secret:version: the secret's name and version, never its value (P1-D-07 onward: GUEST_TOKEN_SECRET).
SECRET_BINDING_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*=[a-z][a-z0-9-]*:(latest|[0-9]+)")


def _gcloud(arguments: list[str]) -> str:
    completed = subprocess.run(
        [shutil.which("gcloud") or "gcloud", *arguments], capture_output=True, text=True, timeout=600, check=True
    )
    return completed.stdout


def resolve_digest(image: str, commit: str, project: str) -> str:
    output = _gcloud(["artifacts", "docker", "images", "describe", f"{image}:{commit}", "--project", project, "--format=value(image_summary.digest)"])
    digest = output.strip()
    if not DIGEST_PATTERN.fullmatch(digest):
        raise RuntimeError(f"{image}:{commit} did not resolve to a digest (got {digest!r})")
    return digest


def revision_tag(commit: str) -> str:
    return f"c-{commit[:12]}"


def deploy_command(
    service: str, image: str, digest: str, commit: str, project: str, region: str, secrets: tuple[str, ...] = ()
) -> list[str]:
    bindings = ["--update-secrets", ",".join(secrets)] if secrets else []
    return [
        "run", "deploy", service,
        "--image", f"{image}@{digest}",
        "--project", project,
        "--region", region,
        "--no-traffic",
        "--tag", revision_tag(commit),
        *bindings,
        "--quiet",
    ]


def pin_command(service: str, revision: str, project: str, region: str) -> list[str]:
    return ["run", "services", "update-traffic", service, "--to-revisions", f"{revision}=100", "--project", project, "--region", region, "--quiet"]


def tagged_revision(service_description: dict, tag: str) -> tuple[str, str]:
    """The revision and URL that carry `tag`, from `gcloud run services describe --format=json`."""
    for route in service_description.get("status", {}).get("traffic", []):
        if route.get("tag") == tag and route.get("revisionName") and route.get("url"):
            return route["revisionName"], route["url"]
    raise RuntimeError(f"no revision carries the tag {tag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", required=True, choices=["qcai-api", "qcai-frontend"])
    parser.add_argument("--commit", required=True)
    parser.add_argument("--digest", help="sha256:..., if already known (else resolved from the commit tag)")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--update-secret", action="append", default=[], help="NAME=secret:version to bind on the new revision (repeatable)")
    parser.add_argument("--no-pin", action="store_true", help="stop after the /health check, with no traffic moved")
    parser.add_argument("--execute", action="store_true", help="make the Cloud Run writes (needs owner and D-05 approval)")
    args = parser.parse_args(argv)
    if not COMMIT_PATTERN.fullmatch(args.commit):
        parser.error("--commit must be a full 40-character commit")
    if args.digest and not DIGEST_PATTERN.fullmatch(args.digest):
        parser.error("--digest must be sha256:<64 hex>; a tag is never deployed")
    if any(not SECRET_BINDING_PATTERN.fullmatch(binding) for binding in args.update_secret):
        parser.error("--update-secret must be NAME=secret:version; a secret value never goes on the command line")

    image = f"{REGISTRY.format(project=args.project)}/{args.service}"
    digest = args.digest or resolve_digest(image, args.commit, args.project)
    deploy = deploy_command(args.service, image, digest, args.commit, args.project, args.region, tuple(args.update_secret))
    print("1. digest:", f"{image}@{digest}")
    print("2. deploy without traffic: gcloud", " ".join(deploy))
    print(f"3. check /health on the {revision_tag(args.commit)} tagged URL reports {args.commit}")
    print("4. pin traffic: gcloud", " ".join(pin_command(args.service, "<new revision>", args.project, args.region)))
    print(f"5. record: python scripts/deployment_record.py --commit {args.commit} --write deploy/records")
    if not args.execute:
        print("Plan only. Nothing was changed; rerun with --execute to deploy.")
        return 0

    _gcloud(deploy)
    description = json.loads(
        _gcloud(["run", "services", "describe", args.service, "--project", args.project, "--region", args.region, "--format=json(status.traffic)"])
    )
    revision, tagged_url = tagged_revision(description, revision_tag(args.commit))
    reported = fetch_health(tagged_url).get("commit")
    if reported != args.commit:
        print(f"Stopped before any traffic moved: {tagged_url}/health reports {reported!r}, not {args.commit}.", file=sys.stderr)
        return 1
    if args.no_pin:
        print(f"{args.service}: {revision} is up at {tagged_url} with no traffic. To move traffic: gcloud", " ".join(pin_command(args.service, revision, args.project, args.region)))
        return 0
    _gcloud(pin_command(args.service, revision, args.project, args.region))
    print(f"{args.service}: 100% of traffic now on {revision} ({image}@{digest}). Next: step 5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
