"""Pipeline step functions.

Each step loads the current ``RunState``, performs one unit of work, persists the
updated state, and returns it. Steps are deliberately small and composable so
they can run either in-process (CLI / tests) or as individual Step Functions
Lambda tasks. The conflict-detection step is pure Python; only retrieval,
drafting, and (optionally) root-cause use an LLM.
"""

from __future__ import annotations

from oligos_agents.agents.batch_health import summarise_batch_health
from oligos_agents.agents.conflict_detector import detect_conflicts
from oligos_agents.agents.data_quality import assess_data_quality
from oligos_agents.agents.oligo_library import retrieve_oligo_records
from oligos_agents.agents.resequencing import recommend_resequencing
from oligos_agents.agents.resynthesis_drafter import draft_resynthesis_order
from oligos_agents.agents.supervisor import route
from oligos_agents.authz import highest_role, required_role_for_severity, role_satisfies
from oligos_agents.deps import AgentDeps
from oligos_agents.models import (
    Approval,
    AuditRecord,
    Intent,
    Role,
    RunState,
    RunStatus,
)
from oligos_agents.store import load_run, save_run
from oligos_agents.tools import audit as audit_tool
from oligos_agents.tools import lims as lims_tool
from oligos_agents.tools import notify as notify_tool


class RunNotFound(RuntimeError):
    pass


class ApprovalDenied(RuntimeError):
    pass


def _load(deps: AgentDeps, run_id: str) -> RunState:
    run = load_run(deps, run_id)
    if run is None:
        raise RunNotFound(run_id)
    return run


def _record_audit(deps: AgentDeps, record: AuditRecord) -> None:
    """Best-effort audit write; never blocks the pipeline in local mode."""
    try:
        audit_tool.append_audit(deps, record)
    except audit_tool.AuditNotConfigured:
        deps.logger.warning("audit_skipped", extra={"action": record.action})


# --- Steps -----------------------------------------------------------------------------


async def route_step(deps: AgentDeps, run_id: str) -> RunState:
    run = _load(deps, run_id)
    run.status = RunStatus.ROUTING
    save_run(deps, run)
    routing = await route(deps, run.query)
    run.intent = routing.intent
    run.batch_id = routing.batch_id or run.batch_id
    save_run(deps, run)
    _record_audit(
        deps,
        AuditRecord(
            run_id=run_id,
            seq=0,
            action="routed",
            actor_sub=run.submitter_sub,
            intent=run.intent,
            evidence={"batch_id": run.batch_id, "oligo_id": routing.oligo_id},
        ),
    )
    return run


async def retrieve_step(deps: AgentDeps, run_id: str) -> RunState:
    run = _load(deps, run_id)
    run.status = RunStatus.RETRIEVING
    save_run(deps, run)
    run.records = await retrieve_oligo_records(deps, run.query)
    save_run(deps, run)
    _record_audit(
        deps,
        AuditRecord(
            run_id=run_id,
            seq=0,
            action="retrieved",
            actor_sub=run.submitter_sub,
            intent=run.intent,
            evidence={"oligo_count": len(run.records)},
        ),
    )
    return run


def detect_step(deps: AgentDeps, run_id: str) -> RunState:
    run = _load(deps, run_id)
    run.status = RunStatus.DETECTING
    report = detect_conflicts(deps, run.records, run_id)
    run.conflict_report = report
    save_run(deps, run)
    _record_audit(
        deps,
        AuditRecord(
            run_id=run_id,
            seq=0,
            action="conflicts_detected",
            actor_sub=run.submitter_sub,
            intent=run.intent,
            evidence={
                "conflict_count": len(report.conflicts),
                "needs_human_review": report.needs_human_review,
                "escalations": report.escalations,
            },
        ),
    )
    return run


async def draft_step(deps: AgentDeps, run_id: str) -> RunState:
    run = _load(deps, run_id)
    if run.conflict_report is None or not run.conflict_report.conflicts:
        # Nothing to re-synthesise; complete the run.
        run.status = RunStatus.COMPLETED
        save_run(deps, run)
        return run
    run.status = RunStatus.DRAFTING
    save_run(deps, run)
    order = await draft_resynthesis_order(deps, run.conflict_report)
    run.resynthesis_order = order
    run.required_approval_role = order.required_approval_role
    run.status = RunStatus.AWAITING_APPROVAL
    save_run(deps, run)
    _record_audit(
        deps,
        AuditRecord(
            run_id=run_id,
            seq=0,
            action="draft_created",
            actor_sub=run.submitter_sub,
            intent=run.intent,
            evidence={"required_approval_role": order.required_approval_role.value},
            model_usage=list(deps.usage),
        ),
    )
    return run


async def specialist_step(deps: AgentDeps, run_id: str) -> RunState:
    """Run a non-QC specialist intent to completion."""
    run = _load(deps, run_id)
    if not run.records:
        run = await retrieve_step(deps, run_id)

    if run.intent == Intent.BATCH_HEALTH:
        run.health_report = summarise_batch_health(run.records, run_id)
    elif run.intent == Intent.DATA_QUALITY:
        run.data_quality_report = assess_data_quality(run.records, run_id)
    elif run.intent == Intent.RESEQUENCING:
        run.resequencing = recommend_resequencing(run.records, run_id)
    elif run.intent == Intent.ROOT_CAUSE:
        # Root cause requires a detected conflict; run detection first.
        run = detect_step(deps, run_id)
        report = run.conflict_report
        if report and report.conflicts:
            from oligos_agents.agents.root_cause import investigate_root_cause

            first = report.conflicts[0]
            match = next((r for r in run.records if r.oligo_id == first.oligo_id), None)
            if match is not None:
                run.root_cause = await investigate_root_cause(deps, run_id, match, first)

    run.status = RunStatus.COMPLETED
    save_run(deps, run)
    return run


