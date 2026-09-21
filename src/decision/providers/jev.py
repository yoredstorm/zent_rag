# =============================================================================
# JevDecisionProvider — TypeSafe System One adapter.
# =============================================================================
# Official API: POST https://api.typesafe.ai/v1/systemone
# SDK optional (typesafe-sdk). CI never calls the live API.
# =============================================================================
from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable, Protocol

from src.core.domain.decision import (
    ComplexityLevel,
    DecisionContext,
    DecisionProviderName,
    RiskLevel,
    RoutingDecision,
)
from src.core.ports.decision import DecisionProvider
from src.decision.costs import JEV_PROVIDER, DecisionCost, resolve_cost
from src.decision.questions import (
    build_routing_questions,
    complexity_from_score,
    noul_certainty,
    noul_from_answer,
    noul_is_uncertain,
    noul_is_yes,
    safe_noul,
)
from src.decision.settings import DecisionEngineSettings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)

logger = get_logger(__name__)

# Resolver inyectable (tests sin DB). Debe devolver un DecisionCost.
CostResolver = Callable[..., Awaitable[DecisionCost] | DecisionCost]


class JevTransportError(Exception):
    """JEV HTTP/SDK failure. Composite catches this and falls back."""


class JevClient(Protocol):
    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
        timeout: float,
    ) -> dict[str, Any]: ...


