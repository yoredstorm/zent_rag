# =============================================================================
# Workflow Notification Options — canales y destinatarios reales para el
# Notification Builder (misión §14).
#
# Solo reporta como `available` los canales que el nodo `notify` puede enviar
# hoy (Zent, correo con SMTP, webhook con suscripciones). Slack/Teams/WhatsApp
# se listan como pendientes con su slug de integración: nunca se simula un
# envío que no existe.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

# Slugs de integración que habilitarán canales conversacionales (aún no
# implementados en el nodo notify; se muestran para pedir la conexión).
_EXTERNAL_CHANNELS: list[dict[str, str]] = [
    {"value": "slack", "label": "Slack", "requires": "slack"},
    {"value": "teams", "label": "Microsoft Teams", "requires": "microsoft-teams"},
    {"value": "whatsapp", "label": "WhatsApp", "requires": "whatsapp"},
]


async def _installed_slugs(organization_id: UUID, workspace_id: UUID | None) -> set[str]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT m.slug FROM installed_integrations i "
                    "JOIN integration_manifests m ON m.id = i.integration_id "
                    "WHERE i.organization_id = :oid AND i.status IN ('active', 'installed') "
                    "AND (i.workspace_id IS NOT DISTINCT FROM :ws)"
                ),
                {"oid": organization_id, "ws": workspace_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {str(r.slug) for r in rows}


async def _webhook_subscriptions(organization_id: UUID) -> int:
    session = await get_async_session()
    try:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM webhook_subscriptions "
                        "WHERE organization_id = :oid AND enabled = true"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
    finally:
        await session.close()


async def notification_targets(
    organization_id: UUID,
    workspace_id: UUID | None = None,
) -> dict:
    """Canales disponibles + personas/equipos del tenant."""
    from src.core.config import get_settings

    settings = get_settings()
    email_configured = bool(settings.SMTP_HOST and settings.SMTP_FROM)
    webhook_count = await _webhook_subscriptions(organization_id)
    installed = await _installed_slugs(organization_id, workspace_id)

    channels: list[dict] = [
        {
            "value": "in_app",
            "label": "Zent",
            "available": True,
            "requires": None,
            "detail": "Notificación en el centro de Zent.",
        },
        {
            "value": "email",
            "label": "Correo",
            "available": email_configured,
            "requires": None,
            "detail": "SMTP configurado." if email_configured else "Configura SMTP para enviar correos.",
        },
        {
            "value": "webhook",
            "label": "Webhook",
            "available": webhook_count > 0,
            "requires": None,
            "detail": (
                f"{webhook_count} suscripción(es) activas."
                if webhook_count
                else "Crea un webhook en Notificaciones para usarlo."
            ),
        },
    ]
    for channel in _EXTERNAL_CHANNELS:
        connected = channel["requires"] in installed
        channels.append(
            {
                **channel,
                "available": False,
                "detail": (
                    "Integración conectada; el envío por este canal llega en una próxima versión."
                    if connected
                    else f"Necesitas conectar {channel['label']} para usar esta acción."
                ),
            }
        )

    session = await get_async_session()
    try:
        people_rows = (
            await session.execute(
                text(
                    "SELECT id, email, role FROM users "
                    "WHERE organization_id = :oid AND email IS NOT NULL "
                    "ORDER BY email LIMIT 200"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        try:
            team_rows = (
                await session.execute(
                    text(
                        "SELECT id, name FROM org_groups "
                        "WHERE organization_id = :oid ORDER BY name LIMIT 100"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
        except Exception:  # noqa: BLE001 — base anterior a la migración 073
            team_rows = []
    finally:
        await session.close()

    return {
        "channels": channels,
        "people": [
            {"id": str(r.id), "email": r.email, "label": r.email, "kind": "person", "role": r.role}
            for r in people_rows
        ],
        "teams": [
            {"id": str(r.id), "label": r.name, "kind": "team"} for r in team_rows
        ],
        "email_configured": email_configured,
        "webhook_subscriptions": webhook_count,
    }


async def resolve_notify_recipient_emails(
    organization_id: UUID,
    recipients: list[dict],
) -> list[str]:
    """Resuelve destinatarios (correo, persona, equipo) a direcciones reales."""
    emails: list[str] = []
    for recipient in recipients or []:
        if not isinstance(recipient, dict):
            continue
        kind = str(recipient.get("kind") or "")
        value = str(recipient.get("value") or "").strip()
        if not value:
            continue
        if kind == "email":
            emails.append(value)
            continue
        if kind == "person":
            emails.extend(await _person_emails(organization_id, value))
            continue
        if kind == "team":
            emails.extend(await _team_emails(organization_id, value))
    # Dedupe preservando orden.
    seen: set[str] = set()
    result: list[str] = []
    for email in emails:
        lowered = email.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            result.append(email)
    return result


async def _person_emails(organization_id: UUID, value: str) -> list[str]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT email FROM users WHERE organization_id = :oid "
                    "AND email IS NOT NULL AND (CAST(id AS text) = :val OR lower(email) = :email)"
                ),
                {"oid": organization_id, "val": value, "email": value.lower()},
            )
        ).fetchone()
    finally:
        await session.close()
    return [row.email] if row is not None and row.email else []


async def _team_emails(organization_id: UUID, value: str) -> list[str]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT u.email FROM users u "
                    "JOIN org_group_memberships m ON m.user_id = u.id "
                    "JOIN org_groups g ON g.id = m.group_id "
                    "WHERE g.organization_id = :oid AND u.email IS NOT NULL "
                    "AND (CAST(g.id AS text) = :val OR lower(g.name) = :name)"
                ),
                {"oid": organization_id, "val": value, "name": value.lower()},
            )
        ).fetchall()
    except Exception:  # noqa: BLE001 — base anterior a 073
        return []
    finally:
        await session.close()
    return [r.email for r in rows if r.email]


__all__ = ["notification_targets", "resolve_notify_recipient_emails"]
