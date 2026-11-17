"""Checks on client-supplied text that reject malformed input instead of raising (Release R1.1, AC-1-1).

Cookies and headers reach the API as latin-1 text, so a client can send any byte. Two standard calls raise
on some of those values, and an exception there became HTTP 500 instead of a refusal:
- `int()` refuses non-ASCII digits such as "²" (which `str.isdigit()` accepts) and, since Python 3.11,
  more than 4300 digits;
- `hmac.compare_digest()` refuses a `str` holding any non-ASCII character.
These helpers return None or False for such input, so a malformed credential is refused like any other.
"""

import hmac
import re

# A unix time as this API issues it: ASCII digits, no leading zero, at most 12 digits. One spelling per value,
# so a signed token has no second, equally valid form.
_UNIX_TIME = re.compile(r"[1-9][0-9]{0,11}")


def parse_unix_time(text: str) -> int | None:
    """The unix time in `text`, or None if it is not a canonical, bounded ASCII integer."""
    return int(text) if _UNIX_TIME.fullmatch(text) else None


def text_matches(supplied: str, expected: str) -> bool:
    """Constant-time equality for a client-supplied value; False, never TypeError, when either is not ASCII."""
    return supplied.isascii() and expected.isascii() and hmac.compare_digest(supplied, expected)
