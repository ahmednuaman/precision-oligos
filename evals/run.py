"""Eval harness runner.

Usage:
    python -m evals.run            # deterministic evals only (CI default)
    python -m evals.run --llm      # also run router accuracy (needs Bedrock)

Exits non-zero if any eval falls below its threshold, so it can gate CI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from evals.harness import EvalResult, evaluate_citations, evaluate_detection, evaluate_router

# Minimum acceptable accuracy per eval.
THRESHOLDS = {
    "detection_correctness": 1.0,
    "citation_validity": 1.0,
    "router_intent_accuracy": 0.8,
}


def _print(result: EvalResult) -> bool:
    threshold = THRESHOLDS.get(result.name, 1.0)
    ok = result.accuracy >= threshold
    status = "PASS" if ok else "FAIL"
    print(  # noqa: T201 - harness output
        f"[{status}] {result.name}: {result.passed}/{result.total} "
        f"({result.accuracy:.0%}, threshold {threshold:.0%})"
    )
    for failure in result.failures:
        print(f"    - {failure}")  # noqa: T201
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="Run LLM-dependent evals.")
    args = parser.parse_args(argv)

    results = [evaluate_detection(), evaluate_citations()]

    if args.llm:
        from oligos_agents.deps import AgentDeps

        results.append(asyncio.run(evaluate_router(AgentDeps())))

    all_ok = all(_print(r) for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
