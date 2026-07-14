"""Supervisor router (LLM).

Classifies an incoming request into an :class:`Intent` and extracts any batch or
oligo id. The deterministic compliance pipeline is only ever invoked as a unit
for ``qc_conflict_check`` - the router never improvises rule logic.
"""

from __future__ import annotations

import time

from pydantic import BaseModel
from pydantic_ai import Agent

from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import Intent
from oligos_agents.observability import record_run_usage
from oligos_agents.prompts import SUPERVISOR_PROMPT


class Routing(BaseModel):
    intent: Intent
    batch_id: str | None = None
    oligo_id: str | None = None


def build_supervisor_agent(settings: Settings) -> Agent[AgentDeps, Routing]:
    return Agent(
        settings.router_model,
        deps_type=AgentDeps,
        output_type=Routing,
        instructions=SUPERVISOR_PROMPT,
        model_settings={"temperature": 0.0},
        retries=2,
    )


async def route(deps: AgentDeps, query: str) -> Routing:
    agent = build_supervisor_agent(deps.settings)
    started = time.monotonic()
    result = await agent.run(query, deps=deps)
    record_run_usage(
        deps, "supervisor", deps.settings.router_model, result,
        int((time.monotonic() - started) * 1000),
    )
    return result.output
