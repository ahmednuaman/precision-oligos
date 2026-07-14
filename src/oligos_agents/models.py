"""Domain models for the precision-oligos data-integrity platform.

These pydantic models are the shared contract between the agents, the
deterministic rule-packs, the orchestration steps, and the storage layer.
Everything the agents produce is strictly typed so that malformed LLM output
is rejected before it can feed the deterministic conflict rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Severity(StrEnum):
    """Conflict severity, ordered so that comparisons are meaningful."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class QCStatus(StrEnum):
    """Lab-notebook validation state."""

    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"


class LimsState(StrEnum):
    """LIMS synthesis-log state for an oligo."""

    RELEASED = "released"
    QC_PASS = "qc_pass"
    QC_FAIL = "qc_fail"
    QC_HOLD = "qc_hold"
    RESYNTHESIZE_ORDERED = "resynthesize_ordered"


class DocumentType(StrEnum):
    NOTEBOOK = "notebook"
    FASTQ = "fastq"
    LIMS = "lims"


class ConflictCode(StrEnum):
    """Fixed SOP-QC-008 conflict type codes."""

    NOTEBOOK_FASTQ_MISMATCH = "notebook_fastq_mismatch"
    FASTQ_NOTEBOOK_MISMATCH = "fastq_notebook_mismatch"
    LIMS_NOTEBOOK_DISCREPANCY = "lims_notebook_discrepancy"
    SEQUENCING_INSUFFICIENT = "sequencing_insufficient"
    YIELD_BELOW_THRESHOLD = "yield_below_threshold"
    OFF_TARGET_EXCESS = "off_target_excess"


class Intent(StrEnum):
    """Supervisor routing intents."""

    QC_CONFLICT_CHECK = "qc_conflict_check"
    BATCH_HEALTH = "batch_health"
    DATA_QUALITY = "data_quality"
    ROOT_CAUSE = "root_cause"
    RESEQUENCING = "resequencing"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    PENDING = "pending"
    ROUTING = "routing"
    RETRIEVING = "retrieving"
    DETECTING = "detecting"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class Role(StrEnum):
    """Authorisation roles, sourced from Entra App Roles via Cognito."""

    QC_APPROVER = "QCApprover"
    QC_LEAD = "QCLead"
    QC_MANAGER = "QCManager"
    DIRECTOR = "Director"


# --- Source documents and provenance -------------------------------------------------


class SourceRef(BaseModel):
    """A citation back to a source document."""

    document_id: str
    document_type: DocumentType
    source_id: str = Field(description="Human-facing id, e.g. NB-2024-018 / RUN-2024-0419")
    author: str | None = None
    date: str | None = None


class NotebookQC(BaseModel):
    source: SourceRef
    qc_status: QCStatus
    notes: str = ""
    hplc_purity_pct: float | None = None
    od260_yield_pct: float | None = Field(
        default=None, description="OD260 yield as a percentage of synthesis scale."
    )


class FastqResult(BaseModel):
    source: SourceRef
    on_target_pct: float
    read_depth: int
    off_target_loci: int
    sequencing_date: str | None = None


class LimsRecord(BaseModel):
    source: SourceRef
    state: LimsState
    batch_id: str | None = None


class OligoRecord(BaseModel):
    """A fully-retrieved, cross-source view of a single oligo.

    Populated by the Oligo Library agent from full documents (never snippets).
    Carries the raw source text so downstream steps can verify that every
    quoted value truly appears verbatim in a source document.
    """

    oligo_id: str
    batch_id: str
    notebook: NotebookQC | None = None
    fastq: FastqResult | None = None
    lims: LimsRecord | None = None
    synthesis_scale: str | None = None
    synthesis_date: str | None = None
    days_in_queue: int = 0
    chemistry: str | None = Field(default=None, description="Backbone / modifications metadata.")
    source_texts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of source_id -> full document text, for citation verification.",
    )
    extraction_warnings: list[str] = Field(default_factory=list)


# --- Conflict detection outputs -------------------------------------------------------


class NotebookEvidence(BaseModel):
    source_id: str
    author: str | None = None
    date: str | None = None
    qc_status: QCStatus | None = None
    notes_quote: str = Field(description="Verbatim quote from the notebook.")


class FastqEvidence(BaseModel):
    source_id: str
    sequencing_date: str | None = None
    on_target_pct: float | None = None
    read_depth: int | None = None
    off_target_loci: int | None = None


class Conflict(BaseModel):
    code: ConflictCode
    severity: Severity
    oligo_id: str
    batch_id: str
    notebook_evidence: NotebookEvidence | None = None
    fastq_evidence: FastqEvidence | None = None
    days_in_queue: int = 0
    recommended_action: str
    escalation_required: bool = False


