# =============================================================================
# API plugins — REST y GraphQL
# =============================================================================
from __future__ import annotations

import time
from typing import ClassVar

import httpx

from src.connectors.plugin.base import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
)
from src.connectors.plugin.models import ColumnSchema, SchemaDiscovery, TableSchema

_AUTH_KEYS = ("bearer_token", "api_key")


class RestApiPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "rest_api"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test"})
    required_secret_keys: ClassVar[list[str]] = ["bearer_token"]

    def _url(self) -> str:
        base = str(self.config.get("base_url") or "").strip().rstrip("/")
        path = str(self.config.get("ping_path") or "").strip().lstrip("/")
        if not base:
            raise ConnectorError("rest_api config requires base_url")
        return f"{base}/{path}" if path else base

    async def validate(self) -> None:
        from urllib.parse import urlparse

        url = self._url()
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ConnectorError("base_url must be http(s)")
        if parsed.hostname:
            assert_host_safe(
                parsed.hostname,
                allowlist=self.config.get("ssrf_allowlist"),
            )

    async def connect(self) -> None:
        pass

    def _headers(self) -> dict:
        headers = dict(self.config.get("headers") or {})
        for key in _AUTH_KEYS:
            if self.secrets.get(key):
                headers.setdefault(
                    "Authorization",
                    f"Bearer {self.secrets[key]}"
                    if key == "bearer_token"
                    else f"ApiKey {self.secrets[key]}",
                )
                break
        return headers

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            await self.validate()
            method = str(self.config.get("method") or "GET").upper()
            async with httpx.AsyncClient(
                timeout=float(self.config.get("timeout_seconds") or 10),
                follow_redirects=False,
            ) as client:
                resp = await client.request(
                    method, self._url(), headers=self._headers()
                )
            ok = 200 <= resp.status_code < 400
            return ConnectionTestResult(
                ok=ok,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=(
                    "ok" if ok else f"HTTP {resp.status_code}"
                ),
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
                message=f"Request failed: {exc}",
            )

    async def discover(self) -> SchemaDiscovery:
        # REST no expone schema: el tenant define el shape en config_json.
        return SchemaDiscovery(tables=[], source="rest_api")


_GRAPHQL_INTROSPECTION = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    types {
      kind
      name
      fields(includeDeprecated: false) {
        name
        type { kind name }
      }
    }
  }
}
"""


class GraphqlPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "graphql"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["bearer_token"]

    def _url(self) -> str:
        url = str(self.config.get("url") or "").strip()
        if not url:
            raise ConnectorError("graphql config requires url")
        return url

    async def validate(self) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(self._url())
        if parsed.scheme not in ("https", "http"):
            raise ConnectorError("url must be http(s)")
        if parsed.hostname:
            assert_host_safe(
                parsed.hostname,
                allowlist=self.config.get("ssrf_allowlist"),
            )

    async def connect(self) -> None:
        pass

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.secrets.get("bearer_token"):
            headers["Authorization"] = f"Bearer {self.secrets['bearer_token']}"
        return headers

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            await self.validate()
            async with httpx.AsyncClient(
                timeout=float(self.config.get("timeout_seconds") or 10),
                follow_redirects=False,
            ) as client:
                resp = await client.post(
                    self._url(),
                    json={"query": "{ __typename }"},
                    headers=self._headers(),
                )
            ok = resp.status_code == 200 and "errors" not in resp.json()
            return ConnectionTestResult(
                ok=ok,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="ok" if ok else f"HTTP {resp.status_code}",
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
                message=f"Request failed: {exc}",
            )

    async def discover(self) -> SchemaDiscovery:
        await self.validate()
        async with httpx.AsyncClient(
            timeout=float(self.config.get("timeout_seconds") or 10),
            follow_redirects=False,
        ) as client:
            resp = await client.post(
                self._url(),
                json={"query": _GRAPHQL_INTROSPECTION},
                headers=self._headers(),
            )
        if resp.status_code != 200:
            raise ConnectorError(f"Introspection failed: HTTP {resp.status_code}")
        data = resp.json()
        types = (data.get("data") or {}).get("__schema", {}).get("types", [])
        tables: list[TableSchema] = []
        for t in types:
            if t.get("kind") != "OBJECT":
                continue
            name = str(t.get("name") or "")
            if name.startswith("__"):
                continue
            fields = t.get("fields") or []
            tables.append(
                TableSchema(
                    name=name,
                    columns=[
                        ColumnSchema(
                            name=str(f.get("name") or ""),
                            data_type=str(
                                (f.get("type") or {}).get("name")
                                or (f.get("type") or {}).get("kind")
                                or "unknown"
                            ),
                        )
                        for f in fields
                    ],
                )
            )
        return SchemaDiscovery(tables=tables, source="graphql")


def register() -> None:
    from src.connectors.plugin.registry import register_plugin

    register_plugin(RestApiPlugin)
    register_plugin(GraphqlPlugin)
