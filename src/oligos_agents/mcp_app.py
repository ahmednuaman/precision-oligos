"""The remote MCP server: a Resource Server exposing the UI's capabilities as tools.

Per the MCP authorization spec (2025-06-18) this server only *consumes* access
tokens - it validates the bearer token on every request against the shared OAuth
store (see :mod:`auth.oauth_store`) and enforces the resource/audience binding.
The companion authorization server in :mod:`auth.oauth_as` issues those tokens.

Every tool delegates to :mod:`runs_service`, so an MCP client submits, polls, and
approves runs through exactly the same maker-checker and audit path as the SPA.
"""

from __future__ import annotations

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from oligos_agents import runs_service
from oligos_agents.auth.oauth_store import OAuthStore
from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import Role


class StoreTokenVerifier(TokenVerifier):
    """Validate opaque bearer tokens against the shared OAuth store."""

    def __init__(self, settings: Settings, store: OAuthStore) -> None:
        self._settings = settings
        self._store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        record = self._store.get_token(token)
        if record is None or record.kind != "access":
            return None
        # Audience binding (RFC 8707): the token must be for this resource.
        resource = self._settings.mcp_resource_url.rstrip("/")
        if record.resource and record.resource.rstrip("/") != resource:
            return None
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scope.split(),
            expires_at=int(record.expires_at.timestamp()),
            resource=record.resource,
            subject=record.sub,
            claims={
                "sub": record.sub,
                "email": record.email,
                "roles": [r.value for r in record.roles],
            },
        )


def _current_identity() -> tuple[str, list[Role]]:
    """Resolve the authenticated subject + roles from the validated access token."""
    token = get_access_token()
    if token is None:  # pragma: no cover - middleware guarantees a token
        raise ValueError("Not authenticated.")
    claims = token.claims or {}
    sub = token.subject or claims.get("sub")
    if not sub:
        raise ValueError("Token is missing a subject.")
    roles: list[Role] = []
    for name in claims.get("roles", []):
        try:
            roles.append(Role(name))
        except ValueError:
            continue
    return sub, roles


def build_mcp(settings: Settings, deps: AgentDeps) -> FastMCP:
    """Construct the FastMCP resource server with tools mirroring the review UI."""
    store = OAuthStore(settings, deps.clients)
    mcp = FastMCP(
        name="Precision Oligos",
        instructions=(
            "Submit oligonucleotide QC requests, poll run state, read cited "
            "conflict/re-synthesis reports, and approve or reject runs "
            "(maker-checker: you cannot approve your own submission)."
        ),
        stateless_http=True,
        json_response=True,
        token_verifier=StoreTokenVerifier(settings, store),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.oauth_issuer_url),
            resource_server_url=AnyHttpUrl(settings.mcp_resource_url),
            required_scopes=settings.mcp_scope_list,
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
    )

    @mcp.tool(description="Return the authenticated user's identity and roles.")
    async def whoami() -> dict:
        sub, roles = _current_identity()
        return {"sub": sub, "roles": [r.value for r in roles]}

    @mcp.tool(
        description=(
            "Submit an oligo QC / analysis request. Returns a run_id to poll with "
            "get_run. Long-running work happens asynchronously."
        )
    )
    async def submit_qc_request(query: str) -> dict:
        sub, _ = _current_identity()
        return runs_service.submit_run(deps, settings, query, sub)

    @mcp.tool(description="Fetch the full state of a run (status, report, draft, audit).")
    async def get_run(run_id: str) -> dict:
        try:
            run = runs_service.get_run(deps, run_id)
        except runs_service.RunNotFound as exc:
            raise ValueError(str(exc)) from exc
        return run.model_dump(mode="json")

    @mcp.tool(description="List the caller's recent runs (newest first).")
    async def list_my_runs() -> list[dict]:
        sub, _ = _current_identity()
        runs = runs_service.list_runs_for(deps, sub)
        return [
            {
                "run_id": r.run_id,
                "status": r.status.value,
                "intent": r.intent.value if r.intent else None,
                "query": r.query,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]

    @mcp.tool(
        description=(
            "Approve a run awaiting a decision. Enforces maker-checker: the "
            "submitter cannot approve their own run, and the caller must hold a "
            "sufficient role for the run's severity."
        )
    )
    async def approve_run(run_id: str, comment: str | None = None) -> dict:
        return _decide(deps, settings, run_id, approved=True, comment=comment)

    @mcp.tool(description="Reject a run awaiting a decision (maker-checker enforced).")
    async def reject_run(run_id: str, comment: str | None = None) -> dict:
        return _decide(deps, settings, run_id, approved=False, comment=comment)

    return mcp


def _decide(
    deps: AgentDeps,
    settings: Settings,
    run_id: str,
    *,
    approved: bool,
    comment: str | None,
) -> dict:
    sub, roles = _current_identity()
    try:
        return runs_service.decide_run(
            deps, settings, run_id, sub=sub, roles=roles, approved=approved, comment=comment
        )
    except runs_service.RunNotFound as exc:
        raise ValueError(str(exc)) from exc
    except runs_service.ApprovalDenied as exc:
        raise ValueError(str(exc)) from exc
