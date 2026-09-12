# =============================================================================
# Hybrid Retrieval — integración con Qdrant real (sparse + dense + fusion)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.config import get_settings


@pytest.mark.asyncio
async def test_sparse_search_finds_keyword_match_real_qdrant() -> None:
    """Upsert con sparse computado + búsqueda lexical por keyword."""
    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org = uuid4()

    def vec(value: float) -> list[float]:
        v = [0.0] * settings.VECTOR_DIMENSION
        v[0] = value
        return v

    try:
        await store.upsert(
            org,
            uuid4(),
            vec(0.9),
            "Ibuprofeno 600mg comprimidos recubiertos",
            metadata={"visibility": "public"},
        )
        await store.upsert(
            org,
            uuid4(),
            vec(0.8),
            "Crema hidratante corporal sin perfume",
            metadata={"visibility": "public"},
        )

        ctx = await store.search_sparse(
            org,
            "ibuprofeno",
            top_k=10,
            score_threshold=0.0,
        )
        contents = [c.content for c in ctx.chunks]
        assert any("Ibuprofeno" in c for c in contents)
    except RuntimeError as exc:
        if "lacks sparse vectors" in str(exc):
            pytest.skip("Colección legacy sin sparse: ejecutar migrate_qdrant_hybrid.py")
        raise
    finally:
        try:
            await store.delete_by_organization(org)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_sparse_search_rejects_missing_organization() -> None:
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    with pytest.raises(ValueError):
        await store.search_sparse(  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            "query",
            top_k=5,
        )


@pytest.mark.asyncio
async def test_hybrid_search_returns_dense_and_sparse_matches_real_qdrant() -> None:
    """La fusión RRF server-side devuelve matches de ambas patas."""
    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org = uuid4()

    def vec(value: float) -> list[float]:
        v = [0.0] * settings.VECTOR_DIMENSION
        v[0] = value
        return v

    try:
        await store.upsert(
            org,
            uuid4(),
            vec(0.9),
            "Paracetamol 500mg comprimidos para el dolor de cabeza",
            metadata={"visibility": "public"},
        )
        await store.upsert(
            org,
            uuid4(),
            vec(0.7),
            "Vitamina C 1000mg efervescente",
            metadata={"visibility": "public"},
        )

        ctx = await store.search_hybrid(
            org,
            "paracetamol dolor cabeza",
            vec(0.9),
            top_k=10,
            score_threshold=0.0,
        )
        contents = [c.content for c in ctx.chunks]
        assert any("Paracetamol" in c for c in contents)
    except RuntimeError as exc:
        if "lacks sparse vectors" in str(exc):
            pytest.skip("Colección legacy sin sparse: ejecutar migrate_qdrant_hybrid.py")
        raise
    finally:
        try:
            await store.delete_by_organization(org)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_sparse_tenant_isolation_real_qdrant() -> None:
    """La pata lexical también aisla por organization_id."""
    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org_a = uuid4()
    org_b = uuid4()

    def vec(value: float) -> list[float]:
        v = [0.0] * settings.VECTOR_DIMENSION
        v[0] = value
        return v

    try:
        await store.upsert(
            org_a,
            uuid4(),
            vec(0.9),
            "Documento secreto único de la organización A",
            metadata={"visibility": "public"},
        )
        await store.upsert(
            org_b,
            uuid4(),
            vec(0.9),
            "Documento secreto único de la organización B",
            metadata={"visibility": "public"},
        )

        ctx_a = await store.search_sparse(org_a, "organización A", top_k=10, score_threshold=0.0)
        contents_a = {c.content for c in ctx_a.chunks}
        assert "Documento secreto único de la organización A" in contents_a
        assert "Documento secreto único de la organización B" not in contents_a
    except RuntimeError as exc:
        if "lacks sparse vectors" in str(exc):
            pytest.skip("Colección legacy sin sparse: ejecutar migrate_qdrant_hybrid.py")
        raise
    finally:
        try:
            await store.delete_by_organization(org_a)
        except Exception:
            pass
        try:
            await store.delete_by_organization(org_b)
        except Exception:
            pass


