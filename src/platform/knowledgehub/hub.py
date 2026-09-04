# =============================================================================
# AI Knowledge Hub v2 — Auto-Discovery & Curation: ingesta de fuentes con
# refresco, deduplicación por firma, metadatos enriquecidos y gaps.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

SOURCE_TYPES = ("url", "rss", "repo", "s3", "manual")
CATEGORY_KEYWORDS = {
    "soporte": ["soporte", "ayuda", "troubleshooting", "error"],
    "ventas": ["venta", "lead", "precio", "plan", "pricing"],
    "producto": ["producto", "feature", "funcionalidad", "guía", "guia", "manual"],
    "técnico": ["api", "sdk", "desarrollo", "integración", "dev"],
    "legal": ["legal", "contrato", "términos", "terminos", "política", "politica"],
    "rrhh": ["rrhh", "hr", "beneficios", "onboarding", "cultura"],
}


def _infer_category(title: str) -> str:
    lowered = title.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return "general"


def _signature(title: str, content: str) -> str:
    normalized = re.sub(r"\s+", " ", (title + "|" + content).strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()


async def _source_documents(organization_id: UUID) -> set[str]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT signature FROM documents "
                    "WHERE organization_id = :oid AND signature IS NOT NULL"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {r.signature for r in rows}


# ---------------------------------------------------------------------------
# CRUD fuentes
# ---------------------------------------------------------------------------
async def list_sources(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT s.id, s.name, s.source_type, s.config, s.refresh_interval_h, "
                    "s.last_refresh_at, s.next_refresh_at, s.status, "
                    "COUNT(d.id) AS docs "
                    "FROM knowledge_sources s "
                    "LEFT JOIN documents d ON d.source_id = s.id "
                    "WHERE s.organization_id = :oid "
                    "GROUP BY s.id ORDER BY s.created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "sources": [
            {
                "id": str(r.id),
                "name": r.name,
                "source_type": r.source_type,
                "config": r.config,
                "refresh_interval_h": int(r.refresh_interval_h),
                "last_refresh_at": r.last_refresh_at.isoformat() if r.last_refresh_at else None,
                "next_refresh_at": r.next_refresh_at.isoformat() if r.next_refresh_at else None,
                "status": r.status,
                "documents": int(r.docs),
            }
            for r in rows
        ]
    }


async def create_source(
    organization_id: UUID,
    name: str,
    source_type: str = "url",
    config: dict | None = None,
    refresh_interval_h: int = 24,
) -> dict:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type debe ser uno de {SOURCE_TYPES}")
    interval = max(1, min(int(refresh_interval_h), 720))
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO knowledge_sources (id, organization_id, name, source_type, "
                    "config, refresh_interval_h, next_refresh_at) "
                    "VALUES (gen_random_uuid(), :oid, :name, :stype, "
                    "CAST(:cfg AS jsonb), :interval, NOW()) RETURNING id, name"
                ),
                {
                    "oid": organization_id,
                    "name": name[:150],
                    "stype": source_type,
                    "cfg": json.dumps(config or {}),
                    "interval": interval,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"source_id": str(row.id), "name": row.name}


async def get_source(organization_id: UUID, source_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, source_type, config, refresh_interval_h, "
                    "last_refresh_at, next_refresh_at, status FROM knowledge_sources "
                    "WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": source_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "name": row.name,
        "source_type": row.source_type,
        "config": row.config,
        "refresh_interval_h": int(row.refresh_interval_h),
        "last_refresh_at": row.last_refresh_at.isoformat() if row.last_refresh_at else None,
        "next_refresh_at": row.next_refresh_at.isoformat() if row.next_refresh_at else None,
        "status": row.status,
    }


