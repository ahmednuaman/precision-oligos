"""Tests for the OTel span serialisation and the Firehose data-lake exporter."""

from __future__ import annotations

import json

import pytest

from oligos_agents.config import Settings

pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace.export import SpanExportResult  # noqa: E402

from oligos_agents import tracing  # noqa: E402


class _FakeSpanContext:
    def __init__(self, trace_id: int, span_id: int) -> None:
        self.trace_id = trace_id
        self.span_id = span_id


class _FakeStatus:
    def __init__(self, name: str = "OK") -> None:
        self.status_code = type("Code", (), {"name": name})()
        self.description = None


class _FakeResource:
    def __init__(self, attrs: dict) -> None:
        self.attributes = attrs


class _FakeKind:
    name = "INTERNAL"


class _FakeSpan:
    def __init__(self) -> None:
        self._ctx = _FakeSpanContext(0x1234, 0xABCD)
        self.parent = None
        self.name = "agent run"
        self.kind = _FakeKind()
        self.start_time = 1_000_000_000
        self.end_time = 1_500_000_000
        self.status = _FakeStatus()
        self.resource = _FakeResource(
            {
                "service.name": "oligos-agents",
                "service.version": "0.1.0",
                "deployment.environment": "dev",
            }
        )
        self.attributes = {"gen_ai.usage.input_tokens": 42, "gen_ai.request.model": "sonnet"}
        self.events = []

    def get_span_context(self) -> _FakeSpanContext:
        return self._ctx


def test_span_to_record_flattens_key_fields():
    record = tracing._span_to_record(_FakeSpan())
    assert record["trace_id"] == format(0x1234, "032x")
    assert record["span_id"] == format(0xABCD, "016x")
    assert record["parent_span_id"] is None
    assert record["name"] == "agent run"
    assert record["duration_ms"] == 500.0
    assert record["status"] == "OK"
    assert record["service_name"] == "oligos-agents"
    assert record["environment"] == "dev"
    assert record["attributes"]["gen_ai.usage.input_tokens"] == 42


class _FakeFirehose:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def put_record_batch(self, DeliveryStreamName: str, Records: list[dict]):  # noqa: N803
        self.batches.append(Records)
        return {"FailedPutCount": 0}


def test_firehose_exporter_emits_ndjson_records():
    client = _FakeFirehose()
    exporter = tracing.FirehoseSpanExporter("stream-x", client)
    result = exporter.export([_FakeSpan(), _FakeSpan()])
    assert result == SpanExportResult.SUCCESS
    assert len(client.batches) == 1
    records = client.batches[0]
    assert len(records) == 2
    for rec in records:
        data = rec["Data"].decode()
        assert data.endswith("\n")
        json.loads(data)  # each record is valid JSON


def test_firehose_exporter_returns_failure_on_client_error():
    class _Boom:
        def put_record_batch(self, **_kwargs):
            raise RuntimeError("firehose down")

    exporter = tracing.FirehoseSpanExporter("stream-x", _Boom())
    assert exporter.export([_FakeSpan()]) == SpanExportResult.FAILURE


def test_configure_tracing_noop_when_not_configured():
    # No sinks configured -> tracing stays inactive and returns False.
    settings = Settings()
    assert settings.tracing_active is False
    assert tracing.configure_tracing(settings) is False


def test_tracing_active_when_stream_set():
    settings = Settings(OTEL_FIREHOSE_STREAM="OligoTracesFirehose-x")
    assert settings.tracing_active is True
