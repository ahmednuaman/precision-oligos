"""Shared fixtures for building OligoRecords in tests."""

from __future__ import annotations

from oligos_agents.models import (
    DocumentType,
    FastqResult,
    LimsRecord,
    LimsState,
    NotebookQC,
    OligoRecord,
    QCStatus,
    SourceRef,
)


def make_record(
    *,
    oligo_id: str = "OLG-2024-0001",
    batch_id: str = "B-2024-0419-003",
    qc_status: QCStatus = QCStatus.PASS,
    notes: str = "Synthesis clean, QC pass.",
    od260_yield_pct: float | None = 80.0,
    on_target_pct: float = 95.0,
    read_depth: int = 300,
    off_target_loci: int = 1,
    lims_state: LimsState | None = None,
    days_in_queue: int = 3,
    with_source_text: bool = True,
) -> OligoRecord:
    nb_source = SourceRef(
        document_id="s3://kb/nb.txt",
        document_type=DocumentType.NOTEBOOK,
        source_id="NB-2024-001",
    )
    fq_source = SourceRef(
        document_id="s3://kb/run.txt",
        document_type=DocumentType.FASTQ,
        source_id="RUN-2024-0419",
    )
    lims = None
    if lims_state is not None:
        lims = LimsRecord(
            source=SourceRef(
                document_id="lims://x",
                document_type=DocumentType.LIMS,
                source_id="LIMS#OLG-2024-0001",
            ),
            state=lims_state,
            batch_id=batch_id,
        )
    return OligoRecord(
        oligo_id=oligo_id,
        batch_id=batch_id,
        notebook=NotebookQC(
            source=nb_source,
            qc_status=qc_status,
            notes=notes,
            od260_yield_pct=od260_yield_pct,
        ),
        fastq=FastqResult(
            source=fq_source,
            on_target_pct=on_target_pct,
            read_depth=read_depth,
            off_target_loci=off_target_loci,
        ),
        lims=lims,
        days_in_queue=days_in_queue,
        source_texts={"nb": notes} if with_source_text else {},
    )
