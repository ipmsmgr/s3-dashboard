"""S3 bucket scanner — file listing and content retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional

import botocore.exceptions
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from domain_feed_health_dashboard.utils.logger import logger


@dataclass
class S3Object:
    """Metadata for a single S3 object."""

    key: str
    size: int
    last_modified: datetime
    storage_class: str = "STANDARD"


class S3Scanner:
    """Lists S3 objects and reads their content."""

    def __init__(self, s3_client) -> None:
        self.s3_client = s3_client

    def list_prefix(
        self,
        bucket: str,
        prefix: str = "",
        after_key: Optional[str] = None,
    ) -> list[S3Object]:
        """Return all objects under *prefix*, optionally filtered to keys
        that sort after *after_key* (used for incremental polling).

        Pagination is handled internally; the full result is returned as a
        list so callers can iterate multiple times without re-fetching.

        Args:
            bucket:    S3 bucket name.
            prefix:    Key prefix to scan (e.g. ``"feeds/"``).
            after_key: If supplied, only keys lexicographically greater than
                       this value are returned.  Useful to avoid re-processing
                       files seen in a previous poll cycle.

        Returns:
            List of :class:`S3Object` instances, sorted by key ascending.
        """
        paginator = self.s3_client.get_paginator("list_objects_v2")
        page_iter = paginator.paginate(Bucket=bucket, Prefix=prefix)

        results: list[S3Object] = []
        try:
            for page in page_iter:
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    if key.endswith("/"):
                        continue
                    if after_key and key <= after_key:
                        continue
                    results.append(
                        S3Object(
                            key=key,
                            size=obj["Size"],
                            last_modified=obj["LastModified"].replace(tzinfo=None),
                            storage_class=obj.get("StorageClass", "STANDARD"),
                        )
                    )
        except Exception as exc:
            logger.error(
                "Error listing prefix",
                extra={"event": "list_prefix_error", "bucket": bucket,
                       "prefix": prefix, "error": str(exc)},
            )
            raise

        results.sort(key=lambda o: o.key)
        logger.info(
            "Listed prefix",
            extra={"event": "list_prefix_complete", "bucket": bucket,
                   "prefix": prefix, "count": len(results)},
        )
        return results

    def _is_transient(exc: BaseException) -> bool:
        if isinstance(exc, botocore.exceptions.ClientError):
            return exc.response["Error"]["Code"] not in ("NoSuchKey", "AccessDenied", "403")
        return True

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def read_text_file(self, bucket: str, key: str) -> str:
        """Download *key* from *bucket* and return its content as a string.

        Retries up to three times with exponential back-off on transient errors.
        Returns ``""`` immediately (no retry, no error log) for missing keys.

        Args:
            bucket: S3 bucket name.
            key:    Object key.

        Returns:
            File content decoded as UTF-8 (errors ignored), or ``""`` on
            unrecoverable failure.
        """
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content: str = response["Body"].read().decode("utf-8", errors="ignore")
            logger.info(
                "Read text file",
                extra={"event": "text_file_read", "bucket": bucket,
                       "key": key, "size_bytes": len(content)},
            )
            return content
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "AccessDenied", "403"):
                logger.debug(
                    "Object not found or not accessible",
                    extra={"event": "text_file_missing", "bucket": bucket,
                           "key": key, "code": code},
                )
                return ""
            logger.error(
                "Failed to read text file",
                extra={"event": "text_file_read_error", "bucket": bucket,
                       "key": key, "error": str(exc)},
            )
            raise
        except Exception as exc:
            logger.error(
                "Failed to read text file",
                extra={"event": "text_file_read_error", "bucket": bucket,
                       "key": key, "error": str(exc)},
            )
            raise
