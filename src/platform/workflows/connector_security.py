# =============================================================================
# P19.1-08 - Politica de red, TLS y pooling para conectores PostgreSQL.
#
# No es un motor nuevo: es la frontera de confianza del conector existente.
# - bloquea loopback/link-local/metadata/privadas en produccion;
# - permite allowlist explicita por entorno/conector;
# - exige TLS con verificacion de CA y hostname en produccion;
# - cachea engines acotados por proceso/loop/tenant/conector.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.platform.workflows.bindings import BindingError

_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.com",
        "169.254.169.254",
    }
)
_BLOCKED_PORTS = frozenset({25, 11211, 6379, 9042, 27017})


@dataclass(frozen=True)
class ConnectorTarget:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_args: dict[str, Any]
    key: tuple[str, str, str, str]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _allowed_hosts() -> tuple[str, ...]:
    raw = os.environ.get("RAG_CONNECTOR_ALLOWED_HOSTS", "")
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _host_matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return host == pattern


def _ip_forbidden(ip: ipaddress._BaseAddress, *, development: bool) -> bool:
    if ip.is_loopback:
        return not development
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if ip.is_private:
        return not (development and _env_bool("RAG_CONNECTOR_ALLOW_PRIVATE", True))
    return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise BindingError("CONNECTION_FAILED", "no se pudo resolver el host") from exc
    addresses = []
    for info in infos:
        addr = info[4][0]
        if addr not in addresses:
            addresses.append(addr)
    if not addresses:
        raise BindingError("CONNECTION_FAILED", "host sin direcciones")
    return addresses


def _ssl_context(config: dict[str, Any], *, production: bool) -> ssl.SSLContext | bool | None:
    mode = str(config.get("ssl_mode") or ("verify-full" if config.get("ssl") else "")).lower()
    if mode in ("", "disable", "off", "false"):
        if production:
            raise BindingError(
                "POLICY_DENIED", "produccion exige TLS verify-full en el conector"
            )
        return None
    context = ssl.create_default_context(cafile=config.get("ssl_ca_file") or None)
    if mode in ("verify-full", "verify_ca", "verify-ca", "true"):
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context
    if mode == "require":
        if production:
            raise BindingError(
                "POLICY_DENIED", "ssl=require no verifica identidad; use verify-full"
            )
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    raise BindingError("NEEDS_CONFIGURATION", "ssl_mode invalido")


async def prepare_connector_target(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    connector_id: UUID,
    config: dict[str, Any],
    password: str,
    policy_config: dict[str, Any] | None = None,
) -> ConnectorTarget:
    """Valida host/puerto/TLS antes de abrir cualquier conexion."""
    production = os.environ.get("RAG_ENVIRONMENT", "development").lower() == "production"
    development = not production
    host = str(config.get("host") or "").strip()
    database = str(config.get("database") or "").strip()
    user = str(config.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector PostgreSQL incompleto")
    try:
        port = int(config.get("port") or 5432)
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "puerto del conector invalido") from exc
    if not 1 <= port <= 65535 or port in _BLOCKED_PORTS:
        raise BindingError("POLICY_DENIED", "puerto de conector no autorizado")
    if host.lower() in _METADATA_HOSTS:
        raise BindingError("POLICY_DENIED", "host de metadata no autorizado")

    allowed = tuple(str(item).lower() for item in (policy_config or {}).get("allowed_hosts", ()))
    effective_allowed = allowed or _allowed_hosts()
    if effective_allowed and not any(_host_matches(host, item) for item in effective_allowed):
        raise BindingError("POLICY_DENIED", "host fuera de la allowlist de egreso")

    addresses = [host] if _is_ip_literal(host) else await _resolve(host, port)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise BindingError("POLICY_DENIED", "resolucion de host invalida") from exc
        if str(ip) == "169.254.169.254" or _ip_forbidden(ip, development=development):
            raise BindingError("POLICY_DENIED", "destino de red no autorizado")

    ssl_value = _ssl_context(config, production=production)
    timeout_s = max(1.0, min(float(config.get("connect_timeout_seconds") or 5), 30.0))
    command_timeout_s = max(0.1, min(float(config.get("statement_timeout_seconds") or 30), 300.0))
    connect_args: dict[str, Any] = {
        "timeout": timeout_s,
        "command_timeout": command_timeout_s,
        "server_settings": {"default_transaction_read_only": "on"},
    }
    if ssl_value is not None:
        connect_args["ssl"] = ssl_value
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{port}/{quote_plus(database)}"
    )
    return ConnectorTarget(
        host=host,
        port=port,
        database=database,
        user=user,
        password=str(password),
        connect_args=connect_args,
        key=(
            str(organization_id),
            str(workspace_id or ""),
            str(connector_id),
            hashlib.sha256(
                f"{dsn}|{password}".encode("utf-8")
            ).hexdigest(),
        ),
    )


@dataclass
class _CachedEngine:
    engine: AsyncEngine
    created_at: float
    last_used: float


_ENGINES: dict[tuple[int, tuple[str, str, str, str]], _CachedEngine] = {}
_MAX_ENGINES = int(os.environ.get("RAG_CONNECTOR_POOL_MAX", "8"))
_ENGINE_TTL_SECONDS = float(os.environ.get("RAG_CONNECTOR_ENGINE_TTL_SECONDS", "300"))


def get_connector_engine(dsn: str, target: ConnectorTarget) -> AsyncEngine:
    """Engine acotado por loop/tenant/conector; no comparte credenciales."""
    if not _env_bool("RAG_CONNECTOR_POOL_ENABLED", True):
        return create_async_engine(
            dsn,
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            pool_timeout=5,
            connect_args=target.connect_args,
        )
    loop_key = id(asyncio.get_running_loop())
    key = (loop_key, target.key)
    now = time.monotonic()
    cached = _ENGINES.get(key)
    if cached and now - cached.created_at < _ENGINE_TTL_SECONDS:
        cached.last_used = now
        return cached.engine
    if cached:
        _ENGINES.pop(key, None)
        _dispose_later(cached.engine)
    while len(_ENGINES) >= max(1, int(os.environ.get("RAG_CONNECTOR_POOL_MAX", str(_MAX_ENGINES)))):
        oldest_key = min(_ENGINES, key=lambda item: _ENGINES[item].last_used)
        _dispose_later(_ENGINES.pop(oldest_key).engine)
    engine = create_async_engine(
        dsn,
        pool_size=max(1, int(os.environ.get("RAG_CONNECTOR_POOL_SIZE", "2"))),
        max_overflow=max(0, int(os.environ.get("RAG_CONNECTOR_POOL_OVERFLOW", "1"))),
        pool_recycle=int(os.environ.get("RAG_CONNECTOR_POOL_RECYCLE", "300")),
        pool_timeout=float(os.environ.get("RAG_CONNECTOR_POOL_TIMEOUT", "5")),
        pool_pre_ping=True,
        connect_args=target.connect_args,
    )
    _ENGINES[key] = _CachedEngine(engine=engine, created_at=now, last_used=now)
    return engine


def _dispose_later(engine: AsyncEngine) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(engine.dispose())
    except RuntimeError:
        return


async def dispose_connector_engines() -> None:
    for key, item in list(_ENGINES.items()):
        _ENGINES.pop(key, None)
        await item.engine.dispose()


__all__ = [
    "ConnectorTarget",
    "dispose_connector_engines",
    "get_connector_engine",
    "prepare_connector_target",
]
