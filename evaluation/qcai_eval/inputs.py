"""The one JSON decoder of every research-plane input (Phase 10 spec 4.1; review 20).

Every file a research-plane script reads as JSON or JSONL (run specs and their design blocks, the harness parameters,
the package, the arms, the analysis plans, items, catalogs, ratings, recordings, checkpoints, verification sets,
`e4_responses`, governance and freeze records, agent-check records, mappings, fingerprints, scan reports and fixtures) is
decoded here, once, by `loads`. It admits only values every later step can compute with:

- no `NaN`, `Infinity` or `-Infinity` (Python's json module accepts them; JSON does not);
- a number with a fraction or an exponent must be a finite float (`1e400` overflows to infinity and is refused) that
  does not underflow (`1e-400` reads as 0.0 although its digits are not zero, and is refused);
- an integer must lie within +-2**53 (`INTEGER_LIMIT`), so that it is exactly representable as a float and every count,
  bound and seed the harness derives from it stays in range (`10**400` is refused; an integer of more digits than
  2**53 has is refused before it is converted, so one past the interpreter's 4300-digit conversion limit is refused the
  same way, never as that limit's plain ValueError);
- every string, object keys included, must be encodable as UTF-8 (an escaped unpaired UTF-16 surrogate such as
  `\\ud800` decodes to a string no hash, log or output can encode, and is refused);
- nesting the decoder can read (a document nested past the interpreter's recursion limit raises `RecursionError`,
  which is not a ValueError, and is refused).

A refusal is `InputInvalid`, a ValueError, so each reader's existing `except ValueError` refuses the input with its own
documented exit code and reason (`canonical.read_jsonl` re-raises it naming the line; a recording or a design input
refuses it as invalid content, `recording_invalid` or `<kind>_invalid`). The shape of each input (its fields, types, vocabularies and ranges) is then checked
by that input's own validator before any request is sent; the last-resort handler of each script (`planes.INTERNAL_ERROR`)
covers what neither catches. Standard library only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

INTEGER_LIMIT = 2 ** 53
_INTEGER_DIGITS = len(str(INTEGER_LIMIT))
_NONZERO_DIGIT = re.compile(r"[1-9]")


class InputInvalid(ValueError):
    """A research-plane input holds a value no later step can compute with (a non-finite, underflowing or out-of-range
    number, a string that is not encodable as UTF-8, or nesting too deep to decode). The message names the class of value,
    never the input's content."""


def _constant(name: str) -> Any:
    raise InputInvalid(f"a non-finite number ({name})")


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise InputInvalid("a number outside the float range")
    mantissa = text.lower().split("e", 1)[0]
    if value == 0.0 and _NONZERO_DIGIT.search(mantissa):
        raise InputInvalid("a number that underflows to zero")
    return value


def _integer(text: str) -> int:
    if len(text.lstrip("-")) > _INTEGER_DIGITS:  # JSON has no leading zeros: more digits than 2**53 is out of range
        raise InputInvalid("an integer outside +-2**53")
    value = int(text)
    if abs(value) > INTEGER_LIMIT:
        raise InputInvalid("an integer outside +-2**53")
    return value


def loads(text: str | bytes) -> Any:
    """`text` decoded as strict JSON (module docstring); `InputInvalid` (a ValueError) for a value it refuses, and
    `json.JSONDecodeError` (a ValueError too) for text that is not JSON."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8")  # UnicodeDecodeError is a ValueError
    try:
        value = json.loads(text, parse_constant=_constant, parse_float=_float, parse_int=_integer)
    except RecursionError:  # nesting deeper than the decoder's recursion limit
        raise InputInvalid("nesting too deep") from None
    _check_strings(value)
    return value


def _check_strings(value: Any) -> None:
    """Every string of a decoded value, object keys included, encodes as UTF-8 (iteratively: no recursion limit)."""
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            strings: list[Any] = [node]
        elif isinstance(node, dict):
            strings = list(node)
            pending.extend(node.values())
        elif isinstance(node, list):
            strings = []
            pending.extend(node)
        else:
            continue
        for string in strings:
            try:
                string.encode("utf-8")
            except UnicodeEncodeError:
                raise InputInvalid("a string with an unpaired surrogate") from None


def read_json(path: Path) -> Any:
    """The strict JSON value of a UTF-8 file (OSError when it cannot be read, ValueError when it is not strict JSON)."""
    return loads(Path(path).read_text(encoding="utf-8"))
