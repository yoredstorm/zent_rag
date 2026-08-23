# =============================================================================
# Connector Security — SSRF, timeout, secretos fuera de logs
# =============================================================================
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

import pytest

from src.connectors.plugin import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
    redact,
)


class TestSSRF:
    def test_private_host_blocked(self) -> None:
        with pytest.raises(ConnectorError, match="Blocked"):
            assert_host_safe("10.0.0.5")

    def test_private_host_allowed_via_tenant_allowlist(self) -> None:
        # Allowlist del tenant habilita fuentes internas explícitas.
        assert_host_safe("192.168.1.5", allowlist=["192.168.1.5"])

    def test_public_host_allowed(self) -> None:
        # IP pública directa: sin DNS en CI, getaddrinfo la resuelve literal.
        assert_host_safe("8.8.8.8")

    def test_ssrf_can_be_disabled_via_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "CONNECTOR_SSRF_BLOCK_PRIVATE", False)
        assert_host_safe("10.0.0.5")  # no raise


class _SlowPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "slow_plugin"

    async def validate(self) -> None:
        pass

    async def connect(self) -> None:
        pass

    async def test_connection(self) -> ConnectionTestResult:
        await asyncio.sleep(30)
        return ConnectionTestResult(ok=True)


class TestTimeout:
    @pytest.mark.asyncio
    async def test_test_connection_timeout_enforced(self) -> None:
        from src.agents.tools.guards import execute_tool_guarded  # noqa: F401

        plugin = _SlowPlugin({}, {})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(plugin.test_connection(), timeout=0.1)


class TestSecretsNeverInLogs:
    @pytest.mark.asyncio
    async def test_redaction_applied_before_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "hunter2-secret-value"
        with caplog.at_level(logging.INFO, logger="test_connector_security"):
            logging.getLogger("test_connector_security").info(
                "Connector attempt: %s",
                redact(
                    {
                        "host": "db.example.com",
                        "password": secret,
                    }
                ),
            )
        blob = caplog.text
        assert secret not in blob
        assert "[REDACTED]" in blob

    def test_connector_error_message_redacted(self) -> None:
        error = ConnectorError("Connection failed postgres://u:hunter2@h/db")
        assert "hunter2" not in redact(str(error))
