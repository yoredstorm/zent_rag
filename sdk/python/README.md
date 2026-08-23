# zent

Python SDK for the Zent API. Not published to PyPI yet — install from this repo:

```bash
pip install -e sdk/python
```

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")
print(client.chat("What is our refund policy?").answer)
```

Default base URL: `http://localhost:8000/api/v1` (override with `ZENT_BASE_URL`).

Docs: [docs/developers/quickstart.md](../../docs/developers/quickstart.md)
