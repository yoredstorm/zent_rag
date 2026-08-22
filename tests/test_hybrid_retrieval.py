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
