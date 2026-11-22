"""Pinned model identifiers (plan Phase 5 task 5.1 "Pinned adapters; preview ids rejected"; AC-5-10; R-24; D-07 option
(a)'s rule, PD-24; Phase 5 spec 4.1).

pin_problem checks, in order, and the first failure gives the result:
1. the version is missing or blank: "unpinned: lacks a version";
2. a token of the model id or the version (split on [^a-z0-9]+ after casefold) is a moving alias (REFUSED_TOKEN), or
   holds one glued to other characters (REFUSED_WITHIN_TOKEN: preview, latest, nightly or experimental anywhere in a
   token, or a token ending in exp and digits): "unpinned: names a moving alias (<alias>)", so
   gemini-3.1-flash-lite-preview, gemini3preview, gpt4latest, -latest, -exp, -exp-0827, gemini3exp, @latest, alias and
   default are refused;
3. the model id or the version is not in its canonical form (surrounding whitespace): "unpinned: the identifier is not
   in its canonical form";
4. the version is not a pinned form (a calendar date, an eight-digit calendar date, a three-digit revision or a dotted
   version; a date must exist, so 2026-13-45 and 00000000 are refused): "unpinned: version is not a pinned form".
The loader applies it to every member of every registry, so an unpinned identifier always stops the load and with
it start-up, and the package's gateway.pinning texts must equal REFUSED_TOKENS_TEXT, REFUSED_WITHIN_TOKEN_TEXT and
PINNED_VERSION_TEXT.
"""

from __future__ import annotations

from datetime import datetime
import re

PIN_RULE = "pinned-version-v1"
REFUSED_TOKENS_TEXT = r"alias|auto|current|default|exp\d*|experimental|latest|nightly|preview\d*"
REFUSED_WITHIN_TOKEN_TEXT = r"preview|latest|nightly|experimental|exp\d*$"
REFUSED_TOKEN = re.compile(rf"^(?:{REFUSED_TOKENS_TEXT})$")
REFUSED_WITHIN_TOKEN = re.compile(REFUSED_WITHIN_TOKEN_TEXT)
PINNED_VERSION = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{3}|v?\d+(?:\.\d+){1,3})$")
PINNED_VERSION_TEXT = PINNED_VERSION.pattern
_DATE_FORMATS = ((re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"), (re.compile(r"^\d{8}$"), "%Y%m%d"))
_SPLIT = re.compile(r"[^a-z0-9]+")


def _moving_alias(value: str) -> str | None:
    for token in _SPLIT.split(value.casefold()):
        if not token:
            continue
        if REFUSED_TOKEN.fullmatch(token):
            return token
        glued = REFUSED_WITHIN_TOKEN.search(token)
        if glued:
            return glued.group(0)
    return None


def _calendar_date(version: str) -> bool:
    """False for a date form that names no calendar day; True for every other form."""
    for pattern, layout in _DATE_FORMATS:
        if pattern.fullmatch(version):
            try:
                datetime.strptime(version, layout)
            except ValueError:
                return False
    return True


def pin_problem(model_id: str, model_version: str | None) -> str | None:
    if model_version is None or not str(model_version).strip():
        return "unpinned: lacks a version"
    model_id, version = str(model_id or ""), str(model_version)
    for value in (model_id, version):
        alias = _moving_alias(value)
        if alias is not None:
            return f"unpinned: names a moving alias ({alias})"
    if model_id != model_id.strip() or version != version.strip():
        return "unpinned: the identifier is not in its canonical form"
    if not PINNED_VERSION.fullmatch(version) or not _calendar_date(version):
        return "unpinned: version is not a pinned form"
    return None
