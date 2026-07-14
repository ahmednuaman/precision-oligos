"""Root-Cause Investigator agent (advisory, LLM).

Deliberately separate from the Conflict Detector, which must never assess root
cause. Given an oligo record and its conflict, this agent proposes plausible
hypotheses with supporting evidence and an overall confidence.
"""

from __future__ import annotations

import time

from pydantic_ai import Agent

from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import Conflict, OligoRecord, RootCauseAssessment
from oligos_agents.observability import record_run_usage
from oligos_agents.prompts import ROOT_CAUSE_PROMPT


def build_root_cause_agent(settings: Settings) -> Agent[AgentDeps, RootCauseAssessment]:
    return Agent(
        settings.router_model,
        deps_type=AgentDeps,
        output_type=RootCauseAssessment,
        instructions=ROOT_CAUSE_PROMPT,
        model_settings={"temperature": 0.0},
        retries=2,
    )


async def investigate_root_cause(
    deps: AgentDeps,
    run_id: str,
    record: OligoRecord,
    conflict: Conflict,
) -> RootCauseAssessment:
    agent = build_root_cause_agent(deps.settings)
    prompt = (
        f"Run id: {run_id}\n"
        f"Oligo: {record.model_dump_json()}\n\n"
        f"Detected conflict: {conflict.model_dump_json()}\n\n"
        "Propose root-cause hypotheses with supporting evidence and a confidence."
    )
    started = time.monotonic()
    result = await agent.run(prompt, deps=deps)
    record_run_usage(
        deps, "root_cause", deps.settings.router_model, result,
        int((time.monotonic() - started) * 1000),
    )
    assessment = result.output
    assessment.run_id = run_id
    assessment.oligo_id = record.oligo_id
    return assessment
