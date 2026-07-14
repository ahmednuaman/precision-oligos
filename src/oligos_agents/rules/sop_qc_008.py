"""SOP-QC-008: the default deterministic conflict-detection rule-pack.

Six fixed rules compare the lab notebook, FASTQ sequencing results, and LIMS
state for a single oligo. Every rule is a pure function of an ``OligoRecord``;
severities and recommended actions are fixed by the SOP and never inferred.
"""

from __future__ import annotations

from oligos_agents.models import (
    Conflict,
    ConflictCode,
    FastqEvidence,
    LimsState,
    NotebookEvidence,
    OligoRecord,
    QCStatus,
    Severity,
)
from oligos_agents.rules.base import RulePack, register_pack

# --- Numeric thresholds (SOP-QC-008) ---
ON_TARGET_MIN = 85.0  # FASTQ on-target percentage (>= 85%)
READ_DEPTH_MIN = 200  # sequencing coverage (>= 200x)
OD260_YIELD_MIN = 50.0  # OD260 yield as % of synthesis scale (>= 50%)
OFF_TARGET_MAX = 5  # off-target loci (<= 5)
QUEUE_TIMEOUT_DAYS = 14  # > 14 days in queue -> escalation required

SOP_CODE = "SOP-QC-008"
SOP_VERSION = "1.0.0"


def is_escalation_required(record: OligoRecord) -> bool:
    """Any oligo more than 14 days in queue must be escalated."""
    return record.days_in_queue > QUEUE_TIMEOUT_DAYS


def _notebook_evidence(record: OligoRecord) -> NotebookEvidence | None:
    if record.notebook is None:
        return None
    nb = record.notebook
    return NotebookEvidence(
        source_id=nb.source.source_id,
        author=nb.source.author,
        date=nb.source.date,
        qc_status=nb.qc_status,
        notes_quote=nb.notes,
    )


def _fastq_evidence(record: OligoRecord) -> FastqEvidence | None:
    if record.fastq is None:
        return None
    fq = record.fastq
    return FastqEvidence(
        source_id=fq.source.source_id,
        sequencing_date=fq.sequencing_date,
        on_target_pct=fq.on_target_pct,
        read_depth=fq.read_depth,
        off_target_loci=fq.off_target_loci,
    )


def _conflict(
    record: OligoRecord,
    code: ConflictCode,
    severity: Severity,
    action: str,
) -> Conflict:
    return Conflict(
        code=code,
        severity=severity,
        oligo_id=record.oligo_id,
        batch_id=record.batch_id,
        notebook_evidence=_notebook_evidence(record),
        fastq_evidence=_fastq_evidence(record),
        days_in_queue=record.days_in_queue,
        recommended_action=action,
        escalation_required=is_escalation_required(record),
    )


def _fastq_is_pass(record: OligoRecord) -> bool:
    fq = record.fastq
    if fq is None:
        return False
    return (
        fq.on_target_pct >= ON_TARGET_MIN
        and fq.read_depth >= READ_DEPTH_MIN
        and fq.off_target_loci <= OFF_TARGET_MAX
    )


def rule_notebook_fastq_mismatch(record: OligoRecord) -> Conflict | None:
    """HIGH: notebook QC PASS but FASTQ on-target below threshold."""
    if record.notebook is None or record.fastq is None:
        return None
    if record.notebook.qc_status == QCStatus.PASS and record.fastq.on_target_pct < ON_TARGET_MIN:
        return _conflict(
            record,
            ConflictCode.NOTEBOOK_FASTQ_MISMATCH,
            Severity.HIGH,
            "Review sequencing quality",
        )
    return None


def rule_fastq_notebook_mismatch(record: OligoRecord) -> Conflict | None:
    """MEDIUM: FASTQ pass but notebook QC FAIL."""
    if record.notebook is None or record.fastq is None:
        return None
    if _fastq_is_pass(record) and record.notebook.qc_status == QCStatus.FAIL:
        return _conflict(
            record,
            ConflictCode.FASTQ_NOTEBOOK_MISMATCH,
            Severity.MEDIUM,
            "Investigate synthesis conditions",
        )
    return None


def rule_lims_notebook_discrepancy(record: OligoRecord) -> Conflict | None:
    """CRITICAL: LIMS state released but notebook shows qc_fail."""
    if record.lims is None or record.notebook is None:
        return None
    if record.lims.state == LimsState.RELEASED and record.notebook.qc_status == QCStatus.FAIL:
        return _conflict(
            record,
            ConflictCode.LIMS_NOTEBOOK_DISCREPANCY,
            Severity.CRITICAL,
            "Immediate escalation to QC Director",
        )
    return None


def rule_sequencing_insufficient(record: OligoRecord) -> Conflict | None:
    """LOW: FASTQ read depth below the minimum coverage."""
    if record.fastq is None:
        return None
    if record.fastq.read_depth < READ_DEPTH_MIN:
        return _conflict(
            record,
            ConflictCode.SEQUENCING_INSUFFICIENT,
            Severity.LOW,
            "Recommend resequencing",
        )
    return None


def rule_yield_below_threshold(record: OligoRecord) -> Conflict | None:
    """HIGH: OD260 yield below 50% of synthesis scale."""
    if record.notebook is None or record.notebook.od260_yield_pct is None:
        return None
    if record.notebook.od260_yield_pct < OD260_YIELD_MIN:
        return _conflict(
            record,
            ConflictCode.YIELD_BELOW_THRESHOLD,
            Severity.HIGH,
            "Flag low yield batch",
        )
    return None


def rule_off_target_excess(record: OligoRecord) -> Conflict | None:
    """HIGH: FASTQ off-target loci above the allowed maximum."""
    if record.fastq is None:
        return None
    if record.fastq.off_target_loci > OFF_TARGET_MAX:
        return _conflict(
            record,
            ConflictCode.OFF_TARGET_EXCESS,
            Severity.HIGH,
            "Mutation/contamination investigation",
        )
    return None


SOP_QC_008 = RulePack(
    code=SOP_CODE,
    version=SOP_VERSION,
    rules=(
        rule_notebook_fastq_mismatch,
        rule_fastq_notebook_mismatch,
        rule_lims_notebook_discrepancy,
        rule_sequencing_insufficient,
        rule_yield_below_threshold,
        rule_off_target_excess,
    ),
)

register_pack(SOP_QC_008)
