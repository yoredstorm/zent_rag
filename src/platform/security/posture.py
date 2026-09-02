# =============================================================================
# Security Center — posture score por tenant, detección de secretos/leaks,
# findings con resolución y revoke one-click.
# =============================================================================
from __future__ import annotations

import json
import re
from datetime import timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("api_key", re.compile(r"\b(zent_sk_(live|test)_[A-Za-z0-9_-]{16,})\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.IGNORECASE)),
    ("password", re.compile(r"(?i)\b(password|passwd|secret)\s*[=:]\s*[^\s]{6,}")),
    ("smtp_password", re.compile(r"(?i)\bSMTP_PASSWORD\s*[=:]\s*\S+")),
]


def scan_secrets(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, pattern in _SECRET_PATTERNS:
        found = pattern.findall(text or "")
        if found:
            counts[name] = len(found)
    return counts


# ---------------------------------------------------------------------------
# Posture score
# ---------------------------------------------------------------------------
async def posture_score(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT sso_enabled, scim_enabled, key_max_age_days, "
                    "dsr_contact_email, data_residency_region, ai_pii_masking_enabled, "
                    "ops_webhook_url FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        if org is None:
            return {"organization_id": str(organization_id), "score": 0, "components": []}
        keys = (
            await session.execute(
                text(
                    "SELECT expires_at, rate_limit_per_minute, ip_allowlist, "
                    "created_at FROM api_keys WHERE organization_id = :oid "
                    "AND is_active = true"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()

    from datetime import datetime as _dt

    now = _dt.now(timezone.utc)
    components: list[dict] = []

    def _check(name: str, ok: bool, weight: int, detail: str) -> None:
        components.append({"name": name, "ok": ok, "weight": weight, "detail": detail})

    _check("sso_enabled", bool(org.sso_enabled), 15, "SSO OIDC activo" if org.sso_enabled else "SSO desactivado")
    _check("scim_enabled", bool(org.scim_enabled), 10,  # noqa: E501
           "SCIM provisioning activo" if org.scim_enabled else "SCIM desactivado")
    _check("key_rotation_policy", org.key_max_age_days is not None, 10,
           f"Política de rotación: {org.key_max_age_days} días" if org.key_max_age_days else "Sin política de rotación")
    _check("dsr_contact", bool(org.dsr_contact_email), 10,  # noqa: E501
           "Contacto DSR configurado" if org.dsr_contact_email else "Sin contacto DSR")
    _check("data_residency", bool(org.data_residency_region), 10,
           f"Residencia: {org.data_residency_region}" if org.data_residency_region else "Sin pin de residencia")
    _check("pii_masking", bool(org.ai_pii_masking_enabled), 15,  # noqa: E501
           "PII masking activo" if org.ai_pii_masking_enabled else "PII masking desactivado")
    _check("ops_webhook", bool(org.ops_webhook_url), 5,  # noqa: E501
           "Webhook de alertas configurado" if org.ops_webhook_url else "Sin webhook de alertas")

    keys_list = list(keys)
    has_keys = len(keys_list) > 0
    keys_no_expiry = sum(1 for k in keys_list if k.expires_at is None)
    keys_old = sum(1 for k in keys_list if k.created_at and (now - k.created_at).days > 90)
    keys_no_rate = sum(1 for k in keys_list if k.rate_limit_per_minute is None)
    keys_no_allowlist = sum(1 for k in keys_list if not (k.ip_allowlist or []))
    _check("keys_with_expiry", not has_keys or keys_no_expiry == 0, 10,
           "Todas las keys con expiración" if keys_no_expiry == 0 else f"{keys_no_expiry} keys sin expiración")
    _check("keys_with_rate_limit", not has_keys or keys_no_rate == 0, 5,
           "Rate limit en todas las keys" if keys_no_rate == 0 else f"{keys_no_rate} keys sin rate limit")
    _check("key_age", keys_old == 0, 5, "Keys recientes" if keys_old == 0 else f"{keys_old} keys con >90 días")
    _check("key_allowlist", not has_keys or keys_no_allowlist == 0, 5,
           "IP allowlist en keys" if keys_no_allowlist == 0 else f"{keys_no_allowlist} keys sin allowlist")

    score = sum(c["weight"] for c in components if c["ok"])
    return {
        "organization_id": str(organization_id),
        "score": min(score, 100),
        "components": components,
    }


async def posture_for_all() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT id FROM organizations WHERE status <> 'deleted'")
            )
        ).fetchall()
    finally:
        await session.close()
    return [await posture_score(r.id) for r in rows]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
async def _insert_finding(
    organization_id: UUID | None,
    finding_type: str,
    severity: str,
    target_type: str,
    target_id: str | None,
    detail: str,
) -> bool:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM security_findings WHERE finding_type = :ftype "
                    "AND status = 'open' AND (target_id IS NOT DISTINCT FROM :tid) "
                    "AND created_at > NOW() - INTERVAL '7 days' LIMIT 1"
                ),
                {"ftype": finding_type, "tid": target_id},
            )
        ).fetchone()
        if exists:
            return False
        await session.execute(
            text(
                "INSERT INTO security_findings (id, organization_id, finding_type, "
                "severity, target_type, target_id, detail) "
                "VALUES (gen_random_uuid(), :oid, :ftype, :sev, :ttype, :tid, :detail)"
            ),
            {
                "oid": organization_id,
                "ftype": finding_type,
                "sev": severity,
                "ttype": target_type,
                "tid": target_id,
                "detail": detail[:500],
            },
        )
        await session.commit()
        return True
    finally:
        await session.close()


async def run_security_scan(organization_id: UUID | None = None) -> dict:
    """Posture + scan de secretos en prompts/marketplace + leaks de API keys."""

    findings_created: list[dict] = []

    # 1) Secretos en prompts de los agentes.
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, name, system_prompt FROM agents "
            "WHERE system_prompt IS NOT NULL AND system_prompt <> '' "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        agents = (await session.execute(text(sql), params)).fetchall()
        sql2 = (
            "SELECT id, name, content FROM prompt_templates "
            "WHERE content IS NOT NULL AND content <> '' "
        )
        templates = (await session.execute(text(sql2), params)).fetchall()
        sql3 = (
            "SELECT id, organization_id, name, agent_snapshot FROM marketplace_listings "
            "WHERE status = 'published' "
        )
        listings = (await session.execute(text(sql3), params)).fetchall()
        sql4 = (
            "SELECT id, organization_id, error FROM api_logs "
            "WHERE error IS NOT NULL AND error LIKE '%zent_sk_%' "
        )
        leaks = (await session.execute(text(sql4), params)).fetchall()
    finally:
        await session.close()

    for a in agents:
        secrets = scan_secrets(a.system_prompt)
        if secrets:
            ok = await _insert_finding(
                a.organization_id, "secret_in_prompt", "critical",
                "agent", str(a.id),
                f"Agente '{a.name}': secretos en system_prompt ({json.dumps(secrets)})",
            )
            if ok:
                findings_created.append({"type": "secret_in_prompt", "agent_id": str(a.id)})
    for t in templates:
        secrets = scan_secrets(t.content)
        if secrets:
            ok = await _insert_finding(
                None, "secret_in_template", "high",
                "prompt_template", str(t.id),
                f"Template '{t.name}': secretos ({json.dumps(secrets)})",
            )
            if ok:
                findings_created.append({"type": "secret_in_template", "template_id": str(t.id)})
    for listing in listings:
        snap = listing.agent_snapshot or {}
        prompt = snap.get("system_prompt") or ""
        secrets = scan_secrets(prompt)
        if secrets:
            ok = await _insert_finding(
                listing.organization_id, "secret_in_marketplace", "critical",
                "listing", str(listing.id),
                f"Listing '{listing.name}': secretos en snapshot ({json.dumps(secrets)})",
            )
            if ok:
                findings_created.append({"type": "secret_in_marketplace", "listing_id": str(listing.id)})
    for leak in leaks:
        ok = await _insert_finding(
            leak.organization_id, "api_key_leak", "critical",
            "api_log", str(leak.id),
            f"Posible API key filtrada en error de api_log ({str(leak.id)[:8]})",
        )
        if ok:
            findings_created.append({"type": "api_key_leak", "api_log_id": str(leak.id)})

    return {"findings_created": findings_created, "count": len(findings_created)}


async def list_findings(
    organization_id: UUID | None, status: str | None = None, limit: int = 100
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, finding_type, severity, target_type, target_id, "
            "detail, status, created_at, resolved_at FROM security_findings WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        if status:
            sql += " AND status = :status "
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id) if r.organization_id else None,
            "finding_type": r.finding_type,
            "severity": r.severity,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in rows
    ]


async def resolve_finding(finding_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE security_findings SET status = 'resolved', resolved_at = NOW() "
                "WHERE id = :fid AND status = 'open'"
            ),
            {"fid": finding_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def revoke_leaked_key(organization_id: UUID, key_id: UUID) -> bool:
    """Revoke one-click de una key señalada como leak."""
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository

    repo = PostgresApiKeyRepository()
    key = await repo.get_key(key_id)
    if key is None or key.organization_id != organization_id:
        return False
    await repo.deactivate_key(key_id)
    return True
