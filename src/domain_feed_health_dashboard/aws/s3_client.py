"""AWS S3 client initialisation and configuration."""

from __future__ import annotations

from typing import Optional

import boto3
from botocore.config import Config

from domain_feed_health_dashboard.utils.logger import logger


class S3ClientFactory:
    """Singleton factory for a configured boto3 S3 client.

    Authentication is resolved automatically by boto3 in this order:
    environment variables → ~/.aws/credentials profile → IAM / ECS task role.
    Credentials are never hard-coded.
    """

    _instance: Optional["S3ClientFactory"] = None

    def __new__(cls) -> "S3ClientFactory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        config = Config(
            max_pool_connections=10,
            retries={"max_attempts": 3, "mode": "adaptive"},
            tcp_keepalive=True,
        )

        try:
            self.s3_client = boto3.client("s3", config=config)
            logger.info("S3 client initialised")
        except Exception as exc:
            logger.error("Failed to initialise S3 client", extra={"error": str(exc)})
            raise

    def get_client(self):
        """Return the configured boto3 S3 client."""
        return self.s3_client


def get_s3_client():
    """Return (or create) the singleton S3 client."""
    return S3ClientFactory().get_client()
