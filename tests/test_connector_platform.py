# =============================================================================
# Connector Platform — extensibilidad, SecretStore, redaction
# =============================================================================
from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest

from src.connectors.plugin import (
    ConnectorPlugin,
    SchemaDiscovery,
    get_plugin,
    get_plugin_class,
    plugin_types,
    redact,
    register_plugin,
)
from src.connectors.plugin.models import ColumnSchema, TableSchema
from src.connectors.plugin.registry import PluginInfo


class TestExtensibility:
    """Agregar un conector nuevo NO toca el core: clase + registro."""

    def test_register_and_resolve_plugin(self) -> None:
        class MyCustomDbPlugin(ConnectorPlugin):
            connector_type: ClassVar[str] = "my_custom_db"
            capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
            required_secret_keys: ClassVar[list[str]] = ["password"]

            async def validate(self) -> None:
                return None

            async def connect(self) -> None:
                return None

            async def discover(self) -> SchemaDiscovery:
                return SchemaDiscovery(
                    tables=[TableSchema(name="t1", columns=[])],
                    source="my_custom_db",
                )

        register_plugin(MyCustomDbPlugin)

        assert get_plugin_class("my_custom_db") is MyCustomDbPlugin
        plugin = get_plugin(
            "my_custom_db",
            {"host": "db.example.com"},
            {"password": "x"},
        )
        assert isinstance(plugin, MyCustomDbPlugin)
        info = plugin_types()["my_custom_db"]
        assert isinstance(info, PluginInfo)
        assert info.required_secret_keys == ["password"]

    def test_unknown_plugin_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown connector type"):
            get_plugin("does_not_exist", {}, {})

    def test_register_requires_type(self) -> None:
        class NoTypePlugin(ConnectorPlugin):
            async def validate(self) -> None:
                pass

            async def connect(self) -> None:
                pass

        with pytest.raises(ValueError, match="connector_type"):
            register_plugin(NoTypePlugin)


class TestSecretStore:
    @pytest.mark.asyncio
    async def test_encrypted_roundtrip_real_db(self) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        if settings.ENVIRONMENT != "development":
            pytest.skip("Requiere Postgres real (stack docker)")

        from src.infrastructure.secrets.encrypted_secret_store import (
            EncryptedPostgresSecretStore,
        )

        store = EncryptedPostgresSecretStore()
        org = uuid4()
        connector_id = uuid4()
        secrets = {
            "password": "super-secret-password",
            "aws_secret_access_key": "AKIA-secret",
        }
        await store.put(org, connector_id, secrets)

        fetched = await store.get(org, connector_id)
        assert fetched == secrets

        # El texto plano NO puede estar en la base de datos.
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT encode(ciphertext, 'escape') AS raw "
                        "FROM connector_secrets "
                        "WHERE organization_id = :org AND connector_id = :cid"
                    ),
                    {"org": org, "cid": connector_id},
                )
            ).fetchone()
            assert row is not None
            assert "super-secret-password" not in str(row.raw)
        finally:
            await session.close()

        await store.delete(org, connector_id)
        assert await store.get(org, connector_id) == {}

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation_real_db(self) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        if settings.ENVIRONMENT != "development":
            pytest.skip("Requiere Postgres real (stack docker)")

        from src.infrastructure.secrets.encrypted_secret_store import (
            EncryptedPostgresSecretStore,
        )

        store = EncryptedPostgresSecretStore()
        org_a = uuid4()
        org_b = uuid4()
        connector_id = uuid4()
        await store.put(org_a, connector_id, {"password": "only-for-a"})

        # Otro organization NUNCA ve los secretos de A.
        assert await store.get(org_b, connector_id) == {}

        await store.delete(org_a, connector_id)


class TestRedaction:
    def test_redacts_dict_keys(self) -> None:
        payload = {
            "host": "db.example.com",
            "password": "hunter2",
            "api_key": "sk-123",
            "nested": {"token": "abc", "ok": "value"},
        }
        out = redact(payload)
        assert out["password"] == "[REDACTED]"
        assert out["api_key"] == "[REDACTED]"
        assert out["host"] == "db.example.com"
        assert out["nested"]["token"] == "[REDACTED]"
        assert out["nested"]["ok"] == "value"

    def test_redacts_urls_with_credentials(self) -> None:
        out = redact("postgres://user:hunter2@db.example.com:5432/app")
        assert "hunter2" not in out
        assert "[REDACTED]" in out

    def test_redacts_headers_strings(self) -> None:
        out = redact("Authorization: Bearer tok-12345")
        assert "tok-12345" not in out
        assert "[REDACTED]" in out

    def test_redact_does_not_mutate_original(self) -> None:
        payload = {"password": "secret"}
        out = redact(payload)
        assert payload["password"] == "secret"
        assert out["password"] == "[REDACTED]"


class TestModels:
    def test_schema_discovery_to_dict(self) -> None:
        discovery = SchemaDiscovery(
            tables=[
                TableSchema(
                    name="products",
                    schema="public",
                    columns=[
                        ColumnSchema(
                            name="id",
                            data_type="uuid",
                            is_primary_key=True,
                        )
                    ],
                    primary_keys=["id"],
                    row_count=42,
                )
            ],
            source="postgres",
        )
        data = discovery.to_dict()
        assert data["source"] == "postgres"
        assert data["tables"][0]["name"] == "products"
        assert data["tables"][0]["primary_keys"] == ["id"]
        assert data["tables"][0]["columns"][0]["is_primary_key"] is True