def _dev_qdrant_stack() -> bool:
    from src.core.config import get_settings

    return get_settings().ENVIRONMENT == "development"


def _vec(value: float) -> list[float]:
    from src.core.config import get_settings

    v = [0.0] * get_settings().VECTOR_DIMENSION
    v[0] = value
    return v


@pytest.mark.asyncio
async def test_search_filters_by_workspace_real_qdrant() -> None:
    """F4: workspace_id filtra el retrieval en Qdrant (pre-LLM)."""
    if not _dev_qdrant_stack():
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org = uuid4()
    workspace_a = uuid4()
    workspace_b = uuid4()
    try:
        await store.upsert(
            org,
            uuid4(),
            _vec(0.9),
            "Documento dentro del workspace A",
            metadata={"visibility": "public"},
            workspace_id=workspace_a,
        )
        await store.upsert(
            org,
            uuid4(),
            _vec(0.9),
            "Documento dentro del workspace B",
            metadata={"visibility": "public"},
            workspace_id=workspace_b,
        )
        ctx = await store.search(
            org, _vec(0.9), top_k=10, score_threshold=0.0,
            workspace_id=workspace_a,
        )
        contents = [c.content for c in ctx.chunks]
        assert "Documento dentro del workspace A" in contents
        assert "Documento dentro del workspace B" not in contents
    finally:
        try:
            await store.delete_by_organization(org)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_get_documents_respects_acl_real_qdrant() -> None:
    """F18: fetch por ID aplica visibility/acl_groups sin filtrar post-LLM."""
    if not _dev_qdrant_stack():
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org = uuid4()
    point_id = uuid4()
    try:
        await store.upsert(
            org,
            point_id,
            _vec(0.9),
            "Contrato confidencial del área legal",
            metadata={
                "visibility": "admin",
                "acl_groups": ["legal"],
            },
        )
        denied = await store.get_documents(org, [point_id], role="viewer")
        assert denied.chunks == []
        allowed = await store.get_documents(
            org, [point_id], role="viewer", groups=["legal"]
        )
        assert len(allowed.chunks) == 1
        admin = await store.get_documents(org, [point_id], role="admin")
        assert len(admin.chunks) == 1
    finally:
        try:
            await store.delete_by_organization(org)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_delete_stale_v2_documents_keeps_v1_and_live_real_qdrant() -> None:
    """F5: purga V2 huérfana sin tocar chunks V1 ni documentos vivos."""
    if not _dev_qdrant_stack():
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org = uuid4()
    source_id = uuid4()
    v1_id, keep_id, gone_id = uuid4(), uuid4(), uuid4()
    try:
        await store.upsert(
            org,
            v1_id,
            _vec(0.9),
            "Chunk legacy V1 que debe sobrevivir",
            metadata={"visibility": "public"},
        )
        await store.upsert(
            org,
            keep_id,
            _vec(0.9),
            "Documento V2 vivo durante el sync",
            metadata={
                "visibility": "public",
                "v2_doc": "true",
                "source_id": str(source_id),
                "external_id": "keep.md",
            },
        )
        await store.upsert(
            org,
            gone_id,
            _vec(0.9),
            "Documento V2 eliminado de la fuente",
            metadata={
                "visibility": "public",
                "v2_doc": "true",
                "source_id": str(source_id),
                "external_id": "gone.md",
            },
        )
        await store.delete_stale_v2_documents(org, source_id, {"keep.md"})
        ctx = await store.get_documents(
            org, [v1_id, keep_id, gone_id], role="admin"
        )
        contents = {c.content for c in ctx.chunks}
        assert "Chunk legacy V1 que debe sobrevivir" in contents
        assert "Documento V2 vivo durante el sync" in contents
        assert "Documento V2 eliminado de la fuente" not in contents
    finally:
        try:
            await store.delete_by_organization(org)
        except Exception:
            pass
