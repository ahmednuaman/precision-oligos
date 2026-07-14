"""Cognito access-token verification against the pool's JWKS.

The access token is the authorisation token: we check the issuer, that it is an
access token (``token_use``), the ``client_id``, and expiry. JWKS keys are cached
by :class:`jwt.PyJWKClient`.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from oligos_agents.config import Settings
from oligos_agents.models import Role


class TokenInvalid(RuntimeError):
    pass


@lru_cache
def _jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def verify_access_token(settings: Settings, token: str) -> dict:
    """Verify and decode a Cognito access token; return its claims."""
    jwks_url = settings.cognito_jwks_url
    issuer = settings.cognito_issuer
    if not jwks_url or not issuer:
        raise TokenInvalid("Cognito is not configured; cannot verify tokens.")

    try:
        signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:  # noqa: TRY003
        raise TokenInvalid(str(exc)) from exc

    if claims.get("token_use") != "access":
        raise TokenInvalid("Token is not an access token.")
    if settings.cognito_client_id and claims.get("client_id") != settings.cognito_client_id:
        raise TokenInvalid("Token client_id does not match this application.")
    return claims


def roles_from_claims(claims: dict) -> list[Role]:
    """Map Cognito group claims (normalised from Entra App Roles) to roles."""
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    roles: list[Role] = []
    for group in groups:
        try:
            roles.append(Role(group))
        except ValueError:
            continue
    return roles
