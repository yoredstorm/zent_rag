# =============================================================================
# Knowledge Compiler — pipeline canónico
# =============================================================================
# Una sola entrada: una fuente ya entendida (StructuredDocument + tabular).
# Una sola salida: conocimiento canónico con provenance.
#
#   RAW SOURCE -> Parsed Source -> Structural Model -> Semantic Units
#              -> Entities -> Facts -> Relationships -> Rules -> Temporal Facts
#              -> Knowledge Objects -> Evidence Links -> Canonical Knowledge
#
# Sin intervención humana en el flujo normal: el compilador corre al terminar
# la ingesta y refuerza (no duplica) lo que ya existe. La revisión humana
# solo aparece para VERIFICAR o para resolver conflictos que el motor no pudo
# clasificar.
# =============================================================================
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from src.core.domain.canonical import CanonicalKind, canonical_uuid
from src.core.domain.knowledge_events import KnowledgeEventType, KnowledgeSystemEvent
from src.core.domain.knowledge_v2 import StructuredDocument
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.compiler import conflicts as conflict_engine
from src.knowledge.compiler import entities as entity_engine
from src.knowledge.compiler import extract, temporal
from src.knowledge.compiler import facts as fact_engine
from src.knowledge.compiler import rules as rule_engine
from src.knowledge.compiler.model import (
    CompilationResult,
    ConflictType,
    EntityCandidate,
    EntityType,
    EvidenceRef,
    EvidenceType,
    FactCandidate,
    QualityIssue,
    RelationshipCandidate,
    RuleCandidate,
    SourceLocator,
    TemporalScope,
    normalize_term,
)
from src.knowledge.compiler.store import CompilerStore, PostgresCompilerStore, object_kind_for_entity
from src.knowledge.quality.ingestion import QualityCollector, QualityKind

logger = get_logger(__name__)


class SystemEventEmitter(Protocol):
    """Emisor de eventos de dominio del conocimiento (C8)."""

    async def emit(self, event: KnowledgeSystemEvent) -> None: ...


