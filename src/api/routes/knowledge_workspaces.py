# =============================================================================
# Knowledge Workspaces — corpora del Knowledge OS
# =============================================================================
# Home de UI: Knowledge Workspaces (list/create/detail/sources) + chat
# grounded (KnowledgeRetriever + GroundingService) sobre el árbol canónico.
# Aislamiento por organization_id + workspace vía resolve_workspace, igual que
# el resto de la plataforma.
# =============================================================================
from __future__ import annotations

import re
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_corpus_repo
from src.core.config import get_settings
from src.core.domain.knowledge_v2 import (
    KnowledgeCorpus,
    KnowledgeObjectStatus,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.platform.workspaces.context import resolve_workspace
from src.runtime.prompt_assembly import evidence_block as prompt_evidence_block

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge Workspaces"])

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "corpus"


class CreateCorpusRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=200)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=32000)
    source_ids: list[UUID] = Field(default_factory=list, max_length=32)


class StudioRequest(BaseModel):
    artifact: str | None = Field(default=None, max_length=40)


# ---------------------------------------------------------------------------
# Home: list/crear corpora (workspace-scoped)
# ---------------------------------------------------------------------------


@router.get("/workspaces", summary="Knowledge corpora del workspace")
async def list_workspaces(request: Request) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    ws = await resolve_workspace(request)
    corpora = await get_corpus_repo().list_corpora(ctx.organization_id, workspace_id=ws.id)
    counts = await _corpus_source_counts(ctx.organization_id)
    return {
        "corpora": [
            {
                **corpus,
                "source_count": counts.get(corpus["id"], 0),
                "coverage": None,  # Knowledge Score V1 federation (Phase H)
                "conflicts": 0,
            }
            for corpus in corpora
        ],
        "count": len(corpora),
    }


@router.post("/workspaces", status_code=201, summary="Crear corpus")
async def create_workspace(body: CreateCorpusRequest, request: Request) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    ws = await resolve_workspace(request)
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=ctx.organization_id,
        workspace_id=ws.id,
        name=body.name,
        slug=body.slug or _slugify(body.name),
        status=KnowledgeObjectStatus.DRAFT,
    )
    await get_corpus_repo().create_corpus(corpus)
    meta = await get_corpus_repo().get_corpus(ctx.organization_id, corpus.id)
    return {"corpus": meta or {"id": str(corpus.id), "name": corpus.name}}


# ---------------------------------------------------------------------------
# Detalle del workspace: corpus + fuentes + documentos estructurados
# ---------------------------------------------------------------------------


@router.get("/workspaces/{corpus_id}", summary="Detalle del corpus")
async def get_workspace(corpus_id: UUID, request: Request) -> dict:
    ctx, ws, meta = await _require_corpus(request, corpus_id)
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    return {"corpus": meta, "sources": sources}


@router.get(
    "/workspaces/{corpus_id}/sources/{source_id}/documents",
    summary="Documentos estructurados de una fuente",
)
async def list_source_documents(corpus_id: UUID, source_id: UUID, request: Request) -> dict:
    ctx, ws, _corpus = await _require_corpus(request, corpus_id)
    # Verifica que la fuente pertenezca al corpus y workspace del mismo tenant.
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    if not any(str(s["id"]) == str(source_id) for s in sources):
        raise HTTPException(404, "Source not found in this workspace")
    documents = await PostgresStructuredDocumentRepository().list_documents(ctx.organization_id, source_id)
    public = [_public_structured_document(row) for row in documents]
    return {"documents": public, "count": len(public)}


def _public_structured_document(row: dict) -> dict:
    """Lista sin el markdown/AST. El detalle los pide aparte."""
    from src.knowledge.understanding import public_understanding

    meta = dict(row.get("metadata") or {})
    understanding = meta.get("understanding")
    if isinstance(understanding, dict):
        trimmed = dict(understanding)
        trimmed.pop("views", None)
        meta["understanding"] = trimmed
    reconstruction = meta.get("semantic_reconstruction")
    if isinstance(reconstruction, dict):
        # En listas solo el resumen: la IR completa se consulta en el detalle.
        meta["semantic_reconstruction"] = {
            key: reconstruction.get(key)
            for key in (
                "schema_version",
                "pipeline",
                "source_kind",
                "adapter",
                "status",
                "stats",
                "quality",
                "llm",
                "elapsed_ms",
                "warnings",
            )
        }
    published = dict(row)
    published["metadata"] = meta
    published["understanding"] = public_understanding(meta)
    return published


