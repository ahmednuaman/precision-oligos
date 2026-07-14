"""Run-state persistence (DynamoDB ``runs`` table).

The full ``RunState`` is stored as a JSON document with a few projected
top-level attributes so GSIs (by status / batch / submitter) work. For local
development without AWS, an in-memory store is used automatically when no table
is configured.
"""

from __future__ import annotations

from oligos_agents.deps import AgentDeps
from oligos_agents.models import RunState

_MEMORY: dict[str, str] = {}


def _table_name(deps: AgentDeps) -> str | None:
    return deps.settings.runs_table


def save_run(deps: AgentDeps, run: RunState) -> None:
    run.touch()
    payload = run.model_dump_json()
    table_name = _table_name(deps)
    if not table_name:
        _MEMORY[run.run_id] = payload
        return
    deps.clients.dynamodb.Table(table_name).put_item(
        Item={
            "run_id": run.run_id,
            "status": run.status.value,
            "batch_id": run.batch_id or "",
            "submitter_sub": run.submitter_sub,
            "updated_at": run.updated_at.isoformat(),
            "state": payload,
        }
    )


def load_run(deps: AgentDeps, run_id: str) -> RunState | None:
    table_name = _table_name(deps)
    if not table_name:
        payload = _MEMORY.get(run_id)
        return RunState.model_validate_json(payload) if payload else None
    resp = deps.clients.dynamodb.Table(table_name).get_item(Key={"run_id": run_id})
    item = resp.get("Item")
    if not item or "state" not in item:
        return None
    return RunState.model_validate_json(item["state"])
