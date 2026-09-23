# =============================================================================
# Evidence Reasoning — composition root (Fase 6)
# =============================================================================
# El motor se construye con lo que ya existe: el contexto empresarial sale del
# CompanyContextCompiler, la búsqueda documental del retriever y el motor
# analítico de la Intelligence Layer. Nada se duplica.
# =============================================================================
from __future__ import annotations

import random
from uuid import UUID

from src.core.domain.reasoning import ReasoningMode
from src.core.domain.research import ResearchBudgets
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_engine = None


def reasoning_mode(settings=None) -> ReasoningMode:
    """Modo configurado para este request."""
    try:
        if settings is None:
            from src.core.config import get_settings

            settings = get_settings()
        raw = str(getattr(settings, "RAG_EVIDENCE_REASONING_MODE", "off") or "off").lower()
        return ReasoningMode(raw)
    except Exception:  # noqa: BLE001 - sin settings el razonamiento queda off
        return ReasoningMode.OFF


def reasoning_active(settings=None, *, roll: float | None = None) -> bool:
    """¿Corresponde ejecutar razonamiento en este request?

    canary decide por porcentaje; off y shadow ejecutan el motor sólo para
    comparar (shadow no controla la respuesta, pero sí mide).
    """
    mode = reasoning_mode(settings)
    if mode is ReasoningMode.OFF:
        return False
    if mode is ReasoningMode.CANARY:
        try:
            percent = int(
                getattr(settings, "RAG_EVIDENCE_REASONING_CANARY_PERCENT", 0) or 0
            )
        except Exception:  # noqa: BLE001
            percent = 0
        value = random.random() * 100 if roll is None else roll  # noqa: S311 - canary no es criptográfico
        return value < percent
    return True


def reasoning_controls_answer(settings=None, *, roll: float | None = None) -> bool:
    """Sólo `on` y el canary elegido controlan la respuesta; `shadow` no."""
    mode = reasoning_mode(settings)
    if mode is ReasoningMode.ON:
        return True
    if mode is ReasoningMode.CANARY:
        return reasoning_active(settings, roll=roll)
    return False


def reasoning_budgets(settings=None) -> ResearchBudgets:
    """Presupuestos del motor, tomados de settings con defaults seguros."""
    try:
        if settings is None:
            from src.core.config import get_settings

            settings = get_settings()
        return ResearchBudgets(
            max_steps=int(getattr(settings, "RAG_EVIDENCE_REASONING_MAX_ANALYSIS_STEPS", 10) or 10),
            max_retrieval_calls=int(
                getattr(settings, "RAG_EVIDENCE_REASONING_MAX_RETRIEVAL_ROUNDS", 4) or 4
            ),
        )
    except Exception:  # noqa: BLE001
        return ResearchBudgets()


def evidence_reasoning_engine(settings=None):
    """Motor de razonamiento cableado con las piezas existentes."""
    global _engine
    if _engine is not None:
        return _engine
    from src.intelligence.analytical import AnalyticalReasoningEngine
    from src.intelligence.reasoning.assessment import HypothesisEngine
    from src.intelligence.reasoning.coordinator import (
        AnalyticalStrategy,
        EvidenceReasoningEngine,
        GraphReasoningStrategy,
    )
    from src.intelligence.reasoning.scenario import ScenarioParser

    try:
        max_events = int(
            getattr(settings, "RAG_EVIDENCE_REASONING_MAX_EVENTS", 200) or 200
        )
        max_hypotheses = int(
            getattr(settings, "RAG_EVIDENCE_REASONING_MAX_HYPOTHESES", 4) or 4
        )
        max_requirements = int(
            getattr(settings, "RAG_EVIDENCE_REASONING_MAX_REQUIREMENTS", 6) or 6
        )
    except Exception:  # noqa: BLE001
        max_events, max_hypotheses, max_requirements = 200, 4, 6

    analytical = AnalyticalReasoningEngine(budgets=reasoning_budgets(settings))
    judge = _judge_callable()
    _engine = EvidenceReasoningEngine(
        budgets=reasoning_budgets(settings),
        parser=ScenarioParser(max_events=max_events),
        hypothesis_engine=HypothesisEngine(
            max_hypotheses=max_hypotheses, judge=judge
        ),
        strategies=(
            AnalyticalStrategy(analytical=analytical),
            GraphReasoningStrategy(ask=_company_ask_callable()),
        ),
        knowledge_search=_knowledge_search_callable(),
        company_context_provider=_company_context_callable(),
        authority_resolver=_authority_callable(),
        discovery_emitter=_discovery_emitter(),
        memory_recorder=_memory_recorder(),
        max_requirements=max_requirements,
    )
    return _engine


