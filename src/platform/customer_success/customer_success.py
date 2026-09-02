# =============================================================================
# Customer Success — mailer SMTP (fail-soft), onboarding checklist derivado,
# usage reports por email, conversion analytics, branding por tenant.
# =============================================================================
from __future__ import annotations

import asyncio
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Mailer (SMTP, fail-soft)
# ---------------------------------------------------------------------------
async def send_email(to: str, subject: str, html: str) -> bool:
    """Envía email vía SMTP; False si SMTP no está configurado o falla."""
    settings = get_settings()
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        logger.info("SMTP not configured, email skipped", to=to, subject=subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))
        await asyncio.to_thread(
            _smtp_send, settings, to, msg.as_string()
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email send failed", to=to, error=str(exc)[:200])
        return False


def _smtp_send(settings, to: str, payload: str) -> None:
    port = settings.SMTP_PORT
    with smtplib.SMTP(settings.SMTP_HOST, port, timeout=15) as server:
        if settings.SMTP_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to], payload)


def _brand(organization_id: UUID) -> str:
    return "Zent RAG"


async def send_invite_email(
    organization_id: UUID, to: str, token: str, company_name: str, role: str
) -> bool:
    settings = get_settings()
    portal_base = (settings.PORTAL_BASE_URL or "http://localhost:5173").rstrip("/")
    link = f"{portal_base}/accept-invite?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2>Invitación a {company_name}</h2>
      <p>Has sido invitado como <b>{role}</b> en la organización <b>{company_name}</b>
      (plataforma {_brand(organization_id)}).</p>
      <p><a href="{link}" style="background:#2563eb;color:#fff;padding:10px 18px;
      border-radius:6px;text-decoration:none">Aceptar invitación</a></p>
      <p style="color:#666;font-size:13px">Si no esperabas esto, ignora este correo.</p>
    </div>
    """
    return await send_email(to, f"Invitación a {company_name}", html)


# ---------------------------------------------------------------------------
# Onboarding checklist (derivado de datos reales)
# ---------------------------------------------------------------------------
ONBOARDING_STEPS = [
    "workspace",        # 1: workspace creado
    "knowledge_base",   # 2: KB creada
    "agent",            # 3: agente creado
    "deployment",       # 4: deployment healthy
    "api_key",          # 5: API key creada
    "first_query",      # 6: primera consulta (usage_events)
]


async def onboarding_checklist(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT onboarding_step, onboarding_completed_at, created_at "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        kb_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
        agent_count = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM agents WHERE organization_id = :oid"),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
        dep_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM deployments WHERE organization_id = :oid "
                        "AND status = 'healthy'"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
        key_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM api_keys WHERE organization_id = :oid "
                        "AND is_active = true"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
        usage_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM usage_events WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
    finally:
        await session.close()

    done_flags = {
        "workspace": True,  # el trial crea la org+workspace implícitamente
        "knowledge_base": kb_count > 0,
        "agent": agent_count > 0,
        "deployment": dep_count > 0,
        "api_key": key_count > 0,
        "first_query": usage_count > 0,
    }
    done_count = sum(done_flags.values())
    step = min(int(org.onboarding_step or 0), done_count)
    completed = bool(org.onboarding_completed_at)
    if done_count == len(ONBOARDING_STEPS) and not completed:
        # Marcar completado la primera vez que se ve.
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE organizations SET onboarding_step = :step, "
                    "onboarding_completed_at = NOW() WHERE id = :oid"
                ),
                {"step": len(ONBOARDING_STEPS), "oid": organization_id},
            )
            await session.commit()
        finally:
            await session.close()
        completed = True

    return {
        "organization_id": str(organization_id),
        "step": step,
        "completed": completed,
        "completed_at": (
            org.onboarding_completed_at.isoformat()
            if org.onboarding_completed_at
            else None
        ),
        "items": [
            {
                "key": key,
                "label": {
                    "workspace": "Crear el workspace",
                    "knowledge_base": "Crear una knowledge base",
                    "agent": "Crear un agente",
                    "deployment": "Desplegar en producción",
                    "api_key": "Crear una API key",
                    "first_query": "Ejecutar la primera consulta",
                }[key],
                "done": done_flags[key],
            }
            for key in ONBOARDING_STEPS
        ],
    }


async def set_onboarding_step(organization_id: UUID, step: int) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET onboarding_step = :step WHERE id = :oid"
            ),
            {"step": step, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Branding por tenant
# ---------------------------------------------------------------------------
async def get_branding(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT branding FROM organizations WHERE id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {"organization_id": str(organization_id), "branding": row.branding or {}}


async def set_branding(organization_id: UUID, branding: dict) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE organizations SET branding = :branding WHERE id = :oid"),
            {"branding": json.dumps(branding), "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Usage reports por email
# ---------------------------------------------------------------------------
async def build_usage_report(organization_id: UUID, days: int = 30) -> dict:
    from src.platform.finops.breakdown import economics, usage_breakdown
    from src.platform.finops.report import build_org_report

    econ = await economics(organization_id, days)
    breakdown = await usage_breakdown(organization_id, days)
    try:
        report = await build_org_report(organization_id)
        margin = report.get("gross_margin_pct")
    except Exception:  # noqa: BLE001
        margin = None
    return {
        "organization_id": str(organization_id),
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "economics": econ,
        "top_agents": breakdown["by_agent"][:5],
        "top_providers": breakdown["by_provider"][:5],
        "gross_margin_pct": margin,
    }


def _report_html(report: dict) -> str:
    e = report["economics"]
    agents = "".join(
        f"<li>{a['label']}: {a['requests']} reqs · ${a['cost']:.4f}</li>"
        for a in report["top_agents"]
    )
    margin = (
        f"{report['gross_margin_pct']:.1f}%"
        if report["gross_margin_pct"] is not None
        else "n/d"
    )
    return f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto">
      <h2>Reporte de uso Zent RAG</h2>
      <p>Resumen de los últimos {report['period_days']} días.</p>
      <table style="width:100%;border-collapse:collapse">
        <tr><th style="text-align:left">Requests</th><td>{e['requests']}</td></tr>
        <tr><th style="text-align:left">Tokens</th><td>{e['tokens']:,}</td></tr>
        <tr><th style="text-align:left">Costo</th><td>${e['total_cost']:.4f}</td></tr>
        <tr><th style="text-align:left">Cost/request</th><td>${e['cost_per_request'] or 0:.6f}</td></tr>
        <tr><th style="text-align:left">Margen bruto</th><td>{margin}</td></tr>
      </table>
      <h3>Top agentes</h3>
      <ul>{agents or '<li>Sin actividad</li>'}</ul>
    </div>
    """


