"""Runtime configuration loaded from the environment.

All deployment- and customer-specific values are configuration only; there are
no hard-coded organisation names or account details anywhere in the codebase.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment identity ---
    envid: str = Field(default="local-oligos-dev", validation_alias="ENVID")
    aws_region: str = Field(default="eu-west-1", validation_alias="AWS_REGION")
    logger_level: str = Field(default="INFO", validation_alias="LOGGER_LEVEL")

    # --- Models (region-pinned inference profiles) ---
    router_model: str = Field(
        default="bedrock:eu.anthropic.claude-3-5-haiku-20241022-v1:0",
        validation_alias="ROUTER_MODEL",
    )
    extraction_model: str = Field(
        default="bedrock:eu.anthropic.claude-3-5-haiku-20241022-v1:0",
        validation_alias="EXTRACTION_MODEL",
    )
    drafting_model: str = Field(
        default="bedrock:eu.anthropic.claude-sonnet-5",
        validation_alias="DRAFTING_MODEL",
    )
    bedrock_guardrail_id: str | None = Field(
        default=None, validation_alias="BEDROCK_GUARDRAIL_ID"
    )
    bedrock_guardrail_version: str | None = Field(
        default=None, validation_alias="BEDROCK_GUARDRAIL_VERSION"
    )

    # --- Knowledge base (consumed, not provisioned) ---
    knowledge_base_id: str | None = Field(default=None, validation_alias="KNOWLEDGE_BASE_ID")
    knowledge_base_region: str = Field(
        default="eu-west-1", validation_alias="KNOWLEDGE_BASE_REGION"
    )
    kb_assume_role_arn: str | None = Field(default=None, validation_alias="KB_ASSUME_ROLE_ARN")
    kb_assume_role_external_id: str | None = Field(
        default=None, validation_alias="KB_ASSUME_ROLE_EXTERNAL_ID"
    )

    # --- Storage ---
    runs_table: str | None = Field(default=None, validation_alias="RUNS_TABLE")
    audit_table: str | None = Field(default=None, validation_alias="AUDIT_TABLE")
    sessions_table: str | None = Field(default=None, validation_alias="SESSIONS_TABLE")
    audit_worm_bucket: str | None = Field(default=None, validation_alias="AUDIT_WORM_BUCKET")

    # --- Orchestration ---
    state_machine_arn: str | None = Field(default=None, validation_alias="STATE_MACHINE_ARN")

    # --- Tracing / observability data lake ---
    service_version: str = Field(default="0.1.0", validation_alias="SERVICE_VERSION")
    # Kinesis Firehose delivery stream that lands OTel spans in the S3 data lake.
    # When unset, no spans are exported to the lake.
    otel_firehose_stream: str | None = Field(
        default=None, validation_alias="OTEL_FIREHOSE_STREAM"
    )
    # Optional Logfire ingestion token (read from Secrets Manager when an ARN is
    # supplied). When present, spans are also sent to Logfire's live platform.
    logfire_token: str | None = Field(default=None, validation_alias="LOGFIRE_TOKEN")
    logfire_token_secret_arn: str | None = Field(
        default=None, validation_alias="LOGFIRE_TOKEN_SECRET_ARN"
    )
    # Capture prompt/response content in spans. Off by default: retrieved
    # documents may contain sensitive data that must not leak into the lake.
    otel_capture_content: bool = Field(default=False, validation_alias="OTEL_CAPTURE_CONTENT")

    # --- Notifications ---
    notifications_topic_arn: str | None = Field(
        default=None, validation_alias="NOTIFICATIONS_TOPIC_ARN"
    )

    # --- LIMS ---
    lims_base_url: str | None = Field(default=None, validation_alias="LIMS_BASE_URL")
    lims_api_key_secret_arn: str | None = Field(
        default=None, validation_alias="LIMS_API_KEY_SECRET_ARN"
    )
    lims_timeout_seconds: float = Field(default=15.0, validation_alias="LIMS_TIMEOUT_SECONDS")

    # --- Authentication (Cognito + BFF) ---
    cognito_user_pool_id: str | None = Field(
        default=None, validation_alias="COGNITO_USER_POOL_ID"
    )
    cognito_client_id: str | None = Field(default=None, validation_alias="COGNITO_CLIENT_ID")
    cognito_client_secret_arn: str | None = Field(
        default=None, validation_alias="COGNITO_CLIENT_SECRET_ARN"
    )
    cognito_domain: str | None = Field(default=None, validation_alias="COGNITO_DOMAIN")
    cognito_region: str = Field(default="eu-west-1", validation_alias="COGNITO_REGION")
    # Name of the Cognito SAML identity provider; when set, login goes straight
    # to Entra (SP-initiated) instead of showing the Cognito provider chooser.
    cognito_saml_provider_name: str | None = Field(
        default=None, validation_alias="COGNITO_SAML_PROVIDER_NAME"
    )
    # Local-development roles granted to the bypass user (comma-separated).
    local_auth_roles: str = Field(default="QCManager", validation_alias="LOCAL_AUTH_ROLES")
    public_base_url: str = Field(
        default="http://localhost:8000", validation_alias="PUBLIC_BASE_URL"
    )
    session_cookie_name: str = Field(
        default="oligos_session", validation_alias="SESSION_COOKIE_NAME"
    )
    session_cookie_secure: bool = Field(default=True, validation_alias="SESSION_COOKIE_SECURE")
    session_ttl_seconds: int = Field(default=28800, validation_alias="SESSION_TTL_SECONDS")
    session_signing_secret: str = Field(
        default="change-me-in-production", validation_alias="SESSION_SIGNING_SECRET"
    )
    local_auth_bypass: bool = Field(default=False, validation_alias="LOCAL_AUTH_BYPASS")

    # --- MCP server (remote, OAuth-protected) ---
    mcp_enabled: bool = Field(default=True, validation_alias="MCP_ENABLED")
    # DynamoDB table backing the OAuth authorization server (clients, codes,
    # tokens, pending authorizations). In-memory fallback when unset.
    mcp_oauth_table: str | None = Field(default=None, validation_alias="MCP_OAUTH_TABLE")
    # Space-separated scopes advertised/required for the MCP resource.
    mcp_scopes: str = Field(default="oligos:use", validation_alias="MCP_SCOPES")
    mcp_access_token_ttl_seconds: int = Field(
        default=3600, validation_alias="MCP_ACCESS_TOKEN_TTL_SECONDS"
    )
    mcp_refresh_token_ttl_seconds: int = Field(
        default=1209600, validation_alias="MCP_REFRESH_TOKEN_TTL_SECONDS"
    )
    mcp_code_ttl_seconds: int = Field(default=300, validation_alias="MCP_CODE_TTL_SECONDS")

    # --- Derived helpers ---
    @property
    def mcp_resource_url(self) -> str:
        """Canonical resource identifier for the MCP endpoint (RFC 8707 audience)."""
        return f"{self.public_base_url.rstrip('/')}/mcp"

    @property
    def oauth_issuer_url(self) -> str:
        """Issuer / authorization-server base URL (this application)."""
        return self.public_base_url.rstrip("/")

    @property
    def oauth_upstream_redirect_uri(self) -> str:
        """Where Cognito returns the user during the brokered MCP login."""
        return f"{self.public_base_url.rstrip('/')}/oauth/callback"

    @property
    def mcp_scope_list(self) -> list[str]:
        return [s for s in self.mcp_scopes.split() if s]
    @property
    def tracing_active(self) -> bool:
        """True when at least one span sink (data lake or Logfire) is configured."""
        return bool(
            self.otel_firehose_stream or self.logfire_token or self.logfire_token_secret_arn
        )

    @property
    def environment(self) -> str:
        """The env segment of the envid (sbx/dev/stg/prd)."""
        return self.envid.rsplit("-", 1)[-1] if "-" in self.envid else self.envid

    @property
    def cognito_issuer(self) -> str | None:
        if not self.cognito_user_pool_id:
            return None
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
            f"{self.cognito_user_pool_id}"
        )

    @property
    def cognito_jwks_url(self) -> str | None:
        issuer = self.cognito_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @property
    def oidc_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/auth/callback"

    @property
    def oidc_logout_redirect_uri(self) -> str:
        return self.public_base_url.rstrip("/") + "/"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
