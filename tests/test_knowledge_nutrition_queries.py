# =============================================================================
# Knowledge Nutrition — acceptance de queries reales (sparse productivo Qdrant)
# =============================================================================
# Ingiere un documento técnico real y verifica que las 5 queries del brief
# recuperan la evidencia correcta en top-5 usando el retriever sparse REAL
# (QdrantVectorStore.search_sparse), el mismo de producción para la pata
# lexical. El dense no se prueba acá porque requiere provider de embeddings;
# la representación de retrieval alimenta el sparse (aliases, identificadores,
# conceptos y preguntas), que es exactamente lo que estas queries ejercitan.
#
# Luego simula retrieval miss y verifica la NutritionAction correspondiente.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.config import get_settings
from src.core.domain.entities import IngestionJobStatus
from src.infrastructure.postgres.knowledge_repos import (
    PostgresDocumentRegistryRepository,
    PostgresIngestionJobRepository,
    PostgresSourceRepository,
    PostgresSyncStateRepository,
)
from src.infrastructure.postgres.relational_db import (
    PostgresKnowledgeBaseRepository,
    PostgresOrganizationRepository,
)
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.connectors.base import Record, SourceConnector
from src.knowledge.connectors.registry import register_connector
from src.knowledge.engine.service import KnowledgeIngestionEngine

MANUAL = """# Category 31 - Voluntary Changes

Category 31 (CAT31) defines voluntary changes for exchange eligibility.

Field: Status Byte
Bytes: 105-105
Description: status of the voluntary change

Byte 105 indicates the status for voluntary changes.

If the status is A, then the change is accepted.
"""

QUERIES = (
    "Byte 105",
    "What does Byte 105 mean?",
    "CAT31 status",
    "Voluntary Changes status byte",
    "Category 31 byte for status",
    "105",
    "Where is the status for voluntary changes stored?",
    "exchange rules status indicator",
)


class QueryProbeConnector(SourceConnector):
    source_type = "test_nutrition_queries"
    self_contained = False

    async def validate(self) -> None:
        pass

    async def iter_records(self, cursor: dict | None):
        yield Record(
            external_id="queries.md",
            content=MANUAL,
            metadata={"filename": "queries.md", "format": "md"},
            raw_data=MANUAL.encode("utf-8"),
            format="md",
        )


register_connector(QueryProbeConnector)


class ConstantEmbedding:
    async def embed(self, texts, model=None):
        if isinstance(texts, str):
            return [0.1] * get_settings().VECTOR_DIMENSION
        return [[0.1] * get_settings().VECTOR_DIMENSION for _ in texts]


def _requires_qdrant() -> bool:
    return get_settings().ENVIRONMENT == "development"


