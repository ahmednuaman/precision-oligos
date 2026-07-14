"""Structured logging via AWS Lambda Powertools.

Using Powertools keeps log output structured (JSON) and consistent across the
FastAPI control-plane and the Lambda pipeline steps, per the workspace Python
standards (never use ``print``).
"""

from __future__ import annotations

from functools import lru_cache

from aws_lambda_powertools import Logger

SERVICE_NAME = "oligos-agents"


@lru_cache
def get_logger(level: str = "INFO") -> Logger:
    """Return a cached Powertools logger for the service."""
    return Logger(service=SERVICE_NAME, level=level.upper())
