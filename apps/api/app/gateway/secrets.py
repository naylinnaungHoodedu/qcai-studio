"""The secret store (plan Phase 5 task 5.12 "Keys in headers from the secret store"; R-06; E-109; Phase 5 spec 4.3).

SecretStore.get(ref) returns the secret named by an adapter's secret_ref, or None. EnvironmentSecretStore reads the
process environment, which is how Cloud Run mounts Secret Manager secrets: it holds no SDK and makes no network call,
and the gateway never discovers application-default credentials (no google.auth import; E-109). Tests use
v2_fakes.FakeSecretStore. No adapter attribute holds a key: an adapter reads it per call. PROVIDER_SECRET_REFS names the
provider credentials the gateway holds outside the registry (the embedding key, app.gateway.embeddings), and
provider_secret_values gives their values to the log redaction installed at start-up (main.py, workers/common.py), so a
key is masked before the gateway's first read registers it again.
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretStore(Protocol):
    def get(self, ref: str) -> str | None: ...


PROVIDER_SECRET_REFS = ("OPENAI_API_KEY",)


class EnvironmentSecretStore:
    def get(self, ref: str) -> str | None:
        value = os.environ.get(ref)
        return value if value and value.strip() else None


def provider_secret_values(store: SecretStore | None = None) -> list[str]:
    """The values of PROVIDER_SECRET_REFS that are set, for the log redaction only."""
    source = store if store is not None else EnvironmentSecretStore()
    return [value for value in (source.get(ref) for ref in PROVIDER_SECRET_REFS) if value]