async def update_source(
    organization_id: UUID,
    source_id: UUID,
    name: str | None = None,
    config: dict | None = None,
    refresh_interval_h: int | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM knowledge_sources WHERE id = :sid AND organization_id = :oid"),
                {"sid": source_id, "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict = {"sid": source_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name[:150]
        if config is not None:
            sets.append("config = CAST(:cfg AS jsonb)")
            params["cfg"] = json.dumps(config)
        if refresh_interval_h is not None:
            interval = max(1, min(int(refresh_interval_h), 720))
            sets.append("refresh_interval_h = :interval")
            params["interval"] = interval
        await session.execute(
            text(f"UPDATE knowledge_sources SET {', '.join(sets)} WHERE id = :sid"),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"updated": True}


async def delete_source(organization_id: UUID, source_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM knowledge_sources WHERE id = :sid AND organization_id = :oid"),
            {"sid": source_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def set_source_status(organization_id: UUID, source_id: UUID, status: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE knowledge_sources SET status = :status, updated_at = NOW() "
                    "WHERE id = :sid AND organization_id = :oid RETURNING status"
                ),
                {"status": status, "sid": source_id, "oid": organization_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return None
    return {"source_id": str(source_id), "status": row.status}


# ---------------------------------------------------------------------------
# Ingesta con deduplicación
# ---------------------------------------------------------------------------
def _generate_items(source_type: str, config: dict) -> list[tuple[str, str]]:
    """Devuelve (title, content) — items explícitos del config o generados."""
    if config.get("items"):
        return [(str(i.get("title", "Doc")), str(i.get("content", ""))) for i in config["items"]]
    prefix = str(config.get("prefix", source_type))
    base = str(config.get("url") or config.get("feed") or config.get("repo") or config.get("bucket") or prefix)
    names = {
        "url": ["Index", "Setup", "FAQ"],
        "rss": ["Post 1", "Post 2", "Post 3"],
        "repo": ["README", "api.md", "CONTRIBUTING"],
        "s3": ["object-1", "object-2", "object-3"],
        "manual": ["Documento A", "Documento B", "Documento C"],
    }
    return [(f"{prefix} {n}", f"Contenido de {n} extraído de {base}.") for n in names.get(source_type, ["Doc"])]


async def refresh_source(organization_id: UUID, source_id: UUID) -> dict:
    """Ingesta/actualiza documentos de la fuente con deduplicación por firma."""
    source = await get_source(organization_id, source_id)
    if source is None:
        return None
    if source["status"] == "paused":
        return {"status": "paused", "source_id": str(source_id)}

    started = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        refresh_id = (
            await session.execute(
                text(
                    "INSERT INTO knowledge_refreshes (id, source_id) "
                    "VALUES (gen_random_uuid(), :sid) RETURNING id"
                ),
                {"sid": source_id},
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()

    items = _generate_items(source["source_type"], source["config"])
    known = await _source_documents(organization_id)
    added = 0
    duplicated = 0
    errors: list[str] = []
    author = str(source["config"].get("author") or "system")
    confidence = float(source["config"].get("confidence", 80 if source["source_type"] != "manual" else 100))
    freshness_base = datetime.now(timezone.utc) - timedelta(days=int(source["config"].get("age_days", 0)))

    for title, content in items:
        signature = _signature(title, content)
        if signature in known:
            duplicated += 1
            continue
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO documents (id, organization_id, external_id, title, "
                    "source_url, content_hash, chunk_count, status, metadata_json, "
                    "source_id, category, author, freshness_score, confidence_score, signature) "
                    "VALUES (gen_random_uuid(), :oid, :ext, :title, :url, :hash, 0, 'active', "
                    "CAST(:meta AS jsonb), :sid, :cat, :author, :fresh, :conf, :sig)"
                ),
                {
                    "oid": organization_id,
                    "ext": f"kh-{source_id.hex[:8]}-{uuid4().hex[:8]}",
                    "title": title,
                    "url": str(source["config"].get("url") or source["config"].get("feed") or ""),
                    "hash": hashlib.sha256(content.encode()).hexdigest(),
                    "meta": json.dumps({"source_type": source["source_type"], "source_name": source["name"]}),
                    "sid": source_id,
                    "cat": _infer_category(title),
                    "author": author,
                    "fresh": 100.0,
                    "conf": confidence,
                    "sig": signature,
                },
            )
            await session.commit()
        finally:
            await session.close()
        known.add(signature)
        added += 1

    duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    status = "failed" if errors else "success"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE knowledge_refreshes SET status = :status, docs_found = :found, "
                "docs_added = :added, docs_duplicated = :dup, error = :err, "
                "completed_at = NOW(), duration_ms = :dur WHERE id = :rid"
            ),
            {
                "status": status,
                "found": len(items),
                "added": added,
                "dup": duplicated,
                "err": "; ".join(errors) or None,
                "dur": duration,
                "rid": refresh_id,
            },
        )
        await session.execute(
            text(
                "UPDATE knowledge_sources SET last_refresh_at = NOW(), "
                "next_refresh_at = NOW() + make_interval(hours => :interval), updated_at = NOW() "
                "WHERE id = :sid"
            ),
            {"interval": source["refresh_interval_h"], "sid": source_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "refresh_id": str(refresh_id),
        "status": status,
        "docs_found": len(items),
        "docs_added": added,
        "docs_duplicated": duplicated,
        "duration_ms": duration,
    }


async def run_refresh_loop() -> dict:
    """Scheduler: refresca fuentes activas cuyo next_refresh_at ya venció."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id FROM knowledge_sources "
                    "WHERE status = 'active' AND next_refresh_at <= NOW() LIMIT 20"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    results = []
    for row in rows:
        try:
            result = await refresh_source(UUID(str(row.organization_id)), UUID(str(row.id)))
            results.append({"source_id": str(row.id), **result})
        except Exception as exc:  # noqa: BLE001
            logger.exception("refresh source failed", source_id=str(row.id))
            results.append({"source_id": str(row.id), "status": "failed", "error": str(exc)})
    return {"refreshed": len(results), "results": results}


async def refresh_history(organization_id: UUID, source_id: UUID, limit: int = 20) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT r.id, r.status, r.docs_found, r.docs_added, r.docs_duplicated, "
                    "r.error, r.started_at, r.completed_at, r.duration_ms "
                    "FROM knowledge_refreshes r "
                    "JOIN knowledge_sources s ON s.id = r.source_id "
                    "WHERE r.source_id = :sid AND s.organization_id = :oid "
                    "ORDER BY r.started_at DESC LIMIT :lim"
                ),
                {"sid": source_id, "oid": organization_id, "lim": min(int(limit), 100)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "refreshes": [
            {
                "id": str(r.id),
                "status": r.status,
                "docs_found": int(r.docs_found),
                "docs_added": int(r.docs_added),
                "docs_duplicated": int(r.docs_duplicated),
                "error": r.error,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": int(r.duration_ms) if r.duration_ms is not None else None,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Curación
# ---------------------------------------------------------------------------
async def curate_document(
    organization_id: UUID,
    document_id: UUID,
    category: str | None = None,
    author: str | None = None,
    confidence: float | None = None,
    title: str | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM documents WHERE id = :did AND organization_id = :oid"
                ),
                {"did": document_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict = {"did": document_id, "oid": organization_id}
        if category is not None:
            sets.append("category = :cat")
            params["cat"] = category[:60]
        if author is not None:
            sets.append("author = :author")
            params["author"] = author[:120]
        if confidence is not None:
            conf = max(0.0, min(float(confidence), 100.0))
            sets.append("confidence_score = :conf")
            params["conf"] = conf
        if title is not None:
            sets.append("title = :title")
            params["title"] = title[:300]
        await session.execute(
            text(f"UPDATE documents SET {', '.join(sets)} WHERE id = :did"),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"document_id": str(document_id), "curated": True}


# ---------------------------------------------------------------------------
# Huecos de conocimiento
# ---------------------------------------------------------------------------
async def record_gap(organization_id: UUID, query: str, intent: str | None = None) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, organization_id, query, intent, occurrences, "
                "last_seen_at) VALUES (gen_random_uuid(), :oid, :query, :intent, 1, NOW()) "
                "ON CONFLICT (organization_id, query) DO UPDATE SET "
                "occurrences = knowledge_gaps.occurrences + 1, last_seen_at = NOW()"
            ),
            {"oid": organization_id, "query": query[:300], "intent": intent},
        )
        await session.commit()
    finally:
        await session.close()


async def list_gaps(organization_id: UUID, status: str = "open") -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, query, intent, occurrences, status, created_at, last_seen_at "
                    "FROM knowledge_gaps WHERE organization_id = :oid AND status = :status "
                    "ORDER BY occurrences DESC, last_seen_at DESC LIMIT 50"
                ),
                {"oid": organization_id, "status": status},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "gaps": [
            {
                "id": str(r.id),
                "query": r.query,
                "intent": r.intent,
                "occurrences": int(r.occurrences),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "last_seen_at": r.last_seen_at.isoformat(),
            }
            for r in rows
        ]
    }


async def resolve_gap(organization_id: UUID, gap_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE knowledge_gaps SET status = 'resolved' "
                    "WHERE id = :gid AND organization_id = :oid RETURNING id"
                ),
                {"gid": gap_id, "oid": organization_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return None
    return {"gap_id": str(gap_id), "status": "resolved"}


# ---------------------------------------------------------------------------
# Cobertura + dashboard
# ---------------------------------------------------------------------------
async def coverage_dashboard(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        by_source = (
            await session.execute(
                text(
                    "SELECT s.name, s.source_type, COUNT(d.id) AS docs, "
                    "COALESCE(AVG(d.confidence_score), 0) AS avg_conf, "
                    "COALESCE(AVG(d.freshness_score), 0) AS avg_fresh "
                    "FROM knowledge_sources s "
                    "LEFT JOIN documents d ON d.source_id = s.id "
                    "WHERE s.organization_id = :oid "
                    "GROUP BY s.id ORDER BY docs DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        by_category = (
            await session.execute(
                text(
                    "SELECT COALESCE(category, 'general') AS category, COUNT(*) AS docs "
                    "FROM documents WHERE organization_id = :oid "
                    "GROUP BY category ORDER BY docs DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        total_docs = (
            await session.execute(
                text("SELECT COUNT(*) FROM documents WHERE organization_id = :oid"),
                {"oid": organization_id},
            )
        ).scalar()
        last_refreshes = (
            await session.execute(
                text(
                    "SELECT r.status, r.docs_added, r.docs_duplicated, r.started_at, "
                    "s.name AS source_name "
                    "FROM knowledge_refreshes r "
                    "JOIN knowledge_sources s ON s.id = r.source_id "
                    "WHERE s.organization_id = :oid "
                    "ORDER BY r.started_at DESC LIMIT 10"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        gap_stats = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FILTER (WHERE status = 'open') AS open_gaps, "
                    "COALESCE(SUM(occurrences) FILTER (WHERE status = 'open'), 0) AS total_occ "
                    "FROM knowledge_gaps WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "total_documents": int(total_docs or 0),
        "sources": [
            {
                "name": r.name,
                "source_type": r.source_type,
                "documents": int(r.docs),
                "avg_confidence": round(float(r.avg_conf or 0), 1),
                "avg_freshness": round(float(r.avg_fresh or 0), 1),
            }
            for r in by_source
        ],
        "categories": [{"category": r.category, "documents": int(r.docs)} for r in by_category],
        "last_refreshes": [
            {
                "source": r.source_name,
                "status": r.status,
                "added": int(r.docs_added),
                "duplicated": int(r.docs_duplicated),
                "started_at": r.started_at.isoformat(),
            }
            for r in last_refreshes
        ],
        "open_gaps": int(gap_stats.open_gaps or 0),
        "gap_occurrences": int(gap_stats.total_occ or 0),
    }


async def knowledge_hub_dashboard() -> dict:
    session = await get_async_session()
    try:
        by_type = (
            await session.execute(
                text(
                    "SELECT source_type, COUNT(*) AS n FROM knowledge_sources "
                    "GROUP BY source_type ORDER BY n DESC"
                )
            )
        ).fetchall()
        total_docs = (await session.execute(text("SELECT COUNT(*) FROM documents"))).scalar()
        total_sources = (await session.execute(text("SELECT COUNT(*) FROM knowledge_sources"))).scalar()
        dup_total = (
            await session.execute(text("SELECT COALESCE(SUM(docs_duplicated), 0) FROM knowledge_refreshes"))
        ).scalar()
        failed_refreshes = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_refreshes WHERE status = 'failed' "
                    "AND started_at >= NOW() - interval '7 days'"
                )
            )
        ).scalar()
        open_gaps = (
            await session.execute(text("SELECT COUNT(*) FROM knowledge_gaps WHERE status = 'open'"))
        ).scalar()
        top_gaps = (
            await session.execute(
                text(
                    "SELECT query, occurrences FROM knowledge_gaps "
                    "WHERE status = 'open' ORDER BY occurrences DESC LIMIT 8"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "total_sources": int(total_sources or 0),
        "total_documents": int(total_docs or 0),
        "duplicates_removed": int(dup_total or 0),
        "failed_refreshes_7d": int(failed_refreshes or 0),
        "open_gaps": int(open_gaps or 0),
        "sources_by_type": [{"source_type": r.source_type, "count": int(r.n)} for r in by_type],
        "top_gaps": [{"query": r.query, "occurrences": int(r.occurrences)} for r in top_gaps],
    }
