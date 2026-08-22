# =============================================================================
# S3SourceConnector — objetos de un bucket → Markdown → Records (boto3)
# =============================================================================
# Credenciales: default chain de boto3 (env/instance profile). Para
# producción, credenciales de servicio vía Vault (path productivo).
# config: { bucket, prefix, extensions: [".pdf", ".txt"], max_objects }
# =============================================================================
from __future__ import annotations

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.normalize.base import NormalizerError, get_normalizer


class S3SourceConnector(SourceConnector):
    source_type = "s3"
    self_contained = False

    def _client(self):
        try:
            import boto3

            return boto3.client("s3")
        except Exception as exc:
            raise ConnectorError(f"boto3 unavailable: {exc}") from exc

    def _bucket(self) -> str:
        bucket = (self.config.get("bucket") or "").strip()
        if not bucket:
            raise ConnectorError("s3 source requires 'bucket' in config")
        return bucket

    def _prefix(self) -> str:
        return (self.config.get("prefix") or "").strip().lstrip("/")

    def _allowed_extensions(self) -> set[str]:
        exts = self.config.get("extensions") or None
        if not exts:
            return set()
        return {e.strip().lower().lstrip(".") for e in exts if e.strip()}

    async def validate(self) -> None:
        self._bucket()
        try:
            self._client().head_bucket(Bucket=self._bucket())
        except Exception as exc:
            raise ConnectorError(f"S3 bucket unreachable: {exc}") from exc

    async def discover(self) -> list[DiscoveredItem]:
        client = self._client()
        kwargs: dict = {"Bucket": self._bucket()}
        if self._prefix():
            kwargs["Prefix"] = self._prefix()
        try:
            paginator = client.get_paginator("list_objects_v2")
            items: list[DiscoveredItem] = []
            for page in paginator.paginate(**kwargs):
                for obj in page.get("Contents", []):
                    key = obj.get("Key", "")
                    if self._allowed_extensions():
                        import os

                        ext = os.path.splitext(key)[1].lower().lstrip(".")
                        if ext not in self._allowed_extensions():
                            continue
                    items.append(
                        DiscoveredItem(
                            external_id=key,
                            label=key,
                            extra={"size_bytes": obj.get("Size", 0)},
                        )
                    )
            return items
        except Exception as exc:
            raise ConnectorError(f"S3 listing failed: {exc}") from exc

    async def iter_records(self, cursor: dict | None):
        client = self._client()
        done_keys: set[str] = set(cursor.get("done_keys", [])) if cursor else set()
        max_objects = int(self.config.get("max_objects") or 100)
        import os

        count = 0
        for item in await self.discover():
            if count >= max_objects:
                break
            key = item.external_id
            if key in done_keys:
                continue
            try:
                response = client.get_object(Bucket=self._bucket(), Key=key)
                data = response["Body"].read()
            except Exception as exc:
                raise ConnectorError(f"S3 read failed for {key}: {exc}") from exc
            ext = os.path.splitext(key)[1].lower()
            normalizer = get_normalizer(ext)
            if normalizer is None:
                raise ConnectorError(
                    f"Unsupported S3 object type '{ext}' for {key}. "
                    f"Set 'extensions' in config."
                )
            try:
                markdown = normalizer.normalize(data, source_name=key)
            except NormalizerError as exc:
                raise ConnectorError(str(exc)) from exc
            count += 1
            done_keys.add(key)
            yield Record(
                external_id=key,
                content=markdown,
                metadata={"bucket": self._bucket(), "object_key": key, "format": ext.lstrip(".")},
            )
            # checkpoint: ceder el cursor actualizado al engine vía atributo
            self._last_cursor = {"done_keys": sorted(done_keys)}
