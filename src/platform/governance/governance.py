# =============================================================================
# Governance — KMS envelope (DEK por versión, KEK derivada), retention purge,
# DSR export/erasure (GDPR), compliance events.
# =============================================================================
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


def _kek() -> bytes:
    return hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()


def _aesgcm(key: bytes, data: bytes) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def _aesgcm_decrypt(key: bytes, blob: str) -> bytes:
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


# ---------------------------------------------------------------------------
# KMS envelope: cada versión de key tiene un DEK cifrado con la KEK.
# ---------------------------------------------------------------------------
async def _get_dek(version: int) -> bytes:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT dek_enc FROM kms_keys WHERE key_version = :v"),
                {"v": version},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise ValueError(f"KMS key version {version} not found")
    return _aesgcm_decrypt(_kek(), row.dek_enc)


async def _active_version() -> int:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT key_version FROM kms_keys WHERE status = 'active' "
                    "ORDER BY key_version DESC LIMIT 1"
                )
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise ValueError("No active KMS key")
    return int(row.key_version)


async def _retire_active(session) -> bool:
    active = (
        await session.execute(
            text(
                "SELECT id, key_version FROM kms_keys "
                "WHERE status = 'active' ORDER BY key_version DESC LIMIT 1"
            )
        )
    ).fetchone()
    if active:
        await session.execute(
            text(
                "UPDATE kms_keys SET status = 'retired', retired_at = NOW() "
                "WHERE id = :kid"
            ),
            {"kid": active.id},
        )
        return True
    return False


async def create_kms_key(name: str = "default") -> dict:
    session = await get_async_session()
    try:
        retired = await _retire_active(session)
        current = (
            await session.execute(
                text("SELECT COALESCE(MAX(key_version), 0) FROM kms_keys")
            )
        ).scalar()
        version = int(current) + 1
        dek = secrets.token_bytes(32)
        dek_enc = _aesgcm(_kek(), dek)
        key_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO kms_keys (id, name, key_version, status, dek_enc, rotated_at) "
                "VALUES (:id, :name, :v, 'active', :dek, NOW())"
            ),
            {"id": key_id, "name": name, "v": version, "dek": dek_enc},
        )
        await session.commit()
        return {
            "id": str(key_id),
            "name": name,
            "key_version": version,
            "status": "active",
            "previous_retired": retired,
        }
    finally:
        await session.close()


async def rotate_kms_key() -> dict:
    """Retira la activa y crea una nueva versión (las viejas siguen descifrando)."""
    session = await get_async_session()
    try:
        retired = await _retire_active(session)
        current = (
            await session.execute(
                text("SELECT COALESCE(MAX(key_version), 0) FROM kms_keys")
            )
        ).scalar()
        version = int(current) + 1
        dek = secrets.token_bytes(32)
        key_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO kms_keys (id, name, key_version, status, dek_enc, rotated_at) "
                "VALUES (:id, 'default', :v, 'active', :dek, NOW())"
            ),
            {"id": key_id, "v": version, "dek": _aesgcm(_kek(), dek)},
        )
        await session.commit()
        return {
            "id": str(key_id),
            "name": "default",
            "key_version": version,
            "status": "active",
            "previous_retired": retired,
        }
    finally:
        await session.close()


async def list_kms_keys() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, key_version, status, created_at, rotated_at, "
                    "retired_at FROM kms_keys ORDER BY key_version"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "key_version": int(r.key_version),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "rotated_at": r.rotated_at.isoformat() if r.rotated_at else None,
            "retired_at": r.retired_at.isoformat() if r.retired_at else None,
        }
        for r in rows
    ]


async def kms_status() -> dict:
    keys = await list_kms_keys()
    return {
        "keys": len(keys),
        "active_version": int(keys[-1]["key_version"]) if keys else None,
        "active_status": keys[-1]["status"] if keys else "uninitialized",
    }


