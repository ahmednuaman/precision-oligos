"""Batch/Trend Health specialist (deterministic).

Aggregates QC metrics across the retrieved oligo records. This is pure
computation - no LLM inference - so trend figures are exact and reproducible.
"""

from __future__ import annotations

from statistics import mean

from oligos_agents.models import HealthReport, OligoRecord, QCStatus


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def summarise_batch_health(records: list[OligoRecord], run_id: str) -> HealthReport:
    batch_ids = sorted({r.batch_id for r in records if r.batch_id})
    on_target = [r.fastq.on_target_pct for r in records if r.fastq is not None]
    yields = [
        r.notebook.od260_yield_pct
        for r in records
        if r.notebook is not None and r.notebook.od260_yield_pct is not None
    ]
    queue_ages = [float(r.days_in_queue) for r in records]
    with_qc = [r for r in records if r.notebook is not None]
    passes = [r for r in with_qc if r.notebook.qc_status == QCStatus.PASS]
    pass_rate = (len(passes) / len(with_qc) * 100.0) if with_qc else None

    lines = [
        f"# Batch health report ({run_id})",
        "",
        f"- Batches: {', '.join(batch_ids) or 'n/a'}",
        f"- Oligos assessed: {len(records)}",
        f"- QC pass rate: {pass_rate:.1f}%" if pass_rate is not None else "- QC pass rate: n/a",
        f"- Mean on-target: {mean(on_target):.1f}%" if on_target else "- Mean on-target: n/a",
        f"- Mean OD260 yield: {mean(yields):.1f}%" if yields else "- Mean OD260 yield: n/a",
        (
            f"- Queue age p95: {_percentile(queue_ages, 0.95):.1f} days"
            if queue_ages
            else "- Queue age p95: n/a"
        ),
    ]

    return HealthReport(
        run_id=run_id,
        batch_ids=batch_ids,
        oligo_count=len(records),
        pass_rate_pct=pass_rate,
        mean_on_target_pct=mean(on_target) if on_target else None,
        mean_od260_yield_pct=mean(yields) if yields else None,
        queue_age_p95_days=_percentile(queue_ages, 0.95),
        markdown="\n".join(lines),
    )
