# =============================================================================
# Tenant Audit & Compliance Reports v2 — reportes con integridad + compliance.
# =============================================================================
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/audit", tags=["Audit & Compliance"])


@router.get("/reports", summary="Reportes de auditoría del tenant")
async def tenant_audit_reports(request: Request):
    from src.platform.compliance.audit_reports import list_reports
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_reports(ctx.organization_id)


@router.post("/reports/generate", summary="Generar reporte de auditoría")
async def tenant_audit_report_generate(body: AuditReportIn, request: Request):
    from src.platform.compliance.audit_reports import generate_report
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    return await generate_report(
        ctx.organization_id,
        body.report_type,
        body.period_start,
        body.period_end,
        body.format,
        created_by=ctx.user_id,
    )


@router.get("/reports/{report_id}/download", summary="Descargar reporte")
async def tenant_audit_report_download(report_id: str, request: Request):
    from src.platform.compliance.audit_reports import get_report_file
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await get_report_file(UUID(report_id))
    if result is None:
        raise HTTPException(404, "Report not found")
    content, fmt = result
    return Response(
        content=content,
        media_type="application/pdf" if fmt == "pdf" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="audit-report-{report_id[:8]}.{fmt}"'
        },
    )


@router.get("/reports/{report_id}/verify", summary="Verificar integridad (hash encadenado)")
async def tenant_audit_report_verify(report_id: str, request: Request):
    from src.platform.compliance.audit_reports import verify_report
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await verify_report(UUID(report_id))
    if result is None:
        raise HTTPException(404, "Report not found")
    return result


@router.get("/compliance", summary="Estado de cumplimiento por framework")
async def tenant_compliance_status(request: Request, framework: str = "soc2"):
    from src.platform.compliance.audit_reports import compliance_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await compliance_status(ctx.organization_id, framework)


@router.put("/compliance", summary="Actualizar estado de un control")
async def tenant_compliance_update(body: ComplianceUpdateIn, request: Request):
    from src.platform.compliance.audit_reports import update_control_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await update_control_status(
            ctx.organization_id, body.framework, body.control_id, body.status, body.evidence
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class AuditReportIn(BaseModel):
    report_type: str = Field(..., pattern="^(activity|config_changes|exports|incidents|full)$")
    period_start: date
    period_end: date
    format: str = Field(default="csv", pattern="^(csv|pdf)$")


class ComplianceUpdateIn(BaseModel):
    framework: str = Field(..., max_length=30)
    control_id: str = Field(..., max_length=40)
    status: str = Field(..., pattern="^(pass|fail|na|review)$")
    evidence: str | None = Field(default=None, max_length=500)
