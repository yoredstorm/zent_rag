# =============================================================================
# Connector Platform — interfaz base de plugins
# =============================================================================
# Un ConnectorPlugin es la ÚNICA interfaz entre el core y una fuente externa
# (SQL, archivo, API, object storage). Agregar DB2 NO requiere modificar el
# core: paquete nuevo + registro (entry point o módulo) + tests.
#
# Seguridad:
#   - config: datos NO secretos (persiste en config_json).
#   - secrets: credenciales cifradas (SecretStore), nunca en config ni logs.
#   - SSRF: _assert_host_safe bloquea redes privadas (opcional por setting).
# =============================================================================
from __future__ import annotations

import ipaddress
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from src.connectors.plugin.models import SchemaDiscovery
from src.core.config import get_settings


class ConnectorError(Exception):
    """Error de configuración, conexión o discovery de un conector.

    El mensaje debe ser SEGURO: sin secretos (la capa API redacta igual).
    """


@dataclass(kw_only=True)
class ConnectionTestResult:
    ok: bool
    latency_ms: float = 0.0
    message: str = ""
    server_version: str | None = None


def _resolve_ip(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return None
        return str(infos[0][4][0])
    except OSError:
        return None


_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]


def assert_host_safe(host: str, allowlist: list[str] | None = None) -> None:
    """Bloquea hosts privados salvo allowlist explícita del tenant.

    El tenant conecta a SUS propias fuentes; en desarrollo local las
    fuentes están en el mismo host, por eso la allowlist permite
    config_json: {"ssrf_allowlist": ["localhost", "192.168.1.5"]}.
    """
    settings = get_settings()
    if not settings.CONNECTOR_SSRF_BLOCK_PRIVATE:
        return
    host_l = (host or "").lower()
    for allowed in allowlist or []:
        allowed_l = str(allowed).lower().strip()
        if host_l == allowed_l or host_l.endswith(f".{allowed_l}"):
            return
    if host_l in _BLOCKED_HOSTS:
        raise ConnectorError(f"Blocked host: {host}")
    ip = _resolve_ip(host)
    if ip is None:
        raise ConnectorError(f"Cannot resolve host: {host}")
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise ConnectorError(f"Invalid IP: {ip}") from None
    for network in _BLOCKED_NETWORKS:
        if addr in network:
            raise ConnectorError(
                f"Blocked private network IP: {ip} "
                "(add host to connector config ssrf_allowlist to allow)"
            )


class ConnectorPlugin(ABC):
    """Contrato de plugin de la Connector Platform.

    Atributos declarativos:
      - connector_type: identificador único (ej: "postgres", "db2").
      - capabilities: frozenset de capacidades (test, discover, ...).
      - required_secret_keys: nombres de secretos esperados (sin valores).
    """

    connector_type: ClassVar[str] = ""
    capabilities: ClassVar[frozenset[str]] = frozenset({"test"})
    required_secret_keys: ClassVar[list[str]] = []

    def __init__(self, config: dict, secrets: dict) -> None:
        self.config: dict = dict(config or {})
        self.secrets: dict = dict(secrets or {})

    @abstractmethod
    async def validate(self) -> None:
        """Valida config + presencia de secretos. Lanza ConnectorError."""

    @abstractmethod
    async def connect(self) -> None:
        """Abre la conexión con la fuente (o valida acceso)."""

    async def test_connection(self) -> ConnectionTestResult:
        """Prueba de conectividad con latencia. Default: connect() + ok."""
        import time

        start = time.perf_counter()
        try:
            await self.connect()
        except ConnectorError as exc:
            return ConnectionTestResult(
                ok=False, latency_ms=(time.perf_counter() - start) * 1000,
                message=str(exc),
            )
        return ConnectionTestResult(
            ok=True, latency_ms=(time.perf_counter() - start) * 1000,
            message="ok",
        )

    async def discover(self) -> SchemaDiscovery:
        """Descubre estructura. Default: vacío (fuentes sin schema)."""
        return SchemaDiscovery(source=self.connector_type)

    async def close(self) -> None:
        """Libera recursos. Default no-op."""
        return None
