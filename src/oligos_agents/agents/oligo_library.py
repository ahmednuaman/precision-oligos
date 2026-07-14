"""Oligo Library agent: retrieves and structures cross-source evidence.

An LLM agent (cheap extraction model, temperature 0) that must fetch full
documents via the knowledge tools before extracting a strictly-typed list of
``OligoRecord``. Every fetched document is captured in ``deps.fetched_documents``
so a later deterministic step can verify that quoted values truly appear in the
source text.
"""

from __future__ import annotations

import time
from dataclasses import asdict

from pydantic_ai import Agent, RunContext

from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import OligoRecord
from oligos_agents.observability import record_run_usage
from oligos_agents.prompts import OLIGO_LIBRARY_PROMPT
from oligos_agents.tools.knowledge import fetch_document, knowledge_search


def build_oligo_library_agent(settings: Settings) -> Agent[AgentDeps, list[OligoRecord]]:
    agent: Agent[AgentDeps, list[OligoRecord]] = Agent(
        settings.extraction_model,
        deps_type=AgentDeps,
        output_type=list[OligoRecord],
        instructions=OLIGO_LIBRARY_PROMPT,
        model_settings={"temperature": 0.0},
        retries=2,
    )

    @agent.tool
    async def search_knowledge(ctx: RunContext[AgentDeps], query: str) -> list[dict]:
        """Search the knowledge base; returns candidate document references."""
        refs = knowledge_search(ctx.deps, query)
        return [asdict(ref) for ref in refs]

    @agent.tool
    async def fetch(ctx: RunContext[AgentDeps], document_id: str) -> str:
        """Fetch the full text of a document and record it for citation checks."""
        text = fetch_document(ctx.deps, document_id)
        ctx.deps.fetched_documents[document_id] = text
        return text

    return agent


async def retrieve_oligo_records(deps: AgentDeps, query: str) -> list[OligoRecord]:
    """Run the Oligo Library agent and return structured records."""
    agent = build_oligo_library_agent(deps.settings)
    started = time.monotonic()
    result = await agent.run(query, deps=deps)
    record_run_usage(
        deps, "oligo_library", deps.settings.extraction_model, result,
        int((time.monotonic() - started) * 1000),
    )
    records = result.output
    # Attach fetched source text to each record for downstream verification.
    combined = "\n\n".join(deps.fetched_documents.values())
    for record in records:
        if not record.source_texts and combined:
            record.source_texts["_fetched"] = combined
    return records
