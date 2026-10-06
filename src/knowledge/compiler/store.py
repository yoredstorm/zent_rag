# =============================================================================
# Knowledge Compiler — persistencia del conocimiento canónico
# =============================================================================
# Escribe en las tablas canónicas del Knowledge OS:
#   knowledge_canonical_objects  (Knowledge Objects, incluidos entity/term/rule)
#   knowledge_entity_aliases     (identidad multi-alias)
#   knowledge_assertions         (Facts, con temporalidad y provenance)
#   knowledge_edges              (Relationships tipadas)
#   evidence_ledger              (provenance: documento/página/bloque/tabla/celda)
#   knowledge_conflicts          (conflictos clasificados)
#   knowledge_compilations       (traza de cada corrida)
#
# Todo es idempotente y scoped por organization_id. La identidad canónica es
# determinista (canonical_uuid), así que recompilar la misma fuente actualiza
# los mismos objetos en lugar de duplicarlos.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from src.core.domain.canonical import CanonicalKind, canonical_uuid
from src.core.domain.knowledge_model import (
    ConfidenceSignals,
    KnowledgeProvenance,
    compute_confidence,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.knowledge.compiler.model import (
    CompilationResult,
    ConflictCandidate,
    EntityAlias,
    EntityCandidate,
    EvidenceRef,
    FactCandidate,
    RelationshipCandidate,
    RuleCandidate,
    SourceLocator,
)

logger = get_logger(__name__)

_ENTITY_KIND_BY_TYPE: dict[str, str] = {
    "concept": CanonicalKind.CONCEPT.value,
    "term": CanonicalKind.TERM.value,
    "field": CanonicalKind.ATTRIBUTE.value,
    "code": CanonicalKind.TERM.value,
    "record": CanonicalKind.ENTITY.value,
    "category": CanonicalKind.ENTITY.value,
    "table": CanonicalKind.TABLE.value,
    "column": CanonicalKind.COLUMN.value,
    "source": CanonicalKind.SOURCE.value,
    "document": CanonicalKind.DOCUMENT.value,
    "organization": CanonicalKind.ENTITY.value,
    "process": CanonicalKind.PROCESS.value,
    "unknown": CanonicalKind.ENTITY.value,
}

_ASSERTION_TYPE_BY_FACT_KIND: dict[str, str] = {
    "definition": "term_definition",
    "field_meaning": "field_meaning",
    "structural": "fact",
    "rule": "business_rule",
    "constraint": "constraint",
    "process_step": "process_step",
    "metric": "metric_definition",
    "reference": "fact",
    "other": "fact",
}

_METHOD_TO_EVIDENCE: dict[str, str] = {
    "deterministic": "deterministic",
    "schema": "schema",
    "structural": "structural",
    "statistical": "statistical",
    "document": "document",
    "human": "human",
    "llm": "llm",
}


def object_kind_for_entity(entity_type: str) -> str:
    return _ENTITY_KIND_BY_TYPE.get(entity_type, CanonicalKind.ENTITY.value)


def assertion_type_for(fact_kind: str) -> str:
    return _ASSERTION_TYPE_BY_FACT_KIND.get(fact_kind, "fact")


class CompilerStore(Protocol):
    """Contrato de persistencia del compilador (implementable en memoria)."""

    async def existing_aliases(self, organization_id: UUID) -> dict[str, str]: ...

    async def existing_rule_keys(self, organization_id: UUID) -> dict[str, str]: ...

    async def upsert_entity(
        self,
        organization_id: UUID,
        entity: EntityCandidate,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
    ) -> UUID: ...

    async def upsert_alias(
        self,
        organization_id: UUID,
        *,
        entity_id: UUID,
        alias: EntityAlias,
        source_id: UUID | None,
        document_id: UUID | None,
        evidence_ids: list[UUID],
    ) -> None: ...

    async def upsert_fact(
        self,
        organization_id: UUID,
        fact: FactCandidate,
        *,
        subject_id: UUID | None,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID | None,
    ) -> tuple[UUID, int, str]: ...

    async def upsert_relationship(
        self,
        organization_id: UUID,
        relationship: RelationshipCandidate,
        *,
        subject_id: UUID | None,
        object_id: UUID | None,
        source_id: UUID | None,
        workspace_id: UUID | None,
    ) -> tuple[UUID | None, str]: ...

    async def upsert_rule(
        self,
        organization_id: UUID,
        rule: RuleCandidate,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID | None,
    ) -> tuple[UUID, str]: ...

    async def add_evidence(
        self,
        organization_id: UUID,
        evidence: EvidenceRef,
        *,
        canonical_id: UUID | None = None,
        assertion_id: UUID | None = None,
        workspace_id: UUID | None = None,
        authority: str | None = None,
    ) -> UUID | None: ...

    async def upsert_conflict(
        self,
        organization_id: UUID,
        conflict: ConflictCandidate,
        *,
        object_id: UUID | None,
        workspace_id: UUID | None,
    ) -> str: ...

    async def record_quality_issue(
        self,
        organization_id: UUID,
        issue: object,
        *,
        workspace_id: UUID | None,
    ) -> None: ...

    async def record_compilation(
        self,
        organization_id: UUID,
        *,
        result: CompilationResult,
        workspace_id: UUID | None,
        duration_ms: int,
        status: str,
        error: str | None = None,
    ) -> None: ...

    async def refresh_counters(self, organization_id: UUID) -> None: ...


class PostgresCompilerStore:
    """Implementación Postgres del contrato (SQL crudo, igual que el resto)."""

    async def existing_aliases(self, organization_id: UUID) -> dict[str, str]:
        """{alias_normalizado: nombre_canónico} de los alias ya persistidos."""
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT a.normalized, o.name
                        FROM knowledge_entity_aliases a
                        JOIN knowledge_canonical_objects o
                          ON o.id = a.entity_id AND o.organization_id = a.organization_id
                        WHERE a.organization_id = :org
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — tabla ausente en entornos previos
            logger.warning("Knowledge alias index unavailable", error=str(exc)[:200])
            return {}
        finally:
            await session.close()
        return {str(row.normalized): str(row.name) for row in rows}

    async def existing_rule_keys(self, organization_id: UUID) -> dict[str, str]:
        """{subject: rule_key} de las reglas ya persistidas por el compilador.

        Las reglas del compilador viven en ``knowledge_canonical_objects`` con
        ``kind='business_rule'`` (ver ``upsert_rule``), con el subject en
        ``name`` y la clave en ``metadata->>'rule_key'``. La tabla
        ``knowledge_business_rules`` pertenece a otra materialización y no la
        escribe este store.
        """
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT name, metadata->>'rule_key' AS rule_key
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND kind = :kind
                          AND metadata->>'rule_key' IS NOT NULL
                        """
                    ),
                    {
                        "org": organization_id,
                        "kind": CanonicalKind.BUSINESS_RULE.value,
                    },
                )
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — tabla ausente en entornos previos
            logger.warning("Knowledge rule index unavailable", error=str(exc)[:200])
            return {}
        finally:
            await session.close()
        return {str(row.name): str(row.rule_key) for row in rows}

    # ------------------------------------------------------------------ objetos
    async def upsert_entity(
        self,
        organization_id: UUID,
        entity: EntityCandidate,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
    ) -> UUID:
        kind = object_kind_for_entity(entity.entity_type)
        natural_key = f"entity:{entity.entity_type}:{entity.normalized}"[:768]
        object_id = canonical_uuid(organization_id, CanonicalKind(kind), natural_key)
        signals = ConfidenceSignals(
            source_reliability=0.85,
            evidence_strength=0.85,
            evidence_count=len(entity.evidence),
            semantic_certainty=0.9,
            freshness=1.0,
            validation=0.85,
        )
        confidence, _detail = compute_confidence(signals)
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_canonical_objects (
                        id, organization_id, workspace_id, kind, natural_key,
                        title, name, display_name, description, domain,
                        provenance, status, confidence, source_id,
                        source_of_truth, evidence_count, last_seen_at,
                        freshness_at, metadata
                    ) VALUES (
                        :oid, :org, :workspace, :kind, :key,
                        :name, :name, :name, :description, :domain,
                        :provenance, :status, :confidence, :source_id,
                        :source_of_truth, :evidence_count, now(),
                        now(), CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (organization_id, kind, natural_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = COALESCE(EXCLUDED.description,
                                               knowledge_canonical_objects.description),
                        domain = COALESCE(EXCLUDED.domain,
                                          knowledge_canonical_objects.domain),
                        confidence = GREATEST(EXCLUDED.confidence,
                                              knowledge_canonical_objects.confidence),
                        evidence_count = GREATEST(
                            EXCLUDED.evidence_count,
                            knowledge_canonical_objects.evidence_count),
                        last_seen_at = now(),
                        freshness_at = now(),
                        metadata = knowledge_canonical_objects.metadata || EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "oid": object_id,
                    "org": organization_id,
                    "workspace": workspace_id,
                    "kind": kind,
                    "key": natural_key,
                    "name": entity.name[:512],
                    "description": entity.description,
                    "domain": entity.domain,
                    "provenance": KnowledgeProvenance.OBSERVED.value,
                    "status": "discovered",
                    "confidence": confidence,
                    "source_id": source_id,
                    "source_of_truth": entity.name[:512],
                    "evidence_count": len(entity.evidence),
                    "metadata": _json(
                        {
                            "entity_type": entity.entity_type,
                            "aliases": [a.alias for a in entity.aliases],
                            "compiled_by": "knowledge_compiler",
                        }
                    ),
                },
            )
            await session.commit()
        finally:
            await session.close()
        return object_id

    async def upsert_alias(
        self,
        organization_id: UUID,
        *,
        entity_id: UUID,
        alias: EntityAlias,
        source_id: UUID | None,
        document_id: UUID | None,
        evidence_ids: list[UUID],
    ) -> None:
        normalized = alias.normalized
        if not normalized:
            return
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_entity_aliases (
                        organization_id, entity_id, alias, normalized, alias_type,
                        confidence, reason, source_id, document_id, evidence_ids,
                        metadata
                    ) VALUES (
                        :org, :entity, :alias, :normalized, :alias_type,
                        :confidence, :reason, :source_id, :document_id,
                        CAST(:evidence_ids AS uuid[]), CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (organization_id, entity_id, normalized) DO UPDATE SET
                        confidence = GREATEST(EXCLUDED.confidence,
                                              knowledge_entity_aliases.confidence),
                        alias_type = EXCLUDED.alias_type,
                        reason = EXCLUDED.reason,
                        document_id = COALESCE(EXCLUDED.document_id,
                                               knowledge_entity_aliases.document_id),
                        evidence_ids = (
                            SELECT ARRAY(
                                SELECT DISTINCT unnest(
                                    knowledge_entity_aliases.evidence_ids
                                    || EXCLUDED.evidence_ids)
                            )
                        ),
                        updated_at = now()
                    """
                ),
                {
                    "org": organization_id,
                    "entity": entity_id,
                    "alias": alias.alias[:512],
                    "normalized": normalized[:512],
                    "alias_type": alias.alias_type,
                    "confidence": max(0.0, min(1.0, alias.confidence)),
                    "reason": (alias.reason or "")[:200],
                    "source_id": source_id,
                    "document_id": document_id,
                    "evidence_ids": [str(value) for value in evidence_ids],
                    "metadata": _json({"compiled_by": "knowledge_compiler"}),
                },
            )
            await session.commit()
        finally:
            await session.close()

    # ------------------------------------------------------------------ hechos
    async def upsert_fact(
        self,
        organization_id: UUID,
        fact: FactCandidate,
        *,
        subject_id: UUID | None,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID | None,
    ) -> tuple[UUID, int, str]:
        """Inserta/refuerza el hecho. Devuelve (assertion_id, evidence_count, status).

        CORROBORACIÓN, NO DUPLICACIÓN: si el mismo hecho ya existe (misma
        fuente o distinta), se incrementa su respaldo. La unicidad de la tabla
        es (org, subject_label, predicate, object_value).

        ``status`` es ``created`` (ZENT no lo sabía) o ``reinforced`` (ya
        existía y esta fuente lo respalda): insumo real del delta de
        aprendizaje, nunca inventado.
        """
        subject_label = fact.subject[:512]
        predicate = fact.predicate[:200]
        object_value = (fact.object_value or "")[:4000] or None
        method = fact.method if fact.method in _METHOD_TO_EVIDENCE else "deterministic"
        temporal = fact.temporal
        session = await get_async_session()
        try:
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT id, evidence_count,
                               metadata->'evidence_sources' AS evidence_sources
                        FROM knowledge_assertions
                        WHERE organization_id = :org
                          AND subject_label = :label
                          AND predicate = :predicate
                          AND COALESCE(object_value, '') = COALESCE(:value, '')
                        """
                    ),
                    {
                        "org": organization_id,
                        "label": subject_label,
                        "predicate": predicate,
                        "value": object_value,
                    },
                )
            ).first()

            signals = ConfidenceSignals(
                source_reliability=0.85,
                evidence_strength=fact.confidence,
                evidence_count=len(fact.evidence),
                semantic_certainty=0.9 if method in {"schema", "deterministic"} else 0.7,
                freshness=1.0,
                validation=0.85,
            )
            score, detail = compute_confidence(signals)
            detail = {
                **detail,
                "fact_kind": fact.fact_kind,
                "temporal": temporal.to_dict(),
            }

            if existing is None:
                status = "created"
                row = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO knowledge_assertions (
                                organization_id, workspace_id, subject_id,
                                subject_label, predicate, object_value,
                                assertion_type, confidence, confidence_detail,
                                status, provenance, method, source_id,
                                evidence_count, valid_from, valid_to, observed_at,
                                scope, metadata
                            ) VALUES (
                                :org, :workspace, :subject, :label, :predicate,
                                :value, :atype, :confidence,
                                CAST(:detail AS jsonb), 'candidate', :provenance,
                                :method, :source_id, :evidence_count,
                                :valid_from, :valid_to, :observed_at, :scope,
                                CAST(:metadata AS jsonb)
                            )
                            RETURNING id
                            """
                        ),
                        {
                            **_fact_params(
                                organization_id=organization_id,
                                workspace_id=workspace_id,
                                subject_id=subject_id,
                                subject_label=subject_label,
                                predicate=predicate,
                                object_value=object_value,
                                assertion_type=assertion_type_for(fact.fact_kind),
                                confidence=score,
                                detail=_json(detail),
                                provenance=KnowledgeProvenance.OBSERVED.value,
                                method=method,
                                source_id=source_id,
                                evidence_count=len(fact.evidence),
                                fact=fact,
                            ),
                            "metadata": _json(
                                {
                                    "attributes": fact.attributes,
                                    "evidence_sources": (
                                        [str(source_id)] if source_id else []
                                    ),
                                    "compiled_by": "knowledge_compiler",
                                }
                            ),
                        },
                    )
                ).first()
                assertion_id = row.id
            else:
                status = "reinforced"
                raw_sources = existing.evidence_sources
                if not isinstance(raw_sources, list):
                    raw_sources = []
                known_sources = {str(value) for value in raw_sources if value}
                new_source = str(source_id) if source_id else None
                independent = bool(new_source) and new_source not in known_sources
                sources = sorted(known_sources | ({new_source} if new_source else set()))
                evidence_count = max(
                    int(existing.evidence_count or 0), len(fact.evidence)
                )
                if independent:
                    evidence_count = max(evidence_count, len(sources))
                corroboration = ConfidenceSignals(
                    source_reliability=0.85,
                    evidence_strength=fact.confidence,
                    evidence_count=max(evidence_count, len(fact.evidence)),
                    semantic_certainty=(
                        0.9 if method in {"schema", "deterministic"} else 0.7
                    ),
                    freshness=1.0,
                    validation=0.85,
                )
                score, detail = compute_confidence(corroboration)
                detail = {
                    **detail,
                    "fact_kind": fact.fact_kind,
                    "temporal": temporal.to_dict(),
                    "independent_sources": len(sources),
                    "corroborated": independent,
                }
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE knowledge_assertions SET
                                confidence = :confidence,
                                confidence_detail = CAST(:detail AS jsonb),
                                method = :method,
                                evidence_count = :evidence_count,
                                valid_from = COALESCE(:valid_from, valid_from),
                                valid_to = COALESCE(:valid_to, valid_to),
                                observed_at = COALESCE(:observed_at, observed_at),
                                scope = COALESCE(:scope, scope),
                                metadata = metadata || CAST(:metadata AS jsonb),
                                updated_at = now()
                            WHERE id = :id
                            RETURNING id
                            """
                        ),
                        {
                            "id": existing.id,
                            "confidence": score,
                            "detail": _json(detail),
                            "method": method,
                            "evidence_count": evidence_count,
                            "valid_from": temporal.effective_from,
                            "valid_to": temporal.effective_to,
                            "observed_at": temporal.observed_at
                            or datetime.now(timezone.utc),
                            "scope": (temporal.scope or "")[:200] or None,
                            "metadata": _json(
                                {
                                    "evidence_sources": sources,
                                    "fact_kind": fact.fact_kind,
                                }
                            ),
                        },
                    )
                ).first()
                assertion_id = row.id
            await session.commit()
            return assertion_id, 1, status
        finally:
            await session.close()

    # ------------------------------------------------------------- relaciones
    async def upsert_relationship(
        self,
        organization_id: UUID,
        relationship: RelationshipCandidate,
        *,
        subject_id: UUID | None,
        object_id: UUID | None,
        source_id: UUID | None,
        workspace_id: UUID | None,
    ) -> tuple[UUID | None, str]:
        if subject_id is None or object_id is None or subject_id == object_id:
            return None, "skipped"
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_edges (
                            organization_id, workspace_id, subject_id, predicate,
                            object_id, relationship_type, confidence, status,
                            provenance, source_id, evidence, metadata
                        ) VALUES (
                            :org, :workspace, :subject, :predicate, :object,
                            :rel_type, :confidence, 'discovered', :provenance,
                            :source_id, CAST(:evidence AS jsonb), CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (organization_id, subject_id, predicate, object_id)
                        DO UPDATE SET
                            confidence = GREATEST(EXCLUDED.confidence,
                                                  knowledge_edges.confidence),
                            evidence = EXCLUDED.evidence,
                            updated_at = now()
                        RETURNING id, (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "org": organization_id,
                        "workspace": workspace_id,
                        "subject": subject_id,
                        "predicate": relationship.predicate[:120],
                        "object": object_id,
                        "rel_type": _relationship_type(relationship.relationship_type),
                        "confidence": max(0.0, min(1.0, relationship.confidence)),
                        "provenance": KnowledgeProvenance.OBSERVED.value,
                        "source_id": source_id,
                        "evidence": _json([e.to_dict() for e in relationship.evidence[:6]]),
                        "metadata": _json(
                            {
                                "subject_label": relationship.subject,
                                "object_label": relationship.object_name,
                                "compiled_by": "knowledge_compiler",
                            }
                        ),
                    },
                )
            ).first()
            await session.commit()
            status = "created" if (row is not None and bool(row.inserted)) else "reinforced"
            return (row.id if row else None), status
        finally:
            await session.close()

    # ------------------------------------------------------------------ reglas
    async def upsert_rule(        self,
        organization_id: UUID,
        rule: RuleCandidate,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID | None,
    ) -> tuple[UUID, str]:
        natural_key = f"rule:{rule.rule_key}"[:768]
        object_id = canonical_uuid(
            organization_id, CanonicalKind.BUSINESS_RULE, natural_key
        )
        signals = ConfidenceSignals(
            source_reliability=0.85,
            evidence_strength=rule.confidence,
            evidence_count=len(rule.evidence),
            semantic_certainty=0.8,
            freshness=1.0,
            validation=0.85,
        )
        confidence, _detail = compute_confidence(signals)
        # Representación recuperable de la regla (discovery, no autoridad): se
        # persiste junto a la semántica para que el Rule Lane la encuentre sin
        # depender de que un chunk recuperado traiga canonical_rule_ids.
        index_metadata: dict = {}
        semantics_payload = getattr(rule, "semantics", None)
        if isinstance(semantics_payload, dict) and semantics_payload:
            try:
                from src.knowledge.rule_compiler.index import (
                    RULE_INDEX_VERSION,
                    rule_fingerprint,
                    rule_index_document,
                )
                from src.knowledge.rule_compiler.model import CanonicalRule

                canonical_for_index = CanonicalRule.from_dict(semantics_payload)
                index_document = rule_index_document(canonical_for_index)
                # Scope del documento/fuente/workspace que produjo la regla.
                index_document["source_id"] = str(source_id or "")
                index_document["document_id"] = str(document_id or "")
                index_document["workspace_id"] = str(workspace_id or "")
                index_metadata = {
                    "retrieval_index": index_document,
                    "retrieval_index_version": RULE_INDEX_VERSION,
                    "rule_fingerprint": rule_fingerprint(canonical_for_index),
                }
            except Exception:  # noqa: BLE001 — el índice es best-effort
                index_metadata = {}
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_canonical_objects (
                            id, organization_id, workspace_id, kind, natural_key,
                            title, name, display_name, description, provenance,
                            status, confidence, source_id, source_of_truth,
                            evidence_count, valid_from, valid_to, metadata
                        ) VALUES (
                            :oid, :org, :workspace, :kind, :key,
                            :name, :name, :name, :description, :provenance,
                            'discovered', :confidence, :source_id, :name,
                            :evidence_count, :valid_from, :valid_to,
                            CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (organization_id, kind, natural_key) DO UPDATE SET
                            description = EXCLUDED.description,
                            confidence = GREATEST(EXCLUDED.confidence,
                                                  knowledge_canonical_objects.confidence),
                            evidence_count = GREATEST(
                                EXCLUDED.evidence_count,
                                knowledge_canonical_objects.evidence_count),
                            valid_from = COALESCE(EXCLUDED.valid_from,
                                                  knowledge_canonical_objects.valid_from),
                            valid_to = COALESCE(EXCLUDED.valid_to,
                                                knowledge_canonical_objects.valid_to),
                            last_seen_at = now(),
                            metadata = knowledge_canonical_objects.metadata || EXCLUDED.metadata,
                            updated_at = now()
                        RETURNING id, (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "oid": object_id,
                        "org": organization_id,
                        "workspace": workspace_id,
                        "kind": CanonicalKind.BUSINESS_RULE.value,
                        "key": natural_key,
                        "name": (rule.subject or "regla")[:512],
                        "description": rule.statement[:4000],
                        "provenance": KnowledgeProvenance.OBSERVED.value,
                        "confidence": confidence,
                        "source_id": source_id,
                        "evidence_count": len(rule.evidence),
                        "valid_from": rule.temporal.effective_from,
                        "valid_to": rule.temporal.effective_to,
                        "metadata": _json(
                            {
                                "rule_type": rule.rule_type,
                                "modality": rule.modality,
                                "rule_key": rule.rule_key,
                                "document_id": str(document_id) if document_id else None,
                                "compiled_by": "knowledge_compiler",
                                # Semantic Rule Compiler: la semántica verificada
                                # viaja con el objeto canónico (sin migración).
                                "rule_kind": getattr(rule, "rule_kind", "") or None,
                                "verification_state": getattr(rule, "verification_state", "") or None,
                                "canonical_rule_id": getattr(rule, "canonical_rule_id", "") or None,
                                "semantics": getattr(rule, "semantics", None) or None,
                                "rule_provenance": getattr(rule, "provenance", None) or None,
                                **index_metadata,
                            }
                        ),
                    },
                )
            ).first()
            await session.commit()
            status = "created" if (row is not None and bool(row.inserted)) else "reinforced"
            return (row.id if row else object_id), status
        finally:
            await session.close()

    # ---------------------------------------------------------------- evidencia
    async def add_evidence(
        self,
        organization_id: UUID,
        evidence: EvidenceRef,
        *,
        canonical_id: UUID | None = None,
        assertion_id: UUID | None = None,
        workspace_id: UUID | None = None,
        authority: str | None = None,
    ) -> UUID | None:
        locator: SourceLocator = evidence.locator
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO evidence_ledger (
                            organization_id, workspace_id, source_id, document_id,
                            canonical_id, assertion_id, page, section_path,
                            table_reference, database_reference, excerpt,
                            content_hash, evidence_type, strength, locator,
                            authority, metadata
                        ) VALUES (
                            :org, :workspace, :source_id, :document_id,
                            :canonical_id, :assertion_id, :page,
                            CAST(:section_path AS jsonb), :table_ref, :db_ref,
                            :excerpt, :content_hash, :evidence_type, :strength,
                            :locator, :authority, CAST(:metadata AS jsonb)
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "org": organization_id,
                        "workspace": workspace_id,
                        "source_id": locator.source_id,
                        "document_id": locator.document_id,
                        "canonical_id": canonical_id,
                        "assertion_id": assertion_id,
                        "page": locator.page,
                        "section_path": _json(list(locator.section_path)),
                        "table_ref": locator.table_reference,
                        "db_ref": locator.database_reference,
                        "excerpt": (evidence.excerpt or "")[:4000],
                        "content_hash": (locator.content_hash or "")[:64] or None,
                        "evidence_type": evidence.evidence_type,
                        "strength": evidence.strength,
                        "locator": locator.locator_uri()[:1000],
                        "authority": authority,
                        "metadata": _json(
                            {
                                "row_reference": locator.row_reference,
                                "cell_reference": locator.cell_reference,
                                "block_id": (
                                    str(locator.block_id) if locator.block_id else None
                                ),
                                "document_title": locator.document_title,
                                "compiled_by": "knowledge_compiler",
                            }
                        ),
                    },
                )
            ).first()
            await session.commit()
            return row.id if row else None
        finally:
            await session.close()

    # --------------------------------------------------------------- conflictos
    async def upsert_conflict(
        self,
        organization_id: UUID,
        conflict: ConflictCandidate,
        *,
        object_id: UUID | None,
        workspace_id: UUID | None,
    ) -> str:
        session = await get_async_session()
        try:
            duplicate = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM knowledge_conflicts
                        WHERE organization_id = :org
                          AND subject_label = :label
                          AND predicate = :predicate
                          AND ((value_a = :value_a AND value_b = :value_b)
                            OR (value_a = :value_b AND value_b = :value_a))
                        LIMIT 1
                        """
                    ),
                    {
                        "org": organization_id,
                        "label": conflict.subject[:512],
                        "predicate": conflict.predicate[:200],
                        "value_a": conflict.value_a[:4000],
                        "value_b": conflict.value_b[:4000],
                    },
                )
            ).first()
            if duplicate is not None:
                return "duplicate"
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_conflicts (
                        organization_id, object_id, subject_label, predicate,
                        value_a, value_b, source_a, source_b, status,
                        conflict_type, classification, evidence_ids, reason
                    ) VALUES (
                        :org, :object_id, :label, :predicate,
                        :value_a, :value_b, :source_a, :source_b, :status,
                        :conflict_type, CAST(:classification AS jsonb),
                        CAST(:evidence_ids AS uuid[]), :reason
                    )
                    """
                ),
                {
                    "org": organization_id,
                    "object_id": object_id,
                    "label": conflict.subject[:512],
                    "predicate": conflict.predicate[:200],
                    "value_a": conflict.value_a[:4000],
                    "value_b": conflict.value_b[:4000],
                    "source_a": (conflict.source_a or "")[:200] or None,
                    "source_b": (conflict.source_b or "")[:200] or None,
                    "status": conflict.status or "open",
                    "conflict_type": conflict.conflict_type,
                    "classification": _json(
                        {
                            "classification": conflict.classification
                            or conflict.conflict_type,
                            "confidence": conflict.confidence,
                            "values_equivalent": conflict.values_equivalent,
                            "possible_explanation": conflict.possible_explanation,
                            "temporal_relation": conflict.temporal_relation,
                            "scope_relation": conflict.scope_relation,
                            "materiality": conflict.materiality,
                            "source_independence": conflict.source_independence,
                            "confidence_components": conflict.confidence_components,
                            "statement_a": conflict.statement_a[:600],
                            "statement_b": conflict.statement_b[:600],
                            "workspace_id": str(workspace_id) if workspace_id else None,
                        }
                    ),
                    "evidence_ids": [str(e) for e in conflict.evidence_ids],
                    "reason": conflict.reason,
                },
            )
            await session.commit()
            return "created"
        finally:
            await session.close()

    async def record_quality_issue(
        self,
        organization_id: UUID,
        issue: object,
        *,
        workspace_id: UUID | None,
    ) -> None:
        """Registra un problema de ingesta. Nunca tumba la compilación."""
        to_dict = getattr(issue, "to_dict", None)
        payload = to_dict() if callable(to_dict) else {}
        evidence = getattr(issue, "evidence", None)
        locator = getattr(evidence, "locator", None) if evidence else None
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_ingestion_quality (
                        organization_id, workspace_id, source_id, document_id,
                        kind, severity, subject, detail, evidence_locator,
                        evidence_excerpt, locator
                    ) VALUES (
                        :org, :workspace, :source_id, :document_id,
                        :kind, :severity, :subject, CAST(:detail AS jsonb),
                        :evidence_locator, :evidence_excerpt, :locator
                    )
                    """
                ),
                {
                    "org": organization_id,
                    "workspace": workspace_id,
                    "source_id": getattr(issue, "source_id", None),
                    "document_id": getattr(issue, "document_id", None),
                    "kind": str(getattr(issue, "kind", "UNKNOWN"))[:80],
                    "severity": str(getattr(issue, "severity", "medium"))[:20],
                    "subject": str(getattr(issue, "subject", ""))[:512],
                    "detail": _json(payload.get("detail") or {}),
                    "evidence_locator": (
                        locator.locator_uri()[:1000] if locator is not None else None
                    ),
                    "evidence_excerpt": (
                        str(getattr(evidence, "excerpt", "") or "")[:2000] or None
                    ),
                    "locator": (
                        payload.get("evidence", {}).get("locator", {}).get("locator")
                        if isinstance(payload.get("evidence"), dict)
                        else None
                    ),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — la calidad nunca rompe la compilación
            logger.debug("Knowledge quality issue insert failed", error=str(exc)[:200])
        finally:
            await session.close()

    async def record_compilation(
        self,
        organization_id: UUID,
        *,
        result: CompilationResult,
        workspace_id: UUID | None,
        duration_ms: int,
        status: str,
        error: str | None = None,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_compilations (
                        organization_id, workspace_id, source_id, document_id,
                        compilation_kind, status, units, entities, entities_merged,
                        facts, relationships, rules, conflicts, evidence,
                        duration_ms, error, metadata, finished_at
                    ) VALUES (
                        :org, :workspace, :source_id, :document_id,
                        :kind, :status, :units, :entities, :merged,
                        :facts, :relationships, :rules, :conflicts, :evidence,
                        :duration_ms, :error, CAST(:metadata AS jsonb), now()
                    )
                    """
                ),
                {
                    "org": organization_id,
                    "workspace": workspace_id,
                    "source_id": result.source_id,
                    "document_id": result.document_id,
                    "kind": result.compilation_kind,
                    "status": status,
                    "units": len(result.units),
                    "entities": len(result.entities),
                    "merged": len(result.merges),
                    "facts": len(result.facts),
                    "relationships": len(result.relationships),
                    "rules": len(result.rules),
                    "conflicts": len(result.conflicts),
                    "evidence": result.evidence_count,
                    "duration_ms": max(0, int(duration_ms)),
                    "error": (error or "")[:2000] or None,
                    "metadata": _json(
                        {
                            "document_title": result.document_title,
                            "merges": [m.reason for m in result.merges][:50],
                            "quality": result.quality_counts(),
                            "rejected": result.rejected_count,
                            "conflicts_displayable": len(result.displayable_conflicts),
                        }
                    ),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — la traza nunca rompe la compilación
            logger.warning("Knowledge compilation record failed", error=str(exc)[:200])
        finally:
            await session.close()

    async def refresh_counters(self, organization_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    UPDATE knowledge_canonical_objects o SET
                        assertion_count = (
                            SELECT COUNT(*) FROM knowledge_assertions a
                            WHERE a.organization_id = o.organization_id
                              AND (a.subject_id = o.id OR a.object_id = o.id)
                        ),
                        evidence_count = GREATEST(
                            o.evidence_count,
                            (SELECT COUNT(*) FROM evidence_ledger e
                             WHERE e.organization_id = o.organization_id
                               AND e.canonical_id = o.id)
                        ),
                        updated_at = now()
                    WHERE o.organization_id = :org
                    """
                ),
                {"org": organization_id},
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Knowledge counters refresh failed", error=str(exc)[:200])
        finally:
            await session.close()

    # ------------------------------------------------------- reglas al fabric
    async def attach_rule_projection(
        self,
        organization_id: UUID,
        projection: dict,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID | None,
    ) -> int:
        """Proyecta CanonicalRule al Semantic Fabric (nodos/aristas).

        Determinista e idempotente: los ids son uuid5 estables; se reemplazan
        SOLO los nodos/aristas de la proyección (nunca los del fabric de
        semantic windows). Sin evidencia no hay nodo.
        """
        nodes = list(projection.get("nodes") or ())
        edges = list(projection.get("edges") or ())
        if not nodes and not edges and document_id is None:
            return 0
        node_ids = [str(node.get("id")) for node in nodes if node.get("id")]
        edge_ids = [str(edge.get("id")) for edge in edges if edge.get("id")]
        session = await get_async_session()
        try:
            if organization_id is not None and document_id is not None:
                for edge_id in edge_ids:
                    await session.execute(
                        text(
                            "DELETE FROM knowledge_fabric_edges "
                            "WHERE organization_id = :org AND id = :id"
                        ),
                        {"org": organization_id, "id": edge_id},
                    )
                for node_id in node_ids:
                    await session.execute(
                        text(
                            "DELETE FROM knowledge_fabric_nodes "
                            "WHERE organization_id = :org AND id = :id"
                        ),
                        {"org": organization_id, "id": node_id},
                    )
            inserted = 0
            for node in nodes:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_fabric_nodes (
                            id, organization_id, workspace_id, source_id,
                            document_id, node_key, node_type, label, text,
                            confidence, scope, unit_key, block_ids, windows,
                            attributes, version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :node_key, :node_type, :label, :text,
                            :confidence, :scope, :unit_key,
                            CAST(:block_ids AS jsonb), CAST(:windows AS jsonb),
                            CAST(:attributes AS jsonb), :version, now(), now()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            label = EXCLUDED.label,
                            text = EXCLUDED.text,
                            confidence = EXCLUDED.confidence,
                            attributes = EXCLUDED.attributes,
                            updated_at = now()
                        """
                    ),
                    {
                        "id": str(node.get("id")),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id) if document_id else None,
                        "node_key": str(node.get("node_key") or "")[:400],
                        "node_type": str(node.get("node_type") or "")[:30],
                        "label": str(node.get("label") or "")[:300],
                        "text": str(node.get("text") or "")[:4000],
                        "confidence": float(node.get("confidence") or 0.7),
                        "scope": str(node.get("scope") or "document")[:30],
                        "unit_key": str(node.get("unit_key") or "")[:300],
                        "block_ids": _json(list(node.get("block_ids") or ())),
                        "windows": _json(list(node.get("windows") or ())),
                        "attributes": _json(dict(node.get("attributes") or {})),
                        "version": str(node.get("version") or "")[:60],
                    },
                )
                inserted += 1
            for edge in edges:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_fabric_edges (
                            id, organization_id, workspace_id, source_id,
                            document_id, edge_key, relation_type, subject_id,
                            object_id, subject_key, object_key, confidence,
                            method, evidence, windows, attributes, version,
                            created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :edge_key, :relation_type, :subject_id,
                            :object_id, :subject_key, :object_key, :confidence,
                            :method, CAST(:evidence AS jsonb), CAST(:windows AS jsonb),
                            CAST(:attributes AS jsonb), :version, now(), now()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            confidence = EXCLUDED.confidence,
                            evidence = EXCLUDED.evidence,
                            attributes = EXCLUDED.attributes,
                            updated_at = now()
                        """
                    ),
                    {
                        "id": str(edge.get("id")),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id) if document_id else None,
                        "edge_key": str(edge.get("edge_key") or "")[:800],
                        "relation_type": str(edge.get("relation_type") or "")[:40],
                        "subject_id": str(edge.get("subject_id")),
                        "object_id": str(edge.get("object_id")),
                        "subject_key": str(edge.get("subject_key") or "")[:400],
                        "object_key": str(edge.get("object_key") or "")[:400],
                        "confidence": float(edge.get("confidence") or 0.7),
                        "method": str(edge.get("method") or "deterministic")[:40],
                        "evidence": _json(list(edge.get("evidence") or ())),
                        "windows": _json(list(edge.get("windows") or ())),
                        "attributes": _json(dict(edge.get("attributes") or {})),
                        "version": str(edge.get("version") or "")[:60],
                    },
                )
                inserted += 1
            await session.commit()
            return inserted
        except Exception as exc:  # noqa: BLE001 — el fabric nunca frena la compilación
            await session.rollback()
            logger.warning(
                "Rule fabric projection failed",
                document_id=str(document_id) if document_id else None,
                error=str(exc)[:200],
            )
            return 0
        finally:
            await session.close()