# --- Approval + write execution --------------------------------------------------------


def check_can_approve(
    run: RunState,
    approver_sub: str,
    approver_roles: list[Role],
) -> Role:
    """Validate maker-checker + role requirements; return the effective role.

    Raises :class:`ApprovalDenied` if the run is not awaiting approval, the
    approver is the submitter, or the approver's role is insufficient.
    """
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise ApprovalDenied(f"Run {run.run_id} is not awaiting approval (status {run.status}).")
    if approver_sub == run.submitter_sub:
        raise ApprovalDenied("The submitter cannot approve their own re-synthesis order.")
    required = run.required_approval_role or required_role_for_severity(
        run.conflict_report.max_severity if run.conflict_report else None
    )
    if not role_satisfies(approver_roles, required):
        raise ApprovalDenied(f"Approver role does not satisfy required level {required.value}.")
    return highest_role(approver_roles) or required


def apply_approval(
    deps: AgentDeps,
    run_id: str,
    approver_sub: str,
    approver_roles: list[Role],
    approved: bool,
    comment: str | None = None,
) -> RunState:
    """Apply a maker-checker approval decision and, if approved, execute writes."""
    run = _load(deps, run_id)
    approver_role = check_can_approve(run, approver_sub, approver_roles)
    run.approval = Approval(
        approver_sub=approver_sub,
        approver_role=approver_role,
        approved=approved,
        comment=comment,
    )

    if not approved:
        run.status = RunStatus.REJECTED
        save_run(deps, run)
        _record_audit(
            deps,
            AuditRecord(
                run_id=run_id,
                seq=0,
                action="rejected",
                actor_sub=approver_sub,
                actor_role=approver_role,
                intent=run.intent,
                evidence={"comment": comment},
            ),
        )
        return run

    run.status = RunStatus.APPROVED
    save_run(deps, run)
    return _execute_writes(deps, run, approver_sub, approver_role)


def set_task_token(deps: AgentDeps, run_id: str, token: str) -> RunState:
    """Persist the Step Functions callback token while awaiting approval."""
    run = _load(deps, run_id)
    run.task_token = token
    run.status = RunStatus.AWAITING_APPROVAL
    save_run(deps, run)
    return run


def execute_after_approval(
    deps: AgentDeps,
    run_id: str,
    approver_sub: str,
    approver_role: Role,
    comment: str | None = None,
) -> RunState:
    """Record approval and execute writes (Step Functions post-approval path).

    Maker-checker/role validation is performed by the API before the task token
    is released, so this trusts the already-validated approver identity.
    """
    run = _load(deps, run_id)
    run.approval = Approval(
        approver_sub=approver_sub, approver_role=approver_role, approved=True, comment=comment
    )
    run.status = RunStatus.APPROVED
    save_run(deps, run)
    return _execute_writes(deps, run, approver_sub, approver_role)


def mark_rejected(
    deps: AgentDeps,
    run_id: str,
    approver_sub: str,
    approver_role: Role,
    comment: str | None = None,
) -> RunState:
    run = _load(deps, run_id)
    run.approval = Approval(
        approver_sub=approver_sub, approver_role=approver_role, approved=False, comment=comment
    )
    run.status = RunStatus.REJECTED
    save_run(deps, run)
    _record_audit(
        deps,
        AuditRecord(
            run_id=run_id,
            seq=0,
            action="rejected",
            actor_sub=approver_sub,
            actor_role=approver_role,
            intent=run.intent,
            evidence={"comment": comment},
        ),
    )
    return run


def _execute_writes(
    deps: AgentDeps,
    run: RunState,
    approver_sub: str,
    approver_role: Role,
) -> RunState:
    report = run.conflict_report
    order = run.resynthesis_order
    oligo_ids = sorted({c.oligo_id for c in report.conflicts}) if report else []

    work_order_id: str | None = None
    try:
        result = lims_tool.submit_to_lims(
            deps,
            run_id=run.run_id,
            oligo_ids=oligo_ids,
            order_markdown=order.markdown if order else "",
            batch_id=run.batch_id,
        )
        work_order_id = result.work_order_id
    except lims_tool.LimsNotConfigured:
        deps.logger.warning("lims_skipped", extra={"run_id": run.run_id})

    _record_audit(
        deps,
        AuditRecord(
            run_id=run.run_id,
            seq=0,
            action="submitted_to_lims",
            actor_sub=approver_sub,
            actor_role=approver_role,
            intent=run.intent,
            evidence={
                "work_order_id": work_order_id,
                "oligo_ids": oligo_ids,
                "escalations": report.escalations if report else [],
            },
        ),
    )

    try:
        notify_tool.send_notifications(
            deps,
            subject=f"Re-synthesis order approved: {run.batch_id or run.run_id}",
            message=(order.markdown if order else "Re-synthesis order approved."),
            severity=(report.max_severity.value if report and report.max_severity else None),
            batch_id=run.batch_id,
        )
    except notify_tool.NotificationsNotConfigured:
        deps.logger.warning("notify_skipped", extra={"run_id": run.run_id})

    run.status = RunStatus.SUBMITTED
    save_run(deps, run)
    return run
