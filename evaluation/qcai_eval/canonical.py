"""Canonical JSON, hashing and LF-normalised file helpers for the research harness (Phase 10 spec 3, 4.1).

Standard library only. `canonical_json` and `canonical_sha256` equal `app.core.config_package`'s (a unit test checks it),
so a configuration package pinned here hashes exactly as the application hashes it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import inputs


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def lf_sha256(path: Path) -> str:
    """The sha256 of a text file with CRLF read as LF, so a checkout under core.autocrlf hashes as the repository does."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def jsonl_lines(text: str) -> list[str]:
    """The lines of a JSONL text: split at LF only, a CR before it dropped (CRLF reads as LF), the empty piece after a
    final LF dropped. Never `str.splitlines`, which also breaks at U+2028, U+2029 and U+0085: JSON allows those raw
    inside a string, and `dumps_line` writes them raw (ensure_ascii=False), so the harness reads back what it writes."""
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def read_jsonl(path: Path) -> list[dict]:
    """The objects of a JSONL file (`jsonl_lines`), each line decoded by `inputs.loads`. An error names the line number
    and the class of value refused, never the line's content."""
    records: list[dict] = []
    for number, line in enumerate(jsonl_lines(Path(path).read_text(encoding="utf-8")), start=1):
        if not line.strip():
            continue
        try:
            value = inputs.loads(line)
        except inputs.InputInvalid as error:  # still InputInvalid, so a reader can refuse it as invalid content
            raise inputs.InputInvalid(f"line {number}: {error}") from None
        except json.JSONDecodeError:
            raise ValueError(f"line {number}: not valid JSON") from None
        if not isinstance(value, dict):
            raise ValueError(f"line {number}: not a JSON object")
        records.append(value)
    return records


def dumps_record(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def dumps_line(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


class OutputUnwritable(OSError):
    """An output path cannot be written: it is a directory, lies under a file, or is not writable. Each research-plane
    script refuses it with exit 2 (spec 5), never a traceback."""


def write_lf(path: Path, text: str) -> None:
    """Write `text` with LF line ends, creating the parent directories; `OutputUnwritable` when the path cannot be written."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as error:
        raise OutputUnwritable(f"output {path.name} cannot be written ({type(error).__name__})") from None


def hashed_hex(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def hashed_int(*parts: str, bits: int = 64) -> int:
    return int(hashed_hex(*parts), 16) >> (256 - bits)
