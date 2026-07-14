"""Tests for the maker-checker approval flow (in-process / memory store)."""

from __future__ import annotations

import pytest

from oligos_agents.deps import AgentDeps
from oligos_agents.models import (
    Conflict,
    ConflictCode,
    ConflictReport,
    Role,
    RunState,
    RunStatus,
    Severity,
)
from oligos_agents.steps import pipeline
from oligos_agents.store import save_run


def _awaiting_run(run_id: str, submitter: str = "maker-1") -> RunState:
    report = ConflictReport(
        run_id=run_id,
        conflicts=[
            Conflict(
                code=ConflictCode.LIMS_NOTEBOOK_DISCREPANCY,
                severity=Severity.CRITICAL,
                oligo_id="OLG-1",
                batch_id="B-1",
                recommended_action="escalate",
            )
        ],
    )
    return RunState(
        run_id=run_id,
        submitter_sub=submitter,
        query="check",
        status=RunStatus.AWAITING_APPROVAL,
        conflict_report=report,
        required_approval_role=Role.QC_MANAGER,
    )


def test_submitter_cannot_approve_own_order():
    deps = AgentDeps()
    save_run(deps, _awaiting_run("run-a", submitter="maker-1"))
    with pytest.raises(pipeline.ApprovalDenied):
        pipeline.apply_approval(deps, "run-a", "maker-1", [Role.QC_MANAGER], approved=True)


def test_insufficient_role_denied():
    deps = AgentDeps()
    save_run(deps, _awaiting_run("run-b"))
    with pytest.raises(pipeline.ApprovalDenied):
        pipeline.apply_approval(deps, "run-b", "checker-1", [Role.QC_APPROVER], approved=True)


def test_valid_approval_executes_writes():
    deps = AgentDeps()
    save_run(deps, _awaiting_run("run-c"))
    result = pipeline.apply_approval(deps, "run-c", "checker-1", [Role.QC_MANAGER], approved=True)
    # LIMS/notify are unconfigured locally, so the run reaches SUBMITTED.
    assert result.status == RunStatus.SUBMITTED
    assert result.approval is not None
    assert result.approval.approved is True


def test_rejection_sets_rejected():
    deps = AgentDeps()
    save_run(deps, _awaiting_run("run-d"))
    result = pipeline.apply_approval(
        deps, "run-d", "checker-1", [Role.QC_MANAGER], approved=False, comment="no"
    )
    assert result.status == RunStatus.REJECTED


def test_check_can_approve_requires_awaiting_status():
    run = _awaiting_run("run-e")
    run.status = RunStatus.COMPLETED
    with pytest.raises(pipeline.ApprovalDenied):
        pipeline.check_can_approve(run, "checker-1", [Role.QC_MANAGER])
