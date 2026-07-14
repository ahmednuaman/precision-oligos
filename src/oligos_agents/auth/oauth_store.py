"""Storage for the MCP OAuth 2.1 authorization server.

Holds dynamically-registered clients, short-lived pending authorizations and
authorization codes, and issued access/refresh tokens. Backed by a single
DynamoDB table (partition key ``pk = "<kind>#<id>"`` with a TTL attribute for
auto-expiry) or an in-memory dict for local development.

The resource server and authorization server run in the same process and share
this store, so access tokens can be opaque and validated by lookup (revocable,
no shared signing key to manage).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from oligos_agents.config import Settings
from oligos_agents.deps import AwsClients
from oligos_agents.models import (
    AuthorizationCode,
    McpToken,
    OAuthClient,
    PendingAuthorization,
)

# Process-local fallback store: {pk: (json_payload, expires_epoch|None)}.
_MEMORY: dict[str, tuple[str, int | None]] = {}


class OAuthStore:
    def __init__(self, settings: Settings, clients: AwsClients) -> None:
        self._settings = settings
        self._clients = clients

    @property
    def _table_name(self) -> str | None:
        return self._settings.mcp_oauth_table

    # --- Low-level helpers -------------------------------------------------------------

    def _put(self, kind: str, key: str, model: BaseModel, ttl_epoch: int | None) -> None:
        pk = f"{kind}#{key}"
        payload = model.model_dump_json()
        if not self._table_name:
            _MEMORY[pk] = (payload, ttl_epoch)
            return
        item: dict = {"pk": pk, "state": payload}
        if ttl_epoch is not None:
            item["ttl"] = ttl_epoch
        self._clients.dynamodb.Table(self._table_name).put_item(Item=item)

    def _get(self, kind: str, key: str) -> str | None:
        pk = f"{kind}#{key}"
        if not self._table_name:
            entry = _MEMORY.get(pk)
            if entry is None:
                return None
            payload, ttl_epoch = entry
            if ttl_epoch is not None and ttl_epoch <= int(datetime.now(UTC).timestamp()):
                _MEMORY.pop(pk, None)
                return None
            return payload
        resp = self._clients.dynamodb.Table(self._table_name).get_item(Key={"pk": pk})
        item = resp.get("Item")
        if not item or "state" not in item:
            return None
        # DynamoDB TTL deletion is best-effort/eventual; enforce it on read too.
        ttl = item.get("ttl")
        if ttl is not None and int(ttl) <= int(datetime.now(UTC).timestamp()):
            return None
        return item["state"]

    def _delete(self, kind: str, key: str) -> None:
        pk = f"{kind}#{key}"
        if not self._table_name:
            _MEMORY.pop(pk, None)
            return
        self._clients.dynamodb.Table(self._table_name).delete_item(Key={"pk": pk})

    # --- Clients (RFC 7591) ------------------------------------------------------------

    def save_client(self, client: OAuthClient) -> None:
        self._put("client", client.client_id, client, ttl_epoch=None)

    def get_client(self, client_id: str) -> OAuthClient | None:
        payload = self._get("client", client_id)
        return OAuthClient.model_validate_json(payload) if payload else None

    # --- Pending authorizations --------------------------------------------------------

    def save_pending(self, pending: PendingAuthorization) -> None:
        ttl = int(pending.created_at.timestamp()) + self._settings.mcp_code_ttl_seconds
        self._put("pending", pending.key, pending, ttl_epoch=ttl)

    def get_pending(self, key: str) -> PendingAuthorization | None:
        payload = self._get("pending", key)
        return PendingAuthorization.model_validate_json(payload) if payload else None

    def delete_pending(self, key: str) -> None:
        self._delete("pending", key)

    # --- Authorization codes -----------------------------------------------------------

    def save_code(self, code: AuthorizationCode) -> None:
        ttl = int(code.created_at.timestamp()) + self._settings.mcp_code_ttl_seconds
        self._put("code", code.code, code, ttl_epoch=ttl)

    def get_code(self, code: str) -> AuthorizationCode | None:
        payload = self._get("code", code)
        return AuthorizationCode.model_validate_json(payload) if payload else None

    def delete_code(self, code: str) -> None:
        self._delete("code", code)

    # --- Tokens ------------------------------------------------------------------------

    def save_token(self, token: McpToken) -> None:
        self._put("token", token.token, token, ttl_epoch=int(token.expires_at.timestamp()))

    def get_token(self, token: str) -> McpToken | None:
        payload = self._get("token", token)
        if not payload:
            return None
        model = McpToken.model_validate_json(payload)
        if model.expires_at <= datetime.now(UTC):
            return None
        return model

    def delete_token(self, token: str) -> None:
        self._delete("token", token)
