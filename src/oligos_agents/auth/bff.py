"""Backend-for-frontend OAuth (Authorization Code + PKCE) against Cognito.

The FastAPI control-plane owns the entire OAuth exchange; tokens are held
server-side (see :mod:`session`) and never exposed to the browser. Cognito
federates to Entra via SAML, so the Hosted UI is only a redirect hop.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from oligos_agents.config import Settings
from oligos_agents.deps import AwsClients
from oligos_agents.models import OidcTokens


class AuthNotConfigured(RuntimeError):
    pass


def generate_pkce() -> tuple[str, str]:
    """Return an (code_verifier, code_challenge) PKCE pair (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(24)


def _require_domain(settings: Settings) -> str:
    if not settings.cognito_domain or not settings.cognito_client_id:
        raise AuthNotConfigured("Cognito domain/client id are not configured.")
    return settings.cognito_domain.rstrip("/")


def build_authorize_url(
    settings: Settings,
    state: str,
    code_challenge: str,
    redirect_uri: str | None = None,
) -> str:
    domain = _require_domain(settings)
    params = {
        "response_type": "code",
        "client_id": settings.cognito_client_id,
        "redirect_uri": redirect_uri or settings.oidc_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if settings.cognito_saml_provider_name:
        params["identity_provider"] = settings.cognito_saml_provider_name
    return f"{domain}/oauth2/authorize?{urlencode(params)}"


def build_logout_url(settings: Settings) -> str:
    domain = _require_domain(settings)
    params = {
        "client_id": settings.cognito_client_id,
        "logout_uri": settings.oidc_logout_redirect_uri,
    }
    return f"{domain}/logout?{urlencode(params)}"


def _client_secret(settings: Settings, clients: AwsClients) -> str | None:
    if not settings.cognito_client_secret_arn:
        return None
    secret = clients.secretsmanager.get_secret_value(SecretId=settings.cognito_client_secret_arn)
    return secret.get("SecretString")


def _token_request(settings: Settings, clients: AwsClients, data: dict) -> OidcTokens:
    domain = _require_domain(settings)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth: tuple[str, str] | None = None
    secret = _client_secret(settings, clients)
    if secret:
        auth = (settings.cognito_client_id, secret)
    else:
        data = {**data, "client_id": settings.cognito_client_id}

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(f"{domain}/oauth2/token", data=data, headers=headers, auth=auth)
    resp.raise_for_status()
    body = resp.json()
    expires_in = int(body.get("expires_in", 3600))
    return OidcTokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        id_token=body.get("id_token"),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


def exchange_code(
    settings: Settings,
    clients: AwsClients,
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
) -> OidcTokens:
    return _token_request(
        settings,
        clients,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or settings.oidc_redirect_uri,
            "code_verifier": code_verifier,
        },
    )


def refresh_tokens(settings: Settings, clients: AwsClients, refresh_token: str) -> OidcTokens:
    tokens = _token_request(
        settings,
        clients,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    # Cognito does not re-issue the refresh token on refresh; carry it forward.
    if tokens.refresh_token is None:
        tokens.refresh_token = refresh_token
    return tokens
