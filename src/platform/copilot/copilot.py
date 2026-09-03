# =============================================================================
# AI Copilot & Assistant Platform v2 — marketplace, chat con router por
# intención, sugerencias de automatización y telemetría de uso.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("knowledge", ["kb", "base de conocimiento", "documento", "pdf", "saber", "conocer", "consulta"]),
    ("deployments", ["desplieg", "deploy", "producción", "publicar", "lanzar", "entorno"]),
    ("agents", ["agente", "crear agente", "asistente", "chatbot", "bot"]),
    ("billing", ["precio", "costo", "pago", "factura", "plan", "suscripcion", "cuenta"]),
    ("evals", ["evaluar", "eval", "test", "calidad", "score", "precisión"]),
    ("usage", ["uso", "cuánto", "metricas", "analitica", "reporte", "consumo"]),
]

FALLBACK_REPLY = (
    "Puedo ayudarte con: consultas a tu base de conocimiento (kb), "
    "despliegues (deploy), creación de agentes, precios/facturación, "
    "evaluación de calidad y métricas de uso. Describe qué necesitas."
)


def _detect_intent(message: str) -> str | None:
    lowered = message.lower()
    for intent, keywords in INTENT_PATTERNS:
        if any(kw in lowered for kw in keywords):
            return intent
    return None


def _reply_for_intent(intent: str, org_agents: list[dict]) -> dict:
    """Construye la respuesta según intención y agentes disponibles."""
    if not org_agents:
        return {
            "text": f"Detecté que quieres algo de **{intent}**, pero aún no tienes agentes "
            "en esta organización. Puedes instalar uno del marketplace o crear uno nuevo.",
            "intent": intent,
            "resolved_agent_id": None,
            "suggested_agents": [],
        }
    best = org_agents[0]
    return {
        "text": f"Detecté la intención **{intent}**. Puedo ayudarte con el agente "
        f"**{best['name']}** (v{best.get('version_number') or '—'}). "
        "Haz una consulta directa o despliégalo en producción.",
        "intent": intent,
        "resolved_agent_id": best["id"],
        "suggested_agents": [{"id": a["id"], "name": a["name"]} for a in org_agents[:3]],
    }


async def _org_agents(organization_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT a.id, a.name FROM agents a "
                    "WHERE a.organization_id = :oid "
                    "AND (a.status IN ('configured', 'ready', 'deployed') OR a.is_active = true) "
                    "ORDER BY a.created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [{"id": str(r.id), "name": r.name, "version_number": 0} for r in rows]


async def _track_usage(organization_id: UUID, assistant_key: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO assistant_usage (id, organization_id, assistant_key, events, last_event_at) "
                "VALUES (gen_random_uuid(), :oid, :key, 1, NOW()) "
                "ON CONFLICT (organization_id, assistant_key) DO UPDATE SET "
                "events = assistant_usage.events + 1, last_event_at = NOW()"
            ),
            {"oid": organization_id, "key": assistant_key[:80]},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------
async def list_marketplace(category: str | None = None) -> dict:
    session = await get_async_session()
    try:
        where = ""
        params: dict = {}
        if category:
            where = " WHERE category = :cat"
            params["cat"] = category
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, slug, description, category, tags, rating, installs, "
                    "featured FROM marketplace_agents WHERE status = 'published'" + where + " "
                    "ORDER BY featured DESC, installs DESC"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "agents": [
            {
                "id": str(r.id),
                "name": r.name,
                "slug": r.slug,
                "description": r.description,
                "category": r.category,
                "tags": r.tags,
                "rating": float(r.rating),
                "installs": int(r.installs),
                "featured": bool(r.featured),
            }
            for r in rows
        ]
    }


async def _marketplace_row(slug: str) -> tuple:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id, name, slug, category, description, prompt_template, "
                    "config_template "
                    "FROM marketplace_agents WHERE slug = :slug AND status = 'published'"
                ),
                {"slug": slug},
            )
        ).fetchone()
    finally:
        await session.close()


