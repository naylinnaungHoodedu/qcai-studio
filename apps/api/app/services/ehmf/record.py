"""The typed record (plan Phase 7 D tasks 1-4; Phase 7 spec 4.6).

build_record_v4 builds a VerificationRecordV4 from the same fields the V2 record is built from
(v2_panel.aggregate._record_fields_v2) plus the ehmf block, so a v4 record's V2 part equals the v3 record EHMF=off would
write wherever no EHMF reason applies. The block types every finding (classify), records precedence and the disclosure
(conflicts), the correction cycles with their set hashes, the X2 list, the weights and routing it used, the detector
state, and the record's config_version (its package version). Only development writes typed records (EHMF not off).
"""

from __future__ import annotations

from typing import Any

from app.services.ehmf.vocabulary import ROUTING_VERSION


def build_ehmf_block(record_fields: dict[str, Any], *, mode: str, package: Any, manifest: Any, corrections: tuple = (),
                     detector_down: tuple[str, ...] = (), detector_absent: tuple[str, ...] = (), library: Any = None) -> Any:
    from app.services.ehmf import classify
    from app.services.ehmf.conflicts import disclosure_text, ehmf_conflicts
    from app.services.tutor_pipeline.contracts import EhmfRecord, VerificationRecordV2

    params = package.ehmf
    weights = params.weight_strings()
    # A plain V2 view of the fields (no validation) for the classifier.
    view = VerificationRecordV2.model_construct(**record_fields)
    generation = int(record_fields.get("generation_attempts") or 0)
    disclosure = record_fields.get("disclosure")
    claims = tuple(classify.claim_entry(verdict, disclosure=disclosure, generation=generation, weights=weights)
                   for verdict in record_fields["verdicts"])
    conflicts = ehmf_conflicts(disclosure, manifest=manifest or {}, weights=weights)
    x2 = tuple(sorted(verdict.claim_id for verdict in record_fields["verdicts"]
                      if getattr(verdict, "v3", None) is not None and getattr(verdict.v3, "escalation", None) == "X2"))
    return EhmfRecord(
        mode=mode, routing_version=ROUTING_VERSION, routing_sha256=params.routing_sha256, config_version=package.package_version,
        library_version=getattr(library, "version", "none"), library_sha256=getattr(library, "sha256", "0" * 64), weights=weights, claims=claims,
        response_findings=classify.response_findings(view), conflicts=conflicts,
        disclosure=disclosure_text(conflicts, template_id=params.disclosure_template_id, template_text=params.disclosure_template_text,
                                   template_sha256=params.disclosure_template_sha256),
        corrections=tuple(corrections), x2_emitted=x2, detector_down=tuple(sorted(set(detector_down))),
        detector_absent=tuple(sorted(set(detector_absent))),
    )


def build_record_v4(record_fields: dict[str, Any], **kwargs: Any) -> Any:
    from app.services.tutor_pipeline.contracts import VerificationRecordV4

    return VerificationRecordV4(**record_fields, ehmf=build_ehmf_block(record_fields, **kwargs))