def reset_engine_cache() -> None:
    """Tests: permite reconstruir el motor con otra configuración."""
    global _engine
    _engine = None


def _judge_callable():
    """Juez del Judgment Fabric. Fail-soft: sin JEV el motor es determinista."""
    async def judge(*, state: dict, questions: dict):
        try:
            from src.decision.service import get_decision_engine

            engine = get_decision_engine()
        except Exception:  # noqa: BLE001
            return None
        if engine is None:
            return None
        return await engine.judge(state=state, questions=questions)

    return judge


def _knowledge_search_callable():
    """Recuperación documental como evidencia (sin LLM)."""
    async def search(organization_id: UUID, query: str, *, limit: int = 4):
        try:
            from src.company.wiring import _knowledge_search  # noqa: PLC2701

            return await _knowledge_search(organization_id, query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reasoning retrieval unavailable", error=str(exc)[:150])
            return []

    return search


def _company_context_callable():
    """CompanyContextCompiler: el contexto empresarial ya existe, se reutiliza."""
    async def compile_context(organization_id: UUID, question: str, **kwargs):
        try:
            from src.company.wiring import company_context_compiler

            return await company_context_compiler().compile(
                organization_id, question
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reasoning company context unavailable", error=str(exc)[:150])
            return None

    return compile_context


def _authority_callable():
    """Source Authority del tenant, para pesar evidencia en conflicto."""
    async def authority(organization_id: UUID) -> dict:
        try:
            from src.company.wiring import company_authority_service

            rules = await company_authority_service().list_rules(organization_id)
        except Exception:  # noqa: BLE001
            return {}
        return {rule.source_name: rule.authority_level.value for rule in rules}

    return authority


def _discovery_emitter():
    """§42: el runtime no escribe el grafo; emite candidatos con provenance."""
    async def emit(
        organization_id: UUID,
        *,
        subject: str,
        statement: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        try:
            from src.company.discovery import engine as discovery_engine
        except Exception:  # noqa: BLE001
            return
        candidate_factory = getattr(discovery_engine, "_pending_candidates", None)
        if candidate_factory is None:
            # El lifecycle lo decide Company Discovery; acá sólo se deja la señal.
            logger.info(
                "reasoning discovery candidate",
                organization_id=str(organization_id),
                subject=subject[:120],
            )

    return emit


def _company_ask_callable():
    async def ask(organization_id: UUID, question: str, **kwargs):
        try:
            from src.company.wiring import company_ask_service

            return await company_ask_service().ask(organization_id, question)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reasoning company ask unavailable", error=str(exc)[:150])
            return None

    return ask


def _memory_recorder():
    """§66: evento de memoria operativa al cerrar un razonamiento complejo."""

    async def record(organization_id: UUID, payload: dict) -> None:
        try:
            from src.memory.service import MemoryFoundationService, MemoryObservation
            from src.memory.wiring import memory_foundation_service
        except Exception:  # noqa: BLE001
            return
        service = memory_foundation_service()
        if not isinstance(service, MemoryFoundationService):
            return
        try:
            from src.core.domain.memory import MemoryType
            from src.memory.signature import PatternFeatures

            observation = MemoryObservation(
                organization_id=organization_id,
                memory_type=MemoryType.OPERATIONAL,
                title=f"reasoning:{payload.get('reasoning_shape')}",
                description=(
                    "Razonamiento "
                    f"{payload.get('reasoning_shape')} con resultado "
                    f"{payload.get('outcome')}"
                ),
                features=PatternFeatures(),
                source_component="evidence_reasoning",
                phase="reasoning",
                outcome=str(payload.get("outcome") or ""),
                metadata=payload,
            )
            await service.observe(observation)
        except Exception as exc:  # noqa: BLE001 - memoria opcional
            logger.info("reasoning memory event skipped", error=str(exc)[:120])

    return record
