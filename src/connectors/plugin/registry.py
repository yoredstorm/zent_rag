# =============================================================================
# Connector Platform — registry de plugins
# =============================================================================
# Registro por entry points (grupo "zent_connectors" en pyproject) con
# fallback a módulos listados en CONNECTOR_PLUGIN_MODULES. Agregar un
# conector nuevo = paquete + entry point + tests. El core no cambia.
# =============================================================================
from __future__ import annotations

import importlib
from dataclasses import dataclass
from importlib.metadata import entry_points

from src.connectors.plugin.base import ConnectorPlugin
from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_PLUGINS: dict[str, type[ConnectorPlugin]] = {}


@dataclass(kw_only=True, frozen=True)
class PluginInfo:
    connector_type: str
    capabilities: frozenset[str]
    required_secret_keys: list[str]


def register_plugin(cls: type[ConnectorPlugin]) -> None:
    """Registra una clase de plugin por su connector_type."""
    if not cls.connector_type:
        raise ValueError("Plugin must define a non-empty connector_type")
    _PLUGINS[cls.connector_type] = cls
    logger.info("Connector plugin registered", type=cls.connector_type)


def get_plugin_class(connector_type: str) -> type[ConnectorPlugin] | None:
    return _PLUGINS.get(connector_type)


def get_plugin(
    connector_type: str, config: dict, secrets: dict
) -> ConnectorPlugin:
    cls = get_plugin_class(connector_type)
    if cls is None:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return cls(config, secrets)


def plugin_types() -> dict[str, PluginInfo]:
    return {
        name: PluginInfo(
            connector_type=cls.connector_type,
            capabilities=cls.capabilities,
            required_secret_keys=list(cls.required_secret_keys),
        )
        for name, cls in sorted(_PLUGINS.items())
    }


def load_entry_points() -> int:
    """Carga plugins desde entry points del grupo zent_connectors."""
    count = 0
    try:
        group = entry_points(group="zent_connectors")
    except TypeError:  # pragma: no cover (importlib.metadata vieja)
        group = entry_points().select(group="zent_connectors")
    for ep in group:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, ConnectorPlugin):
                register_plugin(cls)
                count += 1
        except Exception as exc:
            logger.warning(
                "Failed to load connector entry point",
                entry_point=ep.name,
                error=str(exc),
            )
    return count


def load_plugin_modules(module_paths: list[str] | None = None) -> None:
    """Carga plugins desde módulos (fallback a entry points)."""
    paths = module_paths
    if paths is None:
        paths = [
            p.strip()
            for p in get_settings().CONNECTOR_PLUGIN_MODULES.split(",")
            if p.strip()
        ]
    for path in paths:
        try:
            importlib.import_module(path)
            logger.info("Loaded connector plugin module", module=path)
        except Exception as exc:
            logger.warning(
                "Failed to load connector plugin module",
                module=path,
                error=str(exc),
            )
