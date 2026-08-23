# Connector Platform — plugins extensibles (registro + modelos + seguridad)
from src.connectors.plugin.base import (  # noqa: F401
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
)
from src.connectors.plugin.models import (  # noqa: F401
    ColumnSchema,
    IndexInfo,
    Relationship,
    SchemaDiscovery,
    TableSchema,
)
from src.connectors.plugin.redaction import REDACTED, redact  # noqa: F401
from src.connectors.plugin.registry import (  # noqa: F401
    PluginInfo,
    get_plugin,
    get_plugin_class,
    load_entry_points,
    load_plugin_modules,
    plugin_types,
    register_plugin,
)

__all__ = [
    "ColumnSchema",
    "ConnectorError",
    "ConnectorPlugin",
    "ConnectionTestResult",
    "IndexInfo",
    "PluginInfo",
    "REDACTED",
    "Relationship",
    "SchemaDiscovery",
    "TableSchema",
    "assert_host_safe",
    "get_plugin",
    "get_plugin_class",
    "load_entry_points",
    "load_plugin_modules",
    "plugin_types",
    "redact",
    "register_plugin",
]
