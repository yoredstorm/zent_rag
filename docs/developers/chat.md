# Chat

`client.chat()` envuelve `POST /api/v1/rag/query`.

## Python

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")
response = client.chat("What is our refund policy?")
print(response.answer)
print(response.sources)

for event in client.chat.stream("Summarize Q4"):
    print(event.event, event.data)
```

Async:

```python
from zent import AsyncZent

async with AsyncZent(api_key="...") as client:
    print((await client.chat("hola")).answer)
```

## Node

```ts
import { Zent } from "zent-node";

const client = new Zent({ apiKey: process.env.ZENT_API_KEY! });
const res = await client.chat("What is our refund policy?");
console.log(res.answer);

for await (const event of client.chat.stream("Summarize Q4")) {
  console.log(event.event, event.data);
}
```

## HTTP

`POST /api/v1/rag/query` body `{ "query": "..." }` (campos opcionales: `conversation_id`, `temperature`, `top_k`, `role`).

Stream: `POST /api/v1/rag/query/stream` (SSE: `status`, `sources`, `delta`, `done`, `error`).

Scope requerido: `rag:read`.
