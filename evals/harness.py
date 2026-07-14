"""Scoring functions and dataset loaders for the eval harness.

Three dimensions are measured:

* **Extraction correctness** - structured fields produced by the Oligo Library
  agent versus expected values.
* **Verbatim-citation validity** - every quoted value in a conflict report is
  present in the source text (reuses the production verification logic).
* **Router intent accuracy** - the supervisor's classification versus expected.

The detection and citation scores are fully deterministic and run without any
LLM, so they gate every CI run. The router/extraction scores require Bedrock and
are only run when explicitly enabled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from oligos_agents.agents.conflict_detector import detect_conflicts
from oligos_agents.deps import AgentDeps
from oligos_agents.models import Intent, OligoRecord

DATASETS_DIR = Path(__file__).parent / "datasets"


@dataclass
class EvalResult:
    name: str
    total: int = 0
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.passed / self.total) if self.total else 1.0

    def record(self, ok: bool, detail: str) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failures.append(detail)


def _load(name: str) -> list[dict]:
    return json.loads((DATASETS_DIR / name).read_text())


# --- Deterministic evals (no LLM) ------------------------------------------------------


def evaluate_detection(cases: list[dict] | None = None) -> EvalResult:
    """Check that rule-packs flag exactly the expected conflict codes."""
    cases = cases if cases is not None else _load("detection_cases.json")
    result = EvalResult(name="detection_correctness")
    for case in cases:
        record = OligoRecord.model_validate(case["record"])
        report = detect_conflicts(None, [record], run_id="eval")
        actual = sorted({c.code.value for c in report.conflicts})
        expected = sorted(case["expected_conflict_codes"])
        result.record(
            actual == expected,
            f"{record.oligo_id}: expected {expected}, got {actual}",
        )
    return result


def evaluate_citations(cases: list[dict] | None = None) -> EvalResult:
    """Check that citation verification flags exactly the expected runs."""
    cases = cases if cases is not None else _load("detection_cases.json")
    result = EvalResult(name="citation_validity")
    for case in cases:
        record = OligoRecord.model_validate(case["record"])
        report = detect_conflicts(None, [record], run_id="eval")
        expected_review = bool(case.get("expected_needs_review", False))
        result.record(
            report.needs_human_review == expected_review,
            f"{record.oligo_id}: needs_review expected {expected_review}, "
            f"got {report.needs_human_review} ({report.review_notes})",
        )
    return result


# --- LLM evals (require Bedrock) -------------------------------------------------------


async def evaluate_router(
    deps: AgentDeps, cases: list[dict] | None = None
) -> EvalResult:
    """Measure supervisor intent-classification accuracy."""
    from oligos_agents.agents.supervisor import route

    cases = cases if cases is not None else _load("router_cases.json")
    result = EvalResult(name="router_intent_accuracy")
    for case in cases:
        routing = await route(deps, case["query"])
        expected = Intent(case["expected_intent"])
        result.record(
            routing.intent == expected,
            f"query={case['query']!r}: expected {expected.value}, got {routing.intent.value}",
        )
    return result


def score_extraction(expected: OligoRecord, actual: OligoRecord) -> float:
    """Fraction of key QC fields that match between two records (0..1)."""
    checks: list[bool] = [
        expected.oligo_id == actual.oligo_id,
        expected.batch_id == actual.batch_id,
        (expected.notebook is None) == (actual.notebook is None),
        (expected.fastq is None) == (actual.fastq is None),
    ]
    if expected.notebook and actual.notebook:
        checks.append(expected.notebook.qc_status == actual.notebook.qc_status)
    if expected.fastq and actual.fastq:
        checks.append(abs(expected.fastq.on_target_pct - actual.fastq.on_target_pct) < 0.01)
        checks.append(expected.fastq.read_depth == actual.fastq.read_depth)
    return sum(checks) / len(checks) if checks else 1.0
