"""LIMS submission tool.

A thin, configurable REST client that submits re-synthesis work orders to an
external LIMS. It is:

* **Idempotent** - the run id is sent as an ``Idempotency-Key`` so retries never
  create duplicate work orders.
* **Resilient** - transient failures are retried with exponential backoff, and a
  simple circuit breaker stops hammering an unhealthy LIMS.

There is no universal LIMS API, so the endpoint and credentials are entirely
configuration driven.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from oligos_agents.deps import AgentDeps

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BACKOFF_BASE_SECONDS = 0.5

# Module-level circuit breaker (per process / warm invocation).
_CB_FAILURE_THRESHOLD = 5
_CB_RESET_SECONDS = 30.0
_cb_consecutive_failures = 0
_cb_opened_at: float | None = None


class LimsNotConfigured(RuntimeError):
    pass


class LimsCircuitOpen(RuntimeError):
    pass


class LimsSubmissionError(RuntimeError):
    pass


@dataclass
class LimsResult:
    work_order_id: str
    state: str
    idempotent_replay: bool = False


def _circuit_open() -> bool:
    global _cb_opened_at, _cb_consecutive_failures
    if _cb_opened_at is None:
        return False
    if (time.monotonic() - _cb_opened_at) >= _CB_RESET_SECONDS:
        # Half-open: allow the next call through and reset counters.
        _cb_opened_at = None
        _cb_consecutive_failures = 0
        return False
    return True


def _record_success() -> None:
    global _cb_opened_at, _cb_consecutive_failures
    _cb_consecutive_failures = 0
    _cb_opened_at = None


def _record_failure() -> None:
    global _cb_opened_at, _cb_consecutive_failures
    _cb_consecutive_failures += 1
    if _cb_consecutive_failures >= _CB_FAILURE_THRESHOLD:
        _cb_opened_at = time.monotonic()


def _api_key(deps: AgentDeps) -> str | None:
    arn = deps.settings.lims_api_key_secret_arn
    if not arn:
        return None
    secret = deps.clients.secretsmanager.get_secret_value(SecretId=arn)
    return secret.get("SecretString")


def submit_to_lims(
    deps: AgentDeps,
    run_id: str,
    oligo_ids: list[str],
    order_markdown: str,
    batch_id: str | None = None,
) -> LimsResult:
    """Submit a re-synthesis work order, keyed by ``run_id`` for idempotency."""
    base_url = deps.settings.lims_base_url
    if not base_url:
        raise LimsNotConfigured("LIMS_BASE_URL is not set; cannot submit work orders.")

    if _circuit_open():
        raise LimsCircuitOpen("LIMS circuit breaker is open; refusing to submit.")

    headers = {"Idempotency-Key": run_id, "Content-Type": "application/json"}
    api_key = _api_key(deps)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "run_id": run_id,
        "batch_id": batch_id,
        "oligo_ids": oligo_ids,
        "order_markdown": order_markdown,
        "requested_state": "resynthesize_ordered",
    }
    url = base_url.rstrip("/") + "/work-orders"

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with httpx.Client(timeout=deps.settings.lims_timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code in _TRANSIENT_STATUS:
                raise LimsSubmissionError(f"Transient LIMS status {resp.status_code}")
            resp.raise_for_status()
            body = resp.json()
            _record_success()
            return LimsResult(
                work_order_id=str(body.get("work_order_id", "")),
                state=str(body.get("state", "resynthesize_ordered")),
                idempotent_replay=bool(body.get("idempotent_replay", resp.status_code == 200)),
            )
        except (httpx.HTTPError, LimsSubmissionError) as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))

    _record_failure()
    raise LimsSubmissionError(f"LIMS submission failed after retries: {last_error}")