async def install_marketplace(organization_id: UUID, slug: str) -> dict:
    """Instala un agente del marketplace: crea agente del tenant desde el template."""
    row = await _marketplace_row(slug)
    if row is None:
        raise ValueError("marketplace agent not found")
    existing = await _org_agents(organization_id)
    if any(a["name"].lower() == row.name.lower() for a in existing):
        raise ValueError(f"'{row.name}' ya está instalado")

    session = await get_async_session()
    try:
        agent_id = (
            await session.execute(
                text(
                    "INSERT INTO agents (id, organization_id, name, description, status, "
                    "system_prompt, model, config_json) "
                    "VALUES (gen_random_uuid(), :oid, :name, :desc, 'configured', :prompt, "
                    ":model, CAST(:cfg AS jsonb)) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "name": row.name,
                    "desc": row.description,
                    "prompt": (row.prompt_template or "").replace(
                        "{company}", "tu organización"
                    ),
                    "model": (row.config_template or {}).get("model", "gpt-4o-mini"),
                    "cfg": json.dumps(
                        {
                            "marketplace_slug": row.slug,
                            "max_tokens": (row.config_template or {}).get("max_tokens", 1500),
                        }
                    ),
                },
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO marketplace_installs (id, organization_id, marketplace_agent_id, "
                "agent_id, status) VALUES (gen_random_uuid(), :oid, :mid, :aid, 'installed') "
                "ON CONFLICT (organization_id, marketplace_agent_id, status) DO NOTHING"
            ),
            {"oid": organization_id, "mid": row.id, "aid": agent_id},
        )
        await session.execute(
            text("UPDATE marketplace_agents SET installs = installs + 1 WHERE id = :mid"),
            {"mid": row.id},
        )
        await session.commit()
    finally:
        await session.close()
    await _track_usage(organization_id, f"marketplace:{row.slug}")
    return {"installed": True, "agent_id": str(agent_id), "name": row.name}


async def remove_install(organization_id: UUID, install_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, marketplace_agent_id, agent_id FROM marketplace_installs "
                    "WHERE id = :iid AND organization_id = :oid AND status = 'installed'"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return {"removed": False}
        await session.execute(
            text(
                "UPDATE marketplace_installs SET status = 'removed', removed_at = NOW() "
                "WHERE id = :iid"
            ),
            {"iid": install_id},
        )
        if row.agent_id:
            await session.execute(
                text("UPDATE agents SET status = 'archived' WHERE id = :aid"),
                {"aid": row.agent_id},
            )
        await session.commit()
    finally:
        await session.close()
    return {"removed": True, "agent_id": str(row.agent_id) if row.agent_id else None}


async def my_installs(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT i.id, i.usage_count, i.installed_at, a.id AS agent_id, "
                    "a.name AS agent_name, m.slug, m.category "
                    "FROM marketplace_installs i "
                    "JOIN marketplace_agents m ON m.id = i.marketplace_agent_id "
                    "LEFT JOIN agents a ON a.id = i.agent_id "
                    "WHERE i.organization_id = :oid AND i.status = 'installed' "
                    "ORDER BY i.installed_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "installs": [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "agent_name": r.agent_name,
                "slug": r.slug,
                "category": r.category,
                "usage_count": int(r.usage_count),
                "installed_at": r.installed_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Chat copilot
# ---------------------------------------------------------------------------
async def chat(
    organization_id: UUID,
    user_id: UUID | None,
    message: str,
    session_id: UUID | None = None,
    title: str = "Nueva conversación",
) -> dict:
    intent = _detect_intent(message)
    agents = await _org_agents(organization_id)

    db = await get_async_session()
    try:
        if session_id is None:
            session_id = (
                await db.execute(
                    text(
                        "INSERT INTO copilot_sessions (id, organization_id, user_id, title) "
                        "VALUES (gen_random_uuid(), :oid, :uid, :title) RETURNING id"
                    ),
                    {"oid": organization_id, "uid": user_id, "title": (title or "Nueva conversación")[:200]},
                )
            ).scalar()
        await db.execute(
            text(
                "INSERT INTO copilot_messages (id, session_id, role, content, intent, "
                "resolved_agent_id) VALUES (gen_random_uuid(), :sid, 'user', :content, "
                ":intent, :rid)"
            ),
            {"sid": session_id, "content": message[:2000], "intent": intent, "rid": None},
        )
        await db.execute(
            text(
                "UPDATE copilot_sessions SET last_activity_at = NOW() WHERE id = :sid"
            ),
            {"sid": session_id},
        )
        await db.commit()
    finally:
        await db.close()

    if intent is None:
        reply = FALLBACK_REPLY
        resolved = None
    else:
        built = _reply_for_intent(intent, agents)
        reply = built["text"]
        resolved = built["resolved_agent_id"]

    await _track_usage(organization_id, f"copilot:intent:{intent or 'fallback'}")

    # Telemetría de insights conversacionales (temas + escalaciones).
    try:
        from src.platform.chatinsights.insights import (
            _track_topics,
            _wants_human,
            record_chat_event,
        )

        await _track_topics(organization_id, message)
        if _wants_human(message):
            await record_chat_event(
                organization_id, "escalated", session_id, message[:200]
            )
    except Exception:  # noqa: BLE001 - telemetría nunca debe romper el chat
        logger.exception("chat insights tracking failed")

    # Huecos de conocimiento: consultas sin intención → gap.
    if intent is None:
        try:
            from src.platform.knowledgehub.hub import record_gap

            await record_gap(organization_id, message)
        except Exception:  # noqa: BLE001
            logger.exception("knowledge gap tracking failed")

    db = await get_async_session()
    try:
        await db.execute(
            text(
                "INSERT INTO copilot_messages (id, session_id, role, content, intent, "
                "resolved_agent_id) VALUES (gen_random_uuid(), :sid, 'assistant', :content, "
                ":intent, :rid)"
            ),
            {
                "sid": session_id,
                "content": reply[:2000],
                "intent": intent,
                "rid": UUID(resolved) if resolved else None,
            },
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "session_id": str(session_id),
        "intent": intent,
        "reply": reply,
        "resolved_agent_id": resolved,
        "suggested_agents": [{"id": a["id"], "name": a["name"]} for a in agents[:3]] if intent else [],
    }


async def list_sessions(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT s.id, s.title, s.created_at, s.last_activity_at, "
                    "COUNT(m.id) AS messages "
                    "FROM copilot_sessions s "
                    "LEFT JOIN copilot_messages m ON m.session_id = s.id "
                    "WHERE s.organization_id = :oid "
                    "GROUP BY s.id ORDER BY s.last_activity_at DESC LIMIT 50"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "sessions": [
            {
                "id": str(r.id),
                "title": r.title,
                "created_at": r.created_at.isoformat(),
                "last_activity_at": r.last_activity_at.isoformat(),
                "messages": int(r.messages),
            }
            for r in rows
        ]
    }


async def session_messages(organization_id: UUID, session_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        session_row = (
            await session.execute(
                text(
                    "SELECT id FROM copilot_sessions WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        if session_row is None:
            return None
        rows = (
            await session.execute(
                text(
                    "SELECT id, role, content, intent, resolved_agent_id, created_at "
                    "FROM copilot_messages WHERE session_id = :sid ORDER BY created_at"
                ),
                {"sid": session_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "session_id": str(session_id),
        "messages": [
            {
                "id": str(r.id),
                "role": r.role,
                "content": r.content,
                "intent": r.intent,
                "resolved_agent_id": str(r.resolved_agent_id) if r.resolved_agent_id else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Sugerencias proactivas de automatización
# ---------------------------------------------------------------------------
async def suggest_automations(organization_id: UUID, min_repeats: int = 3) -> dict:
    """Detecta intenciones repetidas (≥3 en 7 días) y sugiere un agente dedicado."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT intent, COUNT(*) AS n, MAX(created_at) AS last_seen, "
                    "ARRAY_AGG(content ORDER BY created_at DESC) FILTER (WHERE role = 'user') "
                    "AS samples FROM copilot_messages "
                    "WHERE session_id IN (SELECT id FROM copilot_sessions WHERE organization_id = :oid) "
                    "AND role = 'user' AND intent IS NOT NULL AND created_at >= :since "
                    "GROUP BY intent"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    suggestions: list[dict] = []
    for r in rows:
        if int(r.n) >= min_repeats:
            samples = (r.samples or [])[:3]
            intent = r.intent
            suggestion = {
                "intent": intent,
                "repeats": int(r.n),
                "last_seen": r.last_seen.isoformat(),
                "suggested_name": f"Agente de {intent}",
                "sample_questions": samples,
                "suggestion": (
                    f"Tu equipo consultó {intent} {r.n} veces esta semana. "
                    "Te recomendamos crear un agente dedicado con las preguntas frecuentes."
                ),
            }
            suggestions.append(suggestion)
    return {"suggestions": suggestions}


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def copilot_dashboard() -> dict:
    session = await get_async_session()
    try:
        top = (
            await session.execute(
                text(
                    "SELECT assistant_key, SUM(events) AS events FROM assistant_usage "
                    "GROUP BY assistant_key ORDER BY events DESC LIMIT 10"
                )
            )
        ).fetchall()
        intents = (
            await session.execute(
                text(
                    "SELECT intent, COUNT(*) AS n FROM copilot_messages "
                    "WHERE role = 'user' AND intent IS NOT NULL "
                    "GROUP BY intent ORDER BY n DESC"
                )
            )
        ).fetchall()
        session_stats = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS sessions, COUNT(DISTINCT organization_id) AS orgs "
                    "FROM copilot_sessions"
                )
            )
        ).fetchone()
        installs = (
            await session.execute(
                text(
                    "SELECT m.name, m.slug, COUNT(i.id) AS active "
                    "FROM marketplace_agents m "
                    "LEFT JOIN marketplace_installs i ON i.marketplace_agent_id = m.id "
                    "AND i.status = 'installed' "
                    "GROUP BY m.id ORDER BY active DESC"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "sessions": int(session_stats.sessions or 0),
        "organizations_using": int(session_stats.orgs or 0),
        "top_assistants": [{"key": r.assistant_key, "events": int(r.events)} for r in top],
        "intents": [{"intent": r.intent, "messages": int(r.n)} for r in intents],
        "installs": [{"name": r.name, "slug": r.slug, "active": int(r.active)} for r in installs],
    }