class KnowledgeCompiler:
    """Compila una fuente en conocimiento canónico verificable."""

    def __init__(self, store: CompilerStore | None = None) -> None:
        self._store = store or PostgresCompilerStore()

    # ------------------------------------------------------- fase determinista
    @staticmethod
    def build(document: StructuredDocument) -> CompilationResult:
        """Semantic units -> entidades -> hechos -> relaciones -> reglas.

        Puro, sin I/O. Es la fase que se puede testear y auditar. Los controles
        de calidad corren ANTES de crear conocimiento: lo que no tiene
        estructura suficiente no llega a entidad, alias ni hecho.
        """
        quality = QualityCollector()
        # Puerta obligatoria: Semantic Reconstruction corre ANTES de extraer
        # unidades. Si el documento llegó crudo (test, conector directo), se
        # reconstruye aquí determinísticamente; nunca se compila texto crudo.
        from src.knowledge.reconstruction import ensure_reconstruction

        document, reconstruction_issues = ensure_reconstruction(document)
        units = extract.extract_semantic_units(document, quality=quality)
        units.extend(extract.extract_tabular_units(document.tabular, document=document))

        sample_text = "\n".join(
            (block.text or "") for block in document.blocks[:200]
        )[:8000]
        scope = temporal.infer_temporal_scope(document, sample_text=sample_text)

        discovered = entity_engine.discover_entities(
            units, document=document, quality=quality
        )
        # Gate de procedencia: entidad sin evidencia no es conocimiento.
        accepted: list[EntityCandidate] = []
        for entity in discovered:
            if not entity.evidence:
                quality.add(
                    QualityKind.EVIDENCE_MISSING.value,
                    entity.name,
                    detail={"stage": "entity_discovery", "entity_type": entity.entity_type},
                    source_id=document.source_id,
                    document_id=document.id,
                )
                continue
            accepted.append(entity)
        rejected_entities = len(discovered) - len(accepted)

        resolver = entity_engine.EntityResolver()
        consolidated, merges = resolver.consolidate(accepted)

        source_label = (document.title or "").strip() or None
        fact_list = fact_engine.build_facts(units, temporal=scope)
        fact_list.extend(fact_engine.entity_facts(consolidated, temporal=scope))
        for fact in fact_list:
            fact.attributes.setdefault("source_label", source_label)
            fact.attributes.setdefault(
                "document_id", str(document.id) if document.id else None
            )

        relationships = fact_engine.build_relationships(
            units,
            document_title=document.title,
            extracted_relations=extract.extracta_for(document).get("relations") or [],
        )

        rules = rule_engine.extract_rules(document, temporal=scope)
        # Semantic Rule Compiler: convierte candidatos normativos en reglas
        # canónicas con propiedades verificadas y provenance por propiedad.
        # Determinista; no reemplaza la detección existente, la profundiza.
        from src.knowledge.rule_compiler import SemanticRuleCompiler

        semantic_compilation = SemanticRuleCompiler().compile(
            document_id=str(document.id or ""),
            document_title=document.title or "",
            organization_id=str(document.organization_id),
            units=units,
            rule_candidates=rules,
        )
        canonical_by_statement = {
            " ".join(rule.statement.lower().split())[:400]: rule
            for rule in semantic_compilation.canonical_rules
        }
        for rule in rules:
            canonical = canonical_by_statement.get(
                " ".join(rule.statement.lower().split())[:400]
            )
            if canonical is None:
                continue
            rule.rule_kind = canonical.kind
            rule.verification_state = canonical.verification_state
            rule.semantics = canonical.to_public_dict()
            rule.provenance = [item.to_dict() for item in canonical.provenance[:16]]
            rule.canonical_rule_id = canonical.rule_id
        conflict_list = conflict_engine.detect_conflicts(fact_list)

        quality_issues = [
            QualityIssue(
                kind=str(item.get("kind") or QualityKind.LOW_QUALITY_EXTRACTION.value),
                subject=str(item.get("subject") or ""),
                detail=item.get("detail") or {},
                evidence=item.get("evidence"),
                source_id=item.get("source_id"),
                document_id=item.get("document_id"),
                severity=str(item.get("severity") or "medium"),
                confidence=item.get("confidence"),
            )
            for item in quality.issues
        ]
        # La cuarentena de Semantic Reconstruction entra como INGESTION_QUALITY:
        # un problema de reconstrucción jamás será conflicto, gap ni canónico.
        quality_issues.extend(
            QualityIssue(
                kind=str(item.get("kind") or "INGESTION_QUALITY"),
                subject=str(item.get("subject") or "")[:300],
                detail=item.get("detail") or {},
                source_id=document.source_id,
                document_id=document.id,
                severity=str(item.get("severity") or "medium"),
                confidence=item.get("confidence"),
            )
            for item in reconstruction_issues[:300]
        )

        return CompilationResult(
            organization_id=document.organization_id,
            source_id=document.source_id,
            document_id=document.id,
            document_title=document.title,
            compilation_kind="tabular" if document.tabular is not None else "document",
            units=units,
            entities=consolidated,
            facts=fact_list,
            relationships=relationships,
            rules=rules,
            canonical_rules=semantic_compilation.canonical_rules,
            conflicts=conflict_list,
            merges=merges,
            quality_issues=quality_issues,
            rejected_count=rejected_entities,
            evidence_count=sum(
                len(entity.evidence) for entity in consolidated
            )
            + sum(len(fact.evidence) for fact in fact_list)
            + sum(len(rule.evidence) for rule in rules)
            + sum(len(rule.provenance) for rule in semantic_compilation.canonical_rules),
        )

    # --------------------------------------------------------------- fase I/O
    async def compile_document(
        self,
        document: StructuredDocument,
        *,
        workspace_id: UUID | None = None,
        persist: bool = True,
        observer: "Callable[[str, dict], Awaitable[None]] | None" = None,
        system_emitter: "SystemEventEmitter | None" = None,
        precomputed: CompilationResult | None = None,
    ) -> CompilationResult:
        """Compila y persiste. En modo offline solo devuelve el resultado.

        ``observer`` recibe eventos semánticos reales (ENTITY_DISCOVERED,
        FACT_REINFORCED, RULE_DISCOVERED, CONFLICT_DETECTED, ...) a medida que
        la persistencia ocurre. Es la fuente del "ZENT está aprendiendo".

        ``system_emitter`` (opcional, C8) recibe eventos de dominio
        (NEW_ENTITY, NEW_RULE, RULE_CHANGED, CONFLICT_DETECTED) derivados de
        esas mismas señales. Es best-effort: nunca altera el flujo.

        ``precomputed`` (Knowledge Nutrition): la vista pura ya calculada por
        la ingesta para anotar el índice. Evita re-ejecutar el build y no
        cambia la semántica de persistencia.
        """
        started = time.perf_counter()
        result = precomputed if precomputed is not None else self.build(document)
        if not persist:
            return result

        status = "completed"
        error: str | None = None
        try:
            result.persisted = await self._persist(
                result,
                workspace_id=workspace_id or document.workspace_id,
                observer=observer,
                system_emitter=system_emitter,
            )
        except Exception as exc:  # noqa: BLE001 — la ingesta ya persistió el documento
            status = "failed"
            error = str(exc)[:2000]
            logger.warning(
                "Knowledge compilation failed",
                document_id=str(document.id),
                error=error[:400],
            )
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                await self._store.record_compilation(
                    document.organization_id,
                    result=result,
                    workspace_id=workspace_id or document.workspace_id,
                    duration_ms=duration_ms,
                    status=status,
                    error=error,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Knowledge compilation trace failed", error=str(exc)[:200]
                )
        result.persisted["status"] = status
        return result

    async def _persist(
        self,
        result: CompilationResult,
        *,
        workspace_id: UUID | None,
        observer: "Callable[[str, dict], Awaitable[None]] | None" = None,
        system_emitter: "SystemEventEmitter | None" = None,
    ) -> dict:
        store = self._store
        organization_id = result.organization_id
        source_id = result.source_id
        document_id = result.document_id

        aliases = await store.existing_aliases(organization_id)
        resolver = entity_engine.EntityResolver(known=aliases)

        counters: dict[str, int] = {
            "entities_new": 0,
            "entities_enriched": 0,
            "entities_rejected": 0,
            "merges": 0,
            "facts_new": 0,
            "facts_reinforced": 0,
            "facts_rejected": 0,
            "relationships": 0,
            "relationships_related": 0,
            "rules": 0,
            "rules_created": 0,
            "rules_reinforced": 0,
            "canonical_rules": 0,
            "canonical_rule_conflicts": 0,
            "fabric_rule_nodes": 0,
            "conflicts": 0,
            "conflicts_auto_resolved": 0,
            "duplicates": 0,
            "updated": 0,
            "evidence": 0,
            "quality_issues": 0,
        }

        def collect_issue(
            kind: str,
            subject: str,
            *,
            detail: dict | None = None,
            evidence: EvidenceRef | None = None,
        ) -> None:
            result.quality_issues.append(
                QualityIssue(
                    kind=kind,
                    subject=subject,
                    detail=detail or {},
                    evidence=evidence,
                    source_id=source_id,
                    document_id=document_id,
                )
            )

        entity_ids: dict[str, UUID] = {}
        alias_ids: dict[str, UUID] = {}
        known_names: set[str] = set()
        objects_created = 0
        merged_aliases: set[str] = set()

        for entity in result.entities:
            # Procedencia obligatoria: sin fuente no se crea conocimiento.
            if source_id is None:
                counters["entities_rejected"] += 1
                collect_issue(
                    QualityKind.SOURCE_MISSING.value,
                    entity.name,
                    detail={"stage": "persist_entity", "entity_type": entity.entity_type},
                    evidence=entity.evidence[0] if entity.evidence else None,
                )
                continue
            if not entity.evidence:
                counters["entities_rejected"] += 1
                collect_issue(
                    QualityKind.EVIDENCE_MISSING.value,
                    entity.name,
                    detail={"stage": "persist_entity", "entity_type": entity.entity_type},
                )
                continue
            outcome = resolver.resolve(entity)
            known_before = _entity_is_known(entity, aliases)
            object_id = await store.upsert_entity(
                organization_id,
                entity,
                source_id=source_id,
                workspace_id=workspace_id,
            )
            entity_ids[_entity_key(entity.entity_type, entity.name)] = object_id
            alias_ids[normalize_term(entity.name)] = object_id
            objects_created += 1
            if known_before:
                known_names.add(normalize_term(entity.name))
                counters["entities_enriched"] += 1
                await self._observe(
                    observer,
                    "ENTITY_MATCHED",
                    {"name": entity.name, "entity_type": entity.entity_type},
                )
            else:
                counters["entities_new"] += 1
                await self._observe(
                    observer,
                    "ENTITY_DISCOVERED",
                    {"name": entity.name, "entity_type": entity.entity_type},
                )
                await self._emit_system(
                    system_emitter,
                    KnowledgeEventType.NEW_ENTITY,
                    organization_id=organization_id,
                    payload={"name": entity.name, "entity_type": entity.entity_type},
                    confidence=entity.confidence,
                    source_id=source_id,
                    document_id=document_id,
                    object_id=object_id,
                )
            for alias in entity.aliases:
                if normalize_term(alias.alias) == normalize_term(entity.name):
                    continue
                evidence_ids = [
                    value
                    for value in [
                        await store.add_evidence(
                            organization_id,
                            alias.evidence,
                            canonical_id=object_id,
                            workspace_id=workspace_id,
                        )
                        if alias.evidence
                        else None
                    ]
                    if value is not None
                ]
                alias_ids[normalize_term(alias.alias)] = object_id
                await store.upsert_alias(
                    organization_id,
                    entity_id=object_id,
                    alias=alias,
                    source_id=source_id,
                    document_id=document_id,
                    evidence_ids=evidence_ids,
                )
            if outcome.merged and outcome.merge is not None:
                merged_aliases.add(outcome.merge.merged_alias)
                counters["merges"] += 1
                result.persisted.setdefault("merges_applied", []).append(
                    outcome.merge.merged_alias
                )
                await self._observe(
                    observer,
                    "ENTITY_MERGED",
                    {
                        "canonical_name": outcome.merge.canonical_name,
                        "merged_alias": outcome.merge.merged_alias,
                        "alias_type": outcome.merge.alias_type,
                        "reason": outcome.merge.reason,
                    },
                )

        for merge in result.merges:
            if merge.merged_alias in merged_aliases:
                continue
            merged_aliases.add(merge.merged_alias)
            counters["merges"] += 1
            await self._observe(
                observer,
                "ENTITY_MERGED",
                {
                    "canonical_name": merge.canonical_name,
                    "merged_alias": merge.merged_alias,
                    "alias_type": merge.alias_type,
                    "reason": merge.reason,
                },
            )

        if result.units:
            await self._observe(
                observer, "SEMANTIC_UNIT_CREATED", {"count": len(result.units)}
            )

        evidence_written = 0
        assertions_written = 0
        bounded_dates: list[str] = []
        for fact in result.facts:
            # Gate de procedencia: sin fuente ni evidencia localizable el hecho
            # no entra al conocimiento canónico.
            if source_id is None or not fact.evidence:
                counters["facts_rejected"] += 1
                collect_issue(
                    (
                        QualityKind.SOURCE_MISSING.value
                        if source_id is None
                        else QualityKind.EVIDENCE_MISSING.value
                    ),
                    fact.subject,
                    detail={"stage": "persist_fact", "predicate": fact.predicate},
                    evidence=fact.evidence[0] if fact.evidence else None,
                )
                continue
            subject_id = entity_ids.get(_entity_key(fact.subject_type, fact.subject)) or (
                alias_ids.get(normalize_term(fact.subject))
            )
            new_subject = False
            if subject_id is None:
                subject_id = await self._ensure_object(
                    organization_id,
                    name=fact.subject,
                    entity_type=fact.subject_type,
                    source_id=source_id,
                    workspace_id=workspace_id,
                )
                alias_ids[normalize_term(fact.subject)] = subject_id
                new_subject = True
            assertion_id, _count, fact_status = await store.upsert_fact(
                organization_id,
                fact,
                subject_id=subject_id,
                source_id=source_id,
                workspace_id=workspace_id,
                document_id=document_id,
            )
            assertions_written += 1
            if new_subject:
                counters["entities_new"] += 1
                objects_created += 1
            if fact_status == "created":
                counters["facts_new"] += 1
                await self._observe(
                    observer,
                    "FACT_DISCOVERED",
                    {
                        "subject": fact.subject,
                        "predicate": fact.predicate,
                        "object_value": fact.object_value,
                        "fact_kind": fact.fact_kind,
                    },
                )
            else:
                counters["facts_reinforced"] += 1
                await self._observe(
                    observer,
                    "FACT_REINFORCED",
                    {
                        "subject": fact.subject,
                        "predicate": fact.predicate,
                        "object_value": fact.object_value,
                        "fact_kind": fact.fact_kind,
                    },
                )
            if fact.temporal.is_bounded:
                if fact.temporal.effective_from:
                    bounded_dates.append(fact.temporal.effective_from.isoformat())
                if fact.temporal.effective_to:
                    bounded_dates.append(fact.temporal.effective_to.isoformat())
            for evidence in fact.evidence:
                written = await store.add_evidence(
                    organization_id,
                    evidence,
                    canonical_id=subject_id,
                    assertion_id=assertion_id,
                    workspace_id=workspace_id,
                )
                evidence_written += 1 if written else 0

        if bounded_dates:
            await self._observe(
                observer,
                "TEMPORAL_RANGE_DISCOVERED",
                {
                    "effective_from": min(bounded_dates),
                    "effective_to": max(bounded_dates),
                    "facts": len(bounded_dates),
                },
            )

        edges_written = 0
        for relationship in result.relationships:
            subject_key = normalize_term(relationship.subject)
            object_key = normalize_term(relationship.object_name)
            subject_known = subject_key in known_names
            object_known = object_key in known_names
            subject_id = alias_ids.get(subject_key)
            if subject_id is None:
                subject_id = await self._ensure_object(
                    organization_id,
                    name=relationship.subject,
                    entity_type=relationship.subject_type,
                    source_id=source_id,
                    workspace_id=workspace_id,
                )
                alias_ids[subject_key] = subject_id
            object_id = alias_ids.get(object_key)
            if object_id is None:
                object_id = await self._ensure_object(
                    organization_id,
                    name=relationship.object_name,
                    entity_type=relationship.object_type,
                    source_id=source_id,
                    workspace_id=workspace_id,
                )
                alias_ids[object_key] = object_id
            edge_id, edge_status = await store.upsert_relationship(
                organization_id,
                relationship,
                subject_id=subject_id,
                object_id=object_id,
                source_id=source_id,
                workspace_id=workspace_id,
            )
            edges_written += 1 if edge_id else 0
            if edge_id and edge_status == "created":
                counters["relationships"] += 1
                related = subject_known and object_known
                if related:
                    counters["relationships_related"] += 1
                await self._observe(
                    observer,
                    "RELATIONSHIP_DISCOVERED",
                    {
                        "subject": relationship.subject,
                        "predicate": relationship.predicate,
                        "object": relationship.object_name,
                        "related": related,
                    },
                )
            for evidence in relationship.evidence:
                written = await store.add_evidence(
                    organization_id,
                    evidence,
                    canonical_id=subject_id,
                    workspace_id=workspace_id,
                )
                evidence_written += 1 if written else 0

        rules_written = 0
        canonical_rule_ids: dict[str, str] = {}
        canonical_rule_objects: dict[str, str] = {}
        existing_rule_keys: dict[str, str] = {}
        if system_emitter is not None:
            try:
                existing_rule_keys = await store.existing_rule_keys(organization_id)
            except Exception as exc:  # noqa: BLE001 — el índice es best-effort
                logger.debug(
                    "Knowledge rule index lookup failed", error=str(exc)[:160]
                )
        for rule in result.rules:
            rule_id, rule_status = await store.upsert_rule(
                organization_id,
                rule,
                source_id=source_id,
                workspace_id=workspace_id,
                document_id=document_id,
            )
            rules_written += 1
            if rule.rule_key:
                canonical_rule_ids[str(rule.rule_key)] = str(rule_id)
                if rule.canonical_rule_id:
                    canonical_rule_objects[rule.canonical_rule_id] = str(rule_id)
            if rule_status == "created":
                counters["rules"] += 1
                counters["rules_created"] += 1
                await self._observe(
                    observer,
                    "RULE_DISCOVERED",
                    {
                        "subject": rule.subject,
                        "statement": rule.statement,
                        "rule_type": rule.rule_type,
                        "modality": rule.modality,
                    },
                )
                previous_rule_key = existing_rule_keys.get(rule.subject)
                if previous_rule_key and previous_rule_key != rule.rule_key:
                    await self._emit_system(
                        system_emitter,
                        KnowledgeEventType.RULE_CHANGED,
                        organization_id=organization_id,
                        payload={
                            "previous_rule_key": previous_rule_key,
                            "rule_key": rule.rule_key,
                            "subject": rule.subject,
                        },
                        confidence=rule.confidence,
                        requires_review=True,
                        source_id=source_id,
                        document_id=document_id,
                        object_id=rule_id,
                        rule_key=rule.rule_key,
                    )
                else:
                    await self._emit_system(
                        system_emitter,
                        KnowledgeEventType.NEW_RULE,
                        organization_id=organization_id,
                        payload={
                            "subject": rule.subject,
                            "statement": rule.statement[:600],
                        },
                        confidence=rule.confidence,
                        source_id=source_id,
                        document_id=document_id,
                        object_id=rule_id,
                        rule_key=rule.rule_key,
                    )
            else:
                counters["rules_reinforced"] += 1
            for evidence in rule.evidence:
                written = await store.add_evidence(
                    organization_id,
                    evidence,
                    canonical_id=rule_id,
                    workspace_id=workspace_id,
                )
                evidence_written += 1 if written else 0

        # Reglas canónicas sin candidato 1:1 (p. ej. "only if"): se persisten
        # como objetos canónicos con su semántica verificada y su provenance.
        for canonical in result.canonical_rules:
            canonical_id = str(getattr(canonical, "rule_id", "") or "")
            if not canonical_id or canonical_id in canonical_rule_objects:
                continue
            wrapper = _rule_candidate_from_canonical(canonical)
            rule_id, _rule_status = await store.upsert_rule(
                organization_id,
                wrapper,
                source_id=source_id,
                workspace_id=workspace_id,
                document_id=document_id,
            )
            canonical_rule_ids[str(wrapper.rule_key)] = str(rule_id)
            canonical_rule_objects[canonical_id] = str(rule_id)
            counters["canonical_rules"] += 1
            for evidence in wrapper.evidence[:6]:
                written = await store.add_evidence(
                    organization_id,
                    evidence,
                    canonical_id=rule_id,
                    workspace_id=workspace_id,
                )
                evidence_written += 1 if written else 0
            await self._observe(
                observer,
                "CANONICAL_RULE_COMPILED",
                canonical.to_public_dict()
                if hasattr(canonical, "to_public_dict")
                else {"rule_id": canonical_id},
            )

        counters["canonical_rule_conflicts"] = sum(
            1 for rule in result.canonical_rules if getattr(rule, "conflicts_with", ())
        )
        # Proyección de reglas canónicas al Semantic Fabric (best-effort).
        attach_rule_projection = getattr(store, "attach_rule_projection", None)
        if callable(attach_rule_projection) and result.canonical_rules:
            try:
                from src.knowledge.rule_compiler import project_rules_to_fabric

                projection = project_rules_to_fabric(
                    result.canonical_rules,
                    document_id=str(document_id or ""),
                    source_id=str(source_id or ""),
                )
                counters["fabric_rule_nodes"] = await attach_rule_projection(
                    organization_id,
                    projection,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    document_id=document_id,
                )
            except Exception as exc:  # noqa: BLE001 — el fabric no frena la ingesta
                logger.warning(
                    "Rule fabric projection skipped", error=str(exc)[:200]
                )
        conflicts_written = 0
        for conflict in result.conflicts:
            subject_id = alias_ids.get(normalize_term(conflict.subject))

            # Gate estricto: sin evidencia y fuentes en AMBOS lados no hay
            # conflicto mostrable. Los fragmentos y la falta de contexto van a
            # la cola de calidad de ingesta, nunca a la cola de conflictos.
            classification = conflict.classification or conflict.conflict_type
            if not conflict.displayable:
                counters["conflicts_auto_resolved"] += 1
                if classification == ConflictType.PARSER_FRAGMENT.value:
                    collect_issue(
                        QualityKind.PARSER_FRAGMENT.value,
                        conflict.subject,
                        detail={
                            "stage": "conflict_gate",
                            "predicate": conflict.predicate,
                            "value_a": conflict.value_a[:200],
                            "value_b": conflict.value_b[:200],
                        },
                        evidence=conflict.evidence[0] if conflict.evidence else None,
                    )
                elif classification in {
                    ConflictType.INSUFFICIENT_CONTEXT.value,
                    ConflictType.UNRESOLVED.value,
                    ConflictType.UNKNOWN.value,
                }:
                    collect_issue(
                        (
                            QualityKind.SOURCE_MISSING.value
                            if not conflict.source_a or not conflict.source_b
                            else QualityKind.EVIDENCE_MISSING.value
                        ),
                        conflict.subject,
                        detail={
                            "stage": "conflict_gate",
                            "predicate": conflict.predicate,
                            "classification": classification,
                        },
                        evidence=conflict.evidence[0] if conflict.evidence else None,
                    )
                await self._observe(
                    observer,
                    "CONFLICT_AUTO_RESOLVED",
                    conflict.to_dict(),
                )
                continue

            conflict.status = "open"
            conflict_status = await store.upsert_conflict(
                organization_id,
                conflict,
                object_id=subject_id,
                workspace_id=workspace_id,
            )
            if conflict_status == "duplicate":
                counters["duplicates"] += 1
                await self._observe(
                    observer,
                    "DUPLICATE_DETECTED",
                    {
                        "subject": conflict.subject,
                        "predicate": conflict.predicate,
                        "conflict_type": conflict.conflict_type,
                    },
                )
                continue
            conflicts_written += 1
            conflict_type = conflict.conflict_type
            if conflict_type in ("VERSION_CHANGE", "TEMPORAL_CHANGE"):
                counters["updated"] += 1
            elif conflict_type == "POSSIBLE_DUPLICATE":
                counters["duplicates"] += 1
                await self._observe(
                    observer,
                    "DUPLICATE_DETECTED",
                    conflict.to_dict(),
                )
                continue
            else:
                counters["conflicts"] += 1
            await self._observe(
                observer,
                "CONFLICT_DETECTED",
                conflict.to_dict(),
            )
            await self._emit_system(
                system_emitter,
                KnowledgeEventType.CONFLICT_DETECTED,
                organization_id=organization_id,
                payload={
                    "subject": conflict.subject,
                    "predicate": conflict.predicate,
                    "conflict_type": conflict.conflict_type,
                    "classification": conflict.classification,
                    "value_a": conflict.value_a[:300],
                    "value_b": conflict.value_b[:300],
                    "evidence_ids": [
                        str(value) for value in conflict.evidence_ids
                    ],
                },
                confidence=conflict.confidence,
                source_id=source_id,
                document_id=document_id,
                object_id=subject_id,
            )

        # Cola de calidad de ingesta: problemas de parsing, no conocimiento.
        for issue in result.quality_issues:
            recorder = getattr(store, "record_quality_issue", None)
            if recorder is None:
                break
            try:
                await recorder(
                    organization_id, issue, workspace_id=workspace_id
                )
                counters["quality_issues"] += 1
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.debug(
                    "Knowledge quality issue not persisted", error=str(exc)[:160]
                )

        if evidence_written:
            counters["evidence"] = evidence_written
            await self._observe(
                observer, "EVIDENCE_LINKED", {"count": evidence_written}
            )

        await self._observe(
            observer,
            "KNOWLEDGE_OBJECT_CREATED",
            {
                "objects": objects_created,
                "assertions": assertions_written,
                "edges": edges_written,
                "rules": rules_written,
                "canonical_rules": counters.get("canonical_rules", 0),
                "fabric_rule_nodes": counters.get("fabric_rule_nodes", 0),
                "conflicts": conflicts_written,
                "quality_issues": counters["quality_issues"],
                "evidence": evidence_written,
                "entities_new": counters["entities_new"],
                "entities_enriched": counters["entities_enriched"],
                "entities_rejected": counters["entities_rejected"],
                "facts_rejected": counters["facts_rejected"],
                "conflicts_auto_resolved": counters["conflicts_auto_resolved"],
                "facts_reinforced": counters["facts_reinforced"],
            },
        )

        await store.refresh_counters(organization_id)
        self._record_quality_metrics(result, counters)

        # Huellas de las reglas canónicas: alimentan el fingerprint de caché
        # (una respuesta vieja no puede sobrevivir a un cambio de regla).
        rule_fingerprints: dict[str, str] = {}
        rule_index_version = ""
        try:
            from src.knowledge.rule_compiler.index import (
                RULE_INDEX_VERSION,
                rule_fingerprint,
            )

            rule_index_version = RULE_INDEX_VERSION
            rule_fingerprints = {
                str(getattr(rule, "rule_id", "")): rule_fingerprint(rule)
                for rule in result.canonical_rules
                if getattr(rule, "rule_id", "")
            }
        except Exception:  # noqa: BLE001 — el fingerprint es best-effort
            rule_fingerprints = {}

        return {
            "objects": objects_created,
            "assertions": assertions_written,
            "edges": edges_written,
            "rules": rules_written,
            "conflicts": conflicts_written,
            "evidence": evidence_written,
            # PASS 2 compiler-aware: ids canónicos para actualizar el payload
            # del índice sin re-embedding (acotado, tenant-scoped).
            "canonical_entity_ids": {
                name: str(object_id)
                for name, object_id in list(alias_ids.items())[:100]
            },
            "canonical_rule_ids": dict(list(canonical_rule_ids.items())[:100]),
            "canonical_rule_objects": dict(list(canonical_rule_objects.items())[:100]),
            "canonical_rule_fingerprints": dict(
                list(rule_fingerprints.items())[:100]
            ),
            "rule_index_version": rule_index_version,
            **counters,
        }

    @staticmethod
    def _record_quality_metrics(result: CompilationResult, counters: dict) -> None:
        """Métricas de calidad: fragmentos, rechazos, conflictos y auto-resueltos.

        Best-effort: Prometheus jamás interrumpe una compilación.
        """
        try:
            from src.infrastructure.observability.metrics import (
                knowledge_conflict_candidates_total,
                knowledge_conflicts_auto_resolved_total,
                knowledge_conflicts_visible_total,
                knowledge_extraction_decisions_total,
                knowledge_ingestion_quality_total,
            )
        except Exception:  # noqa: BLE001
            return
        try:
            for conflict in result.conflicts:
                classification = conflict.classification or conflict.conflict_type
                knowledge_conflict_candidates_total.labels(
                    classification=classification
                ).inc()
                if conflict.displayable:
                    knowledge_conflicts_visible_total.labels(
                        classification=classification,
                        materiality=conflict.materiality,
                    ).inc()
                else:
                    knowledge_conflicts_auto_resolved_total.labels(
                        classification=classification
                    ).inc()
            for issue in result.quality_issues:
                knowledge_ingestion_quality_total.labels(
                    kind=issue.kind,
                    stage=str(issue.detail.get("stage") or "unknown"),
                ).inc()
            knowledge_extraction_decisions_total.labels(
                stage="entity", decision="rejected"
            ).inc(counters.get("entities_rejected", 0))
            knowledge_extraction_decisions_total.labels(
                stage="fact", decision="rejected"
            ).inc(counters.get("facts_rejected", 0))
        except Exception:  # noqa: BLE001 — la métrica nunca rompe el pipeline
            return

    async def _observe(
        self,
        observer: "Callable[[str, dict], Awaitable[None]] | None",
        event_type: str,
        payload: dict,
    ) -> None:
        """Notifica un evento semántico real. Nunca interrumpe la compilación."""
        if observer is None:
            return
        try:
            await observer(event_type, payload)
        except Exception as exc:  # noqa: BLE001 — la observación es best-effort
            logger.debug("Knowledge observer failed", error=str(exc)[:160])

    async def _emit_system(
        self,
        emitter: "SystemEventEmitter | None",
        event_type: KnowledgeEventType,
        *,
        organization_id: UUID,
        payload: dict | None = None,
        confidence: float | None = None,
        requires_review: bool | None = None,
        source_id: UUID | None = None,
        document_id: UUID | None = None,
        object_id: UUID | None = None,
        rule_key: str | None = None,
    ) -> None:
        """Emite un evento de dominio C8. Best-effort: nunca interrumpe."""
        if emitter is None:
            return
        try:
            await emitter.emit(
                KnowledgeSystemEvent(
                    type=event_type,
                    organization_id=organization_id,
                    payload=payload,
                    confidence=confidence,
                    requires_review=requires_review,
                    source_id=source_id,
                    document_id=document_id,
                    object_id=object_id,
                    rule_key=rule_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 — la emisión es best-effort
            logger.debug(
                "Knowledge system event failed",
                event_type=event_type.value,
                error=str(exc)[:160],
            )

    async def _ensure_object(
        self,
        organization_id: UUID,
        *,
        name: str,
        entity_type: str,
        source_id: UUID | None,
        workspace_id: UUID | None,
    ) -> UUID:
        """Crea (determinista) el canónico de un término referenciado sin unidad."""
        candidate = EntityCandidate(
            name=name,
            entity_type=entity_type or EntityType.CONCEPT.value,
            confidence=0.6,
            evidence=[
                EvidenceRef(
                    locator=SourceLocator(
                        source_id=source_id,
                        document_title=name,
                    ),
                    evidence_type=EvidenceType.STRUCTURAL.value,
                    excerpt=name,
                    confidence=0.6,
                )
            ],
        )
        object_id = await self._store.upsert_entity(
            organization_id,
            candidate,
            source_id=source_id,
            workspace_id=workspace_id,
        )
        return object_id


def _entity_key(entity_type: str, name: str) -> str:
    return f"{entity_type}:{normalize_term(name)}"


_MODALITY_TO_COMPILER: dict[str, str] = {
    "MUST": "must",
    "REQUIRED": "must",
    "MUST_NOT": "must_not",
    "SHOULD_NOT": "must_not",
    "CONSTRAINT": "constraint",
    "SHOULD": "should",
    "MAY": "may",
    "OPTIONAL": "should",
    "NONE": "must",
}


def _uuid_or_none(value) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _rule_candidate_from_canonical(canonical) -> RuleCandidate:
    """CanonicalRule -> RuleCandidate para persistencia (misma tabla/objeto).

    La semántica viaja en ``semantics``; la provenance por propiedad se copia
    a evidencia física localizable.
    """
    evidence: list[EvidenceRef] = []
    for item in list(getattr(canonical, "provenance", ()) or ())[:8]:
        locator_data = dict(getattr(item, "locator", {}) or {})
        evidence.append(
            EvidenceRef(
                locator=SourceLocator(
                    source_id=_uuid_or_none(locator_data.get("source_id")),
                    document_id=_uuid_or_none(locator_data.get("document_id")),
                    document_title=str(locator_data.get("document_title") or ""),
                    block_id=_uuid_or_none(locator_data.get("block_id")),
                    page=locator_data.get("page"),
                    section_path=tuple(locator_data.get("section_path") or ()),
                    table_reference=locator_data.get("table_reference"),
                    row_reference=locator_data.get("row_reference"),
                    cell_reference=locator_data.get("cell_reference"),
                    database_reference=locator_data.get("database_reference"),
                ),
                evidence_type=EvidenceType.DOCUMENT.value,
                excerpt=str(getattr(item, "excerpt", "") or canonical.statement)[:400],
                method=str(getattr(item, "method", "deterministic") or "deterministic"),
                confidence=float(getattr(item, "strength", 0.7) or 0.7),
            )
        )
    modality = _MODALITY_TO_COMPILER.get(str(getattr(canonical, "modality", "MUST")), "must")
    rule_key = str(getattr(canonical, "rule_id", "") or "").split("rule:", 1)[-1][:24]
    return RuleCandidate(
        subject=str(getattr(canonical, "subject", "") or "")[:200],
        statement=str(getattr(canonical, "statement", "") or "")[:2000],
        rule_key=rule_key,
        rule_type="constraint" if modality == "constraint" else "business_rule",
        modality=modality,
        confidence=float(getattr(canonical, "confidence", 0.7) or 0.7),
        evidence=evidence,
        rule_kind=str(getattr(canonical, "kind", "") or ""),
        semantics=canonical.to_public_dict()
        if hasattr(canonical, "to_public_dict")
        else {},
        verification_state=str(getattr(canonical, "verification_state", "") or ""),
        canonical_rule_id=str(getattr(canonical, "rule_id", "") or ""),
        provenance=[
            item.to_dict()
            for item in list(getattr(canonical, "provenance", ()) or ())[:16]
            if hasattr(item, "to_dict")
        ],
    )


def _entity_is_known(entity: EntityCandidate, aliases: dict[str, str]) -> bool:
    """¿ZENT ya conocía esta entidad (por nombre o por alias declarado)?"""
    if not aliases:
        return False
    if normalize_term(entity.name) in aliases:
        return True
    return any(alias.normalized in aliases for alias in entity.aliases)


__all__ = [
    "KnowledgeCompiler",
    "SystemEventEmitter",
    "CompilationResult",
    "CompilerStore",
    "PostgresCompilerStore",
    "FactCandidate",
    "RelationshipCandidate",
    "TemporalScope",
    "canonical_uuid",
    "CanonicalKind",
    "object_kind_for_entity",
    "conflict_engine",
]
