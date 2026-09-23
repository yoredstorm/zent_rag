# =============================================================================
# Company Discovery Engine
# =============================================================================
# Ciclo: DISCOVER -> SUPPORT -> SUGGEST -> VALIDATE -> CONFIRM
#
# El motor NO escribe verdad: acumula candidatos con evidencia, resuelve
# identidad (sin fusionar ambiguos) y, cuando un humano valida o la
# verificación es estructural, PROMUEVE al Company Graph de Fase 5A.
#
# Regla dura: ninguna ruta permite que "el LLM dijo X" se convierta en verdad
# de la compañía. Lo interpretativo queda en SUGGESTED y espera validación.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.company.discovery.confidence import next_stage_for, score_candidate
from src.company.discovery.gaps import KnowledgeGapSource, find_process_divergences
from src.company.discovery.metrics import (
    record_candidate,
    record_knowledge_gap,
    record_resolution_conflict,
    record_run,
)
from src.company.discovery.resolution import EntityResolutionEngine
from src.company.discovery.source_base import (
    DiscoverySource,
    DiscoverySourceRegistry,
)
from src.company.service import AuthorityRule, CompanyGraphService
from src.core.domain.company_discovery import (
    AuthorityCandidatePayload,
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoverySourceKind,
    DiscoveryStage,
    DiscoveryTrigger,
    EntityCandidatePayload,
    GapKind,
    KnowledgeGapPayload,
    MappingCandidatePayload,
    ProcessCandidatePayload,
    RelationshipCandidatePayload,
    TemporalCandidatePayload,
    TermCandidatePayload,
    requires_human_confirmation,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    EntityStatus,
    ProvenanceKind,
    ProvenanceRef,
    RelationshipRegistry,
)
from src.core.ports.company_discovery import CompanyDiscoveryRepository
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

#: Camino de progresión legal entre etapas.
_STAGE_PATH: tuple[DiscoveryStage, ...] = (
    DiscoveryStage.DISCOVERED,
    DiscoveryStage.SUPPORTED,
    DiscoveryStage.SUGGESTED,
    DiscoveryStage.VALIDATED,
    DiscoveryStage.CONFIRMED,
)
_STAGE_RANK = {stage: index for index, stage in enumerate(_STAGE_PATH)}

#: Tipos de entidad que la estructura física confirma por sí sola.
_STRUCTURAL_ENTITY_TYPES = frozenset(
    {"table", "field", "database", "dataset", "api", "service", "system"}
)

#: Tipos que descubre el motor (extienden el registry de Fase 5A).
_DISCOVERED_RELATIONSHIP_TYPES = ("SUPERSEDED_BY", "APPLIES_TO", "CONCERNS", "IMPROVES")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class DiscoveryRunResult:
    run: DiscoveryRun
    candidates: tuple[DiscoveryCandidate, ...] = ()
    by_kind: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run": self.run.to_dict(),
            "by_kind": self.by_kind,
            "candidates": [candidate.to_dict() for candidate in self.candidates[:50]],
        }


