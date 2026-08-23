# =============================================================================
# Builtin connector plugins — registro al importar el paquete
# =============================================================================
# El composition root (deps.py) importa este módulo una vez; los plugins
# se auto-registran. Plugins externos (DB2 de un vertical, etc.) llegan
# vía entry points zent_connectors o CONNECTOR_PLUGIN_MODULES.
# =============================================================================
from __future__ import annotations

from src.connectors.plugin.plugins import api_plugins as _api  # noqa: F401
from src.connectors.plugin.plugins import files as _files  # noqa: F401
from src.connectors.plugin.plugins import s3_compat as _s3  # noqa: F401
from src.connectors.plugin.plugins import sql_optional as _sql_optional  # noqa: F401
from src.connectors.plugin.plugins.postgres import PostgresPlugin
from src.connectors.plugin.registry import register_plugin

register_plugin(PostgresPlugin)
_api.register()
_files.register()
_s3.register()
_sql_optional.register()
