"""The secret store (plan Phase 5 task 5.12 "Keys in headers from the secret store"; R-06; E-109; Phase 5 spec 4.3).

SecretStore.get(ref) returns the secret named by an adapter's secret_ref, or None. EnvironmentSecretStore reads the
process environment, which is how Cloud Run mounts Secret Manager secrets: it holds no SDK and makes no network call,
and the gateway never discovers application-default credentials (no google.auth import; E-109). Tests use
v2_fakes.FakeSecretStore. No adapter attribute holds a key: an adapter reads it per call.
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretStore(Protocol):
    def get(self, ref: str) -> str | None: ...


class EnvironmentSecretStore:
    def get(self, ref: str) -> str | None:
        value = os.environ.get(ref)
        return value if value and value.strip() else None
