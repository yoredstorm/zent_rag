# =============================================================================
# Knowledge Session Service — ciclo de vida del aprendizaje
# =============================================================================
# Orquesta:
#   - creación de la sesión (con baseline real del Knowledge OS)
#   - vínculo fuente/job -> sesión
#   - observers por fuente (eventos semánticos)
#   - disponibilidad (consultable) vs optimización de conocimiento derivado
#   - delta final (nuevo/reforzado/actualizado/relacionado/conflictivo/ignorado)
#   - feed de descubrimientos agrupado
#
# Todo lo que expone proviene de tablas reales: knowledge_canonical_objects,
# knowledge_assertions, knowledge_edges, evidence_ledger y los contadores que
# el pipeline fue acumulando por fuente.
# =============================================================================
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.domain.knowledge_session import (
    KnowledgeDelta,
    LearningSession,
    LearningSessionStatus,
    LearningStage,
    SessionEventType,
    SourceLearningStatus,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

from .emitter import LearningSessionObserver
from .semantics import describe

logger = get_logger(__name__)

_SWEEP_LIMIT = 200
# Tareas de optimización en curso (evita que el GC las recoja).
_BACKGROUND_TASKS: set[asyncio.Task] = set()
# Sesiones esperando el cierre explícito del cliente (si nunca llega, se
# finalizan igual tras este margen: la sesión no puede quedar colgada).
_FALLBACK_FINALIZE_SECONDS = 90
_FALLBACKS: set[str] = set()
# DDL idempotente aplicado una sola vez por proceso (dev/tests sin Alembic).
_TABLES_READY = False


class LearningSessionService:
    """Fachada de sesiones: usada por rutas, engine y worker."""

    def __init__(self, repository) -> None:
        self._repo = repository

    @property
    def repository(self):
        """Store subyacente (para replay SSE y consumidores técnicos)."""
        return self._repo

    async def ensure_tables(self) -> None:
        global _TABLES_READY
        if _TABLES_READY:
            return
        try:
            await self._repo.ensure_tables()
            _TABLES_READY = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Knowledge session tables unavailable", error=str(exc)[:200])

    async def get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> LearningSession | None:
        return await self._repo.get_session(organization_id, session_id)

    async def seal_session(self, organization_id: UUID, session_id: UUID) -> None:
        """El cliente terminó de adjuntar fuentes: el aprendizaje puede cerrar."""
        try:
            await self._repo.seal_session(organization_id, session_id)
            await self._repo.refresh_session_rollup(organization_id, session_id)
            await self._maybe_finalize(organization_id, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session seal failed", error=str(exc)[:200])

    async def rename_session(
        self, organization_id: UUID, session_id: UUID, title: str
    ) -> None:
        """Título vivo (p. ej. "Aprendiendo 3 fuentes" mientras se suben)."""
        try:
            await self._repo.update_session(session_id, title=(title or "")[:255])
        except Exception as exc:  # noqa: BLE001
            logger.debug("Learning session rename failed", error=str(exc)[:160])

    async def list_events(self, organization_id: UUID, session_id: UUID, **kwargs) -> list[dict]:
        return await self._repo.list_events(organization_id, session_id, **kwargs)

    # ---------------------------------------------------------------- baseline
    async def knowledge_totals(self, organization_id: UUID) -> dict:
        """Totales reales del Knowledge OS para before/after (1 query)."""
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM knowledge_canonical_objects
                              WHERE organization_id = :org
                                AND kind <> 'business_rule') AS entities,
                            (SELECT COUNT(*) FROM knowledge_assertions
                              WHERE organization_id = :org) AS facts,
                            (SELECT COUNT(*) FROM knowledge_edges
                              WHERE organization_id = :org) AS relationships,
                            (SELECT COUNT(*) FROM knowledge_canonical_objects
                              WHERE organization_id = :org
                                AND kind = 'business_rule') AS rules,
                            (SELECT COUNT(*) FROM evidence_ledger
                              WHERE organization_id = :org) AS evidence
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchone()
            return {
                "entities": int(row.entities or 0),
                "facts": int(row.facts or 0),
                "relationships": int(row.relationships or 0),
                "rules": int(row.rules or 0),
                "evidence": int(row.evidence or 0),
            }
        except Exception as exc:  # noqa: BLE001 — tablas aún no creadas
            logger.warning("Knowledge totals unavailable", error=str(exc)[:200])
            return {"entities": 0, "facts": 0, "relationships": 0, "rules": 0, "evidence": 0}
        finally:
            await session.close()

    # -------------------------------------------------------------- creación
    async def start_session(
        self,
        organization_id: UUID,
        *,
        title: str = "",
        origin: str = "upload",
        workspace_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> LearningSession:
        baseline = await self.knowledge_totals(organization_id)
        learning = await self._repo.create_session(
            organization_id,
            title=title,
            origin=origin,
            workspace_id=workspace_id,
            created_by=created_by,
            totals_before=baseline,
        )
        await self._emit(
            learning,
            SessionEventType.SESSION_STARTED.value,
            payload={"title": title, "origin": origin},
        )
        return learning

    async def attach_source(
        self,
        session: LearningSession,
        *,
        source_id: UUID | None,
        job_id: UUID | None,
        name: str,
        source_type: str,
    ):
        source_row = await self._repo.add_source(
            session.organization_id,
            session_id=session.id,
            source_id=source_id,
            job_id=job_id,
            name=name,
            source_type=source_type,
        )
        await self._repo.refresh_session_rollup(session.organization_id, session.id)
        return source_row

    async def list_sessions(self, organization_id: UUID, *, limit: int = 20) -> list[dict]:
        sessions = await self._repo.list_sessions(organization_id, limit=limit)
        return [session.to_dict() for session in sessions]

    async def get_session_detail(
        self, organization_id: UUID, session_id: UUID
    ) -> dict | None:
        session = await self._repo.get_session(organization_id, session_id)
        if session is None:
            return None
        sources = await self._repo.list_sources(organization_id, session_id)
        detail = session.to_dict()
        detail["sources"] = [source.to_dict() for source in sources]
        detail["metrics"] = _pulse_metrics(detail["metrics"], detail["sources"])
        if not detail["knowledge_delta"]:
            detail["knowledge_delta"] = self._delta_from_sources(sources).to_dict()
        return detail

    # ---------------------------------------------------------------- observer
    async def observer_for_job(self, job) -> LearningSessionObserver | None:
        """Construye el observer de una fuente si el job pertenece a una sesión."""
        if job.source_id is None:
            return None
        try:
            session = await self._repo.find_session_for_job(job.organization_id, job.id)
            if session is None:
                return None
            source_row = await self._repo.get_source_by_job(job.organization_id, job.id)
            if source_row is None:
                return None
            await self._repo.update_source(
                source_row.id,
                status=SourceLearningStatus.LEARNING.value,
                stage=LearningStage.READING.value,
            )
            await self._repo.update_session(
                session.id,
                status=(
                    session.status
                    if session.status
                    in (
                        LearningSessionStatus.AVAILABLE.value,
                        LearningSessionStatus.OPTIMIZING.value,
                    )
                    else LearningSessionStatus.LEARNING.value
                ),
            )
            observer = LearningSessionObserver(
                self._repo,
                session_id=session.id,
                organization_id=job.organization_id,
                source_row_id=source_row.id,
                source_id=job.source_id,
                name=source_row.name,
                source_type=source_row.source_type,
            )
            observer.stage = source_row.stage
            return observer
        except Exception as exc:  # noqa: BLE001 — el aprendizaje nunca tumba la ingesta
            logger.warning("Learning session observer unavailable", error=str(exc)[:200])
            return None

    # --------------------------------------------------------- fin de fuente
    async def on_source_available(self, observer: LearningSessionObserver | None) -> None:
        """La fuente ya responde preguntas; el enriquecimiento puede seguir."""
        if observer is None or observer.source_row_id is None:
            return
        try:
            await observer.source_available()
            await self._repo.update_source(
                observer.source_row_id,
                status=SourceLearningStatus.AVAILABLE.value,
                available_at=datetime.now(timezone.utc),
                stage=LearningStage.VERIFYING.value,
            )
            await self._repo.refresh_session_rollup(
                observer.organization_id, observer.session_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session source available failed", error=str(exc)[:200])

    async def on_source_finished(
        self,
        observer: LearningSessionObserver | None,
        *,
        success: bool,
        error: str | None = None,
        technical: str = "",
    ) -> None:
        if observer is None or observer.source_row_id is None:
            return
        try:
            if success:
                await observer.set_stage(LearningStage.LEARNED.value)
                await observer.source_completed()
                await self._repo.update_source(
                    observer.source_row_id,
                    status=SourceLearningStatus.COMPLETED.value,
                    stage=LearningStage.LEARNED.value,
                    completed_at=datetime.now(timezone.utc),
                )
            else:
                from .semantics import humanize_error

                await observer.source_failed(
                    error or humanize_error(technical), technical=technical
                )
                await self._repo.update_source(
                    observer.source_row_id,
                    status=SourceLearningStatus.FAILED.value,
                    error=error or humanize_error(technical),
                    completed_at=datetime.now(timezone.utc),
                )
                await self._repo.update_session(
                    observer.session_id, errors=self._errors_plus(observer)
                )
            await observer.close()
            await self._repo.refresh_session_rollup(
                observer.organization_id, observer.session_id
            )
            await self._maybe_finalize(
                observer.organization_id, observer.session_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session finish failed", error=str(exc)[:200])

    async def _errors_plus(self, observer: LearningSessionObserver) -> int:
        session = await self._repo.get_session(observer.organization_id, observer.session_id)
        return int(session.errors if session else 0) + 1

    # ------------------------------------------------------------- finalizar
    async def _maybe_finalize(self, organization_id: UUID, session_id: UUID) -> None:
        session = await self._repo.get_session(organization_id, session_id)
        if session is None or session.status in (
            LearningSessionStatus.COMPLETED.value,
            LearningSessionStatus.PARTIAL.value,
            LearningSessionStatus.FAILED.value,
            LearningSessionStatus.CANCELED.value,
        ):
            return
        sources = await self._repo.list_sources(organization_id, session_id)
        if not sources:
            return
        if any(
            source.status
            in (
                SourceLearningStatus.PENDING.value,
                SourceLearningStatus.LEARNING.value,
                SourceLearningStatus.AVAILABLE.value,
            )
            for source in sources
        ):
            return

        if session.sealed_at is None:
            # El cliente aún podría adjuntar más fuentes (subida por lotes).
            # La sesión queda "available" y se cierra sola si nadie la sella.
            self._schedule_fallback_finalize(organization_id, session_id)
            return

        # Todas las fuentes terminaron: el conocimiento derivado (barrido de
        # conflictos entre fuentes) corre sin bloquear la disponibilidad.
        await self._repo.update_session(
            session_id,
            status=LearningSessionStatus.OPTIMIZING.value,
            stage=LearningStage.CONNECTING.value,
        )
        try:
            task = asyncio.get_running_loop().create_task(
                self._optimize(organization_id, session_id)
            )
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
        except RuntimeError:  # sin loop: ejecutar en línea
            await self._optimize(organization_id, session_id)

    def _schedule_fallback_finalize(
        self, organization_id: UUID, session_id: UUID
    ) -> None:
        """Cierra la sesión aunque el cliente nunca llame a ``seal``."""
        key = str(session_id)
        if key in _FALLBACKS:
            return

        async def _later() -> None:
            try:
                await asyncio.sleep(_FALLBACK_FINALIZE_SECONDS)
                await self._repo.seal_session(organization_id, session_id)
                await self._maybe_finalize(organization_id, session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Learning session fallback finalize failed", error=str(exc)[:200]
                )
            finally:
                _FALLBACKS.discard(key)

        try:
            task = asyncio.get_running_loop().create_task(_later())
        except RuntimeError:
            return
        _FALLBACKS.add(key)
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _optimize(self, organization_id: UUID, session_id: UUID) -> None:
        """Conocimiento derivado real: conflictos entre fuentes de la sesión."""
        try:
            session = await self._repo.get_session(organization_id, session_id)
            if session is None:
                return
            sources = await self._repo.list_sources(organization_id, session_id)
            source_ids = [source.source_id for source in sources if source.source_id]
            found = await self._sweep_cross_source_conflicts(organization_id, source_ids)
            totals_after = await self.knowledge_totals(organization_id)
            delta = self._delta_from_sources(sources)
            delta.totals_before = session.totals_before or {}
            delta.totals_after = totals_after
            delta.conflicts = int(delta.conflicts) + found
            status = (
                LearningSessionStatus.PARTIAL.value
                if session.failed_sources
                else LearningSessionStatus.COMPLETED.value
            )
            await self._repo.update_session(
                session_id,
                status=status,
                stage=LearningStage.LEARNED.value,
                knowledge_delta=delta.to_dict(),
                totals_after=totals_after,
            )
            refreshed = await self._repo.get_session(organization_id, session_id)
            if refreshed is not None:
                await self._emit(
                    refreshed,
                    SessionEventType.SESSION_COMPLETED.value,
                    payload=delta.to_dict(),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session optimization failed", error=str(exc)[:300])
            try:
                await self._repo.update_session(
                    session_id,
                    status=LearningSessionStatus.COMPLETED.value,
                    stage=LearningStage.LEARNED.value,
                )
            except Exception:  # noqa: BLE001
                pass

    async def _sweep_cross_source_conflicts(
        self, organization_id: UUID, source_ids: list[UUID]
    ) -> int:
        """Barrido real de contradicciones entre lo nuevo y lo ya conocido."""
        if not source_ids:
            return 0
        session = await get_async_session()
        found = 0
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT n.subject_label, n.predicate, n.object_value AS new_value,
                               o.object_value AS old_value, n.source_id AS new_source,
                               o.source_id AS old_source
                        FROM knowledge_assertions n
                        JOIN knowledge_assertions o
                          ON o.organization_id = n.organization_id
                         AND o.subject_label = n.subject_label
                         AND o.predicate = n.predicate
                         AND COALESCE(o.object_value, '') <>
                             COALESCE(n.object_value, '')
                        WHERE n.organization_id = :org
                          AND n.source_id = ANY(:sources)
                          AND o.source_id IS DISTINCT FROM n.source_id
                        LIMIT :limit
                        """
                    ),
                    {
                        "org": organization_id,
                        "sources": [str(value) for value in source_ids],
                        "limit": _SWEEP_LIMIT,
                    },
                )
            ).fetchall()
            for row in rows:
                exists = (
                    await session.execute(
                        text(
                            """
                            SELECT 1 FROM knowledge_conflicts
                            WHERE organization_id = :org
                              AND subject_label = :label AND predicate = :predicate
                              AND ((value_a = :a AND value_b = :b)
                                OR (value_a = :b AND value_b = :a))
                            LIMIT 1
                            """
                        ),
                        {
                            "org": organization_id,
                            "label": str(row.subject_label)[:512],
                            "predicate": str(row.predicate)[:200],
                            "a": str(row.new_value or "")[:4000],
                            "b": str(row.old_value or "")[:4000],
                        },
                    )
                ).first()
                if exists is not None:
                    continue
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_conflicts (
                            organization_id, subject_label, predicate,
                            value_a, value_b, source_a, source_b, status,
                            conflict_type, classification, evidence_ids, reason
                        ) VALUES (
                            :org, :label, :predicate, :a, :b, :sa, :sb, 'open',
                            'SOURCE_CONFLICT',
                            CAST(:classification AS jsonb),
                            CAST('{}' AS uuid[]),
                            :reason
                        )
                        """
                    ),
                    {
                        "org": organization_id,
                        "label": str(row.subject_label)[:512],
                        "predicate": str(row.predicate)[:200],
                        "a": str(row.new_value or "")[:4000],
                        "b": str(row.old_value or "")[:4000],
                        "sa": str(row.new_source) if row.new_source else None,
                        "sb": str(row.old_source) if row.old_source else None,
                        "classification": _json(
                            {
                                "detected_by": "learning_session_conflict_sweep",
                                "values_equivalent": False,
                            }
                        ),
                        "reason": (
                            "Valores distintos para el mismo sujeto y predicado "
                            "entre fuentes de la sesión de aprendizaje."
                        ),
                    },
                )
                found += 1
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Cross-source conflict sweep failed", error=str(exc)[:200])
        finally:
            await session.close()
        return found

    # ------------------------------------------------------------------ delta
    @staticmethod
    def _sum_stats(sources: list) -> dict:
        totals: dict[str, int] = {}
        for source in sources:
            for key, value in (source.stats or {}).items():
                try:
                    totals[str(key)] = totals.get(str(key), 0) + int(value)
                except (TypeError, ValueError):
                    continue
        return totals

    def _delta_from_sources(self, sources: list) -> KnowledgeDelta:
        stats = self._sum_stats(sources)
        return KnowledgeDelta(
            new_concepts=int(stats.get("concepts", 0)),
            new_entities=int(stats.get("entities_new", 0)),
            new_facts=int(stats.get("facts_new", 0)),
            new_relationships=int(stats.get("relationships", 0)),
            new_rules=int(stats.get("rules", 0)),
            new_evidence=int(stats.get("evidence", 0)),
            reinforced_facts=int(stats.get("facts_reinforced", 0)),
            enriched_entities=int(stats.get("entities_enriched", 0)),
            merged_entities=int(stats.get("merges", 0)),
            updated=int(stats.get("updated", 0)),
            related=int(stats.get("relationships_related", 0)),
            duplicates=int(stats.get("duplicates", 0)),
            conflicts=int(stats.get("conflicts", 0)),
            ignored=int(stats.get("ignored", 0)),
        )

    # ------------------------------------------------------------------ emisión
    async def _emit(
        self, session: LearningSession, event_type: str, *, payload: dict | None = None
    ) -> None:
        try:
            event = await self._repo.append_event(
                session.organization_id,
                session_id=session.id,
                event_type=event_type,
                stage=session.stage,
                severity="info",
                message=describe(event_type, payload),
                payload=payload or {},
                aggregate=False,
            )
            from src.platform.realtime.stream import publish_event

            from .emitter import EVENT_PREFIX

            await publish_event(
                EVENT_PREFIX + event_type.lower(),
                {
                    "session_id": str(session.id),
                    "organization_id": str(session.organization_id),
                    "event_type": event_type,
                    "stage": session.stage,
                    "severity": "info",
                    "message": event.get("message"),
                    "payload": payload or {},
                    "seq": event.get("seq"),
                    "created_at": event.get("created_at"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session emit failed", error=str(exc)[:200])


# ---------------------------------------------------------------------------
# Métricas del Pulse y feed agrupado (compartidos por repo/API/UI)
# ---------------------------------------------------------------------------


def _pulse_metrics(metrics: dict, sources: list[dict] | None = None) -> dict:
    result = {str(key): int(value or 0) for key, value in (metrics or {}).items()}
    for alias, keys in (
        ("entities", ("entities_new", "entities_enriched")),
        ("facts", ("facts_new", "facts_reinforced")),
    ):
        result[alias] = sum(int(result.get(key, 0)) for key in keys)
    if sources is not None:
        result["sources"] = len(sources)
        result["sources_available"] = sum(
            1
            for source in sources
            if source.get("status") in ("available", "completed")
        )
    return result


def group_discoveries(events: list[dict], *, limit: int = 60) -> list[dict]:
    """Agrupa eventos durables en descubrimientos legibles (requisito 9)."""
    grouped: list[dict] = []
    current: dict | None = None
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type in {
            SessionEventType.SESSION_STARTED.value,
            SessionEventType.SOURCE_RECEIVED.value,
            SessionEventType.PARSING_STARTED.value,
            SessionEventType.INDEX_UPDATED.value,
        }:
            continue
        payload = dict(event.get("payload") or {})
        count = int(payload.get("count") or 1)
        key = (event_type, str(event.get("source_id") or ""), str(event.get("stage") or ""))
        if (
            current is not None
            and current["key"] == key
            and len(current["items"]) < 5
        ):
            current["count"] += count
            current["items"].append(payload)
            current["at"] = event.get("created_at") or current["at"]
            current["message"] = event.get("message") or current["message"]
            continue
        current = {
            "key": key,
            "event_type": event_type,
            "severity": event.get("severity") or "info",
            "stage": event.get("stage"),
            "source_id": event.get("source_id"),
            "message": event.get("message") or describe(event_type, payload),
            "count": count,
            "items": [payload],
            "seq": event.get("seq"),
            "at": event.get("created_at"),
        }
        grouped.append(current)
    return grouped[-limit:]


def _json(value: object) -> str:
    import json

    return json.dumps(value or {}, default=str)


__all__ = ["LearningSessionService", "group_discoveries"]