class SeveritySummary(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    def add(self, severity: Severity) -> None:
        setattr(self, severity.value.lower(), getattr(self, severity.value.lower()) + 1)


class ConflictReport(BaseModel):
    run_id: str
    conflicts: list[Conflict] = Field(default_factory=list)
    summary: SeveritySummary = Field(default_factory=SeveritySummary)
    escalations: list[str] = Field(
        default_factory=list, description="Oligo ids flagged ESCALATION REQUIRED."
    )
    needs_human_review: bool = Field(
        default=False,
        description="Set when citation verification fails and the run cannot be trusted.",
    )
    review_notes: list[str] = Field(default_factory=list)

    @property
    def max_severity(self) -> Severity | None:
        if not self.conflicts:
            return None
        return max((c.severity for c in self.conflicts), key=lambda s: s.rank)


# --- Re-synthesis order (draft only) --------------------------------------------------


class ResynthesisOrder(BaseModel):
    run_id: str
    status: str = Field(default="draft", pattern="^draft$")
    markdown: str
    citations: list[str] = Field(default_factory=list)
    required_approval_role: Role
    escalate_to_engineering: bool = True


# --- Other specialist outputs ---------------------------------------------------------


class HealthReport(BaseModel):
    run_id: str
    batch_ids: list[str] = Field(default_factory=list)
    oligo_count: int = 0
    pass_rate_pct: float | None = None
    mean_on_target_pct: float | None = None
    mean_od260_yield_pct: float | None = None
    queue_age_p95_days: float | None = None
    markdown: str = ""


class DataQualityReport(BaseModel):
    run_id: str
    missing_metadata: list[str] = Field(default_factory=list)
    inconsistent_metadata: list[str] = Field(default_factory=list)
    unreported_outcomes: list[str] = Field(default_factory=list)
    markdown: str = ""


class RootCauseAssessment(BaseModel):
    run_id: str
    oligo_id: str
    hypotheses: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: str = "low"
    markdown: str = ""


class ResequencingRecommendation(BaseModel):
    run_id: str
    oligo_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    markdown: str = ""


# --- Run state and audit --------------------------------------------------------------


class Approval(BaseModel):
    approver_sub: str
    approver_role: Role
    decided_at: datetime = Field(default_factory=_utcnow)
    approved: bool
    comment: str | None = None


class RunState(BaseModel):
    run_id: str
    intent: Intent = Intent.UNKNOWN
    status: RunStatus = RunStatus.PENDING
    submitter_sub: str
    query: str
    batch_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    records: list[OligoRecord] = Field(default_factory=list)
    conflict_report: ConflictReport | None = None
    resynthesis_order: ResynthesisOrder | None = None
    health_report: HealthReport | None = None
    data_quality_report: DataQualityReport | None = None
    root_cause: RootCauseAssessment | None = None
    resequencing: ResequencingRecommendation | None = None
    required_approval_role: Role | None = None
    approval: Approval | None = None
    task_token: str | None = Field(
        default=None, description="Step Functions callback token while awaiting approval."
    )
    error: str | None = None

    def touch(self) -> None:
        self.updated_at = _utcnow()


class ModelUsage(BaseModel):
    agent: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class AuditRecord(BaseModel):
    """A tamper-evident audit entry.

    Stores the opaque Cognito ``sub`` and role rather than PII (email/name) so
    the immutable store is compatible with the right to erasure.
    """

    run_id: str
    seq: int
    ts: datetime = Field(default_factory=_utcnow)
    action: str
    actor_sub: str | None = None
    actor_role: Role | None = None
    intent: Intent | None = None
    evidence: dict = Field(default_factory=dict)
    model_usage: list[ModelUsage] = Field(default_factory=list)

    @property
    def sort_key(self) -> str:
        """DynamoDB sort key: timestamp then sequence for a stable ordered log."""
        return f"{self.ts.isoformat()}#{self.seq:06d}"


# --- Session (BFF) --------------------------------------------------------------------


class OidcTokens(BaseModel):
    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_at: datetime


class Session(BaseModel):
    session_id: str
    sub: str
    email: str | None = None
    roles: list[Role] = Field(default_factory=list)
    tokens: OidcTokens
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime
    csrf_token: str


# --- MCP OAuth 2.1 authorization server -----------------------------------------------


class OAuthClient(BaseModel):
    """A dynamically-registered (RFC 7591) MCP client. Public client (PKCE)."""

    client_id: str
    client_name: str | None = None
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    scope: str | None = None
    token_endpoint_auth_method: str = "none"
    created_at: datetime = Field(default_factory=_utcnow)


class PendingAuthorization(BaseModel):
    """State held between /authorize and the brokered Cognito callback + consent."""

    key: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = "S256"
    scope: str
    state: str | None = None
    resource: str | None = None
    # PKCE for the upstream (Cognito) leg, owned by this server.
    upstream_code_verifier: str
    # Identity resolved after the Cognito callback, pending user consent.
    sub: str | None = None
    email: str | None = None
    roles: list[Role] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class AuthorizationCode(BaseModel):
    """A one-time authorization code bound to a client, redirect, PKCE and user."""

    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = "S256"
    scope: str
    resource: str | None = None
    sub: str
    email: str | None = None
    roles: list[Role] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class McpToken(BaseModel):
    """An issued access or refresh token, validated by the resource server."""

    token: str
    kind: str = "access"  # "access" | "refresh"
    client_id: str
    scope: str
    resource: str | None = None
    sub: str
    email: str | None = None
    roles: list[Role] = Field(default_factory=list)
    expires_at: datetime
