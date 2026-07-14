"""CSRF protection and short-lived signed state cookies.

State-changing ``/api`` requests must present the session's CSRF token in a
custom header (double-submit). SameSite=strict on the session cookie is the
first line of defence; this is defence in depth. The login flow also stores the
OAuth ``state`` and PKCE ``code_verifier`` in a short-lived signed cookie.
"""

from __future__ import annotations

import hmac

from itsdangerous import BadSignature, URLSafeTimedSerializer

_LOGIN_STATE_SALT = "oligos-login-state"
_LOGIN_STATE_MAX_AGE = 600  # 10 minutes
_CONSENT_SALT = "oligos-mcp-consent"
_CONSENT_MAX_AGE = 600  # 10 minutes


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def verify_csrf(session_csrf: str, header_value: str | None) -> bool:
    if not header_value:
        return False
    return constant_time_equals(session_csrf, header_value)


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_LOGIN_STATE_SALT)


def sign_login_state(secret: str, state: str, code_verifier: str) -> str:
    return _serializer(secret).dumps({"state": state, "code_verifier": code_verifier})


def unsign_login_state(secret: str, token: str) -> dict:
    try:
        return _serializer(secret).loads(token, max_age=_LOGIN_STATE_MAX_AGE)
    except BadSignature as exc:  # noqa: TRY003
        raise ValueError("Invalid or expired login state.") from exc


def _consent_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_CONSENT_SALT)


def sign_consent(secret: str, pending_key: str) -> str:
    """Sign a short-lived token proving the consent form was served by us."""
    return _consent_serializer(secret).dumps({"key": pending_key})


def unsign_consent(secret: str, token: str) -> str:
    try:
        data = _consent_serializer(secret).loads(token, max_age=_CONSENT_MAX_AGE)
    except BadSignature as exc:  # noqa: TRY003
        raise ValueError("Invalid or expired consent token.") from exc
    return data["key"]
