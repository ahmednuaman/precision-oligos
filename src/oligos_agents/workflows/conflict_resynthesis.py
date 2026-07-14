"""In-process composition of the deterministic pipeline.

Used by the CLI and tests to run the full route -> retrieve -> detect -> draft
flow (and the non-QC specialist intents) without deploying Step Functions. In
AWS these same steps run as Lambda tasks orchestrated by the state machine.
"""

from __future__ import annotations

import uuid

from oligos_agents.deps import AgentDeps
from oligos_agents.models import AuditRecord, Intent, RunState, RunStatus
from oligos_agents.steps import pipeline
from oligos_agents.store import save_run


def create_run(deps: AgentDeps, query: str, submitter_sub: str) -> RunState:
    run = RunState(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        submitter_sub=submitter_sub,
        query=query,
        status=RunStatus.PENDING,
    )
    save_run(deps, run)
    pipeline._record_audit(
        deps,
        AuditRecord(
            run_id=run.run_id,
            seq=0,
            action="created",
            actor_sub=submitter_sub,
            evidence={"query": query},
        ),
    )
    return run


async def run_pipeline(deps: AgentDeps, run_id: str) -> RunState:
    """Route, then run the appropriate intent to its natural stopping point.

    For ``qc_conflict_check`` the run stops at ``awaiting_approval`` (unless there
    are no conflicts); other intents run to ``completed``.
    """
    run = await pipeline.route_step(deps, run_id)

    if run.intent == Intent.QC_CONFLICT_CHECK:
        await pipeline.retrieve_step(deps, run_id)
        pipeline.detect_step(deps, run_id)
        return await pipeline.draft_step(deps, run_id)

    if run.intent == Intent.UNKNOWN:
        run.status = RunStatus.NEEDS_REVIEW
        run.error = "Request could not be classified into a supported intent."
        save_run(deps, run)
        return run

    return await pipeline.specialist_step(deps, run_id)
