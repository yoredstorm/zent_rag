# =============================================================================
# Certification: E2E del guard SSRF de conectores de knowledge
# =============================================================================
# Levanta un servidor local que responde 302 hacia un host interno y verifica
# que el conector (dentro del contenedor desplegado) BLOQUEA el salto.
#
#   docker exec rag-api python /app/scripts/cert/ssrf_e2e.py
#
# Política: el host del conector puede estar en la allowlist explícita del
# tenant (acá 127.0.0.1, el server de prueba); el destino del redirect NO está
# en la allowlist y debe bloquearse sin llegar a pedirlo.
from __future__ import annotations

# ruff: noqa: T201 - herramienta CLI: print es la salida
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

sys.path.insert(0, "/app")

from src.core.domain.entities import KbSource  # noqa: E402
from src.knowledge.connectors.base import ConnectorError  # noqa: E402
from src.knowledge.connectors.web_source import WebSourceConnector  # noqa: E402

INTERNAL_TARGET = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
requests_seen: list[str] = []


class _Redirector(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - API de http.server
        requests_seen.append(self.path)
        self.send_response(302)
        self.send_header("Location", INTERNAL_TARGET)
        self.end_headers()

    def log_message(self, *args) -> None:  # silencio
        return


def main() -> int:
    server = HTTPServer(("127.0.0.1", 8099), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    source = KbSource(
        id=uuid4(),
        organization_id=uuid4(),
        name="ssrf-e2e",
        type="web",
        config_json={
            "url": "http://127.0.0.1:8099/spec",
            "ssrf_allowlist": ["127.0.0.1"],
        },
    )
    connector = WebSourceConnector(source=source)
    try:
        import asyncio

        asyncio.run(connector._fetch_bytes())
        print("FAIL: el redirect interno NO se bloqueo")
        return 1
    except ConnectorError as exc:
        print(f"PASS: redirect interno bloqueado -> {str(exc)[:90]}")
    finally:
        server.shutdown()

    print(f"primer hop pedido: {requests_seen}")
    assert requests_seen == ["/spec"], "el primer hop no fue el esperado"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
