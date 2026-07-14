"""Tests for authorisation: role hierarchy and severity gates."""

from __future__ import annotations

from oligos_agents.authz import (
    highest_role,
    required_role_for_severity,
    role_satisfies,
)
from oligos_agents.models import Role, Severity


def test_required_role_for_severity():
    assert required_role_for_severity(Severity.LOW) == Role.QC_APPROVER
    assert required_role_for_severity(Severity.MEDIUM) == Role.QC_APPROVER
    assert required_role_for_severity(Severity.HIGH) == Role.QC_LEAD
    assert required_role_for_severity(Severity.CRITICAL) == Role.QC_MANAGER
    assert required_role_for_severity(None) == Role.QC_APPROVER


def test_role_satisfies_uses_highest_role():
    assert role_satisfies([Role.QC_MANAGER], Role.QC_LEAD) is True
    assert role_satisfies([Role.QC_APPROVER], Role.QC_MANAGER) is False
    assert role_satisfies([], Role.QC_APPROVER) is False


def test_highest_role():
    assert highest_role([Role.QC_APPROVER, Role.DIRECTOR]) == Role.DIRECTOR
    assert highest_role([]) is None
