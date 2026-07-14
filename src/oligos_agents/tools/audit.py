"""Append-only audit trail.

Audit records are written to a DynamoDB table with a conditional put so an
existing entry can never be overwritten; combined with an IAM policy that denies
``UpdateItem``/``DeleteItem`` (see Terraform), the table is effectively
append-only. DynamoDB Streams then mirror each record into an S3 Object Lock
(WORM) bucket for a tamper-evident, durable compliance record.

To stay compatible with the right to erasure, records store the opaque Cognito
``sub`` and role - never email or name.
"""

from __future__ import annotations

import json
from typing import Any

from boto3.dynamodb.conditions import Key

from oligos_agents.deps import AgentDeps
from oligos_agents.models import AuditRecord


class AuditNotConfigured(RuntimeError):
    pass


def _table(deps: AgentDeps):
    name = deps.settings.audit_table
    if not name:
        raise AuditNotConfigured("AUDIT_TABLE is not set; cannot write audit records.")
    return deps.clients.dynamodb.Table(name)


def _next_seq(table: Any, run_id: str) -> int:
    """Return the next sequence number for a run (count of existing entries)."""
    resp = table.query(
        KeyConditionExpression=Key("run_id").eq(run_id),
        Select="COUNT",
    )
    return int(resp.get("Count", 0))


def append_audit(deps: AgentDeps, record: AuditRecord) -> AuditRecord:
    """Write an audit record with a conditional (no-overwrite) put."""
    table = _table(deps)
    if record.seq == 0:
        record = record.model_copy(update={"seq": _next_seq(table, record.run_id)})

    item = {
        "run_id": record.run_id,
        "sk": record.sort_key,
        "seq": record.seq,
        "ts": record.ts.isoformat(),
        "action": record.action,
        "actor_sub": record.actor_sub,
        "actor_role": record.actor_role.value if record.actor_role else None,
        "intent": record.intent.value if record.intent else None,
        # Serialise nested structures as JSON to avoid DynamoDB float/Decimal issues.
        "evidence": json.dumps(record.evidence, default=str),
        "model_usage": json.dumps([u.model_dump() for u in record.model_usage], default=str),
    }
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(run_id) AND attribute_not_exists(sk)",
    )
    return record


def write_audit(deps: AgentDeps, record: AuditRecord) -> AuditRecord:
    """Convenience wrapper around :func:`append_audit`."""
    return append_audit(deps, record)


def get_audit_trail(deps: AgentDeps, run_id: str) -> list[dict]:
    """Return the ordered audit trail for a run (read side)."""
    table = _table(deps)
    resp = table.query(KeyConditionExpression=Key("run_id").eq(run_id))
    return sorted(resp.get("Items", []), key=lambda i: i.get("sk", ""))


def mirror_record_to_worm(deps: AgentDeps, item: dict) -> None:
    """Copy a single audit item into the S3 Object Lock (WORM) bucket.

    Intended to be called from the DynamoDB Streams handler. The object key is
    deterministic (run_id/sk) so replays are idempotent, and Object Lock on the
    bucket enforces immutability at the storage layer.
    """
    bucket = deps.settings.audit_worm_bucket
    if not bucket:
        raise AuditNotConfigured("AUDIT_WORM_BUCKET is not set; cannot mirror audit records.")
    run_id = item.get("run_id", "unknown")
    sk = item.get("sk", "unknown")
    key = f"audit/{run_id}/{sk}.json"
    deps.clients.s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(item, default=str).encode("utf-8"),
        ContentType="application/json",
    )
