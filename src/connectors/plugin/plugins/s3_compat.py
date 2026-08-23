# =============================================================================
# S3-compatible object storage plugin (AWS S3, MinIO, compatible)
# =============================================================================
from __future__ import annotations

import time
from typing import ClassVar

from src.connectors.plugin.base import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
)
from src.connectors.plugin.models import SchemaDiscovery, TableSchema


class S3CompatPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "s3_compat"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = [
        "aws_access_key_id",
        "aws_secret_access_key",
    ]

    def _client(self):
        import boto3  # type: ignore[import-untyped]

        config = self.config
        endpoint = config.get("endpoint_url")
        return boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=config.get("region"),
            aws_access_key_id=self.secrets.get("aws_access_key_id"),
            aws_secret_access_key=self.secrets.get("aws_secret_access_key"),
        )

    async def validate(self) -> None:
        if not self.config.get("bucket"):
            raise ConnectorError("s3_compat config requires bucket")
        if not self.secrets.get("aws_access_key_id") or not self.secrets.get(
            "aws_secret_access_key"
        ):
            raise ConnectorError(
                "s3_compat requires secrets: aws_access_key_id, "
                "aws_secret_access_key"
            )
        endpoint = self.config.get("endpoint_url")
        if endpoint:
            from urllib.parse import urlparse

            hostname = urlparse(str(endpoint)).hostname
            if hostname:
                assert_host_safe(
                    hostname,
                    allowlist=self.config.get("ssrf_allowlist"),
                )

    async def connect(self) -> None:
        self._client()  # valida credenciales perezosamente en cada call

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            await self.validate()
            client = self._client()
            client.head_bucket(Bucket=str(self.config["bucket"]))
            return ConnectionTestResult(
                ok=True,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="ok",
            )
        except ConnectorError as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=str(exc),
            )
        except Exception as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Bucket check failed: {exc}",
            )

    async def discover(self) -> SchemaDiscovery:
        await self.validate()
        client = self._client()
        prefix = str(self.config.get("prefix") or "")
        max_objects = int(self.config.get("max_objects") or 100)
        try:
            response = client.list_objects_v2(
                Bucket=str(self.config["bucket"]),
                Prefix=prefix,
                MaxKeys=min(max_objects, 1000),
            )
        except Exception as exc:
            raise ConnectorError(f"Listing failed: {exc}") from exc
        items = [
            f"{obj['Key']} ({obj['Size']} bytes, "
            f"modified {obj['LastModified'].isoformat()})"
            for obj in response.get("Contents") or []
        ]
        table = TableSchema(name=f"s3://{self.config['bucket']}/{prefix}")
        return SchemaDiscovery(
            tables=[table],
            source="s3_compat",
        )

    async def close(self) -> None:
        return None


def register() -> None:
    from src.connectors.plugin.registry import register_plugin

    register_plugin(S3CompatPlugin)
