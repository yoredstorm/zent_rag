from __future__ import annotations

from typing import Any


class RagResource:
    def __init__(self, http) -> None:
        self._http = http

    def query(self, message: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(
            "POST", "/rag/query", json={"query": message, **kwargs}
        )
        return response.json()


class AgentsResource:
    def __init__(self, http) -> None:
        self._http = http

    def create(self, name: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(
            "POST", "/agents", json={"name": name, **kwargs}, idempotency=True
        )
        return response.json()

    def list(self) -> dict[str, Any]:
        return self._http.request("GET", "/agents").json()

    def run(self, agent_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(
            "POST",
            f"/agents/{agent_id}/run",
            json={"message": message, **kwargs},
            idempotency=True,
        )
        return response.json()


class ConnectorsResource:
    def __init__(self, http) -> None:
        self._http = http

    def list(self) -> dict[str, Any]:
        return self._http.request("GET", "/connectors").json()

    def create(self, name: str, type: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"name": name, "type": type, **kwargs}
        return self._http.request(
            "POST", "/connectors", json=payload, idempotency=True
        ).json()


class UsageResource:
    def __init__(self, http) -> None:
        self._http = http

    def get(self, *, days: int = 30) -> dict[str, Any]:
        return self._http.request("GET", f"/billing/usage?days={days}").json()


class AsyncRagResource:
    def __init__(self, http) -> None:
        self._http = http

    async def query(self, message: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._http.request(
            "POST", "/rag/query", json={"query": message, **kwargs}
        )
        return response.json()


class AsyncAgentsResource:
    def __init__(self, http) -> None:
        self._http = http

    async def run(self, agent_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._http.request(
            "POST",
            f"/agents/{agent_id}/run",
            json={"message": message, **kwargs},
            idempotency=True,
        )
        return response.json()


class AsyncConnectorsResource:
    def __init__(self, http) -> None:
        self._http = http

    async def list(self) -> dict[str, Any]:
        response = await self._http.request("GET", "/connectors")
        return response.json()


class AsyncUsageResource:
    def __init__(self, http) -> None:
        self._http = http

    async def get(self, *, days: int = 30) -> dict[str, Any]:
        response = await self._http.request("GET", f"/billing/usage?days={days}")
        return response.json()