def _json(value: object) -> str:
    import json

    return json.dumps(value, default=str)


def _relationship_type(raw: str) -> str:
    return raw if raw in {"physical", "logical", "semantic", "business"} else "semantic"


def _fact_params(**kwargs) -> dict:
    """Traduce los kwargs del hecho a los binds del INSERT (:org, :label, ...)."""
    fact: FactCandidate = kwargs.pop("fact")
    return {
        "org": kwargs.pop("organization_id"),
        "workspace": kwargs.pop("workspace_id"),
        "subject": kwargs.pop("subject_id"),
        "label": kwargs.pop("subject_label"),
        "predicate": kwargs.pop("predicate"),
        "value": kwargs.pop("object_value"),
        "atype": kwargs.pop("assertion_type"),
        "confidence": kwargs.pop("confidence"),
        "detail": kwargs.pop("detail"),
        "provenance": kwargs.pop("provenance"),
        "method": kwargs.pop("method"),
        "source_id": kwargs.pop("source_id"),
        "evidence_count": kwargs.pop("evidence_count"),
        "valid_from": fact.temporal.effective_from,
        "valid_to": fact.temporal.effective_to,
        "observed_at": fact.temporal.observed_at or datetime.now(timezone.utc),
        "scope": (fact.temporal.scope or "")[:200] or None,
    }
