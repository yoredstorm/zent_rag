# =============================================================================
# AI Governance — PII masking, anomaly detection, audit intelligence,
# prompt revisions, políticas de gobernanza por org.
# =============================================================================
from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# PII detection / masking
# ---------------------------------------------------------------------------
_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # Teléfono: exige separador entre grupos para no comerse DNI/RUC puros.
    "phone": re.compile(
        r"(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3}[\s.-]\d{3,4}(?!\d)"
    ),
    "dni": re.compile(r"(?<!\d)\d{8}(?!\d)"),
    "ruc": re.compile(r"(?<!\d)\d{11}(?!\d)"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "ip": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


def scan_pii(text: str) -> dict[str, int]:
    counts = {name: len(pat.findall(text)) for name, pat in _PII_PATTERNS.items()}
    return {k: v for k, v in counts.items() if v > 0}


def mask_pii(text: str) -> tuple[str, dict[str, int]]:
    masked = text
    counts: dict[str, int] = {}
    for name, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(masked)
        if not matches:
            continue
        counts[name] = len(matches)
        masked = pattern.sub(f"[{name}:***]", masked)
    return masked, counts


async def apply_guardrails(organization_id: UUID, content: str) -> tuple[str, dict[str, int]]:
    """Aplica políticas de la org (PII masking) a una respuesta."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT ai_pii_masking_enabled FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.ai_pii_masking_enabled:
        return content, {}
    return mask_pii(content)


# ---------------------------------------------------------------------------
# Políticas AI por org
# ---------------------------------------------------------------------------
async def get_ai_policies(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT ai_pii_masking_enabled, ai_guardrails "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "organization_id": str(organization_id),
        "pii_masking_enabled": bool(org.ai_pii_masking_enabled),
        "guardrails": org.ai_guardrails or {},
    }


async def set_ai_policies(
    organization_id: UUID,
    *,
    pii_masking_enabled: bool | None = None,
    guardrails: dict | None = None,
) -> None:
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"oid": organization_id}
        if pii_masking_enabled is not None:
            sets.append("ai_pii_masking_enabled = :pii")
            params["pii"] = pii_masking_enabled
        if guardrails is not None:
            sets.append("ai_guardrails = :guardrails")
            params["guardrails"] = json.dumps(guardrails)
        if sets:
            await session.execute(
                text(f"UPDATE organizations SET {', '.join(sets)} WHERE id = :oid"),  # noqa: S608 (sets whitelisted)
                params,
            )
            await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
ANOMALY_LOGIN_BURST = "failed_login_burst"
ANOMALY_API_ERROR_SPIKE = "api_error_spike"
ANOMALY_NIGHT_ACTIVITY = "night_activity"
ANOMALY_FORBIDDEN_SPIKE = "forbidden_spike"


async def _insert_anomaly(
    organization_id: UUID | None,
    anomaly_type: str,
    severity: str,
    message: str,
    metadata: dict | None = None,
) -> bool:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM anomaly_events WHERE anomaly_type = :atype "
                    "AND status = 'open' AND created_at > NOW() - INTERVAL '24 hours' "
                    "AND (organization_id IS NOT DISTINCT FROM :oid) LIMIT 1"
                ),
                {"atype": anomaly_type, "oid": organization_id},
            )
        ).fetchone()
        if exists:
            return False
        await session.execute(
            text(
                "INSERT INTO anomaly_events (id, organization_id, anomaly_type, "
                "severity, message, metadata) "
                "VALUES (gen_random_uuid(), :oid, :atype, :sev, :msg, :meta)"
            ),
            {
                "oid": organization_id,
                "atype": anomaly_type,
                "sev": severity,
                "msg": message[:500],
                "meta": json.dumps(metadata or {}),
            },
        )
        await session.commit()
        return True
    finally:
        await session.close()


async def run_anomaly_checks(organization_id: UUID | None = None) -> list[dict]:
    settings = get_settings()
    created: list[dict] = []

    session = await get_async_session()
    try:
        orgs = (
            await session.execute(
                text(
                    "SELECT id FROM organizations WHERE status <> 'deleted' "
                    "AND (CAST(:oid AS uuid) IS NULL OR id = :oid)"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()

    for org in orgs:
        oid = org.id

        # 1) Failed-login burst desde Redis (auth:fail:*).
        try:
            from src.infrastructure.redis.cache import _get_redis

            client = await _get_redis()
            keys = await client.keys("auth:fail:*")
            bursts = []
            total_failures = 0
            for key in keys:
                count = int(await client.get(key) or 0)
                total_failures += count
                if count >= 5:
                    bursts.append({"key": key.split(":", 2)[-1], "count": count})
            if total_failures >= 5:
                ok = await _insert_anomaly(
                    oid, ANOMALY_LOGIN_BURST, "critical",
                    f"Burst de logins fallidos: {total_failures} intentos en la ventana de auth",
                    metadata={"entries": (bursts or [{"total": total_failures}])[:10]},
                )
                if ok:
                    created.append({"type": ANOMALY_LOGIN_BURST, "organization_id": str(oid)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Login burst check failed", error=str(exc)[:150])

        # 2) API error spike (api_logs, última hora).
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS total, "
                    "COUNT(*) FILTER (WHERE status >= 500)::int AS errors "
                    "FROM api_logs WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '1 hour'"
                ),
                {"oid": oid},
            )
        ).fetchone()
        total = int(row.total or 0)
        errors = int(row.errors or 0)
        if total >= 20 and errors / total > 0.5:
            ok = await _insert_anomaly(
                oid, ANOMALY_API_ERROR_SPIKE, "critical",
                f"Error rate API 1h: {errors}/{total} ({(errors / total * 100):.0f}%)",
                metadata={"total": total, "errors": errors},
            )
            if ok:
                created.append({"type": ANOMALY_API_ERROR_SPIKE, "organization_id": str(oid)})

        # 3) Actividad nocturna (02:00-05:00, última semana).
        night = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int FROM audit_logs WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '7 days' "
                    "AND EXTRACT(HOUR FROM created_at) BETWEEN 2 AND 5"
                ),
                {"oid": oid},
            )
        ).scalar()
        if int(night or 0) >= 25:
            ok = await _insert_anomaly(
                oid, ANOMALY_NIGHT_ACTIVITY, "warning",
                f"Actividad inusual nocturna: {int(night or 0)} eventos 02:00-05:00 (7d)",
                metadata={"events": int(night or 0)},
            )
            if ok:
                created.append({"type": ANOMALY_NIGHT_ACTIVITY, "organization_id": str(oid)})

        # 4) Spike de 403 (audit_logs, última hora).
        forbidden = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int FROM audit_logs WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '1 hour' "
                    "AND metadata->>'status' = 'denied'"
                ),
                {"oid": oid},
            )
        ).scalar()
        if int(forbidden or 0) >= 10:
            ok = await _insert_anomaly(
                oid, ANOMALY_FORBIDDEN_SPIKE, "warning",
                f"Spike de accesos denegados: {int(forbidden or 0)} en 1h",
                metadata={"denied": int(forbidden or 0)},
            )
            if ok:
                created.append({"type": ANOMALY_FORBIDDEN_SPIKE, "organization_id": str(oid)})

    return created


async def list_anomalies(
    organization_id: UUID | None, status: str | None = None, limit: int = 50
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, anomaly_type, severity, message, metadata, "
            "status, created_at, acknowledged_at FROM anomaly_events WHERE 1=1 "
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
            "anomaly_type": r.anomaly_type,
            "severity": r.severity,
            "message": r.message,
            "metadata": r.metadata or {},
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "acknowledged_at": (
                r.acknowledged_at.isoformat() if r.acknowledged_at else None
            ),
        }
        for r in rows
    ]


async def resolve_anomaly(anomaly_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE anomaly_events SET status = 'resolved', acknowledged_at = NOW() "
                "WHERE id = :aid AND status <> 'resolved'"
            ),
            {"aid": anomaly_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Audit intelligence
# ---------------------------------------------------------------------------
async def audit_intelligence(organization_id: UUID | None) -> dict:
    session = await get_async_session()
    try:
        where = " WHERE 1=1 "
        params: dict = {}
        if organization_id is not None:
            where += " AND organization_id = :oid "
            params["oid"] = organization_id

        total = int(
            (
                await session.execute(
                    text(f"SELECT COUNT(*) FROM audit_logs{where}"), params  # noqa: S608 (where whitelisted)
                )
            ).scalar()
            or 0
        )
        top_actions = (
            await session.execute(
                text(
                    f"SELECT action, COUNT(*)::int AS n FROM audit_logs{where} "  # noqa: S608 (where whitelisted)
                    "GROUP BY action ORDER BY n DESC LIMIT 15"
                ),
                params,
            )
        ).fetchall()
        top_users = (
            await session.execute(
                text(
                    f"SELECT actor_user_id AS user_id, COUNT(*)::int AS n FROM audit_logs{where} "  # noqa: S608 (where whitelisted)
                    "AND actor_user_id IS NOT NULL GROUP BY actor_user_id ORDER BY n DESC LIMIT 10"
                ),
                params,
            )
        ).fetchall()
        timeline = (
            await session.execute(
                text(
                    "SELECT DATE_TRUNC('day', created_at)::date AS day, "  # noqa: S608 (where whitelisted)
                    f"COUNT(*)::int AS n FROM audit_logs{where} "
                    "AND created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY 1 ORDER BY 1"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "organization_id": str(organization_id) if organization_id else "all",
        "total_events": total,
        "top_actions": [{"action": r.action, "count": int(r.n)} for r in top_actions],
        "top_users": [{"user_id": str(r.user_id), "count": int(r.n)} for r in top_users],
        "timeline_30d": [{"date": r.day.isoformat(), "count": int(r.n)} for r in timeline],
    }


# ---------------------------------------------------------------------------
# Prompt revisions
# ---------------------------------------------------------------------------
async def save_prompt_revision(
    prompt_key: str, organization_id: UUID, content: str, created_by: UUID | None
) -> int:
    session = await get_async_session()
    try:
        current = int(
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) FROM prompt_revisions "
                        "WHERE prompt_key = :key AND organization_id = :oid"
                    ),
                    {"key": prompt_key, "oid": organization_id},
                )
            ).scalar()
            or 0
        )
        version = current + 1
        await session.execute(
            text(
                "INSERT INTO prompt_revisions (id, prompt_key, organization_id, "
                "version, content, created_by) "
                "VALUES (gen_random_uuid(), :key, :oid, :v, :content, :by)"
            ),
            {
                "key": prompt_key,
                "oid": organization_id,
                "v": version,
                "content": content,
                "by": created_by,
            },
        )
        await session.commit()
        return version
    finally:
        await session.close()


async def list_prompt_revisions(
    prompt_key: str, organization_id: UUID | None
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT version, content, created_by, created_at "
            "FROM prompt_revisions WHERE prompt_key = :key "
        )
        params: dict = {"key": prompt_key}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY version DESC LIMIT 20"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "version": int(r.version),
            "content": r.content,
            "created_by": str(r.created_by) if r.created_by else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
