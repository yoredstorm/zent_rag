# =============================================================================
# ApiSourceConnector — API JSON genérica config-driven (paginación incluida)
# =============================================================================
# config:
#   base_url, path, method (default GET)
#   headers: dict (no secretos; credenciales vía env var name en auth_env_var)
#   pagination: { type: page|offset|cursor, param, size, start, max_pages }
#   items_path: lista de claves al array de items (ej. ["data", "items"])
#   id_field: clave del id estable por item (default "id")
#   fields: lista opcional de campos a serializar (default: todos)
# =============================================================================
from __future__ import annotations

import json
import os

import httpx

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)


def _flatten_item(item: dict, fields: list[str] | None = None) -> str:
    lines: list[str] = []
    for key, value in item.items():
        if fields is not None and key not in fields:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


class ApiSourceConnector(SourceConnector):
    source_type = "api"
    self_contained = False

    def _endpoint(self) -> str:
        base = (self.config.get("base_url") or "").rstrip("/")
        path = (self.config.get("path") or "").lstrip("/")
        if not base:
            raise ConnectorError("api source requires 'base_url' in config")
        return f"{base}/{path}" if path else base

    def _headers(self) -> dict[str, str]:
        headers = {k: str(v) for k, v in (self.config.get("headers") or {}).items()}
        env_var = self.config.get("auth_env_var")
        if env_var:
            token = os.environ.get(str(env_var), "")
            if not token:
                raise ConnectorError(
                    f"Environment variable '{env_var}' (auth_env_var) is not set"
                )
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _pagination(self) -> dict:
        return self.config.get("pagination") or {}

    async def validate(self) -> None:
        self._endpoint()
        items_path = self.config.get("items_path")
        if not isinstance(items_path, list) or not items_path:
            raise ConnectorError("api source requires 'items_path' (list of keys)")

    async def discover(self) -> list[DiscoveredItem]:
        return [DiscoveredItem(external_id=self._endpoint(), label=self._endpoint())]

    async def _request_json(
        self, params: dict, method: str, json_body: dict | None
    ) -> dict:
        timeout = float(self.config.get("timeout_seconds") or 30)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.request(
                    method,
                    self._endpoint(),
                    params=params or None,
                    headers=self._headers(),
                    json=json_body,
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                raise ConnectorError(f"API request failed: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ConnectorError(f"API returned non-JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConnectorError("API response root must be an object")
        return data

    @staticmethod
    def _dig(data: dict, path: list[str]) -> object:
        current: object = data
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return []
        return current

    async def iter_records(self, cursor: dict | None):
        method = str(self.config.get("method") or "GET").upper()
        json_body = self.config.get("body")
        items_path: list[str] = list(self.config.get("items_path") or [])
        id_field = str(self.config.get("id_field") or "id")
        fields = self.config.get("fields") or None
        pagination = self._pagination()
        pag_type = pagination.get("type") or "page"
        size = int(pagination.get("size") or 50)
        max_pages = int(pagination.get("max_pages") or 10)
        param = pagination.get("param") or ("page" if pag_type == "page" else "offset")

        page_number = int(cursor.get("page", 1)) if cursor else 1
        offset = int(cursor.get("offset", 0)) if cursor else int(pagination.get("start") or 0)
        next_cursor_token: str | None = (cursor.get("cursor") if cursor else None)

        seen_pages = 0
        while seen_pages < max_pages:
            seen_pages += 1
            params = {k: str(v) for k, v in (self.config.get("params") or {}).items()}
            if pag_type == "page":
                params[param] = str(page_number)
                params["per_page"] = str(size)
            elif pag_type == "offset":
                params[param] = str(offset)
                params["limit"] = str(size)
            elif pag_type == "cursor":
                if next_cursor_token:
                    params[param] = next_cursor_token
                params.setdefault("limit", str(size))

            data = await self._request_json(params, method, json_body)
            items = self._dig(data, items_path)
            if not isinstance(items, list):
                raise ConnectorError(
                    f"items_path {items_path} did not resolve to a list"
                )
            if not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                external_id = str(item.get(id_field, "")) or str(len(str(item)))
                yield Record(
                    external_id=external_id,
                    content=_flatten_item(item, fields),
                    metadata={
                        "endpoint": self._endpoint(),
                        "page": page_number,
                        "format": "api",
                    },
                )

            if pag_type == "page":
                page_number += 1
            elif pag_type == "offset":
                offset += len(items)
            elif pag_type == "cursor":
                cursor_path = pagination.get("cursor_path") or ["next_cursor"]
                next_token = self._dig(data, cursor_path)
                if not next_token or next_token == next_cursor_token:
                    break
                next_cursor_token = str(next_token)

            self._last_cursor = (
                {"page": page_number, "offset": offset, "cursor": next_cursor_token}
            )
