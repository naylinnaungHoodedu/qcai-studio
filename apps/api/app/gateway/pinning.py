"""Pinned model identifiers (plan Phase 5 task 5.1 "Pinned adapters; preview ids rejected"; AC-5-10; R-24; D-07 option
(a)'s rule, PD-24; Phase 5 spec 4.1).

pin_problem checks, in order, and the first failure gives the result:
1. the version is missing or blank: "unpinned: lacks a version";
2. a token of the model id or the version (split on [^a-z0-9]+ after casefold) is a moving alias (REFUSED_TOKEN):
   "unpinned: names a moving alias (<token>)", so gemini-3.1-flash-lite-preview, -latest, -exp, -exp-0827, @latest,
   alias and default are refused;
3. the version is not a pinned form (a date, an eight-digit date, a three-digit revision or a dotted version):
   "unpinned: version is not a pinned form".
The loader applies it to every member of every registry, so an unpinned identifier always stops the load and with
it start-up.
"""

from __future__ import annotations

import re

PIN_RULE = "pinned-version-v1"
REFUSED_TOKEN = re.compile(r"^(?:alias|auto|current|default|exp\d*|experimental|latest|nightly|preview\d*)$")
PINNED_VERSION = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{3}|v?\d+(?:\.\d+){1,3})$")
REFUSED_TOKENS_TEXT = r"alias|auto|current|default|exp\d*|experimental|latest|nightly|preview\d*"
PINNED_VERSION_TEXT = PINNED_VERSION.pattern
_SPLIT = re.compile(r"[^a-z0-9]+")


def pin_problem(model_id: str, model_version: str | None) -> str | None:
    if model_version is None or not str(model_version).strip():
        return "unpinned: lacks a version"
    for value in (str(model_id or ""), str(model_version)):
        for token in _SPLIT.split(value.casefold()):
            if token and REFUSED_TOKEN.fullmatch(token):
                return f"unpinned: names a moving alias ({token})"
    if not PINNED_VERSION.fullmatch(str(model_version).strip()):
        return "unpinned: version is not a pinned form"
    return None
