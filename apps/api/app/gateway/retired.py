"""The retired provider settings (plan Phase 5 E "legacy provider code retired"; Phase 5 spec 4.18).

The dead Vertex path and the unused chat-model setting are gone, with their Settings fields. Settings ignore unknown
environment keys (extra="ignore"), so a deployment that still sets one starts unchanged; start-up logs the names it
finds (gateway.retired_setting, upper-case names only, never a value). A retired key set in the process environment is
still masked in every log line (retired_secret_values feeds the redaction). No file is opened: only the process
environment is read, so a retired key kept only in a .env file is neither named nor masked, and no code reads it (the
Settings field is gone, and Settings ignore unknown keys).
"""

from __future__ import annotations

import os

RETIRED_PROVIDER_SETTINGS = ("OPENAI_CHAT_MODEL", "VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL", "VERTEX_AI_LOCATION", "VERTEX_AI_PROJECT_ID")
RETIRED_SECRET_SETTINGS = ("VERTEX_AI_API_KEY",)


def retired_settings_present() -> tuple[str, ...]:
    present = {key.upper() for key in os.environ}
    return tuple(name for name in RETIRED_PROVIDER_SETTINGS if name in present)


def retired_secret_values() -> list[str]:
    upper = {key.upper(): value for key, value in os.environ.items()}
    return [upper[name] for name in RETIRED_SECRET_SETTINGS if upper.get(name)]