class CompanyDiscoveryEngine:
    """Orquesta fuentes, acumula soporte y promueve al grafo con validación."""

    def __init__(
        self,
        store: CompanyDiscoveryRepository,
        graph: CompanyGraphService,
        *,
        sources: list[DiscoverySource] | None = None,
        resolver: EntityResolutionEngine | None = None,
        gap_source: KnowledgeGapSource | None = None,
        authority_service=None,
    ) -> None:
        self._store = store
        self._graph = graph
        self._sources = (
            sources if sources is not None else DiscoverySourceRegistry.all()
        )
        self._resolver = resolver or EntityResolutionEngine()
        self._gaps = gap_source or KnowledgeGapSource()
        self._authority = authority_service
        for relationship_type in _DISCOVERED_RELATIONSHIP_TYPES:
            RelationshipRegistry.register(relationship_type)

    # ------------------------------------------------------------------
    # Descubrimiento
    # ------------------------------------------------------------------
    async def run(
        self,
        organization_id: UUID,
        *,
        trigger: DiscoveryTrigger = DiscoveryTrigger.MANUAL,
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
        workspace_id: UUID | None = None,
        run: DiscoveryRun | None = None,
    ) -> DiscoveryRunResult:
        started = time.monotonic()
        sources = (
            [source for source in self._sources if source.source_kind in source_kinds]
            if source_kinds
            else list(self._sources)
        )
        collected: list[DiscoveryCandidate] = []
        by_source: dict[str, int] = {}
        errors: dict[str, str] = {}
        for source in sources:
            try:
                candidates = await source.discover(
                    organization_id, workspace_id=workspace_id
                )
            except Exception as exc:  # noqa: BLE001 - una fuente no rompe el resto
                errors[source.source_kind.value] = str(exc)[:200]
                logger.warning(
                    "company discovery source failed",
                    source=source.source_kind.value,
                    error=str(exc)[:200],
                )
                continue
            by_source[source.source_kind.value] = len(candidates)
            collected.extend(candidates)

        collected.extend(
            await self._divergence_gaps(organization_id, collected, workspace_id)
        )

        existing_entities = await self._graph.find_entities(
            organization_id, current_only=False, limit=200
        )
        persisted: list[DiscoveryCandidate] = []
        new_count = 0
        for candidate in collected:
            merged, is_new = await self._accumulate(
                candidate, existing_entities=existing_entities
            )
            persisted.append(merged)
            new_count += 1 if is_new else 0
            record_candidate(organization_id, merged.kind.value, merged.stage.value)
            if merged.kind is CandidateKind.KNOWLEDGE_GAP:
                gap_payload = KnowledgeGapPayload.from_dict(merged.payload)
                record_knowledge_gap(organization_id, gap_payload.gap_kind.value)

        conflicts = sum(1 for item in persisted if self._is_conflict(item))
        elapsed = time.monotonic() - started
        duration_ms = int(elapsed * 1000)
        by_kind: dict[str, int] = {}
        for candidate in persisted:
            by_kind[candidate.kind.value] = by_kind.get(candidate.kind.value, 0) + 1

        finished = DiscoveryRun(
            organization_id=organization_id,
            trigger=trigger,
            status=DiscoveryRunStatus.COMPLETED,
            source_kinds=tuple(source.source_kind for source in sources),
            candidates_found=len(collected),
            candidates_new=new_count,
            candidates_updated=len(persisted) - new_count,
            conflicts=conflicts,
            metrics={
                "by_source": by_source,
                "by_kind": by_kind,
                "errors": errors,
                "duration_ms": duration_ms,
            },
            started_at=_utcnow(),
            completed_at=_utcnow(),
            duration_ms=duration_ms,
            id=run.id if run is not None else uuid4(),
        )
        if run is not None:
            finished = await self._store.save_run(finished)
        record_run(organization_id, trigger.value, elapsed)
        return DiscoveryRunResult(
            run=finished, candidates=tuple(persisted), by_kind=by_kind
        )

    async def run_pending(self) -> DiscoveryRunResult | None:
        """Toma una corrida pendiente y la ejecuta (worker §23)."""
        run = await self._store.claim_pending_run()
        if run is None:
            return None
        try:
            return await self.run(
                run.organization_id,
                trigger=run.trigger,
                source_kinds=run.source_kinds,
                run=run,
            )
        except Exception as exc:  # noqa: BLE001 - el worker sigue vivo
            logger.warning("company discovery run failed", error=str(exc)[:200])
            failed = await self._store.save_run(
                replace(
                    run,
                    status=DiscoveryRunStatus.FAILED,
                    error=str(exc)[:2000],
                    completed_at=_utcnow(),
                )
            )
            return DiscoveryRunResult(run=failed)

    @staticmethod
    def _is_conflict(candidate: DiscoveryCandidate) -> bool:
        if candidate.resolution.get("ambiguous"):
            return True
        if candidate.kind is not CandidateKind.KNOWLEDGE_GAP:
            return False
        payload = KnowledgeGapPayload.from_dict(candidate.payload)
        return payload.gap_kind in (
            GapKind.CONTRADICTORY_DEFINITION,
            GapKind.AMBIGUOUS_ENTITY,
        )

    async def _accumulate(
        self,
        candidate: DiscoveryCandidate,
        *,
        existing_entities: list[CompanyEntity],
    ) -> tuple[DiscoveryCandidate, bool]:
        previous = await self._store.get_by_natural_key(
            candidate.organization_id, candidate.kind, candidate.natural_key
        )
        if previous is not None:
            merged = previous.with_observation(
                support=candidate.support,
                evidence=candidate.evidence[0] if candidate.evidence else None,
                confidence=score_candidate(
                    kind=candidate.kind,
                    support=previous.support.merged(candidate.support),
                ),
                stage=previous.stage,
            )
        else:
            merged = candidate
        merged = self._apply_resolution(merged, existing_entities)
        merged = self._apply_stage(merged)
        return await self._store.upsert_candidate(merged)

    def _apply_resolution(
        self,
        candidate: DiscoveryCandidate,
        existing_entities: list[CompanyEntity],
    ) -> DiscoveryCandidate:
        if candidate.kind is not CandidateKind.ENTITY:
            return candidate
        payload = EntityCandidatePayload.from_dict(candidate.payload)
        outcome = self._resolver.resolve(payload, existing_entities)
        if outcome.ambiguous:
            record_resolution_conflict(candidate.organization_id)
            logger.info(
                "company discovery ambiguity",
                entity=payload.canonical_name,
                reason=outcome.reason,
            )
        return candidate.resolved(outcome.to_dict())

    def _apply_stage(self, candidate: DiscoveryCandidate) -> DiscoveryCandidate:
        """Progresión automática. Nunca CONFIRMED: eso es humano o estructural."""
        breakdown = score_candidate(kind=candidate.kind, support=candidate.support)
        candidate = replace(
            candidate,
            confidence=breakdown.total,
            confidence_factors=breakdown.factors,
        )
        if candidate.stage in (
            DiscoveryStage.VALIDATED,
            DiscoveryStage.CONFIRMED,
            DiscoveryStage.REJECTED,
        ):
            return candidate
        if candidate.resolution.get("ambiguous"):
            target = DiscoveryStage.SUGGESTED
        else:
            target = DiscoveryStage(
                next_stage_for(
                    kind=candidate.kind,
                    support=candidate.support,
                    confidence=candidate.confidence,
                    structural=candidate.structural,
                )
            )
        if _STAGE_RANK[target] >= _STAGE_RANK[candidate.stage]:
            return self._advance(candidate, target)
        if candidate.support.contradictions:
            return self._advance(candidate, DiscoveryStage.DISCOVERED)
        return candidate

    @staticmethod
    def _advance(
        candidate: DiscoveryCandidate, target: DiscoveryStage
    ) -> DiscoveryCandidate:
        """Avanza respetando la ley de transiciones (sin saltos)."""
        current = _STAGE_RANK.get(candidate.stage, 0)
        wanted = _STAGE_RANK[target]
        if wanted < current:
            return candidate
        for stage in _STAGE_PATH[current + 1 : wanted + 1]:
            candidate = candidate.with_stage(stage)
        return candidate

    async def _divergence_gaps(
        self,
        organization_id: UUID,
        candidates: list[DiscoveryCandidate],
        workspace_id: UUID | None,
    ) -> list[DiscoveryCandidate]:
        processes = [
            ProcessCandidatePayload.from_dict(candidate.payload)
            for candidate in candidates
            if candidate.kind is CandidateKind.PROCESS
        ]
        if len(processes) < 2:
            return []
        gaps: list[DiscoveryCandidate] = []
        for divergence in find_process_divergences(processes):
            gaps.extend(
                self._gaps.from_divergence(
                    organization_id, divergence, workspace_id=workspace_id
                )
            )
        return gaps

    # ------------------------------------------------------------------
    # Validación y promoción
    # ------------------------------------------------------------------
    async def validate(
        self,
        organization_id: UUID,
        candidate_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> DiscoveryCandidate:
        candidate = await self._require_candidate(organization_id, candidate_id)
        reviewed = self._advance(candidate, DiscoveryStage.VALIDATED)
        return await self._store.update_candidate_state(
            replace(reviewed, reviewed_by=actor_id, reviewed_at=_utcnow())
        )

    async def reject(
        self,
        organization_id: UUID,
        candidate_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> DiscoveryCandidate:
        candidate = await self._require_candidate(organization_id, candidate_id)
        rejected = candidate.with_stage(DiscoveryStage.REJECTED)
        return await self._store.update_candidate_state(
            replace(rejected, reviewed_by=actor_id, reviewed_at=_utcnow())
        )

    async def promote(
        self,
        organization_id: UUID,
        candidate_id: UUID,
        *,
        actor_id: UUID | None = None,
        is_admin: bool = False,
    ) -> dict:
        """Materializa un candidato en el grafo. Nada se promueve sin derecho."""
        candidate = await self._require_candidate(organization_id, candidate_id)
        if candidate.stage is DiscoveryStage.REJECTED:
            raise ValueError("rejected candidates cannot be promoted")
        structural = candidate.structural
        if requires_human_confirmation(candidate.kind, structural=structural):
            if actor_id is None:
                raise ValueError(
                    "human validation required: interpretative candidates are "
                    "never confirmed automatically"
                )
        if candidate.kind is CandidateKind.SOURCE_AUTHORITY and not is_admin:
            raise ValueError(
                "source authority confirmation requires an administrator"
            )

        materialized = await self._materialize(
            organization_id, candidate, actor_id=actor_id
        )
        confirmable = not requires_human_confirmation(
            candidate.kind, structural=structural
        )
        target = (
            DiscoveryStage.CONFIRMED
            if (actor_id is not None or confirmable)
            else DiscoveryStage.VALIDATED
        )
        advanced = self._advance(candidate, target)
        if materialized.get("id"):
            advanced = advanced.materialized(UUID(str(materialized["id"])))
        saved = await self._store.update_candidate_state(
            replace(advanced, reviewed_by=actor_id, reviewed_at=_utcnow())
        )
        record_candidate(organization_id, saved.kind.value, saved.stage.value)
        return {"candidate": saved.to_dict(), "materialized": materialized}

    async def _materialize(
        self,
        organization_id: UUID,
        candidate: DiscoveryCandidate,
        *,
        actor_id: UUID | None,
    ) -> dict:
        handlers = {
            CandidateKind.ENTITY: self._materialize_entity,
            CandidateKind.RELATIONSHIP: self._materialize_relationship,
            CandidateKind.MAPPING: self._materialize_mapping,
            CandidateKind.PROCESS: self._materialize_process,
            CandidateKind.SOURCE_AUTHORITY: self._materialize_authority,
            CandidateKind.KNOWLEDGE_GAP: self._materialize_gap,
            CandidateKind.TERM: self._materialize_term,
            CandidateKind.TEMPORAL: self._materialize_temporal,
        }
        return await handlers[candidate.kind](
            organization_id, candidate, actor_id=actor_id
        )

    async def _materialize_entity(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = EntityCandidatePayload.from_dict(candidate.payload)
        entity = await self._graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type=payload.entity_type,
                canonical_name=payload.canonical_name,
                display_name=payload.display_name,
                description=payload.description,
                domain=payload.domain,
                aliases=tuple(payload.aliases),
                status=self._entity_status(candidate, payload.entity_type, actor_id),
                confidence=candidate.confidence,
                source=candidate.source_kind.value,
                source_ref=candidate.source_ref,
                evidence=self._provenance(candidate),
                metadata={
                    "technical_identifiers": list(payload.technical_identifiers),
                    "candidate_id": str(candidate.id),
                    "discovered_by": candidate.discovered_by,
                },
            )
        )
        return {"kind": "entity", "id": str(entity.id), "status": entity.status.value}

    async def _materialize_relationship(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = RelationshipCandidatePayload.from_dict(candidate.payload)
        await self._ensure_endpoints(organization_id, candidate)
        relationship = await self._graph.propose_relationship(
            organization_id,
            payload.from_ref.entity_id(organization_id),
            payload.to_ref.entity_id(organization_id),
            payload.relationship_type,
            source=candidate.source_kind.value,
            source_ref=candidate.source_ref,
            evidence=self._provenance(candidate),
            confidence=candidate.confidence,
            metadata={
                "candidate_id": str(candidate.id),
                "observed": payload.observed,
            },
            auto_confirm_structural=candidate.structural,
        )
        if actor_id is not None and relationship.status is EntityStatus.DISCOVERED:
            relationship = await self._graph.confirm_relationship(
                organization_id, relationship.id, status=EntityStatus.CONFIRMED
            )
        return {
            "kind": "relationship",
            "id": str(relationship.id),
            "status": relationship.status.value,
            "relationship_type": relationship.relationship_type,
        }

    async def _materialize_mapping(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = MappingCandidatePayload.from_dict(candidate.payload)
        await self._ensure_endpoints(organization_id, candidate)
        relationship = await self._graph.propose_relationship(
            organization_id,
            payload.concept_ref.entity_id(organization_id),
            payload.target_ref.entity_id(organization_id),
            "MAPS_TO",
            source=candidate.source_kind.value,
            source_ref=candidate.source_ref,
            evidence=self._provenance(candidate),
            confidence=candidate.confidence,
            metadata={
                "candidate_id": str(candidate.id),
                "values": list(payload.values),
                "predicate": payload.predicate,
                "mapping_type": payload.mapping_type,
            },
            # MAPS_TO nunca es auto-confirmable (regla dura de Fase 5A).
            auto_confirm_structural=False,
        )
        if actor_id is not None:
            relationship = await self._graph.confirm_relationship(
                organization_id, relationship.id, status=EntityStatus.CONFIRMED
            )
        return {
            "kind": "mapping",
            "id": str(relationship.id),
            "status": relationship.status.value,
        }

    async def _materialize_process(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = ProcessCandidatePayload.from_dict(candidate.payload)
        entity = await self._graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type="process",
                canonical_name=payload.name,
                display_name=payload.name,
                domain="operations",
                status=self._entity_status(candidate, "process", actor_id),
                confidence=candidate.confidence,
                source=candidate.source_kind.value,
                source_ref=candidate.source_ref,
                evidence=self._provenance(candidate),
                metadata={
                    "mode": payload.mode.value,
                    "steps": [step.to_dict() for step in payload.steps],
                    "runs_observed": payload.runs_observed,
                    "workflow_id": payload.workflow_id,
                    "candidate_id": str(candidate.id),
                },
            )
        )
        return {"kind": "process", "id": str(entity.id), "status": entity.status.value}

    async def _materialize_authority(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = AuthorityCandidatePayload.from_dict(candidate.payload)
        if self._authority is None:
            raise ValueError("authority service unavailable for this engine")
        rule = await self._authority.upsert_rule(
            AuthorityRule(
                organization_id=organization_id,
                domain=payload.domain,
                concept=payload.concept,
                source_name=payload.source_name,
                source_type=payload.source_type,
                authority_level=payload.proposed_level,
                priority=1,
            )
        )
        return {
            "kind": "source_authority",
            "id": f"{rule.domain}:{rule.concept}:{rule.source_name}",
            "authority_level": rule.authority_level.value,
        }

    async def _materialize_gap(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        """Un hueco se registra como Finding del Learning Engine (§11)."""
        payload = KnowledgeGapPayload.from_dict(candidate.payload)
        from src.core.domain.learning_cycle import Finding, FindingSeverity
        from src.infrastructure.postgres.learning_cycle_store import (
            PostgresLearningCycleStore,
        )

        finding = Finding(
            organization_id=organization_id,
            category="KNOWLEDGE_GAP",
            severity=FindingSeverity.MEDIUM,
            pattern_key=f"knowledge_gap:{candidate.natural_key}"[:160],
            observed=payload.detail or payload.subject,
            alternative=(
                "document the observed behavior or confirm the proposed mapping"
            ),
            baseline_strategy="current documentation",
            candidate_strategy="proposed documentation update",
            sample_size=payload.observed_runs or 1,
            window="all_time",
            confidence="medium",
            dedupe_key=f"company_gap:{candidate.natural_key}"[:240],
            evidence=[str(candidate.id), *payload.evidence_summary],
            affected=[payload.subject],
        )
        saved = await PostgresLearningCycleStore().upsert_finding(finding)
        return {"kind": "finding", "id": str(saved.id), "category": "KNOWLEDGE_GAP"}

    async def _materialize_term(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = TermCandidatePayload.from_dict(candidate.payload)
        concept = payload.proposed_concept or payload.term
        entity = await self._graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type="concept",
                canonical_name=concept,
                display_name=payload.term,
                domain=payload.domain,
                aliases=tuple(payload.aliases),
                status=self._entity_status(candidate, "concept", actor_id),
                confidence=candidate.confidence,
                source=candidate.source_kind.value,
                source_ref=candidate.source_ref,
                evidence=self._provenance(candidate),
                metadata={
                    "observed_term": payload.term,
                    "candidate_id": str(candidate.id),
                },
            )
        )
        return {"kind": "concept", "id": str(entity.id), "status": entity.status.value}

    async def _materialize_temporal(
        self, organization_id: UUID, candidate: DiscoveryCandidate, *, actor_id
    ) -> dict:
        payload = TemporalCandidatePayload.from_dict(candidate.payload)
        subject = await self._graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type=payload.subject_ref.entity_type,
                canonical_name=payload.subject_ref.canonical_name,
                display_name=payload.subject_ref.canonical_name,
                status=self._entity_status(
                    candidate, payload.subject_ref.entity_type, actor_id
                ),
                confidence=candidate.confidence,
                source=candidate.source_kind.value,
                source_ref=candidate.source_ref,
                evidence=self._provenance(candidate),
                valid_from=payload.effective_from,
                valid_to=payload.effective_to,
                metadata={"version_label": payload.version_label},
            )
        )
        if payload.superseded_by_ref is None:
            return {"kind": "temporal", "id": str(subject.id)}
        successor = await self._graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type=payload.superseded_by_ref.entity_type,
                canonical_name=payload.superseded_by_ref.canonical_name,
                display_name=payload.superseded_by_ref.canonical_name,
                status=EntityStatus.DISCOVERED,
                confidence=candidate.confidence,
                source=candidate.source_kind.value,
                source_ref=candidate.source_ref,
                evidence=self._provenance(candidate),
            )
        )
        relationship = await self._graph.propose_relationship(
            organization_id,
            subject.id,
            successor.id,
            "SUPERSEDED_BY",
            source=candidate.source_kind.value,
            source_ref=candidate.source_ref,
            evidence=self._provenance(candidate),
            confidence=candidate.confidence,
            metadata={"candidate_id": str(candidate.id)},
        )
        return {
            "kind": "temporal",
            "id": str(subject.id),
            "successor_id": str(successor.id),
            "relationship_id": str(relationship.id),
            "relationship_status": relationship.status.value,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _ensure_endpoints(
        self, organization_id: UUID, candidate: DiscoveryCandidate
    ) -> None:
        """Crea los extremos faltantes como DISCOVERED (nunca como verdad)."""
        refs = []
        if candidate.kind is CandidateKind.RELATIONSHIP:
            payload = RelationshipCandidatePayload.from_dict(candidate.payload)
            refs = [payload.from_ref, payload.to_ref]
        elif candidate.kind is CandidateKind.MAPPING:
            payload = MappingCandidatePayload.from_dict(candidate.payload)
            refs = [payload.concept_ref, payload.target_ref]
        for ref in refs:
            existing = await self._graph.get_entity(
                organization_id, ref.entity_id(organization_id)
            )
            if existing is not None:
                continue
            await self._graph.upsert_entity(
                CompanyEntity(
                    organization_id=organization_id,
                    entity_type=ref.entity_type,
                    canonical_name=ref.canonical_name,
                    display_name=ref.canonical_name,
                    status=EntityStatus.DISCOVERED,
                    confidence=candidate.confidence,
                    source=candidate.source_kind.value,
                    source_ref=candidate.source_ref,
                    evidence=self._provenance(candidate),
                    metadata={"created_as_endpoint_of": str(candidate.id)},
                )
            )

    def _entity_status(
        self,
        candidate: DiscoveryCandidate,
        entity_type: str,
        actor_id: UUID | None,
    ) -> EntityStatus:
        """Confirmada sólo por humano; auto-confirmada sólo si la estructura
        física la respalda y el tipo es verificable por estructura."""
        if actor_id is not None:
            return EntityStatus.CONFIRMED
        if candidate.structural and entity_type in _STRUCTURAL_ENTITY_TYPES:
            return EntityStatus.AUTO_CONFIRMED
        return EntityStatus.SUPPORTED

    @staticmethod
    def _provenance(candidate: DiscoveryCandidate) -> tuple[ProvenanceRef, ...]:
        refs = [
            ProvenanceRef(
                kind=_provenance_kind(candidate.source_kind),
                ref=candidate.source_ref or candidate.natural_key,
            )
        ]
        for evidence in candidate.evidence[:5]:
            if evidence.ref == candidate.source_ref:
                continue
            refs.append(
                ProvenanceRef(
                    kind=_provenance_kind(evidence.source_kind), ref=evidence.ref
                )
            )
        return tuple(refs)

    async def _require_candidate(
        self, organization_id: UUID, candidate_id: UUID
    ) -> DiscoveryCandidate:
        candidate = await self._store.get_candidate(organization_id, candidate_id)
        if candidate is None:
            raise ValueError("candidate not found for this organization")
        return candidate


_PROVENANCE_BY_SOURCE: dict[DiscoverySourceKind, ProvenanceKind] = {
    DiscoverySourceKind.CATALOG: ProvenanceKind.CATALOG,
    DiscoverySourceKind.DATABASE_SCHEMA: ProvenanceKind.SCHEMA,
    DiscoverySourceKind.DATABASE_METADATA: ProvenanceKind.SCHEMA,
    DiscoverySourceKind.DOCUMENT: ProvenanceKind.DOCUMENT,
    DiscoverySourceKind.SQL_QUERY: ProvenanceKind.RUN,
    DiscoverySourceKind.VERIFIED_QUERY: ProvenanceKind.RUN,
    DiscoverySourceKind.EVENT: ProvenanceKind.RUN,
    DiscoverySourceKind.CLAIM: ProvenanceKind.CLAIM,
    DiscoverySourceKind.MEMORY: ProvenanceKind.MEMORY,
    DiscoverySourceKind.FINDING: ProvenanceKind.FINDING,
    DiscoverySourceKind.CONVERSATION: ProvenanceKind.CONVERSATION,
    DiscoverySourceKind.EVIDENCE_LEDGER: ProvenanceKind.EVIDENCE,
}


def _provenance_kind(source_kind: DiscoverySourceKind) -> ProvenanceKind:
    return _PROVENANCE_BY_SOURCE.get(source_kind, ProvenanceKind.MANUAL)


__all__ = ["CompanyDiscoveryEngine", "DiscoveryRunResult"]
