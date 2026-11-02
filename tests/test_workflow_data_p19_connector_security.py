# =============================================================================
# P19.1-08 - Politica de red/TLS del conector PostgreSQL.
# =============================================================================
from __future__ import annotations

import ssl
from uuid import uuid4

import pytest

from src.platform.workflows.bindings import BindingError
from src.platform.workflows.connector_security import prepare_connector_target


def _config(**overrides):
    data = {
        "host": "127.0.0.1",
        "port": 55432,
        "database": "demo",
        "user": "reader",
    }
    data.update(overrides)
    return data


async def _target(config, *, environment="development", policy=None):
    return await prepare_connector_target(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        connector_id=uuid4(),
        config=config,
        password="secret",
        policy_config=policy,
    )


@pytest.mark.asyncio
async def test_production_blocks_loopback_and_missing_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENVIRONMENT", "production")
    with pytest.raises(BindingError) as exc:
        await _target(_config(ssl_mode="verify-full"))
    assert exc.value.code == "POLICY_DENIED", exc.value.message
    with pytest.raises(BindingError) as exc:
        await _target(_config(host="93.184.216.34"))
    assert exc.value.code == "POLICY_DENIED", exc.value.message


@pytest.mark.asyncio
async def test_production_rejects_ssl_require_without_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_ENVIRONMENT", "production")
    with pytest.raises(BindingError) as exc:
        await _target(_config(host="93.184.216.34", ssl_mode="require"))
    assert exc.value.code == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_verify_full_builds_hostname_checking_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_ENVIRONMENT", "production")
    # Resolucion real de un host de documentacion; el test no abre conexion.
    target = await _target(_config(host="93.184.216.34", ssl_mode="verify-full"))
    context = target.connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.asyncio
async def test_metadata_and_forbidden_ports_are_blocked() -> None:
    for host in ("169.254.169.254", "metadata.google.internal"):
        with pytest.raises(BindingError) as exc:
            await _target(_config(host=host))
        assert exc.value.code == "POLICY_DENIED"
    with pytest.raises(BindingError) as exc:
        await _target(_config(port=6379))
    assert exc.value.code == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_host_allowlist_is_enforced() -> None:
    with pytest.raises(BindingError) as exc:
        await _target(_config(host="127.0.0.1"), policy={"allowed_hosts": ["93.184.216.34"]})
    assert exc.value.code == "POLICY_DENIED"
    target = await _target(
        _config(host="127.0.0.1"), policy={"allowed_hosts": ["127.0.0.1"]}
    )
    assert target.host == "127.0.0.1"
