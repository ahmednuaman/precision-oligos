"""Knowledge-base retrieval tools.

Two primitives back every agent's access to the notebook / FASTQ / LIMS data:

* ``knowledge_search(query)`` -> a list of matching document references.
* ``fetch_document(document_id)`` -> the full text of a single document.

The critical rule is *never answer from a snippet alone* - agents must fetch the
full document before reasoning about QC. Retrieval targets an existing Bedrock
Knowledge Base (consumed by id); the underlying store is not provisioned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from oligos_agents.deps import AgentDeps

_SOURCE_URI_KEY = "x-amz-bedrock-kb-source-uri"
_TITLE_KEY = "x-amz-bedrock-kb-title"


@dataclass
class DocumentRef:
    """A reference to a knowledge-base document returned by a search."""

    document_id: str
    title: str
    source_uri: str
    score: float
    snippet: str


class KnowledgeBaseNotConfigured(RuntimeError):
    """Raised when no knowledge base id has been configured."""


def _require_kb_id(deps: AgentDeps) -> str:
    kb_id = deps.settings.knowledge_base_id
    if not kb_id:
        raise KnowledgeBaseNotConfigured(
            "KNOWLEDGE_BASE_ID is not set; cannot query the knowledge base."
        )
    return kb_id


def knowledge_search(deps: AgentDeps, query: str, max_results: int = 20) -> list[DocumentRef]:
    """Search the knowledge base and return distinct document references.

    Results are de-duplicated by source URI (one entry per document) and sorted
    by descending relevance so the agent can decide which documents to fetch.
    """
    kb_id = _require_kb_id(deps)
    client = deps.clients.bedrock_agent_runtime
    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": max_results,
                "overrideSearchType": "SEMANTIC",
            }
        },
    )

    best_by_uri: dict[str, DocumentRef] = {}
    for result in response.get("retrievalResults", []):
        metadata = result.get("metadata", {}) or {}
        source_uri = str(metadata.get(_SOURCE_URI_KEY, "")) or _location_uri(result)
        if not source_uri:
            continue
        score = float(result.get("score", 0.0) or 0.0)
        content = result.get("content", {}) or {}
        snippet = content.get("text", "") if isinstance(content, dict) else str(content)
        existing = best_by_uri.get(source_uri)
        if existing is None or score > existing.score:
            best_by_uri[source_uri] = DocumentRef(
                document_id=source_uri,
                title=str(metadata.get(_TITLE_KEY, "")) or _basename(source_uri),
                source_uri=source_uri,
                score=score,
                snippet=snippet,
            )

    return sorted(best_by_uri.values(), key=lambda d: d.score, reverse=True)


def fetch_document(deps: AgentDeps, document_id: str, max_chunks: int = 100) -> str:
    """Return the full text of a document identified by its source URI.

    If the document is an S3 object we read it directly; otherwise we gather all
    knowledge-base chunks for that source URI and concatenate them in order.
    """
    if document_id.startswith("s3://"):
        return _fetch_from_s3(deps, document_id)
    return _fetch_from_kb(deps, document_id, max_chunks=max_chunks)


def _fetch_from_s3(deps: AgentDeps, uri: str) -> str:
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    obj = deps.clients.s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="replace")


def _fetch_from_kb(deps: AgentDeps, source_uri: str, max_chunks: int) -> str:
    kb_id = _require_kb_id(deps)
    client = deps.clients.bedrock_agent_runtime
    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": _basename(source_uri)},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": max_chunks,
                "filter": {"equals": {"key": "x-amz-bedrock-kb-source-uri", "value": source_uri}},
            }
        },
    )
    chunks: list[str] = []
    for result in response.get("retrievalResults", []):
        content = result.get("content", {}) or {}
        text = content.get("text", "") if isinstance(content, dict) else str(content)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _location_uri(result: dict) -> str:
    location = result.get("location", {}) or {}
    s3_location = location.get("s3Location", {}) or {}
    return str(s3_location.get("uri", ""))


def _basename(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1] or uri
