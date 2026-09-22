# =============================================================================
# Composition root for DecisionEngine.
# =============================================================================
from __future__ import annotations

from src.core.ports.rag_ports import LLMProvider
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.composite import CompositeDecisionProvider
from src.decision.engine import DecisionEngine
from src.decision.providers.jev import JevDecisionProvider
from src.decision.providers.llm import LLMDecisionProvider
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings, settings_from_app
from src.decision.traces import DecisionTraceStore
from src.decision.usage import DecisionUsageRecorder


def build_decision_engine(
    *,
    llm: LLMProvider | None = None,
    settings: DecisionEngineSettings | None = None,
    jev_client=None,
) -> DecisionEngine:
    cfg = settings or settings_from_app()
    registry = InMemoryCapabilityRegistry()
    registry.sync_tools()
    rules = RulesDecisionProvider()
    # Cache request-scoped compartida entre provider (escribe PRE_RETRIEVAL) y
    # engine (lee/reutiliza en el planner y las demás fases).
    from src.decision.batch import JudgmentCache

    batch_cache = JudgmentCache(ttl_seconds=cfg.judgment_cache_ttl_seconds)
    jev = (
        JevDecisionProvider(cfg, client=jev_client, cache=batch_cache)
        if (cfg.jev_configured or jev_client is not None)
        else None
    )
    small_llm = LLMDecisionProvider(llm, cfg) if llm is not None else None
    reasoning = (
        LLMDecisionProvider(llm, cfg, model=cfg.complex_model, reasoning=True)
        if llm is not None
        else None
    )
    composite = CompositeDecisionProvider(
        settings=cfg,
        rules=rules,
        jev=jev,
        llm=small_llm,
        reasoning=reasoning,
        registry=registry,
    )
    return DecisionEngine(
        composite,
        cfg,
        registry=registry,
        tracer=DecisionTraceStore(),
        usage=DecisionUsageRecorder(),
        jev=jev,
        cache=batch_cache,
    )
