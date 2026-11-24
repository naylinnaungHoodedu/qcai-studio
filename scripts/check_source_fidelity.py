"""The source-fidelity check over the 12 tracked DOCX (plan F-7 "Remedy: source-fidelity CI check"; plan Phase 7 P (R-18);
Phase 11 task 3 and AC-11-3 brought forward; Phase 7 spec 4.12; PD-49).

Run: python scripts/check_source_fidelity.py --write docs/evaluation/phase7/source_fidelity_report_v1.json
     python scripts/check_source_fidelity.py --check docs/evaluation/phase7/source_fidelity_report_v1.json
     python scripts/check_source_fidelity.py --require-zero        (AC-11-3; not in CI until the Content Owner corrects the DOCX, DI-105)

The register (docs/evaluation/phase7/source_fidelity_register.json) is seeded only with the plan's measured facts (F-7,
E-30): the QUEN row's External Sens. and External FP Rate, and the "perfectly aligned" wording where GEA = 0.40. Q-11
(other DOCX-source discrepancies) is unresolved, so nothing else is in it. The checker lists the DOCX with
`git ls-files '*.docx'` (exactly 12, else exit 2) and reads each read-only with python-docx: a number entry compares
the cell at its table, row and column (after checking the row and column labels, else exit 2 "register location
moved") with the source value as decimals; an absent_phrase entry requires its anchor in the paragraph and matches when
the phrase is absent. It never prints or stores other DOCX text: the report holds the DOCX paths and sha256s, the cell
values the register names, and "present"/"absent". Engineering edits no DOCX (D-16, D-31): the correction at source is
the Content Owner's, so the committed report states the mismatches.
Exit codes: 0 ok; 1 the report differs from a fresh run (--check); 2 usage, a DOCX count other than 12, or a moved
location; 7 mismatches under --require-zero.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTER = REPO_ROOT / "docs" / "evaluation" / "phase7" / "source_fidelity_register.json"
DOCX_COUNT = 12
EXIT_OK, EXIT_DIFFERS, EXIT_USAGE, EXIT_MISMATCH = 0, 1, 2, 7


class FidelityError(RuntimeError):
    """A usage fault: the DOCX set or a register location is not what the register expects (exit 2)."""


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def tracked_docx(root: Path) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "*.docx"], cwd=root, capture_output=True, text=True, timeout=30)
    if listed.returncode != 0:
        raise FidelityError("git ls-files failed")
    return sorted(line.strip() for line in listed.stdout.splitlines() if line.strip())


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def check_entry(entry: dict, document) -> dict:
    location = entry["location"]
    if entry["kind"] == "number":
        try:
            table = document.tables[location["table"]]
            row = table.rows[location["row"]]
            cell = row.cells[location["column"]].text.strip()
            row_label = row.cells[0].text.strip()
            column_label = table.rows[0].cells[location["column"]].text.strip()
        except IndexError as exc:
            raise FidelityError(f"register location moved: {entry['id']}") from exc
        if row_label != entry["row_label"] or column_label != entry["column_label"]:
            raise FidelityError(f"register location moved: {entry['id']}")
        value = _decimal(cell)
        source = Decimal(entry["source_value"])
        return {"id": entry["id"], "docx_value": cell if value is not None else "non_numeric", "source_value": entry["source_value"],
                "match": value is not None and value == source}
    if entry["kind"] == "absent_phrase":
        try:
            text = document.paragraphs[location["paragraph"]].text
        except IndexError as exc:
            raise FidelityError(f"register location moved: {entry['id']}") from exc
        if location["anchor"] not in text:
            raise FidelityError(f"register location moved: {entry['id']}")
        present = entry["phrase"].lower() in text.lower()
        return {"id": entry["id"], "docx_value": "present" if present else "absent", "source_value": entry["source_value"], "match": not present}
    raise FidelityError(f"unknown register entry kind {entry['kind']!r}")


def compute(*, root: Path = REPO_ROOT, register_path: Path = DEFAULT_REGISTER, docx_paths: dict[str, Path] | None = None) -> dict:
    """The report. docx_paths maps a register DOCX name to a file to read instead (a test's corrected copy)."""
    import docx

    register = json.loads(Path(register_path).read_text(encoding="utf-8"))
    listed = tracked_docx(root)
    if len(listed) != DOCX_COUNT:
        raise FidelityError(f"expected {DOCX_COUNT} tracked DOCX, found {len(listed)}")
    overrides = docx_paths or {}
    hashes = []
    for relative in listed:
        path = overrides.get(relative, root / relative)
        hashes.append({"path": relative, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()})
    documents: dict = {}
    entries = []
    for entry in register["entries"]:
        name = entry["docx"]
        if name not in listed:
            raise FidelityError(f"register DOCX {name} is not tracked")
        if name not in documents:
            documents[name] = docx.Document(str(overrides.get(name, root / name)))
        entries.append(check_entry(entry, documents[name]))
    mismatches = sum(1 for entry in entries if not entry["match"])
    return {
        "report": "qcai-source-fidelity-report", "format_version": 1, "register_sha256": canonical_sha256(register),
        "docx": hashes, "entries": entries, "mismatches": mismatches,
        "result": "mismatches_present" if mismatches else "zero_mismatches",
        "ac_11_3": "not met: correction at source is the Content Owner's (D-16; DI-105)" if mismatches else "met",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    mode.add_argument("--require-zero", action="store_true")
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    try:
        fresh = compute(register_path=args.register)
    except FidelityError as exc:
        print(f"source fidelity: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: {fresh['mismatches']} mismatch(es)")
        return EXIT_OK
    if args.check:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
        if committed != fresh:
            print("source fidelity: the committed report differs from a fresh run (rerun --write)", file=sys.stderr)
            return EXIT_DIFFERS
        print(f"source-fidelity report is current: {fresh['mismatches']} mismatch(es); AC-11-3 {fresh['ac_11_3']}")
        return EXIT_OK
    if fresh["mismatches"]:
        print(f"source fidelity: {fresh['mismatches']} DOCX mismatch(es) against the source (AC-11-3 needs zero)", file=sys.stderr)
        return EXIT_MISMATCH
    print("source fidelity: zero DOCX mismatches")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
