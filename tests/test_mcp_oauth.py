"""End-to-end tests for the MCP OAuth 2.1 authorization server + resource server.

Exercises the full brokered flow in local-bypass mode (no Cognito): dynamic
client registration -> authorize -> consent -> token -> bearer-protected MCP
endpoint. Also unit-tests the resource-server token verifier's audience binding.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from starlette.routing import Mount
from starlette.testclient import TestClient

from oligos_agents.auth import bff
from oligos_agents.auth.oauth_as import build_oauth_router
from oligos_agents.auth.oauth_store import OAuthStore
from oligos_agents.config import Settings
from oligos_agents.deps import AgentDeps
from oligos_agents.mcp_app import StoreTokenVerifier, build_mcp
from oligos_agents.models import McpToken, Role

_CONSENT_TOKEN_RE = re.compile(r'name="consent_token" value="([^"]+)"')


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ENVID="local-oligos-dev",
        LOCAL_AUTH_BYPASS=True,
        LOCAL_AUTH_ROLES="QCManager",
        PUBLIC_BASE_URL="http://testserver",
        SESSION_SIGNING_SECRET="test-secret",
    )


def _build_app(settings: Settings) -> tuple[FastAPI, AgentDeps]:
    deps = AgentDeps(settings=settings)
    mcp = build_mcp(settings, deps)
    mcp_app = mcp.streamable_http_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_oauth_router(settings, deps))
    app.router.routes.append(Mount("", app=mcp_app))
    return app, deps


def _complete_oauth_flow(client: TestClient) -> tuple[str, str]:
    """Run register -> authorize -> consent -> token; return (access, refresh)."""
    reg = client.post(
        "/oauth/register",
        json={"client_name": "Test MCP Client", "redirect_uris": ["http://localhost:9999/cb"]},
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    verifier, challenge = bff.generate_pkce()
    authz = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://localhost:9999/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "oligos:use",
            "state": "xyz",
            "resource": "http://testserver/mcp",
        },
        follow_redirects=False,
    )
    assert authz.status_code == 302
    consent_key = authz.headers["location"].split("key=")[1]

    page = client.get("/oauth/consent", params={"key": consent_key})
    assert page.status_code == 200
    consent_token = _CONSENT_TOKEN_RE.search(page.text).group(1)

    decided = client.post(
        "/oauth/consent",
        data={"consent_token": consent_token, "decision": "approve"},
        follow_redirects=False,
    )
    assert decided.status_code == 302
    location = decided.headers["location"]
    assert location.startswith("http://localhost:9999/cb?")
    assert "state=xyz" in location
    code = location.split("code=")[1].split("&")[0]

    token_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "http://localhost:9999/cb",
            "code_verifier": verifier,
            "resource": "http://testserver/mcp",
        },
    )
    assert token_resp.status_code == 200
    body = token_resp.json()
    assert body["token_type"] == "Bearer"
    return body["access_token"], body["refresh_token"]


def test_discovery_metadata_advertises_as_and_resource() -> None:
    app, _ = _build_app(_settings())
    client = TestClient(app)

    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["issuer"] == "http://testserver"
    assert asm["registration_endpoint"] == "http://testserver/oauth/register"
    assert asm["code_challenge_methods_supported"] == ["S256"]

    prm = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == "http://testserver/mcp"
    assert prm["authorization_servers"] == ["http://testserver"]


def test_full_authorization_code_flow_issues_usable_token() -> None:
    app, _ = _build_app(_settings())
    with TestClient(app) as client:
        access, refresh = _complete_oauth_flow(client)
        assert access and refresh

        # The bearer token now passes the resource server's auth layer.
        unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert unauth.status_code == 401

        authed = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert authed.status_code != 401


def test_refresh_token_rotates_and_issues_new_access() -> None:
    app, _ = _build_app(_settings())
    with TestClient(app) as client:
        _, refresh = _complete_oauth_flow(client)
        resp = client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh},
        )
        assert resp.status_code == 200
        assert resp.json()["access_token"]

        # The old refresh token has been rotated out (single use).
        reuse = client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh},
        )
        assert reuse.status_code == 400


def test_token_endpoint_rejects_bad_pkce() -> None:
    app, _ = _build_app(_settings())
    with TestClient(app) as client:
        reg = client.post(
            "/oauth/register",
            json={"redirect_uris": ["http://localhost:9999/cb"]},
        )
        client_id = reg.json()["client_id"]
        _, challenge = bff.generate_pkce()
        authz = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost:9999/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        consent_key = authz.headers["location"].split("key=")[1]
        page = client.get("/oauth/consent", params={"key": consent_key})
        consent_token = _CONSENT_TOKEN_RE.search(page.text).group(1)
        decided = client.post(
            "/oauth/consent",
            data={"consent_token": consent_token, "decision": "approve"},
            follow_redirects=False,
        )
        code = decided.headers["location"].split("code=")[1].split("&")[0]

        resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": "http://localhost:9999/cb",
                "code_verifier": "the-wrong-verifier",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"


def test_authorize_rejects_unregistered_redirect() -> None:
    app, _ = _build_app(_settings())
    client = TestClient(app)
    reg = client.post("/oauth/register", json={"redirect_uris": ["http://localhost:9999/cb"]})
    client_id = reg.json()["client_id"]
    resp = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://evil.example/cb",
            "code_challenge": "abc",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_token_verifier_enforces_audience_binding() -> None:
    settings = _settings()
    deps = AgentDeps(settings=settings)
    store = OAuthStore(settings, deps.clients)
    verifier = StoreTokenVerifier(settings, store)

    good = McpToken(
        token="good-token",
        kind="access",
        client_id="c1",
        scope="oligos:use",
        resource="http://testserver/mcp",
        sub="user-1",
        roles=[Role.QC_MANAGER],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    store.save_token(good)
    result = await verifier.verify_token("good-token")
    assert result is not None
    assert result.subject == "user-1"
    assert result.claims["roles"] == ["QCManager"]

    wrong_aud = good.model_copy(update={"token": "wrong-aud", "resource": "http://other/mcp"})
    store.save_token(wrong_aud)
    assert await verifier.verify_token("wrong-aud") is None

    refresh = good.model_copy(update={"token": "a-refresh", "kind": "refresh"})
    store.save_token(refresh)
    assert await verifier.verify_token("a-refresh") is None
