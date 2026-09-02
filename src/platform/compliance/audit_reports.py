# =============================================================================
# Tenant Audit & Compliance Reports v2 — reportes por org con hash
# encadenado (integridad) y cumplimiento por framework (SOC2/GDPR/ISO27001).
# =============================================================================
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

REPORT_DIR = Path("data") / "reports"
FRAMEWORKS = ("soc2", "gdpr", "iso27001")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Recolección de datos por tipo de reporte
# ---------------------------------------------------------------------------
async def _collect_activity(organization_id: UUID, period_start: date, period_end: date) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_user_id, action, resource_type, resource_id, "
                    "ip_address, created_at FROM audit_logs "
                    "WHERE organization_id = :oid "
                    "AND created_at::date BETWEEN :start AND :end "
                    "ORDER BY created_at DESC LIMIT 2000"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": str(r.resource_id) if r.resource_id else None,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _collect_config_changes(organization_id: UUID, period_start: date, period_end: date) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT agent_id, version_number, status, notes, created_at "
                    "FROM agent_versions WHERE organization_id = :oid "
                    "AND created_at::date BETWEEN :start AND :end "
                    "ORDER BY created_at DESC LIMIT 2000"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
        agents = (
            await session.execute(
                text(
                    "SELECT id, name, model, config_json, updated_at FROM agents "
                    "WHERE organization_id = :oid AND updated_at::date BETWEEN :start AND :end "
                    "ORDER BY updated_at DESC LIMIT 2000"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "agent_versions": [
            {
                "agent_id": str(r.agent_id),
                "version": int(r.version_number or 0),
                "status": r.status,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "agents": [
            {
                "id": str(r.id),
                "name": r.name,
                "model": r.model,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in agents
        ],
    }


async def _collect_exports(organization_id: UUID, period_start: date, period_end: date) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, scope, anonymized, status, size_bytes, row_counts, "
                    "requested_by, requested_at FROM data_exports "
                    "WHERE organization_id = :oid "
                    "AND requested_at::date BETWEEN :start AND :end "
                    "ORDER BY requested_at DESC"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "scope": r.scope,
            "anonymized": bool(r.anonymized),
            "status": r.status,
            "size_bytes": int(r.size_bytes),
            "row_counts": r.row_counts,
            "requested_by": str(r.requested_by) if r.requested_by else None,
            "requested_at": r.requested_at.isoformat(),
        }
        for r in rows
    ]


async def _collect_incidents(organization_id: UUID, period_start: date, period_end: date) -> list[dict]:
    session = await get_async_session()
    try:
        safety = (
            await session.execute(
                text(
                    "SELECT id, direction, rule_name, score, action, status, created_at "
                    "FROM safety_incidents WHERE organization_id = :oid "
                    "AND created_at::date BETWEEN :start AND :end "
                    "ORDER BY created_at DESC LIMIT 2000"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
        ops = (
            await session.execute(
                text(
                    "SELECT id, source, severity, status, title, detected_at FROM incidents "
                    "WHERE organization_id = :oid "
                    "AND detected_at::date BETWEEN :start AND :end "
                    "ORDER BY detected_at DESC LIMIT 2000"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "safety_incidents": [
            {
                "id": str(r.id),
                "direction": r.direction,
                "rule_name": r.rule_name,
                "score": round(float(r.score), 3),
                "action": r.action,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in safety
        ],
        "incidents": [
            {
                "id": str(r.id),
                "source": r.source,
                "severity": r.severity,
                "status": r.status,
                "title": r.title,
                "detected_at": r.detected_at.isoformat(),
            }
            for r in ops
        ],
    }


def _render_csv(sections: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "field", "value"])
    for section, data in sections.items():
        if isinstance(data, list):
            for row in data:
                for key, value in row.items():
                    writer.writerow([section, key, value])
        elif isinstance(data, dict):
            writer.writerow([section, "_", ""])
            for key, value in data.items():
                writer.writerow([section, key, json_dumps(value)])
    return buffer.getvalue()


def json_dumps(value) -> str:
    import json

    return json.dumps(value, default=str)


async def _render_pdf(title: str, sections: dict) -> bytes:
    from src.platform.billing.invoices import _minimal_pdf

    lines = [f"Reporte: {title}", f"Generado: {datetime.now(timezone.utc).isoformat()}", ""]
    for section, data in sections.items():
        lines.append(f"== {section} ==")
        if isinstance(data, list):
            for row in data[:50]:
                lines.append(f"- {json_dumps(row)[:120]}")
        elif isinstance(data, dict):
            for key, value in list(data.items())[:20]:
                lines.append(f"- {key}: {json_dumps(value)[:120]}")
    return _minimal_pdf(title, lines)


# ---------------------------------------------------------------------------
# Generación + cadena de integridad
# ---------------------------------------------------------------------------
async def generate_report(
    organization_id: UUID,
    report_type: str,
    period_start: date,
    period_end: date,
    fmt: str = "csv",
    created_by: UUID | None = None,
) -> dict:
    sections: dict = {}
    if report_type in ("activity", "full"):
        sections["activity"] = await _collect_activity(organization_id, period_start, period_end)
    if report_type in ("config_changes", "full"):
        sections["config_changes"] = await _collect_config_changes(organization_id, period_start, period_end)
    if report_type in ("exports", "full"):
        sections["exports"] = await _collect_exports(organization_id, period_start, period_end)
    if report_type in ("incidents", "full"):
        sections["incidents"] = await _collect_incidents(organization_id, period_start, period_end)

    if fmt == "csv":
        content = _render_csv(sections)
        media = "csv"
    else:
        content_bytes = await _render_pdf(f"audit-{report_type}", sections)
        content = content_bytes.decode("latin-1")
        media = "pdf"
    integrity_hash = _sha256(content)

    session = await get_async_session()
    try:
        prev = (
            await session.execute(
                text(
                    "SELECT integrity_hash FROM audit_reports WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        prev_hash = prev.integrity_hash if prev else None
        file_key = f"reports/{organization_id}/{uuid4().hex}.{media}"
        out_path = REPORT_DIR / file_key
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content.encode("latin-1", "replace") if media == "pdf" else content.encode("utf-8"))
        row = (
            await session.execute(
                text(
                    "INSERT INTO audit_reports (id, organization_id, report_type, "
                    "period_start, period_end, format, file_key, size_bytes, "
                    "integrity_hash, prev_hash, created_by) "
                    "VALUES (gen_random_uuid(), :oid, :rtype, :start, :end, :fmt, "
                    ":fkey, :size, :ihash, :phash, :by) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "rtype": report_type[:30],
                    "start": period_start,
                    "end": period_end,
                    "fmt": fmt[:10],
                    "fkey": file_key,
                    "size": out_path.stat().st_size,
                    "ihash": integrity_hash,
                    "phash": prev_hash,
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "report_type": report_type,
        "format": fmt,
        "integrity_hash": integrity_hash,
        "prev_hash": prev_hash,
        "chain_length": None,
    }


async def list_reports(organization_id: UUID | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"limit": limit}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, report_type, period_start, period_end, "
                    "format, size_bytes, integrity_hash, prev_hash, created_by, created_at "
                    "FROM audit_reports" + where + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "reports": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "report_type": r.report_type,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "format": r.format,
                "size_bytes": int(r.size_bytes),
                "integrity_hash": r.integrity_hash,
                "prev_hash": r.prev_hash,
                "created_by": str(r.created_by) if r.created_by else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def get_report_file(report_id: UUID) -> tuple[bytes, str] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT file_key, format FROM audit_reports WHERE id = :rid"),
                {"rid": report_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.file_key:
        return None
    path = REPORT_DIR / row.file_key
    if not path.exists():
        return None
    return path.read_bytes(), row.format


async def verify_report(report_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT organization_id, report_type, file_key, integrity_hash, "
                    "prev_hash, created_at FROM audit_reports WHERE id = :rid"
                ),
                {"rid": report_id},
            )
        ).fetchone()
        if row is None:
            return None
        chain = (
            await session.execute(
                text(
                    "SELECT integrity_hash FROM audit_reports WHERE organization_id = :oid "
                    "AND created_at < :created ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": row.organization_id, "created": row.created_at},
            )
        ).fetchone()
        actual_prev = chain.integrity_hash if chain else None
    finally:
        await session.close()
    path = REPORT_DIR / row.file_key
    if not path.exists():
        return {"verified": False, "reason": "file_missing"}
    content = path.read_bytes().decode("utf-8", errors="replace")
    current_hash = _sha256(content)
    prev_ok = (row.prev_hash is None and actual_prev is None) or row.prev_hash == actual_prev
    return {
        "verified": current_hash == row.integrity_hash and prev_ok,
        "current_hash": current_hash,
        "stored_hash": row.integrity_hash,
        "chain_prev_hash": row.prev_hash,
        "computed_prev_hash": actual_prev,
        "chain_ok": prev_ok,
    }


# ---------------------------------------------------------------------------
# Compliance por framework
# ---------------------------------------------------------------------------
async def list_controls(framework: str | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if framework:
            where = " WHERE framework = :fw"
            params["fw"] = framework
        rows = (
            await session.execute(
                text(
                    "SELECT framework, control_id, title, category, required_evidence "
                    "FROM compliance_controls" + where + " ORDER BY framework, control_id"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "controls": [
            {
                "framework": r.framework,
                "control_id": r.control_id,
                "title": r.title,
                "category": r.category,
                "required_evidence": r.required_evidence,
            }
            for r in rows
        ]
    }


async def compliance_status(organization_id: UUID, framework: str) -> dict:
    """Estado por control; auto-inicializa en 'review'."""
    controls = (await list_controls(framework))["controls"]
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT control_id, status, evidence, updated_at FROM compliance_status "
                    "WHERE organization_id = :oid AND framework = :fw"
                ),
                {"oid": organization_id, "fw": framework},
            )
        ).fetchall()
    finally:
        await session.close()
    status_by_id = {r.control_id: r for r in rows}
    items = []
    pass_count = fail_count = review_count = na_count = 0
    for control in controls:
        existing = status_by_id.get(control["control_id"])
        status = existing.status if existing else "review"
        evidence = existing.evidence if existing else None
        updated = existing.updated_at.isoformat() if existing else None
        items.append({**control, "status": status, "evidence": evidence, "updated_at": updated})
        if status == "pass":
            pass_count += 1
        elif status == "fail":
            fail_count += 1
        elif status == "na":
            na_count += 1
        else:
            review_count += 1
    total = max(len(items), 1)
    return {
        "framework": framework,
        "controls": items,
        "counts": {
            "pass": pass_count,
            "fail": fail_count,
            "review": review_count,
            "na": na_count,
        },
        "score": round(pass_count / total * 100, 1),
    }


async def update_control_status(
    organization_id: UUID,
    framework: str,
    control_id: str,
    status: str,
    evidence: str | None = None,
) -> dict:
    if status not in ("pass", "fail", "na", "review"):
        raise ValueError("status must be pass|fail|na|review")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO compliance_status (id, organization_id, framework, "
                "control_id, status, evidence) "
                "VALUES (gen_random_uuid(), :oid, :fw, :cid, :status, :evidence) "
                "ON CONFLICT (organization_id, framework, control_id) DO UPDATE SET "
                "status = EXCLUDED.status, evidence = EXCLUDED.evidence, updated_at = NOW()"
            ),
            {
                "oid": organization_id,
                "fw": framework[:30],
                "cid": control_id[:40],
                "status": status,
                "evidence": evidence,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return await compliance_status(organization_id, framework)


async def compliance_dashboard(organization_id: UUID | None = None) -> dict:
    target = organization_id or UUID(int=0)
    frameworks = []
    for framework in FRAMEWORKS:
        status = await compliance_status(target, framework)
        frameworks.append(
            {
                "framework": framework,
                **status["counts"],
                "score": status["score"],
                "controls": len(status["controls"]),
            }
        )
    return {"frameworks": frameworks}