class HttpJevClient:
    """Official HTTP adapter. Does not require typesafe-sdk."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = None

    def _http(self):
        """Shared client: HTTP keep-alive across judgments (one per process)."""
        import httpx

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
        timeout: float,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/v1/systemone"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"state": state, "model": model, "questions": questions}
        response = await self._http().post(
            url, json=payload, headers=headers, timeout=timeout
        )
        if response.status_code >= 400:
            raise JevTransportError(
                f"JEV HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        if not isinstance(data, dict) or "answers" not in data:
            raise JevTransportError("JEV invalid response: missing answers")
        return data


class SdkJevClient:
    """Optional typesafe-sdk wrapper when the extra is installed."""

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            from typesafe_sdk import AsyncTypeSafeClient
        except ImportError as exc:
            raise JevTransportError("typesafe-sdk not installed") from exc
        async with AsyncTypeSafeClient(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=timeout,
            model=model,
        ) as client:
            result = await client.system_one(state=state, questions=questions, model=model)
        answers: dict[str, Any] = {}
        raw_answers = getattr(result, "answers", {}) or {}
        for key, answer in raw_answers.items():
            answers[key] = _answer_to_dict(answer)
        usage = getattr(result, "usage", None)
        return {
            "model": getattr(result, "model", model),
            "answers": answers,
            "usage": {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            },
        }


def _answer_to_dict(answer: Any) -> dict[str, Any]:
    if isinstance(answer, dict):
        return answer
    payload: dict[str, Any] = {"type": getattr(answer, "type", None)}
    if hasattr(answer, "choice"):
        payload["choice"] = answer.choice
        payload["probabilities"] = dict(getattr(answer, "probabilities", {}) or {})
        payload["confidence"] = float(getattr(answer, "confidence", 0.0) or 0.0)
    if hasattr(answer, "score"):
        payload["score"] = float(answer.score)
        payload["probabilities"] = dict(getattr(answer, "probabilities", {}) or {})
        payload["confidence"] = float(getattr(answer, "confidence", 0.0) or 0.0)
    if hasattr(answer, "noul"):
        payload["noul"] = safe_noul(getattr(answer, "noul", None), 0.5)
    return payload


class JevDecisionProvider(DecisionProvider):
    name = DecisionProviderName.JEV.value

    def __init__(
        self,
        settings: DecisionEngineSettings,
        *,
        client: JevClient | None = None,
        circuit: CircuitBreaker | None = None,
        cost_resolver: CostResolver | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._cost_resolver = cost_resolver
        self._circuit = circuit or CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            recovery_timeout=settings.circuit_recovery_seconds,
        )

    @property
    def model(self) -> str:
        """Modelo configurado para producción (observabilidad)."""
        return self._settings.jev_model

    def effective_model(self, request_id=None) -> str:
        """Modelo efectivo del request: producción o candidato/canary."""
        return self._settings.jev_model_for(request_id)

    async def _resolve_cost(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> DecisionCost:
        """Pricing Registry primero; settings legacy solo si el registry falla."""
        if int(prompt_tokens or 0) <= 0 and int(completion_tokens or 0) <= 0:
            return DecisionCost(
                amount=0.0, provider=JEV_PROVIDER, model=model
            )
        try:
            if self._cost_resolver is not None:
                result = self._cost_resolver(
                    provider=JEV_PROVIDER,
                    model=model,
                    prompt_tokens=int(prompt_tokens or 0),
                    completion_tokens=int(completion_tokens or 0),
                )
                if inspect.isawaitable(result):
                    result = await result
                return result
            return await resolve_cost(
                provider=JEV_PROVIDER,
                model=model,
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                legacy_per_1k=self._settings.estimated_cost_per_1k,
            )
        except Exception as exc:  # noqa: BLE001 — costo nunca rompe el juicio
            logger.warning("JEV cost resolution failed", error=str(exc)[:200])
            return DecisionCost(
                amount=0.0, provider=JEV_PROVIDER, model=model
            )

    def _client_or_raise(self) -> JevClient:
        if self._client is not None:
            return self._client
        if not self._settings.jev_configured:
            raise JevTransportError("JEV API key missing")
        try:
            import importlib.util

            if importlib.util.find_spec("typesafe_sdk") is not None:
                return SdkJevClient(
                    api_key=self._settings.jev_api_key,
                    base_url=self._settings.jev_base_url,
                )
        except Exception:  # noqa: BLE001
            pass
        return HttpJevClient(
            base_url=self._settings.jev_base_url,
            api_key=self._settings.jev_api_key,
        )

    async def decide(self, context: DecisionContext) -> RoutingDecision:
        started = time.perf_counter()
        questions = build_routing_questions(context.available_capabilities)
        state = context.sanitized_state()
        model = self.effective_model(context.request_id)
        try:
            payload = await self._circuit.call(
                "jev.system_one",
                lambda: self._client_or_raise().system_one(
                    state=state,
                    questions=questions,
                    model=model,
                    timeout=self._settings.jev_timeout_seconds,
                ),
            )
        except CircuitBreakerOpenError as exc:
            raise JevTransportError("JEV circuit open") from exc
        except JevTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise JevTransportError(str(exc)[:200]) from exc

        answers = payload.get("answers") if isinstance(payload, dict) else None
        if not isinstance(answers, dict):
            raise JevTransportError("JEV invalid response: answers")
        decision = _from_answers(answers, self._settings, context)
        usage = payload.get("usage") if isinstance(payload, dict) else {}
        if isinstance(usage, dict):
            decision.prompt_tokens = int(usage.get("input_tokens") or 0)
            decision.completion_tokens = int(usage.get("output_tokens") or 0)
        cost = await self._resolve_cost(
            model=model,
            prompt_tokens=decision.prompt_tokens,
            completion_tokens=decision.completion_tokens,
        )
        decision.estimated_cost = cost.amount
        decision.metadata["cost_source"] = cost.source
        decision.metadata["cost_kind"] = cost.cost_kind
        decision.latency_ms = (time.perf_counter() - started) * 1000
        decision.metadata["model"] = model
        decision.metadata["model_role"] = (
            "canary" if model != self._settings.jev_model else "production"
        )
        decision.metadata["questions"] = list(questions.keys())
        decision.raw_answers = {
            key: _public_answer(val) for key, val in answers.items()
        }
        return decision

    async def judge(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomic System One questions that are not capability routing."""
        started = time.perf_counter()
        try:
            payload = await self._circuit.call(
                "jev.system_one",
                lambda: self._client_or_raise().system_one(
                    state=state,
                    questions=questions,
                    model=self._settings.jev_model,
                    timeout=self._settings.jev_timeout_seconds,
                ),
            )
        except CircuitBreakerOpenError as exc:
            raise JevTransportError("JEV circuit open") from exc
        except JevTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise JevTransportError(str(exc)[:200]) from exc
        if not isinstance(payload, dict) or "answers" not in payload:
            raise JevTransportError("JEV invalid response: answers")
        model = str(payload.get("model") or self._settings.jev_model)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        cost = await self._resolve_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return {
            **payload,
            "provider": JEV_PROVIDER,
            "model": model,
            "estimated_cost": cost.amount,
            "cost_source": cost.source,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _public_answer(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"value": str(raw)[:200]}
    out: dict[str, Any] = {"type": raw.get("type")}
    for key in ("choice", "score", "noul", "confidence"):
        if key in raw:
            out[key] = raw[key]
    probs = raw.get("probabilities")
    if isinstance(probs, dict):
        out["probabilities"] = {str(k): float(v) for k, v in list(probs.items())[:16]}
    return out


def _from_answers(
    answers: dict[str, Any],
    settings: DecisionEngineSettings,
    context: DecisionContext,
) -> RoutingDecision:
    cap_ans = answers.get("capability") or {}
    capability = str(cap_ans.get("choice") or "knowledge.answer")
    if capability not in context.available_capabilities:
        # Invalid option: do not execute; composite will fallback.
        raise JevTransportError(f"JEV capability not available: {capability}")
    choice_conf = float(cap_ans.get("confidence") or 0.0)
    probs = cap_ans.get("probabilities") or {}
    alternatives = tuple(
        k
        for k, _ in sorted(
            ((str(k), float(v)) for k, v in probs.items() if str(k) != capability),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    )

    domain = str((answers.get("domain") or {}).get("choice") or "")
    score_ans = answers.get("complexity") or {}
    score = float(score_ans.get("score") or 1.0)
    score_conf = float(score_ans.get("confidence") or choice_conf)
    complexity = ComplexityLevel(complexity_from_score(score))
    needs_knowledge = noul_is_yes(
        noul_from_answer(answers.get("needs_private_knowledge"), 0.0),
        settings.noul_yes,
    )
    needs_reasoning = noul_is_yes(
        noul_from_answer(answers.get("needs_complex_reasoning"), 0.0),
        settings.noul_yes,
    )
    needs_action = noul_is_yes(
        noul_from_answer(answers.get("needs_action"), 0.0),
        settings.noul_yes,
    )

    noul_values = [
        noul_from_answer(answers.get(key), 0.5)
        for key in (
            "needs_private_knowledge",
            "needs_complex_reasoning",
            "needs_action",
        )
    ]
    if any(
        noul_is_uncertain(v, settings.noul_yes, settings.noul_no) for v in noul_values
    ):
        choice_conf = min(choice_conf, (settings.high_confidence + settings.low_confidence) / 2)
    # Choice confidence is the primary axis (official docs). Score confidence
    # stays in metadata; it is not blended into routing confidence.
    confidence = min(1.0, max(0.0, choice_conf))

    needs_agent = capability.startswith("agent.")
    needs_workflow = capability.startswith("workflow.")
    needs_tool = capability.startswith("tool.") or (
        needs_action and not capability.startswith("knowledge.")
        and not capability.startswith("database.")
        and capability not in {"respond_directly", "llm.reason", "llm.generate"}
    )
    if capability in {"llm.reason", "respond_directly", "llm.generate"}:
        needs_knowledge = False

    risk = RiskLevel.HIGH if needs_tool else RiskLevel.MEDIUM if needs_action else RiskLevel.LOW
    return RoutingDecision(
        intent=domain or capability,
        capability=capability,
        complexity=complexity,
        needs_knowledge=needs_knowledge,
        needs_agent=needs_agent,
        needs_workflow=needs_workflow,
        needs_tool=needs_tool,
        needs_reasoning=needs_reasoning or capability == "llm.reason",
        risk=risk,
        confidence=confidence,
        provider=DecisionProviderName.JEV.value,
        alternatives=alternatives,
        resolved=True,
        metadata={
            "domain": domain,
            "complexity_score": score,
            "complexity_confidence": round(score_conf, 4),
            "noul_certainty": round(
                min(noul_certainty(v) for v in noul_values), 4
            ),
        },
        raw_answers={"requested_capability": capability},
    )
