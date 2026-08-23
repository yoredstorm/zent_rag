# zent-node

Node SDK for the Zent API. Not published to npm yet — install from this repo:

```bash
cd sdk/node && npm install
```

```ts
import { Zent } from "zent-node";

const client = new Zent({ apiKey: process.env.ZENT_API_KEY! });
const res = await client.chat("What is our refund policy?");
console.log(res.answer);
```

Default base URL: `http://localhost:8000/api/v1` (override with `ZENT_BASE_URL`).

Docs: [docs/developers/quickstart.md](../../docs/developers/quickstart.md)
