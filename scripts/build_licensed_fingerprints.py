"""Build the salted contamination fingerprints in the research plane (Phase 10 spec 5; plan task 7; PD-71).

Run: python scripts/build_licensed_fingerprints.py --licensed-text PATH [--licensed-text PATH ...] --ulqs PATH --set-id ID
         --output-licensed PATH --output-ulqs PATH (--salt-env NAME | --salt-file PATH) --access-log PATH

Writes a `qcai-licensed-fingerprints/1` file (12-word shingles, the format scripts/scan_boundary.py reads) and a
`qcai-ulqs-fingerprints/1` file (whole-text HMACs of every ULQS text of at least 3 words, plus 6-word shingles). A
fingerprint file holds its salt, so it is research-plane material: every input and output must be a research-plane path
(outside the checkout, or a git-ignored private path). The salt is hex, at least 32 bytes, taken from the named environment
variable or file, and never printed. --licensed-text reads text files and .docx.

Exit codes: 0 ok; 2 refused path or usage; 3 bad salt.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import access_log, contamination, planes  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, read_jsonl, write_lf  # noqa: E402


def _salt(args: argparse.Namespace) -> bytes | None:
    if args.salt_env:
        value = os.environ.get(args.salt_env, "")
    else:
        try:
            value = args.salt_file.read_text(encoding="utf-8")
        except OSError:
            return None
    try:
        salt = bytes.fromhex(value.strip())
    except ValueError:
        return None
    return salt if len(salt) >= contamination.MIN_SALT_BYTES else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--licensed-text", type=Path, action="append", default=[])
    parser.add_argument("--ulqs", type=Path, required=True)
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--output-licensed", type=Path, required=True)
    parser.add_argument("--output-ulqs", type=Path, required=True)
    salt_group = parser.add_mutually_exclusive_group(required=True)
    salt_group.add_argument("--salt-env")
    salt_group.add_argument("--salt-file", type=Path)
    parser.add_argument("--access-log", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.access_log is None or not args.licensed_text:
        print("refused (exit 2): --access-log and at least one --licensed-text are required", file=sys.stderr)
        return 2
    try:
        for path in [*args.licensed_text, args.ulqs] + ([args.salt_file] if args.salt_file else []):
            planes.require_private_input(path)
        for path in (args.output_licensed, args.output_ulqs, args.access_log):
            planes.require_private_output(path)
    except planes.PathRefused as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    salt = _salt(args)
    if salt is None:
        print(f"refused (exit 3): the salt must be hex of at least {contamination.MIN_SALT_BYTES} bytes", file=sys.stderr)
        return 3
    texts = []
    for path in args.licensed_text:
        text = contamination._text_of(path.name, path.read_bytes())
        if text is None:
            print(f"refused (exit 2): {path.name} is not a text or .docx file", file=sys.stderr)
            return 2
        texts.append(text)
    items = read_jsonl(args.ulqs)
    licensed = contamination.build_licensed(texts, salt, set_id=args.set_id)
    ulqs_set = contamination.build_ulqs(items, salt, set_id=args.set_id)
    write_lf(args.output_licensed, dumps_record(licensed))
    write_lf(args.output_ulqs, dumps_record(ulqs_set))
    for payload in (licensed, ulqs_set):
        access_log.append(args.access_log, actor_role="MLE", action="write", artifact_kind="fingerprints",
                          artifact_sha256=canonical_sha256(payload["fingerprints"]), purpose="contamination fingerprints")
    print(f"licensed: {licensed['sources']['documents']} documents, {licensed['sources']['shingles']} shingles; "
          f"ULQS: {ulqs_set['sources']['items']} items, {ulqs_set['sources']['texts']} texts, {len(ulqs_set['exact'])} exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
