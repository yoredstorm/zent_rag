# =============================================================================
# Certification battery — aislamiento multi-tenant bajo contenido idéntico.
# =============================================================================
# Parte H del checklist de canary: no alcanza con dos tests unitarios. Se crean
# organizaciones A y B con datos DELIBERADAMENTE PARECIDOS (mismo texto, mismo
# filename, misma etiqueta de conversación, misma query) y se verifica que
# retrieval, cache, usage y billing no crucen el boundary. La clave de
# aislamiento debe ser correcta aunque el contenido coincida.
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.knowledge_scope import KnowledgeScope, narrow
from src.infrastructure.redis.cache import RedisCache
from src.platform.billing.reconciliation import reconcile
from src.platform.usage.usage_engine import UsageEvent, record_event

IDENTICAL_QUERY = "¿Cuál es la política de vacaciones de la empresa?"
IDENTICAL_FILENAME = "informe-anual-2026.pdf"
IDENTICAL_TEXT = "Política interna: 20 días de vacaciones por año calendario."


# ---------------------------------------------------------------------------
# 1. Cache de respuestas: mismo texto, mismo rol, misma etiqueta de conversación
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_response_cache_key_isolates_tenants_with_identical_query() -> None:
    cache = RedisCache()
    org_a, org_b = uuid4(), uuid4()
    conversation_label = "shared-conversation-label"
    fingerprint = "same-knowledge-fingerprint"

    def key(org, conversation: str = conversation_label) -> str:
        return RedisCache._build_key(
            "resp",
            RedisCache._hash_query(
                str(org),
                IDENTICAL_QUERY,
                "model-x",
                "admin",
                knowledge_fingerprint=fingerprint,
                conversation_id=conversation,
            ),
        )

    key_a, key_b = key(org_a), key(org_b)
    assert key_a != key_b, "la clave de caché no incluye el tenant"

    try:
        await cache.set(key_a, "RESPUESTA-ORG-A", ttl_seconds=30)
        assert await cache.get(key_a) == "RESPUESTA-ORG-A"
        # B con la MISMA query/rol/conversación no puede leer la respuesta de A.
        assert await cache.get(key_b) is None
        # A con OTRA conversación tampoco (scope real, no TTL).
        assert await cache.get(key(org_a, "otra-conversacion")) is None
        # Sin fingerprint de conocimiento la clave cambia (fail-closed del caller).
        sin_fingerprint = RedisCache._build_key(
            "resp",
            RedisCache._hash_query(
                str(org_a),
                IDENTICAL_QUERY,
                "model-x",
                "admin",
                knowledge_fingerprint="",
                conversation_id=conversation_label,
            ),
        )
        assert sin_fingerprint != key_a
    finally:
        await cache.delete(key_a)


# ---------------------------------------------------------------------------
# 2. Retrieval: mismo texto y mismo filename en dos organizaciones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_vector_search_isolates_tenants_with_identical_documents() -> None:
    from src.core.config import get_settings
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    store = QdrantVectorStore()
    org_a, org_b, org_c = uuid4(), uuid4(), uuid4()
    dim = settings.VECTOR_DIMENSION

    def vec(value: float) -> list[float]:
        vector = [0.0] * dim
        vector[0] = value
        return vector

    metadata = {"visibility": "public", "filename": IDENTICAL_FILENAME}
    try:
        await store.upsert(org_a, uuid4(), vec(0.9), IDENTICAL_TEXT, metadata=dict(metadata))
        await store.upsert(org_b, uuid4(), vec(0.9), IDENTICAL_TEXT, metadata=dict(metadata))

        ctx_a = await store.search(org_a, vec(0.9), top_k=10, score_threshold=0.0)
        ctx_b = await store.search(org_b, vec(0.9), top_k=10, score_threshold=0.0)
        ctx_c = await store.search(org_c, vec(0.9), top_k=10, score_threshold=0.0)

        # El contenido es idéntico: la única defensa es el filtro por tenant.
        assert len(ctx_a.chunks) == 1
        assert len(ctx_b.chunks) == 1
        assert len(ctx_c.chunks) == 0
    finally:
        for org in (org_a, org_b):
            try:
                await store.delete_by_organization(org)
            except Exception:  # noqa: BLE001 - limpieza best-effort
                pass


# ---------------------------------------------------------------------------
# 3. Usage/billing: mismos tokens y costo en dos organizaciones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_usage_and_billing_are_tenant_scoped() -> None:
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        event = UsageEvent(
            request_id=uuid4(),
            event_type="rag_query",
            organization_id=org,
            total_tokens=100,
            estimated_cost=0.01,
            actual_cost=0.01,
            model="test-model",
            status="completed",
        )
        assert await record_event(event) is True

    report_a = await reconcile(org_a, days=1)
    report_b = await reconcile(org_b, days=1)

    row_a = [r for r in report_a if str(r["organization_id"]) == str(org_a)]
    row_b = [r for r in report_b if str(r["organization_id"]) == str(org_b)]
    assert len(row_a) == 1 and len(row_b) == 1
    assert row_a[0]["requests"] == 1 and row_b[0]["requests"] == 1
    assert row_a[0]["tokens"] == 100 and row_b[0]["tokens"] == 100
    assert row_a[0]["usage_cost"] == pytest.approx(0.01)
    assert row_b[0]["usage_cost"] == pytest.approx(0.01)
    # El reporte de A jamás incluye filas de B (ni agregados).
    assert all(str(r["organization_id"]) != str(org_b) for r in report_a)


# ---------------------------------------------------------------------------
# 4. Knowledge scope: scopes disjuntos no se amplían nunca
# ---------------------------------------------------------------------------
def test_knowledge_scope_never_widens_across_tenants() -> None:
    source_a, source_b = uuid4(), uuid4()
    scope_a = KnowledgeScope(source_ids=(source_a,), canonical_kinds=("rule",))
    scope_b = KnowledgeScope(source_ids=(source_b,), canonical_kinds=("rule",))

    assert narrow(scope_a, scope_b).source_ids == ()
    assert narrow(scope_b, scope_a).source_ids == ()
    # Un scope vacío NO restringe (documentado): por eso el caller debe
    # construir el scope base desde el tenant, nunca desde el modelo.
    assert narrow(KnowledgeScope(), scope_a).source_ids == (source_a,)
    assert narrow(scope_a, KnowledgeScope(source_ids=(source_a,))).source_ids == (source_a,)
