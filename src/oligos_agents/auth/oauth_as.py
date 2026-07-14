"""A compact OAuth 2.1 authorization server for the MCP resource.

Implements the endpoints an MCP client needs to authenticate a user and obtain a
resource-bound access token, per the MCP authorization spec (2025-06-18):

* RFC 8414 Authorization Server Metadata  - ``/.well-known/oauth-authorization-server``
* RFC 9728 Protected Resource Metadata    - ``/.well-known/oauth-protected-resource``
* RFC 7591 Dynamic Client Registration    - ``POST /oauth/register``
* Authorization Code + PKCE (S256)        - ``GET /oauth/authorize`` -> ``POST /oauth/consent``
* RFC 8707 Resource Indicators (audience) - the ``resource`` parameter is bound onto tokens
* Token + refresh + revoke                - ``POST /oauth/token`` / ``POST /oauth/revoke``

User authentication is *brokered* to Cognito (which federates to Entra via SAML):
``/oauth/authorize`` redirects the browser to the Cognito Hosted UI, and the user
is returned to ``/oauth/callback``, where we render a consent screen and finally
hand an authorization code back to the MCP client's redirect URI.
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from oligos_agents.auth import bff, csrf
from oligos_agents.auth.jwt_verify import roles_from_claims, verify_access_token
from oligos_agents.auth.oauth_store import OAuthStore
from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.models import (
    AuthorizationCode,
    McpToken,
    OAuthClient,
    PendingAuthorization,
    Role,
)


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return csrf.constant_time_equals(expected, code_challenge)


def _error_redirect(redirect_uri: str, error: str, state: str | None) -> RedirectResponse:
    params = {"error": error}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


def _oauth_error(error: str, description: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=code)


def build_oauth_router(settings: Settings, deps: AgentDeps) -> APIRouter:
    router = APIRouter()
    store = OAuthStore(settings, deps.clients)

    # --- Discovery metadata ------------------------------------------------------------

    @router.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata() -> JSONResponse:
        issuer = settings.oauth_issuer_url
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/oauth/authorize",
                "token_endpoint": f"{issuer}/oauth/token",
                "registration_endpoint": f"{issuer}/oauth/register",
                "revocation_endpoint": f"{issuer}/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": settings.mcp_scope_list,
                "resource_indicators_supported": True,
                "authorization_response_iss_parameter_supported": True,
            }
        )

    async def _protected_resource_metadata() -> JSONResponse:
        return JSONResponse(
            {
                "resource": settings.mcp_resource_url,
                "authorization_servers": [settings.oauth_issuer_url],
                "scopes_supported": settings.mcp_scope_list,
                "bearer_methods_supported": ["header"],
            }
        )

    # Clients derive this path from the resource URL (…/mcp) per RFC 9728; we serve
    # both the suffixed and bare forms so discovery works either way.
    router.add_api_route(
        "/.well-known/oauth-protected-resource/mcp",
        _protected_resource_metadata,
        methods=["GET"],
    )
    router.add_api_route(
        "/.well-known/oauth-protected-resource",
        _protected_resource_metadata,
        methods=["GET"],
    )

    # --- Dynamic client registration (RFC 7591) ----------------------------------------

    @router.post("/oauth/register", status_code=201)
    async def register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _oauth_error("invalid_client_metadata", "Body must be JSON.")

        redirect_uris = body.get("redirect_uris") or []
        if not isinstance(redirect_uris, list) or not redirect_uris:
            return _oauth_error("invalid_redirect_uri", "redirect_uris is required.")

        client = OAuthClient(
            client_id=f"mcp-{secrets.token_urlsafe(16)}",
            client_name=body.get("client_name"),
            redirect_uris=[str(u) for u in redirect_uris],
            grant_types=body.get("grant_types") or ["authorization_code", "refresh_token"],
            response_types=body.get("response_types") or ["code"],
            scope=body.get("scope") or settings.mcp_scopes,
            token_endpoint_auth_method=body.get("token_endpoint_auth_method") or "none",
        )
        store.save_client(client)
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_id_issued_at": int(client.created_at.timestamp()),
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "grant_types": client.grant_types,
                "response_types": client.response_types,
                "scope": client.scope,
                "token_endpoint_auth_method": client.token_endpoint_auth_method,
            },
            status_code=201,
        )

    # --- Authorization endpoint --------------------------------------------------------

    @router.get("/oauth/authorize", response_model=None)
    async def authorize(request: Request) -> RedirectResponse | JSONResponse:
        q = request.query_params
        client_id = q.get("client_id", "")
        redirect_uri = q.get("redirect_uri", "")
        client = store.get_client(client_id)

        # Errors that cannot be safely redirected (untrusted/unknown redirect) are
        # returned directly; everything else goes back to the client per OAuth.
        if client is None:
            return _oauth_error("invalid_client", "Unknown client_id.")
        if redirect_uri not in client.redirect_uris:
            return _oauth_error("invalid_request", "redirect_uri not registered for client.")

        state = q.get("state")
        if q.get("response_type") != "code":
            return _error_redirect(redirect_uri, "unsupported_response_type", state)
        code_challenge = q.get("code_challenge")
        if not code_challenge or q.get("code_challenge_method", "S256") != "S256":
            return _error_redirect(redirect_uri, "invalid_request", state)

        resource = q.get("resource")
        if resource and resource.rstrip("/") != settings.mcp_resource_url.rstrip("/"):
            return _error_redirect(redirect_uri, "invalid_target", state)

        scope = q.get("scope") or settings.mcp_scopes
        upstream_verifier, upstream_challenge = bff.generate_pkce()
        pending = PendingAuthorization(
            key=secrets.token_urlsafe(32),
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            state=state,
            resource=settings.mcp_resource_url,
            upstream_code_verifier=upstream_verifier,
        )

        # Local development without Cognito: skip the upstream leg entirely.
        if settings.local_auth_bypass:
            pending.sub = "local-user"
            pending.email = "local@example.com"
            pending.roles = [
                Role(r.strip()) for r in settings.local_auth_roles.split(",") if r.strip()
            ]
            store.save_pending(pending)
            return RedirectResponse(f"/oauth/consent?key={pending.key}", status_code=302)

        store.save_pending(pending)
        cognito_url = bff.build_authorize_url(
            settings,
            state=pending.key,
            code_challenge=upstream_challenge,
            redirect_uri=settings.oauth_upstream_redirect_uri,
        )
        return RedirectResponse(cognito_url, status_code=302)

    # --- Brokered Cognito callback -----------------------------------------------------

    @router.get("/oauth/callback")
    async def callback(request: Request, code: str = "", state: str = "") -> HTMLResponse:
        pending = store.get_pending(state)
        if not code or pending is None:
            return HTMLResponse("<h1>Login failed</h1><p>Invalid or expired request.</p>", 400)

        tokens = bff.exchange_code(
            settings,
            deps.clients,
            code,
            pending.upstream_code_verifier,
            redirect_uri=settings.oauth_upstream_redirect_uri,
        )
        claims = verify_access_token(settings, tokens.access_token)
        pending.sub = claims["sub"]
        pending.email = claims.get("email")
        pending.roles = roles_from_claims(claims)
        store.save_pending(pending)
        return HTMLResponse(_consent_page(settings, pending))

    # --- Consent decision --------------------------------------------------------------

    @router.get("/oauth/consent")
    async def consent_page(key: str = "") -> HTMLResponse:
        pending = store.get_pending(key)
        if pending is None or pending.sub is None:
            return HTMLResponse("<h1>Consent expired</h1><p>Please restart sign-in.</p>", 400)
        return HTMLResponse(_consent_page(settings, pending))

    @router.post("/oauth/consent", response_model=None)
    async def consent(
        consent_token: str = Form(...),
        decision: str = Form(...),
    ) -> RedirectResponse | HTMLResponse:
        try:
            key = csrf.unsign_consent(settings.session_signing_secret, consent_token)
        except ValueError:
            return HTMLResponse("<h1>Invalid consent</h1>", 400)

        pending = store.get_pending(key)
        if pending is None or pending.sub is None:
            return HTMLResponse("<h1>Consent expired</h1><p>Please restart sign-in.</p>", 400)

        store.delete_pending(key)
        if decision != "approve":
            return _error_redirect(pending.redirect_uri, "access_denied", pending.state)

        auth_code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            client_id=pending.client_id,
            redirect_uri=pending.redirect_uri,
            code_challenge=pending.code_challenge,
            scope=pending.scope,
            resource=pending.resource,
            sub=pending.sub,
            email=pending.email,
            roles=pending.roles,
        )
        store.save_code(auth_code)
        params = {"code": auth_code.code}
        if pending.state:
            params["state"] = pending.state
        return RedirectResponse(f"{pending.redirect_uri}?{urlencode(params)}", status_code=302)

    # --- Token endpoint ----------------------------------------------------------------

    @router.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return _grant_authorization_code(settings, store, form)
        if grant_type == "refresh_token":
            return _grant_refresh_token(settings, store, form)
        return _oauth_error("unsupported_grant_type", f"Unsupported grant_type: {grant_type!r}")

    @router.post("/oauth/revoke")
    async def revoke(token: str = Form(...)) -> JSONResponse:
        # RFC 7009: always return 200, even for unknown tokens.
        store.delete_token(token)
        return JSONResponse({})

    return router


# --- Token grant helpers ---------------------------------------------------------------


def _issue_tokens(
    settings: Settings,
    store: OAuthStore,
    *,
    client_id: str,
    scope: str,
    resource: str | None,
    sub: str,
    email: str | None,
    roles: list[Role],
) -> JSONResponse:
    now = datetime.now(UTC)
    access = McpToken(
        token=secrets.token_urlsafe(32),
        kind="access",
        client_id=client_id,
        scope=scope,
        resource=resource,
        sub=sub,
        email=email,
        roles=roles,
        expires_at=now + timedelta(seconds=settings.mcp_access_token_ttl_seconds),
    )
    refresh = McpToken(
        token=secrets.token_urlsafe(32),
        kind="refresh",
        client_id=client_id,
        scope=scope,
        resource=resource,
        sub=sub,
        email=email,
        roles=roles,
        expires_at=now + timedelta(seconds=settings.mcp_refresh_token_ttl_seconds),
    )
    store.save_token(access)
    store.save_token(refresh)
    return JSONResponse(
        {
            "access_token": access.token,
            "token_type": "Bearer",
            "expires_in": settings.mcp_access_token_ttl_seconds,
            "refresh_token": refresh.token,
            "scope": scope,
        }
    )


def _grant_authorization_code(settings: Settings, store: OAuthStore, form) -> JSONResponse:
    code = form.get("code", "")
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier", "")
    resource = form.get("resource")

    auth_code = store.get_code(code)
    if auth_code is None:
        return _oauth_error("invalid_grant", "Authorization code is invalid or expired.")
    # Codes are single-use.
    store.delete_code(code)

    if auth_code.client_id != client_id:
        return _oauth_error("invalid_grant", "client_id mismatch.")
    if auth_code.redirect_uri != redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri mismatch.")
    if not code_verifier or not _verify_pkce(code_verifier, auth_code.code_challenge):
        return _oauth_error("invalid_grant", "PKCE verification failed.")
    if resource and auth_code.resource and resource.rstrip("/") != auth_code.resource.rstrip("/"):
        return _oauth_error("invalid_target", "resource does not match the granted audience.")

    return _issue_tokens(
        settings,
        store,
        client_id=auth_code.client_id,
        scope=auth_code.scope,
        resource=auth_code.resource,
        sub=auth_code.sub,
        email=auth_code.email,
        roles=auth_code.roles,
    )


def _grant_refresh_token(settings: Settings, store: OAuthStore, form) -> JSONResponse:
    refresh_token = form.get("refresh_token", "")
    client_id = form.get("client_id", "")
    record = store.get_token(refresh_token)
    if record is None or record.kind != "refresh":
        return _oauth_error("invalid_grant", "Refresh token is invalid or expired.")
    if client_id and record.client_id != client_id:
        return _oauth_error("invalid_grant", "client_id mismatch.")

    # Rotate: invalidate the presented refresh token.
    store.delete_token(refresh_token)
    return _issue_tokens(
        settings,
        store,
        client_id=record.client_id,
        scope=record.scope,
        resource=record.resource,
        sub=record.sub,
        email=record.email,
        roles=record.roles,
    )


# --- Consent screen --------------------------------------------------------------------


def _consent_page(settings: Settings, pending: PendingAuthorization) -> str:
    consent_token = csrf.sign_consent(settings.session_signing_secret, pending.key)
    client_label = html.escape(pending.client_id)
    roles = ", ".join(r.value for r in pending.roles) or "none"
    email = html.escape(pending.email or pending.sub or "unknown user")
    scopes = html.escape(pending.scope)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Authorise MCP access</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; display: grid; place-items: center;
         min-height: 100vh; background: #0f172a; color: #e2e8f0; }}
  .card {{ background: #1e293b; padding: 2rem 2.25rem; border-radius: 14px; max-width: 30rem;
          box-shadow: 0 10px 40px rgba(0,0,0,.4); }}
  h1 {{ font-size: 1.25rem; margin: 0 0 .75rem; }}
  dl {{ display: grid; grid-template-columns: auto 1fr; gap: .35rem 1rem; margin: 1rem 0 1.5rem;
        font-size: .9rem; }}
  dt {{ color: #94a3b8; }}
  code {{ background: #334155; padding: .1rem .35rem; border-radius: 4px; }}
  .actions {{ display: flex; gap: .75rem; }}
  button {{ flex: 1; padding: .65rem 1rem; border: 0; border-radius: 8px; font-weight: 600;
           cursor: pointer; }}
  .approve {{ background: #22c55e; color: #06210f; }}
  .deny {{ background: #334155; color: #e2e8f0; }}
</style>
</head>
<body>
  <form class="card" method="post" action="/oauth/consent">
    <h1>Authorise MCP access</h1>
    <p>An MCP client is requesting access to Precision Oligos on your behalf.</p>
    <dl>
      <dt>Client</dt><dd><code>{client_label}</code></dd>
      <dt>Signed in as</dt><dd>{email}</dd>
      <dt>Your roles</dt><dd>{roles}</dd>
      <dt>Scopes</dt><dd><code>{scopes}</code></dd>
    </dl>
    <input type="hidden" name="consent_token" value="{consent_token}" />
    <div class="actions">
      <button class="deny" type="submit" name="decision" value="deny">Deny</button>
      <button class="approve" type="submit" name="decision" value="approve">Approve</button>
    </div>
  </form>
</body>
</html>"""
