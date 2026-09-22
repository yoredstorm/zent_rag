# =============================================================================
# MemoryFoundationService — observa, refuerza, contradice. No optimiza.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from src.core.domain.memory import (
    KNOWLEDGE_EVIDENCE_KINDS,
    TERMINAL_STATUSES,
    EvidenceRef,
    MemoryEvent,
    MemoryEventType,
    MemoryEvidenceLink,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
    ValidationPath,
)
from src.core.ports.memory import MemoryRepository
from src.memory.content import assert_safe_text, sanitize_metadata
from src.memory.policy import MemoryMaturityPolicy, MemoryPolicyError
from src.memory.signature import PatternFeatures, pattern_key, pattern_signature
from src.memory.taxonomy import (
    FailureCode,
    SuccessSignal,
    coerce_failure,
    coerce_success,
    failure_is_admitted,
)


class KnowledgeEvidenceChecker(Protocol):
    async def has_backing(self, organization_id: UUID, links: list[MemoryEvidenceLink]) -> bool:
        ...


@dataclass(kw_only=True)
class MemoryObservation:
    organization_id: UUID
    memory_type: MemoryType
    title: str
    description: str
    features: PatternFeatures
    source_component: str
    phase: str
    outcome: str
    confidence: float = 0.5
    conversation_id: UUID | None = None
    run_id: UUID | None = None
    request_id: UUID | None = None
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    success: bool | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    actor_id: UUID | None = None

    def __post_init__(self) -> None:
        if isinstance(self.memory_type, str):
            self.memory_type = MemoryType(self.memory_type)


class MemoryNotFound(KeyError):
    pass


