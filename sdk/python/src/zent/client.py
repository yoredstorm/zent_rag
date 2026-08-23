from __future__ import annotations

import httpx

from zent._http import AsyncHttpClient, HttpClient, default_base_url
from zent.resources import (
    AgentsResource,
    AsyncAgentsResource,
    AsyncConnectorsResource,
    AsyncRagResource,
    AsyncUsageResource,
    ConnectorsResource,
    RagResource,
    UsageResource,
)
from zent.resources.chat import AsyncChatResource, ChatResource


class Zent:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = HttpClient(
            api_key=api_key,
            base_url=base_url or default_base_url(),
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
        )
        self.chat = ChatResource(self._http)
        self.rag = RagResource(self._http)
        self.agents = AgentsResource(self._http)
        self.connectors = ConnectorsResource(self._http)
        self.usage = UsageResource(self._http)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Zent:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncZent:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = AsyncHttpClient(
            api_key=api_key,
            base_url=base_url or default_base_url(),
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
        )
        self.chat = AsyncChatResource(self._http)
        self.rag = AsyncRagResource(self._http)
        self.agents = AsyncAgentsResource(self._http)
        self.connectors = AsyncConnectorsResource(self._http)
        self.usage = AsyncUsageResource(self._http)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncZent:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
