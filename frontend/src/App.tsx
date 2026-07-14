import { useCallback, useEffect, useRef, useState } from "react";
import {
  decideRun,
  getMe,
  getRun,
  loadConfig,
  loginUrl,
  logout,
  submitRequest,
  Unauthorised,
} from "./api";
import type { Conflict, Me, RunState } from "./types";

const ROLE_RANK: Record<string, number> = {
  QCApprover: 0,
  QCLead: 1,
  QCManager: 2,
  Director: 3,
};

function highestRank(roles: string[]): number {
  return roles.reduce((acc, r) => Math.max(acc, ROLE_RANK[r] ?? -1), -1);
}

function canApprove(me: Me, run: RunState): boolean {
  if (run.status !== "awaiting_approval") return false;
  if (me.sub === run.submitter_sub) return false; // maker-checker
  const required = run.required_approval_role ?? "QCApprover";
  return highestRank(me.roles) >= (ROLE_RANK[required] ?? 0);
}

const TERMINAL = new Set([
  "submitted",
  "completed",
  "rejected",
  "failed",
  "needs_review",
]);

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [envLabel, setEnvLabel] = useState("");
  const [query, setQuery] = useState(
    "Check QC conflicts for batch B-2024-0419-003 and draft any re-synthesis order.",
  );
  const [run, setRun] = useState<RunState | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      const cfg = await loadConfig();
      setEnvLabel(cfg.envLabel);
      try {
        setMe(await getMe());
      } catch (e) {
        if (!(e instanceof Unauthorised)) setError(String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const poll = useCallback((runId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const state = await getRun(runId);
        setRun(state);
        if (TERMINAL.has(state.status) && pollRef.current) {
          window.clearInterval(pollRef.current);
        }
      } catch (e) {
        setError(String(e));
      }
    }, 2000);
  }, []);

  async function onSubmit() {
    setError("");
    setRun(null);
    try {
      const { run_id } = await submitRequest(query);
      const state = await getRun(run_id);
      setRun(state);
      poll(run_id);
    } catch (e) {
      setError(String(e));
    }
  }

  async function onDecide(approve: boolean) {
    if (!run) return;
    setError("");
    try {
      await decideRun(run.run_id, approve, comment);
      setRun(await getRun(run.run_id));
    } catch (e) {
      setError(String(e));
    }
  }

  if (loading) return <div className="container">Loading…</div>;

  if (!me) {
    return (
      <div className="container center">
        <h1>Precision Oligos QC</h1>
        <p>Enterprise sign-in is required.</p>
        <a className="btn primary" href={loginUrl()}>
          Sign in
        </a>
      </div>
    );
  }

  return (
    <div className="container">
      <header>
        <h1>Precision Oligos QC</h1>
        <div className="user">
          <span className="env">{envLabel}</span>
          <span>{me.email ?? me.sub}</span>
          <span className="roles">{me.roles.join(", ") || "no roles"}</span>
          <button className="btn" onClick={() => logout().then(() => setMe(null))}>
            Sign out
          </button>
        </div>
      </header>

      <section className="card">
        <h2>New request</h2>
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={3} />
        <button className="btn primary" onClick={onSubmit}>
          Submit
        </button>
      </section>

      {error && <div className="card error">{error}</div>}

      {run && (
        <section className="card">
          <h2>
            Run {run.run_id} <span className={`badge ${run.status}`}>{run.status}</span>
          </h2>
          <p className="muted">
            Intent: {run.intent} · Batch: {run.batch_id ?? "n/a"}
          </p>
          {run.error && <div className="error">{run.error}</div>}

          {run.conflict_report && <ConflictReportView run={run} />}
          {run.resynthesis_order && (
            <div>
              <h3>Draft re-synthesis order</h3>
              <p className="muted">
                Requires approval: {run.resynthesis_order.required_approval_role}
              </p>
              <pre className="markdown">{run.resynthesis_order.markdown}</pre>
              {run.resynthesis_order.citations.length > 0 && (
                <p className="muted">
                  Citations: {run.resynthesis_order.citations.join(", ")}
                </p>
              )}
            </div>
          )}

          <MarkdownBlock title="Batch health" md={run.health_report?.markdown} />
          <MarkdownBlock title="Data quality" md={run.data_quality_report?.markdown} />
          <MarkdownBlock title="Root cause" md={run.root_cause?.markdown} />
          <MarkdownBlock title="Resequencing" md={run.resequencing?.markdown} />

          {run.status === "awaiting_approval" && (
            <div className="approval">
              <h3>Approval</h3>
              {canApprove(me, run) ? (
                <>
                  <textarea
                    placeholder="Optional comment"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={2}
                  />
                  <div className="actions">
                    <button className="btn primary" onClick={() => onDecide(true)}>
                      Approve
                    </button>
                    <button className="btn danger" onClick={() => onDecide(false)}>
                      Reject
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted">
                  You are not authorised to approve this order (segregation of
                  duties / insufficient role).
                </p>
              )}
            </div>
          )}

          {run.approval && (
            <p className="muted">
              Decision: {run.approval.approved ? "approved" : "rejected"} by{" "}
              {run.approval.approver_role}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function ConflictReportView({ run }: { run: RunState }) {
  const report = run.conflict_report!;
  return (
    <div>
      <h3>Conflict report</h3>
      {report.needs_human_review && (
        <div className="error">
          Flagged for human review — citations could not be fully verified.
          <ul>
            {report.review_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted">
        CRITICAL {report.summary.critical} · HIGH {report.summary.high} · MEDIUM{" "}
        {report.summary.medium} · LOW {report.summary.low}
        {report.escalations.length > 0 && ` · Escalations: ${report.escalations.join(", ")}`}
      </p>
      {report.conflicts.length === 0 ? (
        <p className="muted">No conflicts detected.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Oligo</th>
              <th>Type</th>
              <th>Severity</th>
              <th>Evidence</th>
              <th>Recommended action</th>
            </tr>
          </thead>
          <tbody>
            {report.conflicts.map((c, i) => (
              <ConflictRow key={i} c={c} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ConflictRow({ c }: { c: Conflict }) {
  return (
    <tr>
      <td>{c.oligo_id}</td>
      <td>{c.code}</td>
      <td>
        <span className={`sev ${c.severity}`}>{c.severity}</span>
        {c.escalation_required && <span className="sev CRITICAL"> ESC</span>}
      </td>
      <td>
        {c.notebook_evidence && (
          <div>
            <strong>{c.notebook_evidence.source_id}</strong> ({c.notebook_evidence.qc_status}):{" "}
            <em>"{c.notebook_evidence.notes_quote}"</em>
          </div>
        )}
        {c.fastq_evidence && (
          <div>
            <strong>{c.fastq_evidence.source_id}</strong>: on-target{" "}
            {c.fastq_evidence.on_target_pct}% · depth {c.fastq_evidence.read_depth}x · off-target{" "}
            {c.fastq_evidence.off_target_loci}
          </div>
        )}
      </td>
      <td>{c.recommended_action}</td>
    </tr>
  );
}

function MarkdownBlock({ title, md }: { title: string; md?: string }) {
  if (!md) return null;
  return (
    <div>
      <h3>{title}</h3>
      <pre className="markdown">{md}</pre>
    </div>
  );
}
