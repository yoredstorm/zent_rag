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


@pytest.mark.asyncio
async def test_engine_cache_is_bounded_and_reuses_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.platform.workflows import connector_security as security

    monkeypatch.setenv("RAG_CONNECTOR_POOL_ENABLED", "true")
    monkeypatch.setenv("RAG_CONNECTOR_POOL_MAX", "2")
    security._ENGINES.clear()
    target = await _target(_config(host="127.0.0.1", ssl_mode="disable"))
    dsn = "postgresql+asyncpg://reader:secret@127.0.0.1:55432/demo"
    first = security.get_connector_engine(dsn, target)
    second = security.get_connector_engine(dsn, target)
    assert first is second

    other = await _target(_config(host="127.0.0.1", port=55433, ssl_mode="disable"))
    security.get_connector_engine(dsn + "2", other)
    third = await _target(_config(host="127.0.0.1", port=55434, ssl_mode="disable"))
    security.get_connector_engine(dsn + "3", third)
    assert len(security._ENGINES) <= 2
    await security.dispose_connector_engines()
    security._ENGINES.clear()


@pytest.mark.asyncio
async def test_tls_verify_full_rejects_wrong_hostname(tmp_path) -> None:
    import asyncio
    import datetime
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from src.platform.workflows.connector_security import _ssl_context

    def _name(value: str) -> x509.Name:
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, value)])

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("P19 Test CA"))
        .issuer_name(_name("P19 Test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("localhost"))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server.key"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_path, key_path)

    async def _handler(reader, writer):
        await reader.read(1)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        client_ctx = _ssl_context(
            {"ssl_mode": "verify-full", "ssl_ca_file": str(ca_path)}, production=True
        )
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=client_ctx, server_hostname="localhost"
        )
        writer.close()
        await writer.wait_closed()

        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.open_connection(
                "127.0.0.1", port, ssl=client_ctx, server_hostname="wrong.example"
            )
    finally:
        server.close()
        await server.wait_closed()