class MemoryFoundationService:
    def __init__(
        self,
        repository: MemoryRepository,
        policy: MemoryMaturityPolicy | None = None,
        *,
        knowledge_checker: KnowledgeEvidenceChecker | None = None,
    ) -> None:
        self._repo = repository
        self._policy = policy or MemoryMaturityPolicy()
        self._knowledge_checker = knowledge_checker

    async def observe(self, observation: MemoryObservation) -> MemoryRecord:
        title, description, metadata = self._clean(observation)
        async with self._repo.exclusive():
            prior = await self._existing_idempotent(observation)
            if prior is not None:
                return prior
            signature = pattern_signature(observation.features)
            key = pattern_key(observation.features)
            features = observation.features.normalized()
            live = await self._repo.find_live(
                observation.organization_id, observation.memory_type, signature
            )
            now = _utcnow()
            if live is None:
                record = self._new_record(
                    observation,
                    title=title,
                    description=description,
                    metadata=metadata,
                    signature=signature,
                    key=key,
                    features=features,
                    now=now,
                )
                await self._repo.insert(record)
                await self._event(
                    observation,
                    record,
                    MemoryEventType.CREATED,
                    _created_snapshot(record, metadata),
                    anchor=True,
                )
                await self._event(observation, record, MemoryEventType.OBSERVED, metadata)
            else:
                record = live
                support_before = record.support_count
                confidence_before = float(record.confidence)
                record.support_count += 1
                if observation.success:
                    record.success_count += 1
                record.confidence = self._policy.blend_confidence(
                    record.confidence, observation.confidence, record.support_count
                )
                record.last_observed_at = now
                record.updated_at = now
                record.description = description or record.description
                _apply_success_signal(record, metadata)
                await self._attach(observation, record)
                backed = await self._backed(record)
                record.status = self._policy.status_after_support(
                    record, has_knowledge_evidence=backed
                )
                await self._repo.save(record)
                await self._event(
                    observation,
                    record,
                    MemoryEventType.REINFORCED,
                    _reinforced_snapshot(
                        record,
                        metadata,
                        support_before=support_before,
                        confidence_before=confidence_before,
                        support_delta=1,
                    ),
                    anchor=True,
                )
            if live is None:
                await self._attach(observation, record)
            return record

    async def contradict(self, observation: MemoryObservation) -> MemoryRecord:
        title, description, metadata = self._clean(observation)
        async with self._repo.exclusive():
            prior = await self._existing_idempotent(observation)
            if prior is not None:
                return prior
            signature = pattern_signature(observation.features)
            key = pattern_key(observation.features)
            features = observation.features.normalized()
            live = await self._repo.find_live(
                observation.organization_id, observation.memory_type, signature
            )
            now = _utcnow()
            if live is None:
                record = self._new_record(
                    observation,
                    title=title,
                    description=description,
                    metadata=metadata,
                    signature=signature,
                    key=key,
                    features=features,
                    now=now,
                )
                record.support_count = 0
                record.contradiction_count = 1
                record.confidence = min(record.confidence, 0.2)
                await self._repo.insert(record)
                await self._event(observation, record, MemoryEventType.CREATED, metadata)
            else:
                record = live
                record.contradiction_count += 1
                record.last_observed_at = now
                record.updated_at = now
                record.status = self._policy.status_after_contradiction(record)
                if record.status == MemoryStatus.CONTRADICTED:
                    record.activated_at = None
                await self._repo.save(record)
            await self._attach(observation, record)
            await self._event(
                observation,
                record,
                MemoryEventType.CONTRADICTED,
                {**metadata, "status": record.status.value},
                anchor=True,
            )
            return record

    async def record_failure(
        self,
        observation: MemoryObservation,
        code: str | FailureCode,
        *,
        occurrences: int = 1,
    ) -> MemoryRecord | None:
        failure = coerce_failure(code)
        if failure is None:
            return None
        if not failure_is_admitted(
            failure,
            occurrences=occurrences,
            isolated_min=self._policy.isolated_failure_min_occurrences,
        ):
            return None
        features = observation.features
        observation.features = PatternFeatures(
            intent_family=features.intent_family,
            source_type=features.source_type,
            retrieval_modality=features.retrieval_modality,
            tool_family=features.tool_family,
            failure_category=failure.value,
        )
        observation.outcome = observation.outcome or failure.value
        observation.success = False
        if observation.memory_type == MemoryType.CONVERSATION:
            observation.memory_type = MemoryType.LEARNING
        return await self.observe(observation)

    async def record_success(
        self,
        observation: MemoryObservation,
        signal: str | SuccessSignal,
    ) -> MemoryRecord | None:
        parsed = coerce_success(signal)
        if parsed is None:
            return None
        observation.success = True
        observation.outcome = parsed.value
        observation.metadata = {**observation.metadata, "success_signal": parsed.value}
        return await self.observe(observation)

    async def record_cluster(
        self,
        observation: MemoryObservation,
        *,
        support_delta: int,
        success_delta: int = 0,
    ) -> MemoryRecord | None:
        """Una firma, un MemoryRecord. El delta es el tamaño del grupo, no un error suelto."""
        if support_delta < 1:
            raise MemoryPolicyError("cluster support_delta must be >= 1")
        if success_delta < 0 or success_delta > support_delta:
            raise MemoryPolicyError("cluster success_delta out of range")
        code = coerce_failure(observation.features.failure_category)
        if code is not None:
            if not failure_is_admitted(
                code,
                occurrences=support_delta,
                isolated_min=self._policy.isolated_failure_min_occurrences,
            ):
                return None
            observation.success = False
            if observation.memory_type == MemoryType.CONVERSATION:
                observation.memory_type = MemoryType.LEARNING
        title, description, metadata = self._clean(observation)
        async with self._repo.exclusive():
            prior = await self._existing_idempotent(observation)
            if prior is not None:
                return prior
            signature = pattern_signature(observation.features)
            key = pattern_key(observation.features)
            features = observation.features.normalized()
            live = await self._repo.find_live(
                observation.organization_id, observation.memory_type, signature
            )
            now = _utcnow()
            if live is None:
                record = self._new_record(
                    observation,
                    title=title,
                    description=description,
                    metadata=metadata,
                    signature=signature,
                    key=key,
                    features=features,
                    now=now,
                )
                _apply_cluster_counts(
                    record, metadata, support_delta=support_delta, success_delta=success_delta, is_new=True
                )
                record.confidence = _cluster_confidence(record, observation.confidence, code is not None)
                _apply_success_signal(record, metadata)
                record.status = self._policy.status_after_support(
                    record, has_knowledge_evidence=await self._backed(record)
                )
                await self._repo.insert(record)
                await self._attach(observation, record)
                event_type = MemoryEventType.CREATED
                event_metadata = _created_snapshot(
                    record, {**record.metadata, "support_delta": support_delta}
                )
            else:
                record = live
                support_before = record.support_count
                confidence_before = float(record.confidence)
                _apply_cluster_counts(
                    record, metadata, support_delta=support_delta, success_delta=success_delta, is_new=False
                )
                record.confidence = _cluster_confidence(record, observation.confidence, code is not None)
                record.last_observed_at = now
                record.updated_at = now
                record.description = description or record.description
                _apply_success_signal(record, metadata)
                await self._attach(observation, record)
                record.status = self._policy.status_after_support(
                    record, has_knowledge_evidence=await self._backed(record)
                )
                await self._repo.save(record)
                event_type = MemoryEventType.REINFORCED
                event_metadata = _reinforced_snapshot(
                    record,
                    record.metadata,
                    support_before=support_before,
                    confidence_before=confidence_before,
                    support_delta=support_delta,
                )
            await self._event(
                observation,
                record,
                event_type,
                event_metadata,
                anchor=True,
            )
            return record

    async def record_use(
        self,
        *,
        organization_id: UUID,
        memory_id: UUID,
        source_component: str,
        phase: str,
        outcome: str,
        conversation_id: UUID | None = None,
        run_id: UUID | None = None,
        request_id: UUID | None = None,
        agent_id: UUID | None = None,
        workflow_id: UUID | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEvent:
        safe = sanitize_metadata(metadata)
        async with self._repo.exclusive():
            if idempotency_key:
                prior = await self._repo.find_event_idempotency(organization_id, idempotency_key)
                if prior is not None:
                    return prior
            record = await self._require(organization_id, memory_id)
            event = MemoryEvent(
                organization_id=organization_id,
                memory_id=record.id,
                event_type=MemoryEventType.USED,
                source_component=source_component[:80],
                phase=phase[:80],
                outcome=outcome[:80],
                conversation_id=conversation_id,
                run_id=run_id,
                request_id=request_id,
                agent_id=agent_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                metadata=safe,
            )
            return await self._repo.append_event(event)

    async def validate(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        via: ValidationPath,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        if isinstance(via, str):
            via = ValidationPath(via)
        async with self._repo.exclusive():
            record = await self._require(organization_id, memory_id)
            backed = await self._backed(record)
            self._policy.validation_allowed(record, via, has_knowledge_evidence=backed)
            now = _utcnow()
            record.status = MemoryStatus.VALIDATED
            record.validated_at = now
            record.updated_at = now
            await self._repo.save(record)
            await self._repo.append_event(
                self._admin_event(
                    record,
                    MemoryEventType.VALIDATED,
                    source_component=source_component,
                    outcome=via.value,
                    actor_id=actor_id,
                )
            )
            return record

    async def activate(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        return await self._admin_transition(
            organization_id,
            memory_id,
            event_type=MemoryEventType.ACTIVATED,
            actor_id=actor_id,
            source_component=source_component,
            apply=self._apply_activate,
        )

    async def deactivate(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        async def apply(record: MemoryRecord, now: datetime) -> None:
            if record.status != MemoryStatus.ACTIVE:
                raise MemoryPolicyError("only active memory can be deactivated")
            record.status = MemoryStatus.VALIDATED
            record.activated_at = None
            record.updated_at = now

        return await self._admin_transition(
            organization_id,
            memory_id,
            event_type=MemoryEventType.DEACTIVATED,
            actor_id=actor_id,
            source_component=source_component,
            apply=apply,
        )

    async def reject(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        return await self._set_status(
            organization_id,
            memory_id,
            status=MemoryStatus.REJECTED,
            event_type=MemoryEventType.REJECTED,
            actor_id=actor_id,
            source_component=source_component,
        )

    async def mark_stale(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "learning.engine",
    ) -> MemoryRecord:
        async def apply(record: MemoryRecord, now: datetime) -> None:
            if record.status == MemoryStatus.STALE:
                return
            if record.status in TERMINAL_STATUSES:
                raise MemoryPolicyError(f"cannot stale status {record.status.value}")
            record.status = MemoryStatus.STALE
            record.activated_at = None
            record.updated_at = now

        return await self._admin_transition(
            organization_id,
            memory_id,
            event_type=MemoryEventType.STALED,
            actor_id=actor_id,
            source_component=source_component,
            apply=apply,
        )

    async def expire(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        return await self._set_status(
            organization_id,
            memory_id,
            status=MemoryStatus.EXPIRED,
            event_type=MemoryEventType.EXPIRED,
            actor_id=actor_id,
            source_component=source_component,
        )

    async def restore(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        actor_id: UUID | None = None,
        source_component: str = "memory.inspector",
    ) -> MemoryRecord:
        async def apply(record: MemoryRecord, now: datetime) -> None:
            self._policy.restore_allowed(record)
            record.status = MemoryStatus.OBSERVED
            record.activated_at = None
            record.validated_at = None
            record.updated_at = now

        return await self._admin_transition(
            organization_id,
            memory_id,
            event_type=MemoryEventType.RESTORED,
            actor_id=actor_id,
            source_component=source_component,
            apply=apply,
        )

    async def supersede(
        self,
        organization_id: UUID,
        memory_id: UUID,
        replacement: MemoryObservation,
        *,
        actor_id: UUID | None = None,
    ) -> MemoryRecord:
        if replacement.organization_id != organization_id:
            raise MemoryPolicyError("replacement organization does not match")
        async with self._repo.exclusive():
            current = await self._require(organization_id, memory_id)
            now = _utcnow()
            current.status = MemoryStatus.SUPERSEDED
            current.activated_at = None
            current.updated_at = now
            await self._repo.save(current)
            await self._repo.append_event(
                self._admin_event(
                    current,
                    MemoryEventType.SUPERSEDED,
                    source_component=replacement.source_component,
                    outcome="superseded",
                    actor_id=actor_id,
                )
            )
        return await self.observe(replacement)

    async def get(self, organization_id: UUID, memory_id: UUID) -> MemoryRecord:
        record = await self._repo.get(organization_id, memory_id)
        if record is None:
            raise MemoryNotFound(str(memory_id))
        return record

    async def list_memories(self, organization_id: UUID, **filters: Any) -> list[MemoryRecord]:
        limit = min(int(filters.pop("limit", 50) or 50), 100)
        offset = max(int(filters.pop("offset", 0) or 0), 0)
        return await self._repo.list_records(organization_id, limit=limit, offset=offset, **filters)

    async def timeline(
        self, organization_id: UUID, memory_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[MemoryEvent]:
        await self._require(organization_id, memory_id)
        return await self._repo.list_events(
            organization_id, memory_id, limit=min(limit, 100), offset=max(offset, 0)
        )

    async def evidence(
        self, organization_id: UUID, memory_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[MemoryEvidenceLink]:
        await self._require(organization_id, memory_id)
        return await self._repo.list_evidence(
            organization_id, memory_id, limit=min(limit, 100), offset=max(offset, 0)
        )

    async def conversations(
        self, organization_id: UUID, memory_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        await self._require(organization_id, memory_id)
        return await self._repo.list_conversations(
            organization_id, memory_id, limit=min(limit, 100), offset=max(offset, 0)
        )

    async def metrics(self, organization_id: UUID, memory_id: UUID) -> dict[str, Any]:
        record = await self._require(organization_id, memory_id)
        events = await self._repo.list_events(organization_id, memory_id, limit=500, offset=0)
        used = [event for event in events if event.event_type == MemoryEventType.USED]
        last_used = used[-1].created_at.isoformat() if used else None
        return {
            "memory_id": str(record.id),
            "status": record.status.value,
            "support_count": record.support_count,
            "success_count": record.success_count,
            "success_rate": round(record.success_rate, 4),
            "contradiction_count": record.contradiction_count,
            "confidence": round(float(record.confidence), 4),
            "used_count": len(used),
            "last_used_at": last_used,
        }

    async def run_impact(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> dict[str, Any]:
        events = await self._repo.events_for_scope(
            organization_id, run_id=run_id, conversation_id=conversation_id
        )
        buckets = {
            MemoryEventType.USED: [],
            MemoryEventType.CREATED: [],
            MemoryEventType.REINFORCED: [],
            MemoryEventType.CONTRADICTED: [],
        }
        for event in events:
            if event.event_type in buckets:
                buckets[event.event_type].append(event)
        return {
            "organization_id": str(organization_id),
            "run_id": str(run_id) if run_id else None,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "used": await self._impact_items(organization_id, buckets[MemoryEventType.USED]),
            "created": await self._impact_items(organization_id, buckets[MemoryEventType.CREATED]),
            "reinforced": await self._impact_items(
                organization_id, buckets[MemoryEventType.REINFORCED]
            ),
            "contradicted": await self._impact_items(
                organization_id, buckets[MemoryEventType.CONTRADICTED]
            ),
        }

    async def query_impact(
        self,
        organization_id: UUID,
        *,
        query_id: UUID,
        request_id: UUID,
    ) -> dict[str, Any]:
        events = await self._repo.events_for_request(organization_id, request_id, limit=101)
        truncated = len(events) > 100
        if truncated:
            events = events[:100]
        payload = empty_query_impact(query_id)
        payload["truncated"] = truncated
        grouped: dict[MemoryEventType, list[MemoryEvent]] = {kind: [] for kind in _QUERY_BUCKETS}
        for event in events:
            if event.event_type in grouped:
                grouped[event.event_type].append(event)
        for kind, name in _QUERY_BUCKETS.items():
            items = await self._query_items(organization_id, grouped[kind], kind)
            payload[name] = items
            payload["counts"][name] = len(items)
        return payload

    async def _query_items(
        self,
        organization_id: UUID,
        events: list[MemoryEvent],
        event_type: MemoryEventType,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[UUID] = set()
        for event in events:
            if event.memory_id in seen:
                continue
            seen.add(event.memory_id)
            record = await self._repo.get(organization_id, event.memory_id)
            if record is None:
                continue
            items.append(_public_query_item(record, event, event_type))
        return items

    async def _impact_items(
        self, organization_id: UUID, events: list[MemoryEvent]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[UUID] = set()
        for event in events:
            if event.memory_id in seen:
                continue
            seen.add(event.memory_id)
            record = await self._repo.get(organization_id, event.memory_id)
            if record is None:
                continue
            items.append(
                {
                    "memory_id": str(record.id),
                    "memory_type": record.memory_type.value,
                    "title": record.title,
                    "pattern_key": record.pattern_key,
                    "status": record.status.value,
                    "confidence": round(float(record.confidence), 4),
                }
            )
        return items

    def _clean(
        self, observation: MemoryObservation
    ) -> tuple[str, str, dict[str, Any]]:
        if observation.memory_type == MemoryType.CONVERSATION and observation.conversation_id is None:
            raise MemoryPolicyError("conversation memory requires conversation_id")
        title = assert_safe_text(observation.title, field_name="title")
        description = assert_safe_text(observation.description, field_name="description")
        metadata = sanitize_metadata(observation.metadata)
        if observation.actor_id is not None:
            metadata["actor_id"] = str(observation.actor_id)
        return title, description, metadata

    async def _existing_idempotent(self, observation: MemoryObservation) -> MemoryRecord | None:
        if not observation.idempotency_key:
            return None
        prior = await self._repo.find_event_idempotency(
            observation.organization_id, observation.idempotency_key
        )
        if prior is None:
            return None
        return await self._repo.get(observation.organization_id, prior.memory_id)

    def _new_record(
        self,
        observation: MemoryObservation,
        *,
        title: str,
        description: str,
        metadata: dict[str, Any],
        signature: str,
        key: str,
        features: PatternFeatures,
        now: datetime,
    ) -> MemoryRecord:
        return MemoryRecord(
            organization_id=observation.organization_id,
            memory_type=observation.memory_type,
            title=title,
            description=description,
            pattern_key=key,
            pattern_signature=signature,
            visibility=MemoryVisibility.TENANT,
            status=self._policy.initial_status(),
            confidence=min(1.0, max(0.0, float(observation.confidence))),
            support_count=1,
            success_count=1 if observation.success else 0,
            first_observed_at=now,
            last_observed_at=now,
            created_from_conversation_id=observation.conversation_id,
            created_from_run_id=observation.run_id,
            intent_family=features.intent_family,
            source_type=features.source_type,
            retrieval_modality=features.retrieval_modality,
            tool_family=features.tool_family,
            failure_category=features.failure_category,
            success_signal=_success_signal(metadata),
            source_component=observation.source_component[:80],
            agent_id=observation.agent_id,
            workflow_id=observation.workflow_id,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )

    async def _attach(self, observation: MemoryObservation, record: MemoryRecord) -> None:
        for ref in observation.evidence:
            if ref.kind in KNOWLEDGE_EVIDENCE_KINDS and ref.ref_id is None:
                raise MemoryPolicyError("knowledge evidence requires ref_id")
            await self._repo.add_evidence(
                MemoryEvidenceLink(
                    organization_id=record.organization_id,
                    memory_id=record.id,
                    kind=ref.kind,
                    ref_id=ref.ref_id,
                    ref_label=assert_safe_text(ref.ref_label, field_name="ref_label")
                    if ref.ref_label
                    else "",
                )
            )

    async def _event(
        self,
        observation: MemoryObservation,
        record: MemoryRecord,
        event_type: MemoryEventType,
        metadata: dict[str, Any],
        *,
        anchor: bool = False,
    ) -> MemoryEvent:
        key = observation.idempotency_key if anchor else None
        return await self._repo.append_event(
            MemoryEvent(
                organization_id=record.organization_id,
                memory_id=record.id,
                event_type=event_type,
                source_component=observation.source_component[:80],
                phase=observation.phase[:80],
                outcome=(observation.outcome or event_type.value)[:80],
                conversation_id=observation.conversation_id,
                run_id=observation.run_id,
                request_id=observation.request_id,
                agent_id=observation.agent_id,
                workflow_id=observation.workflow_id,
                idempotency_key=key or None,
                metadata=metadata,
            )
        )

    async def _backed(self, record: MemoryRecord) -> bool:
        links = await self._repo.list_evidence(record.organization_id, record.id, limit=100, offset=0)
        backed = [
            link
            for link in links
            if link.kind in KNOWLEDGE_EVIDENCE_KINDS and link.ref_id is not None
        ]
        if not backed:
            return False
        if self._knowledge_checker is None or record.memory_type != MemoryType.KNOWLEDGE:
            return True
        return await self._knowledge_checker.has_backing(record.organization_id, backed)

    async def _require(self, organization_id: UUID, memory_id: UUID) -> MemoryRecord:
        record = await self._repo.get(organization_id, memory_id)
        if record is None:
            raise MemoryNotFound(str(memory_id))
        return record

    async def _apply_activate(self, record: MemoryRecord, now: datetime) -> None:
        self._policy.activation_allowed(record)
        record.status = MemoryStatus.ACTIVE
        record.activated_at = now
        record.updated_at = now

    async def _set_status(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        status: MemoryStatus,
        event_type: MemoryEventType,
        actor_id: UUID | None,
        source_component: str,
    ) -> MemoryRecord:
        async def apply(record: MemoryRecord, now: datetime) -> None:
            record.status = status
            record.activated_at = None
            record.updated_at = now

        return await self._admin_transition(
            organization_id,
            memory_id,
            event_type=event_type,
            actor_id=actor_id,
            source_component=source_component,
            apply=apply,
        )

    async def _admin_transition(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        event_type: MemoryEventType,
        actor_id: UUID | None,
        source_component: str,
        apply,
    ) -> MemoryRecord:
        async with self._repo.exclusive():
            record = await self._require(organization_id, memory_id)
            now = _utcnow()
            await apply(record, now)
            await self._repo.save(record)
            await self._repo.append_event(
                self._admin_event(
                    record,
                    event_type,
                    source_component=source_component,
                    outcome=record.status.value,
                    actor_id=actor_id,
                )
            )
            return record

    def _admin_event(
        self,
        record: MemoryRecord,
        event_type: MemoryEventType,
        *,
        source_component: str,
        outcome: str,
        actor_id: UUID | None,
    ) -> MemoryEvent:
        metadata: dict[str, Any] = {"status": record.status.value}
        if actor_id is not None:
            metadata["actor_id"] = str(actor_id)
        return MemoryEvent(
            organization_id=record.organization_id,
            memory_id=record.id,
            event_type=event_type,
            source_component=source_component[:80],
            phase="admin",
            outcome=outcome[:80],
            metadata=metadata,
        )


def _success_signal(metadata: dict[str, Any]) -> str:
    value = metadata.get("success_signal")
    if isinstance(value, str):
        return value[:80]
    return ""


def _apply_success_signal(record: MemoryRecord, metadata: dict[str, Any]) -> None:
    signal = _success_signal(metadata)
    if signal:
        record.success_signal = signal


def _merge_labels(previous: Any, incoming: Any) -> list[str]:
    merged: list[str] = []
    for item in list(previous or []) + list(incoming or []):
        text = str(item).strip()[:200]
        if text and text not in merged:
            merged.append(text)
        if len(merged) >= 20:
            break
    return merged


def _apply_cluster_counts(
    record: MemoryRecord,
    metadata: dict[str, Any],
    *,
    support_delta: int,
    success_delta: int,
    is_new: bool,
) -> None:
    batch_latency = float(metadata.get("latency_total_ms") or 0.0)
    batch_cost = float(metadata.get("cost_total") or 0.0)
    if is_new:
        record.support_count = support_delta
        record.success_count = success_delta
        total_latency = batch_latency
        total_cost = batch_cost
        sources = _merge_labels([], metadata.get("affected_sources"))
    else:
        record.support_count += support_delta
        record.success_count += success_delta
        total_latency = float(record.metadata.get("latency_total_ms") or 0.0) + batch_latency
        total_cost = float(record.metadata.get("cost_total") or 0.0) + batch_cost
        sources = _merge_labels(record.metadata.get("affected_sources"), metadata.get("affected_sources"))
    record.metadata.update(metadata)
    record.metadata["affected_sources"] = sources
    record.metadata["latency_total_ms"] = round(total_latency, 4)
    record.metadata["cost_total"] = round(total_cost, 6)
    if record.support_count:
        record.metadata["average_latency_ms"] = round(total_latency / record.support_count, 2)
        record.metadata["average_cost"] = round(total_cost / record.support_count, 6)
    record.metadata["occurrences"] = record.support_count
    record.metadata["runs"] = record.support_count
    record.metadata["successful"] = record.success_count
    record.metadata["success_rate"] = round(record.success_rate, 4)


def _cluster_confidence(record: MemoryRecord, observed: float, is_failure: bool) -> float:
    if is_failure:
        return min(1.0, max(0.0, float(observed)))
    if record.support_count <= 0:
        return 0.0
    return min(1.0, max(0.0, record.success_count / record.support_count))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_QUERY_BUCKETS: dict[MemoryEventType, str] = {
    MemoryEventType.USED: "used",
    MemoryEventType.CREATED: "created",
    MemoryEventType.REINFORCED: "reinforced",
    MemoryEventType.CONTRADICTED: "contradicted",
    MemoryEventType.VALIDATED: "validated",
}

_STATUS_VALUES = {item.value for item in MemoryStatus}


def empty_query_impact(query_id: UUID) -> dict[str, Any]:
    counts = {name: 0 for name in _QUERY_BUCKETS.values()}
    payload: dict[str, Any] = {"query_id": str(query_id), "truncated": False, "counts": counts}
    for name in _QUERY_BUCKETS.values():
        payload[name] = []
    return payload


def _created_snapshot(record: MemoryRecord, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        **metadata,
        "status": record.status.value,
        "support_after": record.support_count,
        "confidence_after": round(float(record.confidence), 4),
    }


def _reinforced_snapshot(
    record: MemoryRecord,
    metadata: dict[str, Any],
    *,
    support_before: int,
    confidence_before: float,
    support_delta: int,
) -> dict[str, Any]:
    return {
        **metadata,
        "status": record.status.value,
        "support_delta": support_delta,
        "support_before": support_before,
        "support_after": record.support_count,
        "confidence_before": round(float(confidence_before), 4),
        "confidence_after": round(float(record.confidence), 4),
    }


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _opt_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _public_query_item(
    record: MemoryRecord,
    event: MemoryEvent,
    event_type: MemoryEventType,
) -> dict[str, Any]:
    meta = event.metadata or {}
    status = record.status.value
    if event_type != MemoryEventType.USED:
        raw_status = meta.get("status")
        if isinstance(raw_status, str) and raw_status in _STATUS_VALUES:
            status = raw_status
    item: dict[str, Any] = {
        "memory_id": str(record.id),
        "display_id": str(record.id).replace("-", "")[:8],
        "title": record.title,
        "memory_type": record.memory_type.value,
        "status": status,
        "confidence": None,
        "support_count": None,
        "success_rate": None,
        "phase": event.phase or None,
        "outcome": event.outcome or None,
        "needs_evidence": status == MemoryStatus.OBSERVED.value and event_type != MemoryEventType.USED,
        "previous_support": None,
        "previous_confidence": None,
        "support_after": None,
        "confidence_after": None,
    }
    if event_type == MemoryEventType.USED:
        item["needs_evidence"] = False
        item["confidence"] = round(float(record.confidence), 4)
        item["support_count"] = record.support_count
        if record.support_count > 0:
            item["success_rate"] = round(record.success_rate, 4)
        return item
    item["previous_support"] = _opt_int(meta.get("support_before"))
    item["previous_confidence"] = _opt_float(meta.get("confidence_before"))
    item["support_after"] = _opt_int(meta.get("support_after"))
    item["confidence_after"] = _opt_float(meta.get("confidence_after"))
    return item
