"""Tests for the deterministic specialist agents."""

from __future__ import annotations

from oligos_agents.agents.batch_health import summarise_batch_health
from oligos_agents.agents.data_quality import assess_data_quality
from oligos_agents.agents.resequencing import recommend_resequencing
from oligos_agents.models import LimsState, QCStatus
from tests.fixtures import make_record


def test_batch_health_pass_rate_and_means():
    records = [
        make_record(oligo_id="A", qc_status=QCStatus.PASS, on_target_pct=90.0),
        make_record(oligo_id="B", qc_status=QCStatus.FAIL, on_target_pct=80.0),
    ]
    report = summarise_batch_health(records, "run-h")
    assert report.oligo_count == 2
    assert report.pass_rate_pct == 50.0
    assert report.mean_on_target_pct == 85.0
    assert "Batch health report" in report.markdown


def test_resequencing_flags_low_read_depth_only():
    records = [
        make_record(oligo_id="A", read_depth=150),
        make_record(oligo_id="B", read_depth=300),
    ]
    rec = recommend_resequencing(records, "run-r")
    assert rec.oligo_ids == ["A"]


def test_data_quality_reports_inconsistent_batch_id():
    record = make_record(oligo_id="A", batch_id="B-1", lims_state=LimsState.QC_PASS)
    record.lims.batch_id = "B-2"
    report = assess_data_quality([record], "run-d")
    assert any("disagrees with LIMS" in item for item in report.inconsistent_metadata)


def test_data_quality_reports_missing_metadata():
    record = make_record(oligo_id="A")
    report = assess_data_quality([record], "run-d2")
    # chemistry and synthesis_date and HPLC purity are unset in the fixture.
    assert any("missing chemistry" in item for item in report.missing_metadata)
    assert any("missing synthesis date" in item for item in report.missing_metadata)
