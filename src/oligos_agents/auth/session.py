"""Server-side session store (BFF).

Sessions hold the OIDC tokens on the server so they never reach the browser; the
client only carries an opaque, signed session-id cookie. Backed by a DynamoDB
table with a TTL attribute for auto-expiry, or an in-memory dict for local dev.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from oligos_agents.config import Settings
from oligos_agents.deps import AwsClients
from oligos_agents.models import OidcTokens, Role, Session

_MEMORY: dict[str, str] = {}


class SessionStore:
    def __init__(self, settings: Settings, clients: AwsClients) -> None:
        self._settings = settings
        self._clients = clients

    @property
    def _table_name(self) -> str | None:
        return self._settings.sessions_table

    def create(
        self,
        sub: str,
        email: str | None,
        roles: list[Role],
        tokens: OidcTokens,
    ) -> Session:
        now = datetime.now(UTC)
        session = Session(
            session_id=secrets.token_urlsafe(32),
            sub=sub,
            email=email,
            roles=roles,
            tokens=tokens,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.session_ttl_seconds),
            csrf_token=secrets.token_urlsafe(32),
        )
        self._put(session)
        return session

    def get(self, session_id: str) -> Session | None:
        payload = self._read(session_id)
        if payload is None:
            return None
        session = Session.model_validate_json(payload)
        if session.expires_at <= datetime.now(UTC):
            self.delete(session_id)
            return None
        return session

    def save(self, session: Session) -> None:
        """Persist an updated session (e.g. after a token refresh)."""
        self._put(session)

    def delete(self, session_id: str) -> None:
        if not self._table_name:
            _MEMORY.pop(session_id, None)
            return
        self._clients.dynamodb.Table(self._table_name).delete_item(
            Key={"session_id": session_id}
        )

    def _put(self, session: Session) -> None:
        payload = session.model_dump_json()
        if not self._table_name:
            _MEMORY[session.session_id] = payload
            return
        self._clients.dynamodb.Table(self._table_name).put_item(
            Item={
                "session_id": session.session_id,
                "sub": session.sub,
                # DynamoDB TTL expects epoch seconds.
                "ttl": int(session.expires_at.timestamp()),
                "state": payload,
            }
        )

    def _read(self, session_id: str) -> str | None:
        if not self._table_name:
            return _MEMORY.get(session_id)
        resp = self._clients.dynamodb.Table(self._table_name).get_item(
            Key={"session_id": session_id}
        )
        item = resp.get("Item")
        return item["state"] if item and "state" in item else None