@router.get(
    "/workspaces/{corpus_id}/sources/{source_id}/documents/{document_id}/understanding",
    summary="Informe, árbol, markdown y AST canónicos",
)
async def document_understanding(corpus_id: UUID, source_id: UUID, document_id: UUID, request: Request) -> dict:
    from src.knowledge.reconstruction import tech_view_from_metadata
    from src.knowledge.understanding import public_understanding, understanding_views

    ctx, ws, _corpus = await _require_corpus(request, corpus_id)
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    if not any(str(item["id"]) == str(source_id) for item in sources):
        raise HTTPException(404, "Source not found in this workspace")
    row = await PostgresStructuredDocumentRepository().get_document(ctx.organization_id, document_id)
    if row is None or str(row.get("source_id")) != str(source_id):
        raise HTTPException(404, "Document not found")
    return {
        "document_id": str(document_id),
        "understanding": public_understanding(row.get("metadata")),
        "views": understanding_views(row.get("metadata")),
        "reconstruction": tech_view_from_metadata(row.get("metadata")),
    }


@router.get(
    "/workspaces/{corpus_id}/sources/{source_id}/insight",
    summary="Proyección documental explicable (knowledge_explorer_insight/v1)",
)
async def source_insight(corpus_id: UUID, source_id: UUID, request: Request) -> dict:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.knowledge.understanding.explorer import build_explorer_insight

    ctx, ws, _corpus = await _require_corpus(request, corpus_id)
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    source = next((item for item in sources if str(item["id"]) == str(source_id)), None)
    if source is None:
        raise HTTPException(404, "Source not found in this workspace")

    start = time.perf_counter()
    documents = await PostgresStructuredDocumentRepository().list_documents(ctx.organization_id, source_id, limit=20)
    documents_total = await PostgresStructuredDocumentRepository().count_documents(ctx.organization_id, source_id)
    document = documents[0] if documents else None
    blocks: list[dict] = []
    blocks_truncated = False
    if document is not None:
        blocks = await PostgresStructuredDocumentRepository().list_blocks(
            ctx.organization_id, document["id"], limit=5000
        )
        blocks_truncated = int(document.get("block_count") or 0) > len(blocks)

    session = await get_async_session()
    try:
        objects_total = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM knowledge_canonical_objects "
                        "WHERE organization_id = :oid AND source_id = :sid"
                    ),
                    {"oid": ctx.organization_id, "sid": source_id},
                )
            ).scalar_one()
            or 0
        )
        objects: list[dict] = []
        objects_cursor: str | None = None
        objects_truncated = False
        while len(objects) < 10000:
            cursor_clause = (
                "AND id > CAST(:cursor AS uuid) " if objects_cursor else ""
            )
            cursor_params = {"cursor": objects_cursor} if objects_cursor else {}
            rows = (
                await session.execute(
                    text(
                        "SELECT id, kind, name, display_name, description, status, "
                        "confidence, evidence_count, metadata "
                        "FROM knowledge_canonical_objects "
                        "WHERE organization_id = :oid AND source_id = :sid "
                        + cursor_clause
                        + "ORDER BY id ASC LIMIT 1000"
                    ),
                    {
                        "oid": ctx.organization_id,
                        "sid": source_id,
                        **cursor_params,
                    },
                )
            ).fetchall()
            if not rows:
                break
            objects.extend(dict(row._mapping) for row in rows)
            objects_cursor = str(rows[-1].id)
            if len(rows) < 1000:
                break
        if objects_total > len(objects):
            objects_truncated = True
        objects_total = max(objects_total, len(objects))

        evidence_total = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM evidence_ledger "
                        "WHERE organization_id = :oid AND source_id = :sid"
                    ),
                    {"oid": ctx.organization_id, "sid": source_id},
                )
            ).scalar_one()
            or 0
        )
        passages_available = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM evidence_ledger "
                        "WHERE organization_id = :oid AND source_id = :sid "
                        "AND excerpt IS NOT NULL AND excerpt <> ''"
                    ),
                    {"oid": ctx.organization_id, "sid": source_id},
                )
            ).scalar_one()
            or 0
        )
        evidence: list[dict] = []
        evidence_truncated = False
        evidence_cursor = None
        while len(evidence) < 10000:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, canonical_id, page, section_path, excerpt, locator, "
                        "evidence_type, strength, created_at "
                        "FROM evidence_ledger "
                        "WHERE organization_id = :oid AND source_id = :sid "
                        "AND (:has_cursor = false OR "
                        "     (COALESCE(strength, 0), created_at, id) < "
                        "     (:c_strength, :c_created, CAST(:c_id AS uuid))) "
                        "ORDER BY strength DESC NULLS LAST, created_at DESC, id ASC "
                        "LIMIT 1000"
                    ),
                    {
                        "oid": ctx.organization_id,
                        "sid": source_id,
                        "has_cursor": evidence_cursor is not None,
                        "c_strength": evidence_cursor[0] if evidence_cursor else 0,
                        "c_created": evidence_cursor[1] if evidence_cursor else None,
                        "c_id": evidence_cursor[2] if evidence_cursor else None,
                    },
                )
            ).fetchall()
            if not rows:
                break
            evidence.extend(dict(row._mapping) for row in rows)
            last = rows[-1]
            evidence_cursor = (
                float(last.strength or 0),
                last.created_at,
                str(last.id),
            )
            if len(rows) < 1000:
                break
        if evidence_total > len(evidence):
            evidence_truncated = True
    finally:
        await session.close()

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    return build_explorer_insight(
        source=source,
        document=document,
        documents=documents,
        objects=objects,
        evidence=evidence,
        blocks=blocks,
        read_stats={
            "objects_total": objects_total,
            "objects_truncated": objects_truncated,
            "objects_next_cursor": objects_cursor if objects_truncated else None,
            "evidence_total": evidence_total,
            "evidence_truncated": evidence_truncated,
            "passages_available": passages_available,
            "documents_total": documents_total,
            "documents_truncated": documents_total > len(documents),
            "blocks_truncated": blocks_truncated,
            "timing": {
                "elapsed_ms": elapsed_ms,
                "documents_read": len(documents),
                "objects_read": len(objects),
                "evidence_read": len(evidence),
                "blocks_read": len(blocks),
            },
        },
    )


class LocateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=4000)
    page_hint: int | None = Field(default=None, ge=1)


@router.post(
    "/workspaces/{corpus_id}/sources/{source_id}/locate",
    summary="Resolver anchor de cita → página (PDF highlight)",
)
async def locate_source(
    corpus_id: UUID,
    source_id: UUID,
    body: LocateRequest,
    request: Request,
) -> dict:
    ctx, ws, _corpus = await _require_corpus(request, corpus_id)
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    source = next((s for s in sources if str(s["id"]) == str(source_id)), None)
    if source is None:
        raise HTTPException(404, "Source not found in this workspace")

    from src.knowledge.locate import CitationLocator

    settings = get_settings()
    llm = None
    if settings.KNOWLEDGE_LOCATE_LLM_ENABLED:
        from src.api.deps import get_llm_provider

        llm = get_llm_provider()
    locator = CitationLocator(llm=llm)
    result = await locator.locate(
        ctx.organization_id,
        source_id,
        body.query,
        page_hint=body.page_hint,
    )
    return result.to_dict()


@router.get(
    "/workspaces/{corpus_id}/sources/{source_id}/file",
    summary="Archivo original de la fuente (para el Source Viewer)",
)
async def source_file(corpus_id: UUID, source_id: UUID, request: Request) -> object:
    from fastapi.responses import FileResponse

    ctx, ws, _corpus = await _require_corpus(request, corpus_id)
    sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    source = next((s for s in sources if str(s["id"]) == str(source_id)), None)
    if source is None:
        raise HTTPException(404, "Source not found in this workspace")
    object_key = source.get("object_key")
    if not object_key:
        raise HTTPException(404, "Source has no uploaded file")
    from src.knowledge.storage import resolve_path

    try:
        path = resolve_path(ctx.organization_id, object_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not path.exists():
        raise HTTPException(404, "File not found on storage")
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"
    is_pdf = path.suffix.lower() == ".pdf"
    return FileResponse(
        path,
        media_type=media_type,
        filename=source.get("name") or path.name,
        content_disposition_type="inline" if is_pdf else "attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Chat grounded sobre el corpus (requiere retina V2 activa)
# ---------------------------------------------------------------------------


@router.post("/workspaces/{corpus_id}/chat", summary="Chat grounded V2")
async def workspace_chat(corpus_id: UUID, body: ChatRequest, request: Request) -> dict:
    settings = get_settings()
    ctx, ws, _corpus = await _require_corpus(request, corpus_id)

    from src.api.deps import (
        get_embedding_provider,
        get_knowledge_retriever,
        get_llm_provider,
    )
    from src.rag.grounding import GroundingService
    from src.rag.retrieval.models import RetrievalQuery
    from src.rag.retrieval.structured import V2RetrievalOptions

    role = "admin" if ctx.is_organization_admin() else "user"
    user_id = getattr(ctx, "user_id", None)
    groups: list[str] = []
    if user_id:
        from src.platform.acl.groups import user_group_names

        groups = list(await user_group_names(ctx.organization_id, user_id))

    # El corpus es la frontera de recuperación. La UI no decide el ámbito:
    # se resuelve aquí desde la base y nunca se cae al workspace completo.
    corpus_sources = await _sources_for_corpus(ctx.organization_id, corpus_id, workspace_id=ws.id)
    corpus_source_ids = {str(source["id"]) for source in corpus_sources}
    ready_source_ids = {
        str(source["id"])
        for source in corpus_sources
        if str(source.get("status") or "").lower() in _READY_SOURCE_STATUSES
    }

    if body.source_ids:
        requested = [str(source_id) for source_id in body.source_ids]
        if any(source_id not in corpus_source_ids for source_id in requested):
            raise HTTPException(404, "Source not found in this corpus")
        effective_source_ids = requested
    else:
        effective_source_ids = sorted(ready_source_ids)

    scope = {
        "corpus_id": str(corpus_id),
        "source_count": len(effective_source_ids),
        "restricted": True,
    }
    if not effective_source_ids:
        from src.rag.grounding import GroundedAnswer

        empty = GroundedAnswer(
            answer="No tengo suficiente información para responder tu pregunta.",
            confidence=0.0,
        )
        return {"grounded": empty.to_dict(), "retrieval_scope": scope}

    logger.info(
        "grounded chat corpus scope",
        corpus_id=str(corpus_id),
        workspace_id=str(ws.id),
        explicit_sources=len(body.source_ids),
        scoped_sources=len(effective_source_ids),
        ready_sources=len(ready_source_ids),
    )

    query_embedding = await get_embedding_provider().embed(body.query)
    if isinstance(query_embedding[0], list):
        query_embedding = query_embedding[0]

    rquery = RetrievalQuery(
        query=body.query,
        organization_id=ctx.organization_id,
        role=role,
        user_id=user_id,
        groups=groups,
        workspace_id=ws.id,
        source_ids=[UUID(str(source_id)) for source_id in effective_source_ids],
        top_k=100,
        rerank_top_k=12,
        score_threshold=max(settings.RAG_SCORE_THRESHOLD, 0.1),
        strategy=settings.RAG_RETRIEVAL_STRATEGY,
        fusion=settings.RAG_HYBRID_FUSION,
        filters={
            "metadata.v2_chunk": "true",
            "workspace_id": str(ws.id),
        },
        query_embedding=list(query_embedding),
    )
    assembled = await get_knowledge_retriever().retrieve(rquery, V2RetrievalOptions())

    # Defensa en profundidad: aunque el retriever ya recibe source_ids, no
    # dejamos pasar ningún chunk cuya fuente esté fuera del corpus resuelto.
    allowed_context = tuple(
        chunk for chunk in assembled.context if str(chunk.metadata.get("source_id") or "") in set(effective_source_ids)
    )
    if len(allowed_context) != len(assembled.context):
        logger.error(
            "retrieval returned chunks outside corpus scope",
            corpus_id=str(corpus_id),
            returned=len(assembled.context),
            kept=len(allowed_context),
        )
        import dataclasses

        assembled = dataclasses.replace(assembled, context=allowed_context)

    if not assembled.context:
        from src.rag.grounding import GroundedAnswer

        empty = GroundedAnswer(
            answer="No tengo suficiente información para responder tu pregunta.",
            confidence=0.0,
        )
        return {"grounded": empty.to_dict(), "retrieval_scope": scope}

    context_snippets = "\n\n---\n\n".join(f"[{i + 1}] {chunk.content}" for i, chunk in enumerate(assembled.context))
    prompt = (
        f"{prompt_evidence_block(context_snippets).render()}\n\n"
        f"<user_question>\n{body.query}\n</user_question>\n\n"
        "Answer based on the context above. If the answer is not in the "
        "context, say so. Keep it concise."
    )
    llm_response = await get_llm_provider().generate(
        prompt,
        system_prompt=(
            "You are a grounded enterprise assistant. Never invent facts; answer only from the provided context."
        ),
    )
    grounded = GroundingService().ground(llm_response.content, assembled)
    payload = grounded.to_dict()
    payload["raw_answer"] = llm_response.content

    # Phase 2 slice 2: la respuesta grounded deja evidencia append-only con
    # locators reales (nunca rompe la respuesta si el ledger falla).
    try:
        from src.api.deps import get_evidence_ledger_repo
        from src.rag.grounding.recorder import GroundingLedgerRecorder

        evidence_ids = await GroundingLedgerRecorder(get_evidence_ledger_repo()).record_evidence_aligned(
            organization_id=ctx.organization_id,
            answer=grounded,
            workspace_id=ws.id,
        )
        payload["evidence_ids"] = [str(eid) for eid in evidence_ids if eid is not None]
        payload["citation_evidence_ids"] = [str(eid) if eid is not None else None for eid in evidence_ids]
    except Exception:  # noqa: BLE001 - el ledger nunca rompe el chat
        logger.warning("Failed to record grounded evidence", corpus_id=str(corpus_id))

    # Costo por query (§41): tokens LLM reales + categoría query.
    try:
        from src.knowledge.cost import KnowledgeUsageTracker

        await KnowledgeUsageTracker().record(
            ctx.organization_id,
            category="llm",
            tokens=llm_response.prompt_tokens + llm_response.completion_tokens,
            workspace_id=ws.id,
            corpus_id=corpus_id,
            metadata={"model": llm_response.model},
        )
        await KnowledgeUsageTracker().record(
            ctx.organization_id,
            category="query",
            tokens=0,
            workspace_id=ws.id,
            corpus_id=corpus_id,
            metadata={"latency_ms": round(assembled.retrieval_latency_ms, 2)},
        )
    except Exception:  # noqa: BLE001 - el tracking nunca rompe el chat
        logger.warning("Failed to record knowledge usage", corpus_id=str(corpus_id))

    return {"grounded": payload}


@router.post("/workspaces/{corpus_id}/studio", summary="Studio MVP (artefactos reales)")
async def workspace_studio(corpus_id: UUID, body: StudioRequest, request: Request) -> dict:
    ctx, _ws, _corpus = await _require_corpus(request, corpus_id)

    from src.platform.studio.service import CorpusStudioService

    artifacts = None
    if body.artifact:
        artifacts = (body.artifact,)
    result = await CorpusStudioService().build(ctx.organization_id, corpus_id, artifacts=artifacts)
    return result.to_dict()


@router.get("/workspaces/{corpus_id}/suggestions", summary="Preguntas sugeridas reales")
async def workspace_suggestions(corpus_id: UUID, request: Request) -> dict:
    ctx, _ws, _corpus = await _require_corpus(request, corpus_id)

    from src.rag.suggestions import QuestionSuggestionService

    questions = await QuestionSuggestionService().suggest(ctx.organization_id, corpus_id)
    return {"suggestions": [q.to_dict() for q in questions]}


# ---------------------------------------------------------------------------
# Helpers (scoped por tenant y workspace)
# ---------------------------------------------------------------------------

# Estados de kb_sources con contenido consultable. Los estados de sesión usan
# "available"/"completed"; la fuente subida usa "indexed". Nunca asumimos que
# una fuente en procesamiento ya tiene chunks.
_READY_SOURCE_STATUSES = frozenset({"indexed", "available", "completed"})


async def _require_corpus(request: Request, corpus_id: UUID) -> tuple[object, object, dict]:
    """Corpus autorizado del workspace actual o 404 sin revelar existencia."""
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    ws = await resolve_workspace(request)
    corpus = await get_corpus_repo().get_corpus(ctx.organization_id, corpus_id)
    if corpus is None or str(corpus.get("workspace_id")) != str(ws.id):
        raise HTTPException(404, "Knowledge workspace not found")
    return ctx, ws, corpus


async def _corpus_source_counts(organization_id: UUID) -> dict[str, int]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT corpus_id, COUNT(*)::int AS n FROM kb_sources "
                    "WHERE organization_id = :oid AND corpus_id IS NOT NULL "
                    "GROUP BY corpus_id"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        return {str(row.corpus_id): row.n for row in rows}
    finally:
        await session.close()


async def _sources_for_corpus(
    organization_id: UUID,
    corpus_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> list[dict]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        clauses = [
            "organization_id = :oid",
            "corpus_id = :cid",
        ]
        params: dict[str, object] = {
            "oid": organization_id,
            "cid": str(corpus_id),
        }
        if workspace_id is not None:
            clauses.append("workspace_id = :wid")
            params["wid"] = str(workspace_id)
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, type, status, workspace_id, "
                    "(config_json->>'object_key') AS object_key "
                    "FROM kb_sources WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC"
                ),
                params,
            )
        ).fetchall()
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "type": row.type,
                "status": row.status,
                "workspace_id": str(row.workspace_id) if row.workspace_id else None,
                "object_key": row.object_key,
            }
            for row in rows
        ]
    finally:
        await session.close()