async def subscribe_report(organization_id: UUID, email: str, frequency: str) -> dict:
    session = await get_async_session()
    try:
        next_send = datetime.now(timezone.utc) + (
            timedelta(days=7) if frequency == "weekly" else timedelta(days=30)
        )
        await session.execute(
            text(
                "INSERT INTO report_subscriptions (id, organization_id, email, "
                "frequency, next_send_at) "
                "VALUES (gen_random_uuid(), :oid, :email, :freq, :next) "
                "ON CONFLICT (organization_id, email, frequency) DO NOTHING"
            ),
            {"oid": organization_id, "email": email, "freq": frequency, "next": next_send},
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "subscribed", "email": email, "frequency": frequency}


async def list_report_subscriptions(organization_id: UUID | None) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, email, frequency, next_send_at, last_sent_at, "
            "created_at FROM report_subscriptions WHERE 1=1 "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY created_at DESC"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "email": r.email,
            "frequency": r.frequency,
            "next_send_at": r.next_send_at.isoformat(),
            "last_sent_at": r.last_sent_at.isoformat() if r.last_sent_at else None,
        }
        for r in rows
    ]


async def unsubscribe_report(subscription_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM report_subscriptions WHERE id = :sid"),
            {"sid": subscription_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def send_report_now(subscription_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, email, frequency FROM report_subscriptions "
                    "WHERE id = :sid"
                ),
                {"sid": subscription_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"status": "not_found"}
    report = await build_usage_report(row.organization_id, 30)
    ok = await send_email(
        row.email, "Reporte de uso Zent RAG", _report_html(report)
    )
    if ok:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE report_subscriptions SET last_sent_at = NOW(), "
                    "next_send_at = NOW() + INTERVAL '30 days' WHERE id = :sid"
                ),
                {"sid": subscription_id},
            )
            await session.commit()
        finally:
            await session.close()
    return {"status": "sent" if ok else "skipped_no_smtp"}


async def report_scheduler_loop() -> None:
    """Cada 5 minutos: envía reportes cuyo next_send_at venció."""
    while True:
        try:
            session = await get_async_session()
            try:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id FROM report_subscriptions "
                            "WHERE next_send_at <= NOW() LIMIT 20"
                        )
                    )
                ).fetchall()
            finally:
                await session.close()
            for row in rows:
                try:
                    await send_report_now(row.id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Scheduled report failed", error=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Report scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(300)


# ---------------------------------------------------------------------------
# Conversion analytics (trial → paid)
# ---------------------------------------------------------------------------
async def conversion_analytics() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(p.name, 'unknown') AS plan, s.status, s.created_at, "
                    "CASE WHEN s.status = 'active' THEN s.created_at END AS paid_at "
                    "FROM subscriptions s LEFT JOIN plans p ON p.id = s.plan_id"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    total = len(rows)
    trials = [r for r in rows if (r.plan or "").lower() in ("trial", "starter", "free", "")]
    paid = [r for r in rows if (r.status or "").lower() == "active" and (r.plan or "").lower() not in ("trial", "")]
    by_plan: dict[str, dict] = {}
    for r in rows:
        plan = (r.plan or "unknown").lower()
        entry = by_plan.setdefault(plan, {"plan": plan, "total": 0, "active": 0})
        entry["total"] += 1
        if (r.status or "").lower() == "active":
            entry["active"] += 1
    conversion_rate = (len(paid) / len(trials) * 100) if trials else None
    return {
        "total_subscriptions": total,
        "trials": len(trials),
        "paid_active": len(paid),
        "conversion_rate_pct": round(conversion_rate, 1) if conversion_rate is not None else None,
        "by_plan": sorted(by_plan.values(), key=lambda p: -p["total"]),
    }
