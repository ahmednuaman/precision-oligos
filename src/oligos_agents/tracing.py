"""OpenTelemetry tracing for pydantic-ai via Logfire, sunk into an S3 data lake.

pydantic-ai emits rich OTel spans for every agent run, tool call, and model
request (including ``gen_ai.*`` token-usage attributes). We capture those with
Logfire's OpenTelemetry-based SDK and fan them out to two optional sinks:

* **Logfire platform** - live observability, enabled when an ingestion token is
  configured (directly or via Secrets Manager).
* **S3 data lake** - durable, queryable history. Spans are serialised to
  newline-delimited JSON and pushed to a Kinesis Data Firehose delivery stream,
  which buffers, partitions by date, compresses, and lands them in S3 for
  Athena/Glue. Firehose is fire-and-forget, so it never blocks a short-lived
  Lambda step or a request behind the API.

All configuration is optional and best-effort: if the tracing extra is not
installed, or nothing is configured, the platform runs exactly as before.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from oligos_agents.config import Settings, get_settings

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter

# Firehose accepts at most 500 records / 4 MB per PutRecordBatch call.
_FIREHOSE_MAX_BATCH = 500

_configured = False


def _resolve_logfire_token(settings: Settings) -> str | None:
    """Return the Logfire token, resolving a Secrets Manager ARN if given."""
    if settings.logfire_token:
        return settings.logfire_token
    if not settings.logfire_token_secret_arn:
        return None
    try:
        import boto3

        client = boto3.client("secretsmanager", region_name=settings.aws_region)
        secret = client.get_secret_value(SecretId=settings.logfire_token_secret_arn)
        value = secret.get("SecretString")
        if not value:
            return None
        # Support either a raw token or a JSON blob {"token": "..."}.
        stripped = value.strip()
        if stripped.startswith("{"):
            return json.loads(stripped).get("token")
        return stripped
    except Exception:  # noqa: BLE001 - tracing must never break the app
        return None


def _span_to_record(span: ReadableSpan) -> dict[str, Any]:
    """Flatten a span into a JSON-serialisable data-lake record."""
    ctx = span.get_span_context()
    parent = span.parent
    start_ns = span.start_time or 0
    end_ns = span.end_time or 0
    resource_attrs = dict(span.resource.attributes) if span.resource else {}
    return {
        "trace_id": format(ctx.trace_id, "032x") if ctx else None,
        "span_id": format(ctx.span_id, "016x") if ctx else None,
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "name": span.name,
        "kind": span.kind.name if span.kind else None,
        "start_time": datetime.fromtimestamp(start_ns / 1e9, tz=UTC).isoformat(),
        "end_time": datetime.fromtimestamp(end_ns / 1e9, tz=UTC).isoformat(),
        "duration_ms": round((end_ns - start_ns) / 1e6, 3),
        "status": span.status.status_code.name if span.status else None,
        "status_message": span.status.description if span.status else None,
        "service_name": resource_attrs.get("service.name"),
        "service_version": resource_attrs.get("service.version"),
        "environment": resource_attrs.get("deployment.environment"),
        "attributes": _jsonable(dict(span.attributes or {})),
        "events": [
            {
                "name": event.name,
                "timestamp": datetime.fromtimestamp(
                    (event.timestamp or 0) / 1e9, tz=UTC
                ).isoformat(),
                "attributes": _jsonable(dict(event.attributes or {})),
            }
            for event in span.events
        ],
    }


def _jsonable(value: Any) -> Any:
    """Coerce OTel attribute values into JSON-serialisable primitives."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class FirehoseSpanExporter:
    """OTel ``SpanExporter`` that ships spans to Kinesis Firehose (S3 data lake)."""

    def __init__(self, stream_name: str, client: Any) -> None:
        self._stream_name = stream_name
        self._client = client

    def export(self, spans: list[ReadableSpan]):  # type: ignore[override]
        from opentelemetry.sdk.trace.export import SpanExportResult

        records = [
            {"Data": (json.dumps(_span_to_record(span), default=str) + "\n").encode("utf-8")}
            for span in spans
        ]
        try:
            for start in range(0, len(records), _FIREHOSE_MAX_BATCH):
                batch = records[start : start + _FIREHOSE_MAX_BATCH]
                self._client.put_record_batch(
                    DeliveryStreamName=self._stream_name, Records=batch
                )
        except Exception:  # noqa: BLE001 - telemetry export must not raise
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True


def _data_lake_processors(settings: Settings) -> list:
    """Build the batching span processor(s) for the S3 data lake, if configured."""
    if not settings.otel_firehose_stream:
        return []
    try:
        import boto3
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        client = boto3.client("firehose", region_name=settings.aws_region)
        exporter: SpanExporter = FirehoseSpanExporter(settings.otel_firehose_stream, client)  # type: ignore[assignment]
        return [BatchSpanProcessor(exporter)]
    except Exception:  # noqa: BLE001
        return []


def configure_tracing(settings: Settings | None = None) -> bool:
    """Idempotently configure Logfire + pydantic-ai instrumentation.

    Returns ``True`` when tracing was activated. Safe to call from every Lambda
    cold start and at API startup; a module guard prevents re-configuration.
    """
    global _configured
    if _configured:
        return True
    settings = settings or get_settings()
    if not settings.tracing_active:
        return False

    try:
        import logfire
    except ImportError:
        return False

    token = _resolve_logfire_token(settings)
    try:
        logfire.configure(
            service_name="oligos-agents",
            service_version=settings.service_version,
            environment=settings.environment,
            send_to_logfire="if-token-present",
            token=token,
            console=False,
            additional_span_processors=_data_lake_processors(settings),
        )
        # Tag every span with the envid so the data lake is queryable per env.
        logfire.instrument_pydantic_ai(include_content=settings.otel_capture_content)
        logfire.instrument_httpx(capture_headers=False)
    except Exception:  # noqa: BLE001 - never fail the app on telemetry setup
        return False

    _configured = True
    return True


def flush_tracing() -> None:
    """Force-flush pending spans. Call at the end of a Lambda invocation."""
    if not _configured:
        return
    try:
        import logfire

        logfire.force_flush()
    except Exception:  # noqa: BLE001
        pass
