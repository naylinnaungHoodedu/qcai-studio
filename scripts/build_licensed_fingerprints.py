"""Build the salted contamination fingerprints in the research plane (Phase 10 spec 5; plan task 7; PD-71).

Run: python scripts/build_licensed_fingerprints.py --licensed-text PATH [--licensed-text PATH ...] --ulqs PATH --set-id ID
         --output-licensed PATH --output-ulqs PATH (--salt-env NAME | --salt-file PATH) --access-log PATH --actor-role ROLE

Writes a `qcai-licensed-fingerprints/1` file (12-word shingles, the format scripts/scan_boundary.py reads) and a
`qcai-ulqs-fingerprints/1` file (whole-text HMACs of every ULQS text of at least 3 words, plus 6-word shingles). A
fingerprint file holds its salt, so it is research-plane material: every input and output must be a research-plane path
(outside the checkout, or a git-ignored private path). The salt is hex, at least 32 bytes, taken from the named environment
variable or file, and never printed. --licensed-text reads text files and .docx. The access log records, under the
actor's role, the read of each licensed text and of the ULQS items (as soon as each is read, before any check that can
refuse; ULQS items that do not parse are logged by the file's LF sha256), and the write of each fingerprint file. The
ULQS items are validated (`ulqs.validate_dataset`) before any fingerprint is built from them.

Exit codes: 0 ok; 2 refused path or usage, a licensed text or the ULQS file unreadable, a licensed text that is not
text or .docx or that holds fewer than 12 words (it gives no shingle, so it would check nothing), or an output or the
access log that cannot be written; 3 bad salt; 4 the ULQS items are not valid JSON lines or fail validation, or give an
empty ULQS set (no text of at least 3 words); nothing is written on a refusal. Every set written reads back as the
scanner reads it (`contamination.set_from_payload`);
10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.qcai_eval import access_log, contamination, planes, ulqs  # noqa: E402
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, lf_sha256, read_jsonl, write_lf  # noqa: E402


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


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--licensed-text", type=planes.cli_path, action="append", default=[])
    parser.add_argument("--ulqs", type=planes.cli_path, required=True)
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--output-licensed", type=planes.cli_path, required=True)
    parser.add_argument("--output-ulqs", type=planes.cli_path, required=True)
    salt_group = parser.add_mutually_exclusive_group(required=True)
    salt_group.add_argument("--salt-env")
    salt_group.add_argument("--salt-file", type=planes.cli_path)
    parser.add_argument("--access-log", type=planes.cli_path)
    parser.add_argument("--actor-role", choices=access_log.ROLES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0) and 2
    if args.access_log is None or args.actor_role is None or not args.licensed_text:
        print("refused (exit 2): --access-log, --actor-role and at least one --licensed-text are required", file=sys.stderr)
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
    def log(action: str, kind: str, sha256: str) -> None:
        access_log.append(args.access_log, actor_role=args.actor_role, action=action, artifact_kind=kind, artifact_sha256=sha256,
                          purpose="contamination fingerprints")

    texts = []
    for path in args.licensed_text:
        try:
            data = path.read_bytes()
        except (OSError, ValueError) as error:
            print(f"refused (exit 2): licensed text {path.name} unreadable ({type(error).__name__})", file=sys.stderr)
            return 2
        log("read", "licensed_text", hashlib.sha256(data).hexdigest())
        text = contamination._text_of(path.name, data)
        if text is None:
            print(f"refused (exit 2): {path.name} is not a text or .docx file", file=sys.stderr)
            return 2
        if len(contamination.normalized_words(text)) < contamination.LICENSED_N:  # no shingle: it would check nothing
            print(f"refused (exit 2): licensed text {path.name} holds fewer than {contamination.LICENSED_N} words, so it gives no "
                  "fingerprint", file=sys.stderr)
            return 2
        texts.append(text)
    try:
        ulqs_sha = lf_sha256(args.ulqs)
    except (OSError, ValueError) as error:
        print(f"refused (exit 2): ULQS items {args.ulqs.name} unreadable ({type(error).__name__})", file=sys.stderr)
        return 2
    try:
        items = read_jsonl(args.ulqs)
    except (OSError, ValueError) as error:
        log("read", "ulqs_items", ulqs_sha)
        print(f"refused (exit 4): ULQS items are not valid JSON lines ({error})", file=sys.stderr)
        return 4
    try:
        items_sha = ulqs.dataset_sha256(items)
    except (AttributeError, TypeError, ValueError):
        items_sha = ulqs_sha
    log("read", "ulqs_items", items_sha)
    problems = ulqs.validate_dataset(items)
    if problems:
        for problem in problems[:50]:
            print(f"problem: {problem}")
        print(f"refused (exit 4): {len(problems)} ULQS schema problems", file=sys.stderr)
        return 4
    licensed = contamination.build_licensed(texts, salt, set_id=args.set_id)
    ulqs_set = contamination.build_ulqs(items, salt, set_id=args.set_id)
    # Each set must read back as the scanner reads it (contamination.set_from_payload): never write a set it refuses,
    # an empty one among them (a ULQS set whose items hold no text of at least 3 words).
    for payload, code, label in ((licensed, 2, "licensed"), (ulqs_set, 4, "ULQS")):
        try:
            contamination.set_from_payload(payload)
        except ValueError as error:
            print(f"refused (exit {code}): the {label} fingerprint set is not usable ({error})", file=sys.stderr)
            return code
    write_lf(args.output_licensed, dumps_record(licensed))
    write_lf(args.output_ulqs, dumps_record(ulqs_set))
    for payload in (licensed, ulqs_set):
        log("write", "fingerprints", canonical_sha256(payload["fingerprints"]))
    print(f"licensed: {licensed['sources']['documents']} documents, {licensed['sources']['shingles']} shingles; "
          f"ULQS: {ulqs_set['sources']['items']} items, {ulqs_set['sources']['texts']} texts, {len(ulqs_set['exact'])} exact")
    return 0


def main(argv: list[str] | None = None) -> int:
    """An output or the access log that cannot be written is refused with exit 2; any other exception the script does not
    handle is the last-resort refusal, exit 10 (`internal_error`, `planes.internal_error`): never a traceback, never exit 1
    (spec 5)."""
    try:
        return _main(argv)
    except planes.UNWRITABLE as error:
        print(f"refused (exit 2): {error}", file=sys.stderr)
        return 2
    except Exception as error:  # the last-resort handler (planes.INTERNAL_ERROR)
        planes.internal_error(error)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
