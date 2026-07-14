"""AWS Lambda entrypoints for the Step Functions pipeline states.

Each handler is a thin adapter: it reads ``run_id`` (and, for the approval-wait
state, the injected ``taskToken``) from the event, invokes the corresponding
pipeline step, and returns a small JSON payload for the state machine. Full
intermediate data is persisted in the ``runs`` table so the state passed between
tasks stays tiny.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any

from oligos_agents.deps import AgentDeps
from oligos_agents.models import Intent
from oligos_agents.steps import pipeline
from oligos_agents.tracing import configure_tracing, flush_tracing

_powertools_available = True
try:  # pragma: no cover - tracing is optional at runtime
    from aws_lambda_powertools import Logger

    _logger = Logger(service="oligos-agents-steps")
except Exception:  # pragma: no cover
    _powertools_available = False

# Configure Logfire / data-lake tracing once per Lambda cold start.
configure_tracing()


def _deps() -> AgentDeps:
    return AgentDeps()


def _traced(handler: Callable[[dict, Any], dict]) -> Callable[[dict, Any], dict]:
    """Force-flush spans to the data lake before the Lambda invocation returns."""

    @functools.wraps(handler)
    def wrapper(event: dict, context: Any = None) -> dict:
        try:
            return handler(event, context)
        finally:
            flush_tracing()

    return wrapper


@_traced
def route_handler(event: dict, _context: Any = None) -> dict:
    run_id = event["run_id"]
    run = asyncio.run(pipeline.route_step(_deps(), run_id))
    return {"run_id": run_id, "intent": run.intent.value}


@_traced
def retrieve_handler(event: dict, _context: Any = None) -> dict:
    run_id = event["run_id"]
    run = asyncio.run(pipeline.retrieve_step(_deps(), run_id))
    return {"run_id": run_id, "oligo_count": len(run.records)}


@_traced
def detect_handler(event: dict, _context: Any = None) -> dict:
    run_id = event["run_id"]
    run = pipeline.detect_step(_deps(), run_id)
    report = run.conflict_report
    return {
        "run_id": run_id,
        "conflict_count": len(report.conflicts) if report else 0,
        "needs_human_review": bool(report.needs_human_review) if report else False,
    }


@_traced
def draft_handler(event: dict, _context: Any = None) -> dict:
    run_id = event["run_id"]
    run = asyncio.run(pipeline.draft_step(_deps(), run_id))
    return {
        "run_id": run_id,
        "status": run.status.value,
        "awaiting_approval": run.status.value == "awaiting_approval",
    }


@_traced
def store_token_handler(event: dict, _context: Any = None) -> dict:
    """Persist the Step Functions task token while the run awaits approval.

    Invoked via ``lambda:invoke.waitForTaskToken``; the state machine pauses
    until the API calls SendTaskSuccess/SendTaskFailure with this token.
    """
    run_id = event["run_id"]
    token = event["taskToken"]
    pipeline.set_task_token(_deps(), run_id, token)
    return {"run_id": run_id, "status": "awaiting_approval"}


@_traced
def execute_writes_handler(event: dict, _context: Any = None) -> dict:
    """Post-approval writes. Receives approver identity from SendTaskSuccess."""
    from oligos_agents.models import Role

    run_id = event["run_id"]
    approver_sub = event["approver_sub"]
    approver_role = Role(event["approver_role"])
    run = pipeline.execute_after_approval(_deps(), run_id, approver_sub, approver_role)
    return {"run_id": run_id, "status": run.status.value}


@_traced
def specialist_handler(event: dict, _context: Any = None) -> dict:
    run_id = event["run_id"]
    run = asyncio.run(pipeline.specialist_step(_deps(), run_id))
    return {"run_id": run_id, "status": run.status.value, "intent": run.intent.value}


def stream_mirror_handler(event: dict, _context: Any = None) -> dict:
    """DynamoDB Streams handler: mirror new audit records to the WORM bucket."""
    from boto3.dynamodb.types import TypeDeserializer

    from oligos_agents.tools.audit import mirror_record_to_worm

    deps = _deps()
    deserializer = TypeDeserializer()
    mirrored = 0
    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue
        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue
        item = {k: deserializer.deserialize(v) for k, v in new_image.items()}
        mirror_record_to_worm(deps, item)
        mirrored += 1
    return {"mirrored": mirrored}


# Expose intents for state-machine choice authoring.
QC_INTENT = Intent.QC_CONFLICT_CHECK.value
