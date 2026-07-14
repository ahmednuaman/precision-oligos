"""FastAPI control-plane and backend-for-frontend.

Thin control-plane: it authenticates via Cognito (BFF pattern), starts pipeline
executions (Step Functions in AWS, in-process for local dev), serves run state
for polling, and relays maker-checker approvals. No long-running LLM work runs
synchronously behind the request.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.routing import Mount

from oligos_agents import runs_service
from oligos_agents.auth import bff, csrf
from oligos_agents.auth.jwt_verify import TokenInvalid, roles_from_claims, verify_access_token
from oligos_agents.auth.oauth_as import build_oauth_router
from oligos_agents.auth.session import SessionStore
from oligos_agents.config import get_settings
from oligos_agents.deps import AgentDeps
from oligos_agents.mcp_app import build_mcp
from oligos_agents.models import OidcTokens, Role, RunState, Session
from oligos_agents.tracing import configure_tracing

_deps = AgentDeps()
_settings = get_settings()
_session_store = SessionStore(_settings, _deps.clients)

# Capture pydantic-ai OTel spans (Logfire + S3 data lake) if configured.
configure_tracing(_settings)

# The remote MCP server (Resource Server) is mounted alongside the control-plane
# when enabled; its OAuth authorization server is a set of routes on this app.
_mcp = build_mcp(_settings, _deps) if _settings.mcp_enabled else None
_mcp_app = _mcp.streamable_http_app() if _mcp is not None else None


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # The MCP StreamableHTTP session manager needs its task group running.
    if _mcp is not None:
        async with _mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="Precision Oligos QC control-plane", version="0.1.0", lifespan=_lifespan)

if _mcp_app is not None:
    # Authorization server metadata + endpoints (DCR, authorize, token, consent).
    app.include_router(build_oauth_router(_settings, _deps))

_LOGIN_STATE_COOKIE = "oligos_login_state"


# --- Request/response models -----------------------------------------------------------


class SubmitRequest(BaseModel):
    query: str


class DecisionRequest(BaseModel):
    comment: str | None = None


# --- Session helpers -------------------------------------------------------------------


def _local_session() -> Session:
    roles = [Role(r.strip()) for r in _settings.local_auth_roles.split(",") if r.strip()]
    now = datetime.now(UTC)
    return Session(
        session_id="local",
        sub="local-user",
        email="local@example.com",
        roles=roles,
        tokens=OidcTokens(access_token="local", expires_at=now + timedelta(hours=8)),
        expires_at=now + timedelta(hours=8),
        csrf_token="local-csrf",
    )


async def current_session(request: Request) -> Session:
    """Resolve the authenticated session or raise 401."""
    if _settings.local_auth_bypass:
        return _local_session()

    session_id = request.cookies.get(_settings.session_cookie_name)
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session.")
    session = _session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")

    # Refresh the access token server-side if it is about to expire.
    if session.tokens.expires_at <= datetime.now(UTC) + timedelta(seconds=60):
        if not session.tokens.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Session requires re-login."
            )
        session.tokens = bff.refresh_tokens(
            _settings, _deps.clients, session.tokens.refresh_token
        )
        _session_store.save(session)

    try:
        verify_access_token(_settings, session.tokens.access_token)
    except TokenInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
        ) from exc
    return session


def require_csrf(session: Session, x_csrf_token: str | None) -> None:
    if _settings.local_auth_bypass:
        return
    if not csrf.verify_csrf(session.csrf_token, x_csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed.")


# --- Health ----------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "envid": _settings.envid}


# --- Auth (BFF) ------------------------------------------------------------------------


@app.get("/api/auth/login")
async def login() -> Response:
    state = bff.new_state()
    verifier, challenge = bff.generate_pkce()
    url = bff.build_authorize_url(_settings, state, challenge)
    response = RedirectResponse(url)
    response.set_cookie(
        _LOGIN_STATE_COOKIE,
        csrf.sign_login_state(_settings.session_signing_secret, state, verifier),
        max_age=600,
        httponly=True,
        secure=_settings.session_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
    return response


@app.get("/api/auth/callback")
async def callback(request: Request, code: str = "", state: str = "") -> Response:
    raw_state = request.cookies.get(_LOGIN_STATE_COOKIE)
    if not code or not raw_state:
        raise HTTPException(status_code=400, detail="Missing authorization code or state.")
    try:
        signed = csrf.unsign_login_state(_settings.session_signing_secret, raw_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not csrf.constant_time_equals(signed["state"], state):
        raise HTTPException(status_code=400, detail="State mismatch.")

    tokens = bff.exchange_code(_settings, _deps.clients, code, signed["code_verifier"])
    claims = verify_access_token(_settings, tokens.access_token)
    session = _session_store.create(
        sub=claims["sub"],
        email=claims.get("email"),
        roles=roles_from_claims(claims),
        tokens=tokens,
    )

    response = RedirectResponse(_settings.oidc_logout_redirect_uri)
    response.set_cookie(
        _settings.session_cookie_name,
        session.session_id,
        max_age=_settings.session_ttl_seconds,
        httponly=True,
        secure=_settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(_LOGIN_STATE_COOKIE, path="/api/auth")
    return response


@app.post("/api/auth/logout")
async def logout(request: Request) -> Response:
    session_id = request.cookies.get(_settings.session_cookie_name)
    if session_id:
        _session_store.delete(session_id)
    body = {"logout_url": None}
    try:
        body["logout_url"] = bff.build_logout_url(_settings)
    except bff.AuthNotConfigured:
        pass
    response = JSONResponse(body)
    response.delete_cookie(_settings.session_cookie_name, path="/")
    return response


@app.get("/api/me")
async def me(session: Session = Depends(current_session)) -> dict:
    return {
        "sub": session.sub,
        "email": session.email,
        "roles": [r.value for r in session.roles],
        "csrf_token": session.csrf_token,
    }


# --- Runs ------------------------------------------------------------------------------


@app.post("/api/requests", status_code=status.HTTP_202_ACCEPTED)
async def submit(
    body: SubmitRequest,
    session: Session = Depends(current_session),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    require_csrf(session, x_csrf_token)
    return runs_service.submit_run(_deps, _settings, body.query, session.sub)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, session: Session = Depends(current_session)) -> RunState:
    try:
        return runs_service.get_run(_deps, run_id)
    except runs_service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/approve")
async def approve(
    run_id: str,
    body: DecisionRequest,
    session: Session = Depends(current_session),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    require_csrf(session, x_csrf_token)
    return _decide(run_id, session, approved=True, comment=body.comment)


@app.post("/api/runs/{run_id}/reject")
async def reject(
    run_id: str,
    body: DecisionRequest,
    session: Session = Depends(current_session),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    require_csrf(session, x_csrf_token)
    return _decide(run_id, session, approved=False, comment=body.comment)


def _decide(run_id: str, session: Session, approved: bool, comment: str | None) -> dict:
    try:
        return runs_service.decide_run(
            _deps,
            _settings,
            run_id,
            sub=session.sub,
            roles=session.roles,
            approved=approved,
            comment=comment,
        )
    except runs_service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except runs_service.ApprovalDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


# Mount the MCP resource server last so explicit control-plane routes win.
if _mcp_app is not None:
    app.router.routes.append(Mount("", app=_mcp_app))
