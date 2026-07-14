"""Observability: tracing and LLM cost/latency telemetry.

Per-agent token usage and latency are the dominant variable cost of the system,
so every LLM call records a :class:`~oligos_agents.models.ModelUsage` (captured in
the audit trail) and emits CloudWatch EMF metrics for dashboards and cost
attribution. All emission is best-effort so local runs never fail on telemetry.
"""

from __future__ import annotations

import contextlib
from typing import Any

from oligos_agents.config import get_settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import ModelUsage

METRICS_NAMESPACE = "PrecisionOligos"


def _tokens(result: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a pydantic-ai run result."""
    usage = None
    with contextlib.suppress(Exception):
        usage = result.usage()
    if usage is None:
        return 0, 0
    input_tokens = (
        getattr(usage, "request_tokens", None) or getattr(usage, "input_tokens", None) or 0
    )
    output_tokens = (
        getattr(usage, "response_tokens", None) or getattr(usage, "output_tokens", None) or 0
    )
    return int(input_tokens), int(output_tokens)


def _emit(agent: str, input_tokens: int, output_tokens: int, latency_ms: int) -> None:
    try:
        from aws_lambda_powertools.metrics import MetricUnit, single_metric

        envid = get_settings().envid
        for name, unit, value in (
            ("LLMInputTokens", MetricUnit.Count, input_tokens),
            ("LLMOutputTokens", MetricUnit.Count, output_tokens),
            ("LLMLatencyMs", MetricUnit.Milliseconds, latency_ms),
        ):
            with single_metric(
                name=name, unit=unit, value=value, namespace=METRICS_NAMESPACE
            ) as metric:
                metric.add_dimension(name="agent", value=agent)
                metric.add_dimension(name="envid", value=envid)
    except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
        pass


def record_run_usage(
    deps: AgentDeps,
    agent: str,
    model_id: str,
    result: Any,
    latency_ms: int,
) -> ModelUsage:
    """Record token usage + latency for an agent run."""
    input_tokens, output_tokens = _tokens(result)
    usage = ModelUsage(
        agent=agent,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
    deps.usage.append(usage)
    deps.logger.info(
        "llm_usage",
        extra={
            "agent": agent,
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        },
    )
    _emit(agent, input_tokens, output_tokens, latency_ms)
    return usage
