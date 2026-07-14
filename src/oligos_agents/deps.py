"""Shared dependencies: lazily-constructed boto3 clients and agent context.

``AgentDeps`` is passed to pydantic-ai agents (and the in-process pipeline) so
that tools can reach AWS services and per-run context without importing globals.
Clients are created lazily and cached so the same instance is reused across a
warm Lambda invocation or the long-running Fargate process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any

import boto3

from oligos_agents.config import Settings, get_settings

if TYPE_CHECKING:
    from aws_lambda_powertools import Logger


class AwsClients:
    """Lazily-instantiated, cached boto3 clients."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def dynamodb(self) -> Any:
        return boto3.resource("dynamodb", region_name=self._settings.aws_region)

    @cached_property
    def s3(self) -> Any:
        return boto3.client("s3", region_name=self._settings.aws_region)

    @cached_property
    def sns(self) -> Any:
        return boto3.client("sns", region_name=self._settings.aws_region)

    @cached_property
    def sfn(self) -> Any:
        return boto3.client("stepfunctions", region_name=self._settings.aws_region)

    @cached_property
    def firehose(self) -> Any:
        return boto3.client("firehose", region_name=self._settings.aws_region)

    @cached_property
    def secretsmanager(self) -> Any:
        return boto3.client("secretsmanager", region_name=self._settings.aws_region)

    @cached_property
    def cognito_idp(self) -> Any:
        return boto3.client("cognito-idp", region_name=self._settings.cognito_region)

    @cached_property
    def bedrock_agent_runtime(self) -> Any:
        """Client for Bedrock KB retrieval, optionally cross-account via STS."""
        role_arn = self._settings.kb_assume_role_arn
        region = self._settings.knowledge_base_region
        if not role_arn:
            return boto3.client("bedrock-agent-runtime", region_name=region)

        sts = boto3.client("sts", region_name=region)
        assume_kwargs: dict[str, Any] = {
            "RoleArn": role_arn,
            "RoleSessionName": "oligos-agents-kb",
        }
        if self._settings.kb_assume_role_external_id:
            assume_kwargs["ExternalId"] = self._settings.kb_assume_role_external_id
        creds = sts.assume_role(**assume_kwargs)["Credentials"]
        return boto3.client(
            "bedrock-agent-runtime",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )


@dataclass
class AgentDeps:
    """Dependency bundle handed to agents and pipeline steps."""

    settings: Settings = field(default_factory=get_settings)
    run_id: str | None = None
    usage: list = field(default_factory=list)
    # Full text of every document fetched during a run, keyed by document id.
    # Used downstream for deterministic verbatim-citation verification so that
    # extraction mistakes cannot silently produce an untrustworthy report.
    fetched_documents: dict[str, str] = field(default_factory=dict)

    @cached_property
    def clients(self) -> AwsClients:
        return AwsClients(self.settings)

    @cached_property
    def logger(self) -> Logger:
        from oligos_agents.logging_utils import get_logger

        return get_logger(self.settings.logger_level)
