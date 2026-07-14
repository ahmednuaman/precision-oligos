export interface RuntimeConfig {
  apiBase: string;
  envLabel: string;
}

export interface Me {
  sub: string;
  email: string | null;
  roles: string[];
  csrf_token: string;
}

export interface NotebookEvidence {
  source_id: string;
  author: string | null;
  date: string | null;
  qc_status: string | null;
  notes_quote: string;
}

export interface FastqEvidence {
  source_id: string;
  sequencing_date: string | null;
  on_target_pct: number | null;
  read_depth: number | null;
  off_target_loci: number | null;
}

export interface Conflict {
  code: string;
  severity: string;
  oligo_id: string;
  batch_id: string;
  notebook_evidence: NotebookEvidence | null;
  fastq_evidence: FastqEvidence | null;
  days_in_queue: number;
  recommended_action: string;
  escalation_required: boolean;
}

export interface ConflictReport {
  run_id: string;
  conflicts: Conflict[];
  summary: { critical: number; high: number; medium: number; low: number };
  escalations: string[];
  needs_human_review: boolean;
  review_notes: string[];
}

export interface ResynthesisOrder {
  run_id: string;
  status: string;
  markdown: string;
  citations: string[];
  required_approval_role: string;
}

export interface RunState {
  run_id: string;
  intent: string;
  status: string;
  submitter_sub: string;
  query: string;
  batch_id: string | null;
  conflict_report: ConflictReport | null;
  resynthesis_order: ResynthesisOrder | null;
  health_report: { markdown: string } | null;
  data_quality_report: { markdown: string } | null;
  root_cause: { markdown: string } | null;
  resequencing: { markdown: string } | null;
  required_approval_role: string | null;
  approval: { approver_sub: string; approver_role: string; approved: boolean } | null;
  error: string | null;
}
