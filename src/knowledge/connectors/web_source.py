# =============================================================================
# WebSourceConnector — URL → HTML → Markdown (httpx + markitdown/markdownify)
# =============================================================================
from __future__ import annotations

import httpx

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.normalize.doc_html_normalizer import HtmlNormalizer
from src.knowledge.normalize.text_normalizer import TextNormalizer


class WebSourceConnector(SourceConnector):
    source_type = "web"
    self_contained = False

    def _url(self) -> str:
        url = (self.config.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ConnectorError("web source requires a valid 'url' (http/https)")
        return url

    async def validate(self) -> None:
        self._url()

    async def discover(self) -> list[DiscoveredItem]:
        return [DiscoveredItem(external_id=self._url(), label=self._url())]

    async def _fetch_bytes(self) -> tuple[bytes, str]:
        headers = {k: str(v) for k, v in (self.config.get("headers") or {}).items()}
        timeout = float(self.config.get("timeout_seconds") or 30)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.get(self._url(), headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Fetch failed for {self._url()}: {exc}") from exc
        return response.content, response.headers.get("content-type", "")

    async def iter_records(self, cursor: dict | None):
        data, content_type = await self._fetch_bytes()
        is_html = "html" in content_type.lower() or data.lstrip().startswith(b"<")
        if is_html:
            markdown = HtmlNormalizer().normalize(data, source_name=self._url())
        else:
            markdown = TextNormalizer().normalize(data, source_name=self._url())
        yield Record(
            external_id=self._url(),
            content=markdown,
            metadata={"url": self._url(), "content_type": content_type},
        )
