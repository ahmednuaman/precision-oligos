"""Data-Quality / Metadata Gap specialist (deterministic).

Inspects the retrieved records for missing or inconsistent metadata and
unreported outcomes. This directly serves the data-curation goal: turning QC
runs into clean, AI-ready, context-rich records over time.
"""

from __future__ import annotations

from oligos_agents.models import DataQualityReport, OligoRecord


def assess_data_quality(records: list[OligoRecord], run_id: str) -> DataQualityReport:
    missing: list[str] = []
    inconsistent: list[str] = []
    unreported: list[str] = []

    for record in records:
        oid = record.oligo_id
        if record.notebook is None:
            missing.append(f"{oid}: no lab-notebook record")
        else:
            if record.notebook.hplc_purity_pct is None:
                missing.append(f"{oid}: missing HPLC purity")
            if record.notebook.od260_yield_pct is None:
                missing.append(f"{oid}: missing OD260 yield")
        if record.fastq is None:
            missing.append(f"{oid}: no FASTQ run record")
        if record.lims is None:
            missing.append(f"{oid}: no LIMS record")
        if record.chemistry is None:
            missing.append(f"{oid}: missing chemistry/modification metadata")
        if not record.synthesis_date:
            missing.append(f"{oid}: missing synthesis date")

        # Inconsistency: batch id present on record but disagrees with LIMS.
        if record.lims is not None and record.lims.batch_id:
            if record.lims.batch_id != record.batch_id:
                inconsistent.append(
                    f"{oid}: batch id {record.batch_id} disagrees with LIMS "
                    f"{record.lims.batch_id}"
                )

        # Unreported outcome: extraction flagged a gap.
        unreported.extend(f"{oid}: {w}" for w in record.extraction_warnings)

    lines = [
        f"# Data-quality report ({run_id})",
        "",
        f"- Records inspected: {len(records)}",
        f"- Missing-metadata findings: {len(missing)}",
        f"- Inconsistencies: {len(inconsistent)}",
        f"- Unreported/flagged outcomes: {len(unreported)}",
    ]
    if missing:
        lines += ["", "## Missing metadata", *[f"- {m}" for m in missing]]
    if inconsistent:
        lines += ["", "## Inconsistencies", *[f"- {m}" for m in inconsistent]]
    if unreported:
        lines += ["", "## Unreported / flagged", *[f"- {m}" for m in unreported]]

    return DataQualityReport(
        run_id=run_id,
        missing_metadata=missing,
        inconsistent_metadata=inconsistent,
        unreported_outcomes=unreported,
        markdown="\n".join(lines),
    )
