"""The reviewer gate (plan Phase 6 A, B "OPEN DECISION: reviewer staffing [Decision D-18]; production adjudication MAY start
once staffed"; AC-6-7; plan 9.4 H4; Phase 6 spec 4.12, conflict 7; PD-38).

require_reviewer is the one dependency of every V3 reviewer route. Its sub-dependency require_role("reviewer") checks
the role first, so a caller whose role is not reviewer (a guest's is learner) gets 403 and one authz.denied security
event (required "role:reviewer") in every environment; the authorization matrix reads its allowed_roles. Then
reviewer_admitted: true in development, where reviewers are synthetic demo identities; elsewhere only when the package's
v3.reviewer_pool is staffed, which it is not while D-18 is open, so outside development a reviewer-role caller is
refused too, with 403 and an authz.denied event (required "reviewer_pool:D-18"), whatever token or header carries the
role. Authentication (get_current_user) runs before both checks: without a credential a caller gets 401 and no security
event where demo auth is off (the default outside development). No in-app grant of any role exists (provisioning is
DI-91 with DI-38). The ledger route's reviewer branch reads the same gate.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import AuthUser, require_role
from app.core.config import Settings, get_settings
from app.services.security_log import record_security_event, route_template

REVIEWER_ROLE = "reviewer"
POOL_REFUSAL = "No reviewer is admitted outside development while the reviewer pool (D-18) is unstaffed."
_require_reviewer_role = require_role(REVIEWER_ROLE)


def reviewer_admitted(settings: Settings) -> bool:
    if settings.environment.lower() == "development":
        return True
    from app.core.config_package import ConfigPackageError, get_config_package

    try:
        package = get_config_package(settings)
    except ConfigPackageError:
        return False
    return package.v3 is not None and package.v3.reviewer_pool != "unstaffed"


def require_reviewer(request: Request, user: AuthUser = Depends(_require_reviewer_role), settings: Settings = Depends(get_settings)) -> AuthUser:
    if not reviewer_admitted(settings):
        record_security_event("authz.denied", "denied", connection=request, actor_role=user.role, subject=user.user_id,
                              details={"route": route_template(request), "required": "reviewer_pool:D-18", "provider": user.provider})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=POOL_REFUSAL)
    return user
