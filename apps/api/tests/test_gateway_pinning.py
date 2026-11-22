"""Phase 5 pinned model identifiers (plan Phase 5 task 5.1 "preview ids rejected"; AC-5-10; R-24; D-07 option (a)'s rule,
PD-24; Phase 5 spec 4.1)."""

from __future__ import annotations

import pytest

from app.gateway.pinning import pin_problem


@pytest.mark.parametrize("model_id, version, reason", [
    ("gemini-3.1-flash-lite-preview", "2026-01-01", "moving alias (preview)"),
    ("model-x", None, "lacks a version"),
    ("model-x", "  ", "lacks a version"),
    ("model-x-latest", "2026-01-01", "moving alias (latest)"),
    ("model-x", "latest", "moving alias (latest)"),
    ("model-x@latest", "2026-01-01", "moving alias (latest)"),
    ("model-x-exp", "2026-01-01", "moving alias (exp)"),
    ("model-x-exp-0827", "2026-01-01", "moving alias (exp)"),
    ("model-x-exp2", "2026-01-01", "moving alias (exp2)"),
    ("model-x", "preview2", "moving alias (preview2)"),
    ("alias", "2026-01-01", "moving alias (alias)"),
    ("default", "2026-01-01", "moving alias (default)"),
    ("model-x", "current", "moving alias (current)"),
    ("model-x-nightly", "1.2", "moving alias (nightly)"),
    ("model-x", "2026-1-1", "not a pinned form"),
    ("model-x", "v1", "not a pinned form"),
    ("model-x", "stable", "not a pinned form"),
])
def test_every_unpinned_form_is_refused_and_names_unpinned(model_id, version, reason):
    problem = pin_problem(model_id, version)
    assert problem is not None and problem.startswith("unpinned: ") and reason in problem


@pytest.mark.parametrize("model_id, version", [
    ("fake-alpha-verifier", "2026-11-21"), ("model-x", "20261121"), ("model-x", "002"), ("model-x", "1.2"), ("model-x", "v2.0.1"),
    ("model-x", "1.2.3.4"),
])
def test_the_pinned_forms_pass(model_id, version):
    assert pin_problem(model_id, version) is None


def test_the_retired_vertex_default_is_unpinned():
    assert pin_problem("gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite-preview") == "unpinned: names a moving alias (preview)"