@pytest.mark.asyncio
async def test_five_queries_find_evidence_and_failure_creates_nutrition_action() -> None:
    if not _requires_qdrant():
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore
    from src.knowledge.acceptance import PostgresAcceptanceStore
    from src.knowledge.nutrition import (
        FailureSignals,
        FailureType,
        NutritionActionType,
        apply_feedback_nutrition,
    )

    store = QdrantVectorStore()
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"Queries Org {uuid4().hex[:6]}"
    )
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id, "KB Queries", chunking_strategy="fixed", chunk_size=500, chunk_overlap=50
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id, "src-queries", "test_nutrition_queries", knowledge_base_id=kb.id
    )
    structured_repo = PostgresStructuredDocumentRepository()
    engine = KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=store,
        embedding_provider=ConstantEmbedding(),
        backoff_base_seconds=1,
        max_attempts_default=2,
        structured_doc_repo=structured_repo,
    )

    async def _skip_acceptance(job, document, enrichment):
        return None

    engine._run_acceptance = _skip_acceptance  # type: ignore[method-assign]
    try:
        job_repo = PostgresIngestionJobRepository()
        job = await job_repo.create_job(
            organization.id,
            job_type="sync_source:test_nutrition_queries",
            source_id=source.id,
            knowledge_base_id=kb.id,
            max_attempts=2,
        )
        result = await engine.execute_job(job.id)
        assert result.status == IngestionJobStatus.COMPLETED

        # Las 5 queries del brief encuentran la evidencia en top-5 (sparse real).
        failures: dict[str, list[str]] = {}
        for query in QUERIES:
            context = await store.search_sparse(
                organization.id,
                query,
                top_k=5,
                score_threshold=0.0,
                role="admin",
                source_ids=[source.id],
            )
            hits = []
            for chunk in context.chunks:
                metadata = chunk.metadata or {}
                evidence = "Byte 105" in (chunk.content or "") or "Byte 105" in str(
                    metadata.get("enrichment_identifiers") or []
                )
                if evidence:
                    hits.append(chunk)
            if not hits:
                failures[query] = [c.content[:80] for c in context.chunks[:3]]
            else:
                top = hits[0]
                metadata = top.metadata or {}
                # Citation/source/section/exact evidence verificables.
                assert metadata.get("source_id") == str(source.id)
                assert metadata.get("document_id")
                assert metadata.get("section_id")
                assert "Byte 105" in (top.content or "") or "Byte 105" in str(
                    metadata.get("enrichment_identifiers") or []
                )
        assert not failures, failures

        # PASS 2 real: los ids canónicos viven DENTRO de metadata (contrato de
        # retrieval), no en claves top-level invisibles.
        pass2_visible = False
        for query in ("Byte 105", "CAT31"):
            context = await store.search_sparse(
                organization.id, query, top_k=5, score_threshold=0.0, role="admin"
            )
            if any(
                (chunk.metadata or {}).get("canonical_entity_ids")
                for chunk in context.chunks
            ):
                pass2_visible = True
                break
        assert pass2_visible, "PASS 2 debe ser visible en metadata de retrieval"

        # Simulación de fallo: retrieval miss -> NutritionAction no destructiva.
        outcome = await apply_feedback_nutrition(
            FailureSignals(
                query="Byte 105 in Category 31",
                retrieved_chunks=0,
                lexical_hit=False,
                semantic_hit=False,
                source_id=str(source.id),
                workspace_id=None,
            ),
            organization_id=organization.id,
        )
        assert outcome.classification.failure_type == FailureType.RETRIEVAL_MISS.value
        assert (
            outcome.action.action_type
            == NutritionActionType.GENERATE_RETRIEVAL_ALIASES.value
        )
        assert outcome.action.destructive is False
        assert outcome.persisted is True

        # Query inexistente: el sistema NO debe presentar evidencia inventada.
        fictional = "What is the quantum encryption algorithm used by CAT31?"
        context = await store.search_sparse(
            organization.id, fictional, top_k=5, score_threshold=0.0, role="admin"
        )
        for chunk in context.chunks:
            content = (chunk.content or "").lower()
            assert "quantum" not in content
            assert "encryption" not in content
        # Un probe con evidencia ficticia falla y el gate lo reporta FAIL.
        from src.knowledge.acceptance import RetrievalProbe, evaluate_probes

        fictional_probe = RetrievalProbe(
            probe_id=str(uuid4()),
            organization_id=organization.id,
            document_id=uuid4(),  # documento que no existe en el corpus
            query=fictional,
            query_type="semantic_paraphrase",
            expected_document_id=str(uuid4()),
            expected_unit_id=str(uuid4()),
        )
        fictional_report = await evaluate_probes(
            (fictional_probe,),
            embedder=ConstantEmbedding(),
            vector_store=store,
            measure_lexical=False,
        )
        assert fictional_report.gate_state == "FAIL"
        assert fictional_report.probes_passed == 0
        # Clasificación correcta: falta conocimiento, no gap de ranking.
        gap_outcome = await apply_feedback_nutrition(
            FailureSignals(
                query=fictional,
                retrieved_chunks=len(context.chunks),
                no_source_match=True,
            ),
            organization_id=organization.id,
        )
        assert gap_outcome.classification.failure_type == FailureType.MISSING_KNOWLEDGE.value
        assert gap_outcome.action.requires_review is True
        assert gap_outcome.action.destructive is False

        # La evaluación quedó persistida y re-ejecutable.
        acceptance_store = PostgresAcceptanceStore()
        probes = await acceptance_store.list_probes(organization.id, active_only=True)
        assert isinstance(probes, list)
    finally:
        try:
            await store.delete_by_organization(organization.id)
        except Exception:
            pass
