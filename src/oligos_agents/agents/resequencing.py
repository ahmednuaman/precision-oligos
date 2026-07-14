"""Resequencing Recommender specialist (deterministic).

Distinct from re-synthesis: recommends resequencing where sequencing coverage is
insufficient (FASTQ read depth below the SOP minimum), rather than re-making the
oligo. Selection is deterministic against the SOP threshold.
"""

from __future__ import annotations

from oligos_agents.models import OligoRecord, ResequencingRecommendation
from oligos_agents.rules.sop_qc_008 import READ_DEPTH_MIN


def recommend_resequencing(records: list[OligoRecord], run_id: str) -> ResequencingRecommendation:
    flagged: list[str] = []
    detail: list[str] = []
    for record in records:
        if record.fastq is not None and record.fastq.read_depth < READ_DEPTH_MIN:
            flagged.append(record.oligo_id)
            detail.append(
                f"- {record.oligo_id}: read depth {record.fastq.read_depth}x "
                f"< {READ_DEPTH_MIN}x minimum"
            )

    rationale = (
        f"{len(flagged)} oligo(s) have sequencing coverage below the "
        f"{READ_DEPTH_MIN}x minimum and should be resequenced before any QC verdict "
        "is trusted."
    )
    lines = [f"# Resequencing recommendation ({run_id})", "", rationale]
    if detail:
        lines += ["", *detail]

    return ResequencingRecommendation(
        run_id=run_id,
        oligo_ids=flagged,
        rationale=rationale,
        markdown="\n".join(lines),
    )
