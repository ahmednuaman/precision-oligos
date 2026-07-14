"""Shared run lifecycle logic used by both the REST control-plane and the MCP server.

Keeping submit / fetch / approve / reject here (rather than inline in the FastAPI
handlers) guarantees the MCP tools enforce exactly the same maker-checker rules,
Step Functions task-token handling, and audit trail as the browser UI.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import Role, RunState, RunStatus
from oligos_agents.steps import pipeline
from oligos_agents.store import load_run, save_run
from oligos_agents.workflows.conflict_resynthesis import create_run, run_pipeline


class RunServiceError(Exception):
    """Base class for run-service failures (mapped to HTTP/MCP errors by callers)."""


class RunNotFound(RunServiceError):
    pass


class ApprovalDenied(RunServiceError):
    pass


async def _run_in_process(deps: AgentDeps, run_id: str) -> None:
    try:
        await run_pipeline(deps, run_id)
    except Exception as exc:  # noqa: BLE001 - record failure on the run
        run = load_run(deps, run_id)
        if run is not None:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            save_run(deps, run)


def submit_run(deps: AgentDeps, settings: Settings, query: str, sub: str) -> dict:
    """Create a run and kick off execution (Step Functions in AWS, else in-process).

    Must be called from within a running event loop when Step Functions is not
    configured, because the in-process fallback is scheduled as a task.
    """
    run = create_run(deps, query, sub)
    if settings.state_machine_arn:
        deps.clients.sfn.start_execution(
            stateMachineArn=settings.state_machine_arn,
            name=run.run_id,
            input=json.dumps({"run_id": run.run_id}),
        )
    else:
        asyncio.create_task(_run_in_process(deps, run.run_id))
    return {"run_id": run.run_id, "status": run.status.value}


def get_run(deps: AgentDeps, run_id: str) -> RunState:
    run = load_run(deps, run_id)
    if run is None:
        raise RunNotFound(f"Run {run_id!r} not found.")
    return run


def list_runs_for(deps: AgentDeps, submitter_sub: str, limit: int = 50) -> list[RunState]:
    """Return recent runs submitted by ``submitter_sub`` (newest first).

    Uses the ``by_submitter`` GSI in AWS; falls back to scanning the in-memory
    store for local development.
    """
    from oligos_agents import store

    table = store._table_name(deps)  # type: ignore[attr-defined]
    if table is None:
        all_runs = [RunState.model_validate_json(p) for p in store._MEMORY.values()]  # type: ignore[attr-defined]
        runs = [r for r in all_runs if r.submitter_sub == submitter_sub]
    else:
        resp = deps.clients.dynamodb.Table(table).query(
            IndexName="by_submitter",
            KeyConditionExpression="submitter_sub = :s",
            ExpressionAttributeValues={":s": submitter_sub},
        )
        runs = [RunState.model_validate_json(i["state"]) for i in resp.get("Items", [])]
    runs.sort(key=lambda r: r.created_at, reverse=True)
    return runs[:limit]


def decide_run(
    deps: AgentDeps,
    settings: Settings,
    run_id: str,
    *,
    sub: str,
    roles: Sequence[Role],
    approved: bool,
    comment: str | None,
) -> dict:
    """Apply a maker-checker decision, honouring the Step Functions task token."""
    run = load_run(deps, run_id)
    if run is None:
        raise RunNotFound(f"Run {run_id!r} not found.")

    try:
        approver_role = pipeline.check_can_approve(run, sub, list(roles))
    except pipeline.ApprovalDenied as exc:
        raise ApprovalDenied(str(exc)) from exc

    if settings.state_machine_arn and run.task_token:
        if approved:
            deps.clients.sfn.send_task_success(
                taskToken=run.task_token,
                output=json.dumps(
                    {
                        "run_id": run_id,
                        "approver_sub": sub,
                        "approver_role": approver_role.value,
                    }
                ),
            )
        else:
            pipeline.mark_rejected(deps, run_id, sub, approver_role, comment)
            deps.clients.sfn.send_task_failure(
                taskToken=run.task_token,
                error="Rejected",
                cause=comment or "Rejected by approver",
            )
        return {"run_id": run_id, "decision": "approved" if approved else "rejected"}

    updated = pipeline.apply_approval(
        deps, run_id, sub, list(roles), approved=approved, comment=comment
    )
    return {"run_id": run_id, "status": updated.status.value}
