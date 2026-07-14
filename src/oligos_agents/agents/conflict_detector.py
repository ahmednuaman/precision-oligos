"""Conflict Detector: deterministic SOP application + citation verification.

This is intentionally NOT an LLM agent. Conflicts are decided purely by the
registered rule-packs, so the compliance path is fully reproducible and never
"invents" a conflict. As a safety net against upstream extraction errors, every
quoted value in the report is verified against the fetched source text; if a
citation cannot be verified the run is flagged for human review rather than
trusted.
"""

from __future__ import annotations

from oligos_agents.deps import AgentDeps
from oligos_agents.models import (
    Conflict,
    ConflictReport,
    OligoRecord,
    SeveritySummary,
)
from oligos_agents.rules import get_packs, run_all
from oligos_agents.rules.sop_qc_008 import is_escalation_required


def _source_text_for(record: OligoRecord, deps: AgentDeps | None) -> str:
    parts = list(record.source_texts.values())
    if deps is not None:
        parts.extend(deps.fetched_documents.values())
    return "\n".join(parts)


def _verify_conflict_citations(conflict: Conflict, source_text: str) -> list[str]:
    """Return a list of unverifiable-citation warnings for a conflict."""
    if not source_text:
        # No source text available to verify against; treat as unverifiable.
        return [f"{conflict.oligo_id}: no source text available to verify citations."]

    warnings: list[str] = []
    nb = conflict.notebook_evidence
    if nb and nb.notes_quote and nb.notes_quote.strip():
        if nb.notes_quote.strip() not in source_text:
            warnings.append(
                f"{conflict.oligo_id}: notebook quote from {nb.source_id} "
                "not found verbatim in source text."
            )
    return warnings


def detect_conflicts(
    deps: AgentDeps | None,
    records: list[OligoRecord],
    run_id: str,
) -> ConflictReport:
    """Apply all rule-packs to every record and assemble a cited report."""
    packs = get_packs()
    conflicts: list[Conflict] = []
    escalations: list[str] = []
    review_notes: list[str] = []

    for record in records:
        record_conflicts = run_all(record, packs)
        conflicts.extend(record_conflicts)

        if is_escalation_required(record):
            escalations.append(record.oligo_id)

        source_text = _source_text_for(record, deps)
        for conflict in record_conflicts:
            review_notes.extend(_verify_conflict_citations(conflict, source_text))

    summary = SeveritySummary()
    for conflict in conflicts:
        summary.add(conflict.severity)

    return ConflictReport(
        run_id=run_id,
        conflicts=conflicts,
        summary=summary,
        escalations=sorted(set(escalations)),
        needs_human_review=bool(review_notes),
        review_notes=review_notes,
    )