async def envelope_encrypt(plaintext: bytes) -> dict:
    """Cifra con el DEK activo; devuelve version.blob + version."""
    version = await _active_version()
    dek = await _get_dek(version)
    blob = _aesgcm(dek, plaintext)
    return {"key_version": version, "ciphertext": blob}


async def envelope_decrypt(key_version: int, ciphertext: str) -> bytes:
    dek = await _get_dek(key_version)
    return _aesgcm_decrypt(dek, ciphertext)


# ---------------------------------------------------------------------------
# Compliance events
# ---------------------------------------------------------------------------
async def record_compliance_event(
    organization_id: UUID,
    event_type: str,
    metadata: dict | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO compliance_events (id, organization_id, event_type, "
                "actor_user_id, metadata) VALUES (gen_random_uuid(), :oid, :etype, "
                ":actor, :meta)"
            ),
            {
                "oid": organization_id,
                "etype": event_type[:40],
                "actor": actor_user_id,
                "meta": json.dumps(metadata or {}),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def list_compliance_events(organization_id: UUID | None, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (  # noqa: E501
            "SELECT id, organization_id, event_type, actor_user_id, metadata, created_at "
            "FROM compliance_events WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "event_type": r.event_type,
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "metadata": r.metadata or {},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Perfil de governance por org
# ---------------------------------------------------------------------------
async def get_org_governance(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT retention_days, data_residency_region, dsr_contact_email "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "organization_id": str(organization_id),
        "retention_days": int(org.retention_days or 365),
        "data_residency_region": org.data_residency_region,
        "dsr_contact_email": org.dsr_contact_email,
    }


async def set_org_governance(
    organization_id: UUID,
    *,
    retention_days: int | None = None,
    data_residency_region: str | None = None,
    dsr_contact_email: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"oid": organization_id}
        if retention_days is not None:
            sets.append("retention_days = :ret")
            params["ret"] = retention_days
        if data_residency_region is not None:
            sets.append("data_residency_region = :region")
            params["region"] = data_residency_region
        if dsr_contact_email is not None:
            sets.append("dsr_contact_email = :email")
            params["email"] = dsr_contact_email
        if sets:
            await session.execute(
                text(
                    f"UPDATE organizations SET {', '.join(sets)} WHERE id = :oid"  # noqa: S608 (sets whitelisted)
                ),
                params,
            )
            await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Retention enforcement
# ---------------------------------------------------------------------------
async def enforce_retention(dry_run: bool = True, organization_id: UUID | None = None) -> dict:
    """Purgar usage_events/api_logs/audit_logs más viejos que retention_days."""
    session = await get_async_session()
    try:
        sql = "SELECT id, retention_days FROM organizations WHERE status <> 'deleted'"
        params: dict = {}
        if organization_id is not None:
            sql += " AND id = :oid "
            params["oid"] = organization_id
        orgs = (await session.execute(text(sql), params)).fetchall()
        results = []
        for org in orgs:
            retention = int(org.retention_days or 365)
            counts: dict[str, int] = {}
            for table in ("usage_events", "api_logs", "audit_logs"):
                counts[table] = int(
                    (
                        await session.execute(
                            text(
                                f"SELECT COUNT(*) FROM {table} "  # noqa: S608 (tablas fijas)
                                "WHERE organization_id = :oid "
                                "AND created_at < NOW() - MAKE_INTERVAL(days => :ret)"
                            ),
                            {"oid": org.id, "ret": retention},
                        )
                    ).scalar()
                    or 0
                )
            results.append(
                {
                    "organization_id": str(org.id),
                    "retention_days": retention,
                    "expired": counts,
                }
            )
            if not dry_run and sum(counts.values()) > 0:
                for table in ("usage_events", "api_logs", "audit_logs"):
                    await session.execute(
                        text(
                            f"DELETE FROM {table} "  # noqa: S608 (tablas fijas)
                            "WHERE organization_id = :oid "
                            "AND created_at < NOW() - MAKE_INTERVAL(days => :ret)"
                        ),
                        {"oid": org.id, "ret": retention},
                    )
        if not dry_run:
            await session.commit()
    finally:
        await session.close()
    if not dry_run and organization_id is not None:
        await record_compliance_event(
            organization_id, "retention.purge", metadata={"dry_run": False}
        )
    return {"dry_run": dry_run, "organizations": results}


# ---------------------------------------------------------------------------
# DSR (GDPR)
# ---------------------------------------------------------------------------
DSR_DIR = Path(get_settings().DR_BACKUP_DIR).parent / "dsr"


def _dsr_dir(organization_id: UUID) -> Path:
    d = DSR_DIR / str(organization_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def dsr_export(organization_id: UUID) -> dict:
    """Exporta datos personales; el artefacto se cifra con KMS envelope."""
    session = await get_async_session()
    try:
        users = (
            await session.execute(
                text(
                    "SELECT id, external_id, email, role, created_at, last_active_at "
                    "FROM users WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        memberships = (
            await session.execute(
                text(
                    "SELECT u.email, r.name AS role_name FROM memberships m "
                    "JOIN users u ON u.id = m.user_id "
                    "JOIN roles r ON r.id = m.role_id "
                    "WHERE m.organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        audit_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_logs WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
        usage_summary = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()

    payload = {
        "organization_id": str(organization_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "users": [
            {
                "id": str(u.id),
                "external_id": u.external_id,
                "email": u.email,
                "role": u.role,
                "created_at": u.created_at.isoformat(),
                "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
            }
            for u in users
        ],
        "memberships": [
            {"email": m.email, "role": m.role_name} for m in memberships
        ],
        "audit_entries": audit_count,
        "usage": {
            "requests": int(usage_summary.requests or 0),
            "cost": round(float(usage_summary.cost or 0.0), 6),
        },
    }
    raw = json.dumps(payload, indent=2, default=str).encode()
    receipt = hashlib.sha256(raw).hexdigest()
    encrypted = await envelope_encrypt(raw)
    artifact = _dsr_dir(organization_id) / f"dsr_{receipt[:12]}.json.enc"
    artifact.write_text(json.dumps(encrypted))
    await record_compliance_event(
        organization_id,
        "dsr.export",
        metadata={"receipt": receipt, "users": len(users), "artifact": artifact.name},
    )
    return {
        "status": "exported",
        "receipt_sha256": receipt,
        "key_version": encrypted["key_version"],
        "artifact": artifact.name,
        "users": len(users),
        "audit_entries": audit_count,
        "usage_requests": int(usage_summary.requests or 0),
    }


async def dsr_erasure(organization_id: UUID) -> dict:
    """Borra datos personales: anonimiza usuarios, elimina actividad y secretos."""
    session = await get_async_session()
    try:
        users = (
            await session.execute(
                text("SELECT id, email FROM users WHERE organization_id = :oid"),
                {"oid": organization_id},
            )
        ).fetchall()
        erased = 0
        for u in users:
            ident = (u.email or str(u.id)).lower()
            fake = f"{hashlib.sha256(ident.encode()).hexdigest()[:24]}@erased.invalid"
            await session.execute(
                text(
                    "UPDATE users SET email = :fake, external_id = 'erased', "
                    "email_hash = :eh, password_hash = NULL, last_active_at = NULL "
                    "WHERE id = :uid"
                ),
                {"fake": fake, "eh": hashlib.sha256(fake.encode()).hexdigest(), "uid": u.id},
            )
            erased += 1
        # Actividad y datos personales.
        await session.execute(
            text("DELETE FROM memberships WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.execute(
            text("DELETE FROM api_logs WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.execute(
            text("DELETE FROM usage_events WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.execute(
            text("DELETE FROM audit_logs WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.execute(
            text("DELETE FROM connector_secrets WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.execute(
            text("DELETE FROM organization_invites WHERE organization_id = :oid"),
            {"oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    await record_compliance_event(
        organization_id, "dsr.erasure", metadata={"users_erased": erased}
    )
    return {"status": "erased", "users_erased": erased}
