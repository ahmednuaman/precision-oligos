"""Unit tests for the deterministic SOP-QC-008 rule-pack."""

from __future__ import annotations

from oligos_agents.agents.conflict_detector import detect_conflicts
from oligos_agents.models import ConflictCode, LimsState, QCStatus, Severity
from oligos_agents.rules import run_all
from oligos_agents.rules.sop_qc_008 import is_escalation_required
from tests.fixtures import make_record


def _codes(record) -> set[str]:
    return {c.code.value for c in run_all(record)}


def test_notebook_fastq_mismatch_high():
    record = make_record(qc_status=QCStatus.PASS, on_target_pct=70.0)
    conflicts = run_all(record)
    codes = {c.code for c in conflicts}
    assert ConflictCode.NOTEBOOK_FASTQ_MISMATCH in codes
    high = next(c for c in conflicts if c.code == ConflictCode.NOTEBOOK_FASTQ_MISMATCH)
    assert high.severity == Severity.HIGH


def test_fastq_notebook_mismatch_medium():
    record = make_record(qc_status=QCStatus.FAIL, on_target_pct=95.0, read_depth=300)
    assert ConflictCode.FASTQ_NOTEBOOK_MISMATCH.value in _codes(record)


def test_lims_notebook_discrepancy_critical():
    record = make_record(qc_status=QCStatus.FAIL, lims_state=LimsState.RELEASED)
    conflicts = run_all(record)
    crit = next(c for c in conflicts if c.code == ConflictCode.LIMS_NOTEBOOK_DISCREPANCY)
    assert crit.severity == Severity.CRITICAL


def test_sequencing_insufficient_low():
    record = make_record(read_depth=150)
    assert ConflictCode.SEQUENCING_INSUFFICIENT.value in _codes(record)


def test_yield_below_threshold_high():
    record = make_record(od260_yield_pct=40.0)
    assert ConflictCode.YIELD_BELOW_THRESHOLD.value in _codes(record)


def test_off_target_excess_high():
    record = make_record(off_target_loci=8)
    assert ConflictCode.OFF_TARGET_EXCESS.value in _codes(record)


def test_clean_record_has_no_conflicts():
    record = make_record()
    assert run_all(record) == []


def test_escalation_after_14_days():
    assert is_escalation_required(make_record(days_in_queue=15)) is True
    assert is_escalation_required(make_record(days_in_queue=14)) is False


def test_report_summary_and_escalation():
    record = make_record(qc_status=QCStatus.PASS, on_target_pct=70.0, days_in_queue=20)
    report = detect_conflicts(None, [record], run_id="t1")
    assert report.summary.high >= 1
    assert record.oligo_id in report.escalations
    assert report.needs_human_review is False


def test_citation_verification_flags_fabricated_quote():
    record = make_record(
        qc_status=QCStatus.PASS,
        on_target_pct=70.0,
        notes="A quote that is not present",
        with_source_text=False,
    )
    report = detect_conflicts(None, [record], run_id="t2")
    assert report.needs_human_review is True
    assert report.review_notes
