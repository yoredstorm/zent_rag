from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from zent.types import ChatEvent, ChatResponse


def _chat_response(payload: dict[str, Any]) -> ChatResponse:
    return ChatResponse(
        answer=str(payload.get("answer") or ""),
        query_id=str(payload["query_id"]) if payload.get("query_id") else None,
        conversation_id=(
            str(payload["conversation_id"]) if payload.get("conversation_id") else None
        ),
        model=payload.get("model"),
        sources=list(payload.get("sources") or []),
        usage=dict(payload.get("usage") or {}),
        raw=payload,
    )


class ChatResource:
    def __init__(self, http) -> None:
        self._http = http

    def __call__(self, message: str, **kwargs: Any) -> ChatResponse:
        return self.create(message, **kwargs)

    def create(self, message: str, **kwargs: Any) -> ChatResponse:
        body = {"query": message, **kwargs}
        response = self._http.request("POST", "/rag/query", json=body)
        return _chat_response(response.json())

    def stream(self, message: str, **kwargs: Any) -> Iterator[ChatEvent]:
        body = {"query": message, **kwargs}
        for event, data in self._http.stream_sse("/rag/query/stream", json=body):
            try:
                parsed: Any = json.loads(data)
            except json.JSONDecodeError:
                parsed = data
            yield ChatEvent(event=event, data=parsed)


class AsyncChatResource:
    def __init__(self, http) -> None:
        self._http = http

    async def __call__(self, message: str, **kwargs: Any) -> ChatResponse:
        return await self.create(message, **kwargs)

    async def create(self, message: str, **kwargs: Any) -> ChatResponse:
        body = {"query": message, **kwargs}
        response = await self._http.request("POST", "/rag/query", json=body)
        return _chat_response(response.json())

    async def stream(self, message: str, **kwargs: Any) -> AsyncIterator[ChatEvent]:
        body = {"query": message, **kwargs}
        headers = {"Accept": "text/event-stream"}
        async with self._http._client.stream(
            "POST", "/rag/query/stream", json=body, headers=headers
        ) as response:
            event = "message"
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "":
                    if data_lines:
                        raw = "\n".join(data_lines)
                        try:
                            parsed: Any = json.loads(raw)
                        except json.JSONDecodeError:
                            parsed = raw
                        yield ChatEvent(event=event, data=parsed)
                    event = "message"
                    data_lines = []
