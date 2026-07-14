"""Tests for BFF auth helpers: PKCE, authorize URL, CSRF, claim mapping."""

from __future__ import annotations

import base64
import hashlib

import pytest

from oligos_agents.auth import bff, csrf
from oligos_agents.auth.jwt_verify import roles_from_claims
from oligos_agents.config import Settings
from oligos_agents.models import Role


def test_generate_pkce_challenge_matches_verifier():
    verifier, challenge = bff.generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.decode().rstrip("=")


def test_build_authorize_url_includes_saml_provider():
    settings = Settings(
        COGNITO_DOMAIN="https://acme.auth.eu-west-1.amazoncognito.com",
        COGNITO_CLIENT_ID="client123",
        COGNITO_SAML_PROVIDER_NAME="EntraSAML",
        PUBLIC_BASE_URL="https://app.example.com",
    )
    url = bff.build_authorize_url(settings, "state123", "challenge123")
    assert "identity_provider=EntraSAML" in url
    assert "code_challenge_method=S256" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fapi%2Fauth%2Fcallback" in url


def test_authorize_url_requires_domain():
    with pytest.raises(bff.AuthNotConfigured):
        bff.build_authorize_url(Settings(), "s", "c")


def test_csrf_double_submit():
    assert csrf.verify_csrf("token", "token") is True
    assert csrf.verify_csrf("token", "other") is False
    assert csrf.verify_csrf("token", None) is False


def test_login_state_round_trip():
    secret = "test-secret"
    signed = csrf.sign_login_state(secret, "state-x", "verifier-y")
    data = csrf.unsign_login_state(secret, signed)
    assert data == {"state": "state-x", "code_verifier": "verifier-y"}


def test_login_state_rejects_tampering():
    with pytest.raises(ValueError):
        csrf.unsign_login_state("secret", "not-a-valid-token")


def test_roles_from_claims_filters_unknown_groups():
    claims = {"cognito:groups": ["QCManager", "Random", "Director"]}
    assert roles_from_claims(claims) == [Role.QC_MANAGER, Role.DIRECTOR]
