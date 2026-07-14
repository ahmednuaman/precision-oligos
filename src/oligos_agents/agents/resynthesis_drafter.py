"""Re-synthesis Drafter agent: produces a draft-only, cited work order.

An LLM agent (stronger drafting model, temperature 0) turns the cited conflict
report into a Markdown re-synthesis order. The order is always a draft and never
claims execution. The required approval role is set deterministically from the
report's maximum severity - not left to the model.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from oligos_agents.authz import required_role_for_severity
from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import ConflictReport, ResynthesisOrder
from oligos_agents.observability import record_run_usage
from oligos_agents.prompts import RESYNTHESIS_DRAFTER_PROMPT


class _DraftContent(BaseModel):
    """Internal LLM output; the enriched order is assembled deterministically."""

    markdown: str = Field(description="The re-synthesis order in Markdown.")
    citations: list[str] = Field(
        default_factory=list, description="Source ids cited (NB-.../RUN-...)."
    )


def build_resynthesis_drafter_agent(settings: Settings) -> Agent[AgentDeps, _DraftContent]:
    return Agent(
        settings.drafting_model,
        deps_type=AgentDeps,
        output_type=_DraftContent,
        instructions=RESYNTHESIS_DRAFTER_PROMPT,
        model_settings={"temperature": 0.0},
        retries=2,
    )


async def draft_resynthesis_order(deps: AgentDeps, report: ConflictReport) -> ResynthesisOrder:
    """Run the drafter and assemble a draft-only, cited re-synthesis order."""
    agent = build_resynthesis_drafter_agent(deps.settings)
    prompt = (
        "Draft a re-synthesis order from this cited conflict report. "
        "Cite source ids and remember this is a draft only.\n\n"
        f"{report.model_dump_json(indent=2)}"
    )
    started = time.monotonic()
    result = await agent.run(prompt, deps=deps)
    record_run_usage(
        deps, "resynthesis_drafter", deps.settings.drafting_model, result,
        int((time.monotonic() - started) * 1000),
    )
    draft = result.output
    return ResynthesisOrder(
        run_id=report.run_id,
        status="draft",
        markdown=draft.markdown,
        citations=draft.citations,
        required_approval_role=required_role_for_severity(report.max_severity),
        escalate_to_engineering=True,
    )
