"""The provenance-first two-channel tutor (plan Phase 3; docs/architecture/phase3-implementation-spec.md).

Modules: contracts (versioned schemas), text, resolve (3.1), retrieve (3.2), evidential (3.3), bind (3.4),
lock (3.5), render (3.6), the subset checker in app.services.claim_gate (3.7), pipeline, shadow (plan G), metrics
(plan I) and package_check (configuration package schema 2 and later: v2, v3, v4 since Phase 5, and v5 since Phase 6, the shipped package).
The ledger (3.8) is app.services.ledger.

No module here imports a learner module, the auth layer, a route, the answer history or the frozen Phase 1
retrieval (AC-3-1 import scan). Names are re-exported lazily, so importing a submodule never imports the pipeline.
"""

from __future__ import annotations

from typing import Any

_EXPORTS = {
    "TwoPassPipeline": "app.services.tutor_pipeline.pipeline",
    "PipelineInput": "app.services.tutor_pipeline.pipeline",
    "PipelineResult": "app.services.tutor_pipeline.pipeline",
    "DeliveryNotImplemented": "app.services.tutor_pipeline.pipeline",
    "ShadowJob": "app.services.tutor_pipeline.shadow",
    "run_shadow": "app.services.tutor_pipeline.shadow",
    "effective_mode": "app.services.tutor_pipeline.shadow",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(module_name), name)
