# =============================================================================
# Knowledge connectors — HTTP seguro (SSRF + redirects)
# =============================================================================
# Los conectores de knowledge traen contenido server-side. Igual que la
# Connector Platform (src/connectors/plugin/base.py:63), la URL debe apuntar a
# un host público y cada salto de redirect debe re-validarse: un 302 a
# 169.254.169.254 / localhost no puede convertirse en un fetch interno.
#
# Política:
#   - `assert_public_url`: bloquea redes privadas salvo ssrf_allowlist del
#     conector (setting RAG_CONNECTOR_SSRF_BLOCK_PRIVATE, default true).
#   - `request_with_safe_redirects`: follow manual acotado (5 saltos) con
#     re-validación del host destino en cada hop.
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from src.knowledge.connectors.base import ConnectorError

MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def assert_public_url(url: str, allowlist: list[str] | None = None) -> None:
    """Valida esquema + host público. Lanza ConnectorError si no es seguro."""
    from src.connectors.plugin.base import ConnectorError as HostBlocked
    from src.connectors.plugin.base import assert_host_safe

    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise ConnectorError(f"Blocked URL scheme: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise ConnectorError("URL without host")
    try:
        assert_host_safe(parsed.hostname, allowlist=list(allowlist or []))
    except HostBlocked as exc:
        raise ConnectorError(f"Blocked URL host: {exc}") from exc


async def request_with_safe_redirects(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    allowlist: list[str] | None = None,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs: Any,
) -> httpx.Response:
    """Request con follow_redirects=False y re-validación SSRF por salto."""
    current_url = url
    current_method = method
    current_kwargs = dict(kwargs)
    for _ in range(max_redirects + 1):
        assert_public_url(current_url, allowlist)
        response = await client.request(current_method, current_url, **current_kwargs)
        if response.status_code not in _REDIRECT_STATUSES:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current_url = str(httpx.URL(current_url).join(location))
        if response.status_code == 303 or current_method not in ("GET", "HEAD"):
            current_method = "GET"
            current_kwargs.pop("json", None)
            current_kwargs.pop("content", None)
            current_kwargs.pop("data", None)
        current_kwargs.pop("params", None)
    raise ConnectorError(f"Too many redirects (>{max_redirects}) for {url}")
