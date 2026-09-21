# =============================================================================
# LLMDecisionProvider — cheap generative fallback (Novita via LiteLLM).
# =============================================================================
# Structured JSON only. Never used to write user-facing answers.
# =============================================================================
from __future__ import annotations

import json
import re
import time
from typing import Any

from src.core.domain.decision import (
    ComplexityLevel,
    DecisionContext,
    DecisionProviderName,
    RoutingDecision,
)
from src.core.ports.decision import DecisionProvider
from src.core.ports.rag_ports import LLMProvider
from src.decision.costs import resolve_cost
from src.decision.questions import complexity_from_score
from src.decision.settings import DecisionEngineSettings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.resilience.circuit_breaker import CircuitBreaker

logger = get_logger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM = (
    "You are a routing classifier. Reply with JSON only. "
    "Do not write an answer for the user."
)

_PROMPT = """Classify the user request into one capability.
Allowed capabilities: {caps}

Return JSON:
{{
  "capability": "<one of the allowed ids>",
  "intent": "<short intent id>",
  "complexity": "trivial|bounded|multi_step|reasoning",
  "needs_knowledge": true,
  "needs_agent": false,
  "needs_workflow": false,
  "needs_tool": false,
  "needs_reasoning": false,
  "confidence": 0.0
}}

user_request: {request}
sql_enabled: {sql}
knowledge_enabled: {knowledge}
"""


class LLMDecisionProvider(DecisionProvider):
    name = DecisionProviderName.LLM.value

    def __init__(
        self,
        llm: LLMProvider,
        settings: DecisionEngineSettings,
        *,
        model: str | None = None,
        circuit: CircuitBreaker | None = None,
        reasoning: bool = False,
    ) -> None:
        self._llm = llm
        self._settings = settings
        self._model = model or (
            settings.complex_model if reasoning else settings.fallback_model
        )
        self._reasoning = reasoning
        self._circuit = circuit or CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            recovery_timeout=settings.circuit_recovery_seconds,
        )

    async def decide(self, context: DecisionContext) -> RoutingDecision:
        started = time.perf_counter()
        caps = ", ".join(context.available_capabilities)
        prompt = _PROMPT.format(
            caps=caps,
            request=(context.user_request or "")[:1500],
            sql=context.sql_enabled,
            knowledge=context.knowledge_enabled,
        )
        try:
            response = await self._circuit.call(
                "decision.llm",
                lambda: self._llm.generate(
                    prompt=prompt,
                    model=self._model or None,
                    max_tokens=200,
                    temperature=0.0,
                    system_prompt=_SYSTEM,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM decision provider failed", error=str(exc))
            return RoutingDecision(
                provider=self.name,
                resolved=False,
                fallback_used=True,
                latency_ms=(time.perf_counter() - started) * 1000,
                metadata={"error": str(exc)[:200]},
            )
        parsed = _parse_json(getattr(response, "content", "") or "")
        capability = str(parsed.get("capability") or "knowledge.answer")
        if capability not in context.available_capabilities:
            capability = "knowledge.answer" if context.knowledge_enabled else "respond_directly"
        complexity_raw = str(parsed.get("complexity") or "bounded")
        try:
            complexity = ComplexityLevel(complexity_raw)
        except ValueError:
            complexity = ComplexityLevel(complexity_from_score(1.0))
        confidence = float(parsed.get("confidence") or 0.55)
        confidence = min(1.0, max(0.0, confidence))
        model = str(getattr(response, "model", self._model) or "")
        decision = RoutingDecision(
            intent=str(parsed.get("intent") or capability),
            capability=capability,
            complexity=complexity,
            needs_knowledge=bool(parsed.get("needs_knowledge", capability.startswith("knowledge."))),
            needs_agent=bool(parsed.get("needs_agent", capability.startswith("agent."))),
            needs_workflow=bool(parsed.get("needs_workflow", capability.startswith("workflow."))),
            needs_tool=bool(parsed.get("needs_tool", capability.startswith("tool."))),
            needs_reasoning=bool(parsed.get("needs_reasoning") or self._reasoning),
            confidence=confidence,
            provider=self.name,
            resolved=True,
            latency_ms=(time.perf_counter() - started) * 1000,
            prompt_tokens=int(getattr(response, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(response, "completion_tokens", 0) or 0),
            metadata={"model": model, "reasoning": self._reasoning},
        )
        # Pricing Registry primero; estimated_cost_per_1k solo si el registry cae.
        cost = await resolve_cost(
            provider="default",
            model=model,
            prompt_tokens=decision.prompt_tokens,
            completion_tokens=decision.completion_tokens,
            legacy_per_1k=self._settings.estimated_cost_per_1k,
        )
        decision.estimated_cost = cost.amount
        decision.metadata["cost_source"] = cost.source
        return decision


def _parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    match = _JSON_RE.search(raw)
    if match:
        raw = match.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
