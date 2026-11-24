"""The detector guard (plan Phase 7 J "detector down -> claim withheld"; Phase 7 spec 4.3, conflict 14).

Under EHMF=on the V1 track wraps each detector call in guarded(): any exception becomes DetectorDown(name), and the
runner abstains the whole response with ehmf_detector_down (stricter than withholding the claim), records the detector
in ehmf.detector_down and logs tutor.ehmf.detector_down. V1.3's own unavailability keeps Phase 4's checker_unavailable
abstention and is recorded as detector_down ("V1.3",). A V2 panel with no member is Phase 5's ZERO path (withhold), not a
detector fault. Under shadow and off nothing is wrapped (Phase 6 behaviour). DETECTORS is the closed list of guarded
detector names: guarded() and DetectorDown refuse any other name (ValueError, a programming error), so a new or renamed
guard call site cannot exist without a DETECTORS entry, and test_phase7_acceptance's detector-down cases equal DETECTORS.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
DETECTORS = ("V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9", "V2", "alignment")


def _known(detector: str) -> str:
    if detector not in DETECTORS:
        raise ValueError(f"{detector!r} is not a guarded EHMF detector (ehmf.detectors.DETECTORS)")
    return detector


class DetectorDown(RuntimeError):
    def __init__(self, detector: str) -> None:
        _known(detector)
        super().__init__(f"EHMF detector {detector} is down")
        self.detector = detector


def guarded(detector: str, fn: Callable[..., T], *args, **kwargs) -> T:
    _known(detector)
    try:
        return fn(*args, **kwargs)
    except DetectorDown:
        raise
    except Exception as exc:  # noqa: BLE001 - every detector fault is a detector down (spec 4.3)
        raise DetectorDown(detector) from exc
