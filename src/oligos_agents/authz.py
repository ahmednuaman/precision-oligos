"""Authorisation helpers: role hierarchy and severity-based approval gates.

Roles originate from Entra App Roles, normalised into Cognito claims. The
approval level required for a re-synthesis order is derived deterministically
from the maximum conflict severity, per the SOP approval matrix.
"""

from __future__ import annotations

from oligos_agents.models import Role, Severity

# Higher rank = more authority. Any role satisfies a requirement if its rank is
# at least the required rank.
ROLE_RANK: dict[Role, int] = {
    Role.QC_APPROVER: 0,
    Role.QC_LEAD: 1,
    Role.QC_MANAGER: 2,
    Role.DIRECTOR: 3,
}

# Severity -> minimum role required to approve.
#   MEDIUM  -> standard QC approval (QCApprover)
#   HIGH    -> QC Lead or above
#   CRITICAL-> QC Manager or above (Director also notified downstream)
_SEVERITY_MIN_ROLE: dict[Severity, Role] = {
    Severity.LOW: Role.QC_APPROVER,
    Severity.MEDIUM: Role.QC_APPROVER,
    Severity.HIGH: Role.QC_LEAD,
    Severity.CRITICAL: Role.QC_MANAGER,
}


def required_role_for_severity(severity: Severity | None) -> Role:
    """Return the minimum role permitted to approve at *severity*."""
    if severity is None:
        return Role.QC_APPROVER
    return _SEVERITY_MIN_ROLE[severity]


def highest_role(roles: list[Role]) -> Role | None:
    if not roles:
        return None
    return max(roles, key=lambda r: ROLE_RANK[r])


def role_satisfies(user_roles: list[Role], required: Role) -> bool:
    """True if any of *user_roles* meets or exceeds *required*."""
    top = highest_role(user_roles)
    if top is None:
        return False
    return ROLE_RANK[top] >= ROLE_RANK[required]
