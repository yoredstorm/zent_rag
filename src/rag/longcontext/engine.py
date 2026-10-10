# =============================================================================
# AdaptiveLongContextEngine — START SMALL, EXPAND, MEASURE, STOP WHEN COMPLETE
# =============================================================================
# No construye un contexto enorme al principio ni manda documentos completos.
# Arranca en el tier chico, mide evidencia (quality + requirements + anchors),
# expande con una estrategia por vuelta, mide information gain y se detiene
# cuando la evidencia alcanza o cuando la expansión ya no aporta.
# El tope final es siempre usable_context del modelo real.
# =============================================================================
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.infrastructure.observability.logging_config import get_logger
from src.rag.longcontext.budget import AdaptiveContextBudget, compute_context_budget
from src.rag.longcontext.context_compiler import (
    CompiledContext,
    compile_context,
)
from src.rag.longcontext.coverage import (
    AnchorCoverage,
    anchor_coverage,
    apply_coverage_to_quality,
    requirements_satisfied,
)
from src.rag.longcontext.expansion import (
    ExpansionCache,
    ExpansionContext,
    ExpansionStrategy,
    RetrieveFn,
    default_strategies,
)
from src.rag.longcontext.information import compute_information_gain, snapshot
from src.rag.longcontext.packager import ContextPackager, PackResult
from src.rag.longcontext.requirement_graph import (
    QueryRequirementGraph,
    build_requirement_graph,
)
from src.rag.longcontext.requirements import (
    EvidenceRequirement,
    RequirementCoverage,
    build_requirements,
    evaluate_requirements,
)
from src.rag.longcontext.settings import (
    LongContextSettings,
    ProfilePolicy,
    start_tier_for_complexity,
)
from src.rag.longcontext.views import QueryViews, build_query_views
from src.rag.retrieval.models import RetrievalQuery

logger = get_logger(__name__)

EvidenceCheck = Callable[[list[RetrievalChunk]], Awaitable[Any]]

_CHARS_PER_TOKEN = 4

STOP_EVIDENCE_INITIAL = "evidence_complete_initial"
STOP_EVIDENCE_COMPLETE = "evidence_complete"
STOP_CONFIDENCE = "confidence_threshold"
STOP_REDUNDANT = "expansion_redundant"
STOP_REDUNDANT_STREAK = "redundant_streak"
STOP_MAX_EXPANSIONS = "max_expansions"
STOP_MAX_TIER = "max_tier_reached"
STOP_NO_STRATEGIES = "strategies_exhausted"
STOP_NO_SOURCES = "no_more_sources"
STOP_COST_LIMIT = "cost_limit_reached"
STOP_LONG_CONTEXT = "long_context_escalated"
STOP_NO_RETRIEVAL = "no_retrieval"


@dataclass(kw_only=True)
class ExpansionRecord:
    index: int
    strategy: str
    reason: str
    tier: int
    context_tokens: int
    added_chunks: int
    added_tokens: int
    gain: dict[str, Any]
    sufficient: bool
    missing_requirements: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "strategy": self.strategy,
            "reason": self.reason,
            "tier": self.tier,
            "context_tokens": self.context_tokens,
            "added_chunks": self.added_chunks,
            "added_tokens": self.added_tokens,
            "information_gain": self.gain,
            "sufficient": self.sufficient,
            "missing_requirements": list(self.missing_requirements[:6]),
        }


@dataclass(kw_only=True)
class LongContextResult:
    retrieved: RetrievalContext
    packed: PackResult
    budget: AdaptiveContextBudget
    requirements: RequirementCoverage
    anchors: AnchorCoverage
    quality: Any | None = None
    expansions: list[ExpansionRecord] = field(default_factory=list)
    stop_reason: str = STOP_EVIDENCE_INITIAL
    initial_tokens: int = 0
    final_tokens: int = 0
    shadow: bool = False
    views: QueryViews | None = None
    #: Crecimiento del contexto para la vista de debug (tokens reales).
    timeline: list[dict[str, Any]] = field(default_factory=list)
    #: Fase 12: grafo de requisitos (qué conocimiento exige la pregunta).
    requirement_graph: QueryRequirementGraph | None = None
    #: Fase 13: contexto compilado estructurado (no chunks concatenados).
    compiled_context: CompiledContext | None = None

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.budget.capability.to_public_dict(),
            "budget": self.budget.to_public_dict(),
            "initial_tokens": self.initial_tokens,
            "final_tokens": self.final_tokens,
            "headroom_tokens": max(0, self.budget.usable_context - self.final_tokens),
            "stop_reason": self.stop_reason,
            "stopped_because": self.stop_reason,
            "timeline": list(self.timeline),
            "anchors": self.anchors.to_public_dict(),
            "requirements": self.requirements.to_public_dict(),
            "expansions": [record.to_public_dict() for record in self.expansions],
            "pack": self.packed.stats(),
            "shadow": self.shadow,
        }
        if self.views is not None:
            payload["query_views"] = self.views.to_public_dict()
        if self.requirement_graph is not None:
            payload["requirement_graph"] = self.requirement_graph.to_public_dict()
        if self.compiled_context is not None:
            payload["compiled_context"] = self.compiled_context.to_public_dict()
        if self.quality is not None and hasattr(self.quality, "to_public_dict"):
            payload["quality"] = self.quality.to_public_dict()
        return payload


class AdaptiveLongContextEngine:
    """Motor de expansión progresiva con presupuesto adaptativo."""

    def __init__(
        self,
        *,
        retrieve_fn: RetrieveFn,
        settings: LongContextSettings,
        store: object | None = None,
        packager: ContextPackager | None = None,
        strategies: list[ExpansionStrategy] | None = None,
        evidence_check: EvidenceCheck | None = None,
    ) -> None:
        self._retrieve = retrieve_fn
        self._settings = settings
        self._store = store
        self._packager = packager or ContextPackager()
        self._strategies = (
            list(strategies)
            if strategies is not None
            else default_strategies(store or _NullStore(), retrieve_fn)
        )
        self._evidence_check = evidence_check

    @property
    def settings(self) -> LongContextSettings:
        return self._settings

    async def run(
        self,
        *,
        query: RetrievalQuery,
        model: str,
        initial: RetrievalContext | None = None,
        system_tokens: int = 0,
        conversation_tokens: int = 0,
        request_limit: int | None = None,
        tenant_limit: int | None = None,
        cost_limit_tokens: int | None = None,
        profile: str | None = None,
        shadow: bool = False,
        complexity: str = "",
        multi_document: bool = False,
        start_tier: int | None = None,
    ) -> LongContextResult:
        settings = self._settings.with_profile(profile) if profile else self._settings
        policy = settings.policy()
        budget = compute_context_budget(
            model=model,
            settings=settings,
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            request_limit=request_limit,
            tenant_limit=tenant_limit,
            cost_limit_tokens=cost_limit_tokens,
        )

        raw = query.query or ""
        views = build_query_views(raw)
        anchors = list(views.anchors)
        entities = list(views.entities)
        requirements = build_requirements(
            raw, anchors, entities, examples=list(views.examples)
        )

        chunks = list(initial.chunks) if initial is not None else []
        if not chunks:
            try:
                fetched = await self._retrieve(
                    {
                        "text": raw,
                        "strategy": query.strategy,
                        "top_k": query.top_k,
                        "exact_needles": list(views.exact_terms),
                        "lexical_terms": list(views.lexical_terms),
                    }
                )
                chunks = list(fetched.chunks)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Initial retrieval for long-context failed", error=str(exc)[:200])
                chunks = []

        # Cache por run: nada de repetir barridos ni fetches ya hechos.
        cache = ExpansionCache(
            seen_document_ids={str(chunk.document_id) for chunk in chunks}
        )
        # La pata exacta del retrieval inicial ya barrió estos needles.
        for needle in query.exact_needles or []:
            value = str(needle or "").strip().lower()
            if value:
                cache.scanned_needles.add(value)

        # Punto de partida según complejidad (PLAN); es un INICIO, no un límite.
        if start_tier is not None:
            tier_index = max(0, min(int(start_tier), len(budget.tiers) - 1))
        else:
            tier_index = start_tier_for_complexity(
                settings, path=complexity, multi_document=multi_document
            )
            tier_index = max(0, min(tier_index, len(budget.tiers) - 1))
        if tier_index > budget.max_tier:
            # Arrancar más arriba no puede bloquear las expansiones siguientes.
            budget = replace(budget, max_tier=tier_index)

        packed, coverage = self._pack_and_measure(
            chunks, budget, tier_index, requirements, anchors
        )
        anchors_cov = anchor_coverage(anchors, packed.chunks)
        quality = await self._check(packed.chunks)
        apply_coverage_to_quality(
            quality, anchors=anchors_cov, requirements=coverage
        )
        initial_tokens = packed.used_tokens
        expansions: list[ExpansionRecord] = []
        timeline: list[dict[str, Any]] = [
            {
                "step": "initial_retrieval",
                "strategy": "retrieval",
                "reason": "contexto inicial según plan",
                "tokens": initial_tokens,
                "delta": 0,
                "tier": tier_index,
            }
        ]

        if self._sufficient(quality, coverage, policy) and self._initial_base_ok(
            packed.chunks
        ):
            timeline.append(
                {
                    "step": "stop",
                    "reason": STOP_EVIDENCE_INITIAL,
                    "tokens": packed.used_tokens,
                    "delta": 0,
                    "tier": tier_index,
                }
            )
            req_graph = build_requirement_graph(
                question=raw,
                requirements=requirements,
                chunks=packed.chunks,
                runtime_inputs=list(views.examples),
            )
            compiled = compile_context(
                question=raw,
                chunks=packed.chunks,
                requirements=requirements,
                requirement_graph=req_graph,
                user_inputs=list(views.examples),
            )
            return LongContextResult(
                retrieved=RetrievalContext(
                    chunks=chunks,
                    query_embedding=query.query_embedding,
                    retrieval_latency_ms=0.0,
                ),
                packed=packed,
                budget=budget,
                requirements=coverage,
                anchors=anchors_cov,
                quality=quality,
                stop_reason=STOP_EVIDENCE_INITIAL,
                initial_tokens=initial_tokens,
                final_tokens=packed.used_tokens,
                shadow=shadow,
                views=views,
                timeline=timeline,
                requirement_graph=req_graph,
                compiled_context=compiled,
            )

        used_strategies: set[str] = set()
        pending = list(self._strategies)
        stop_reason = STOP_NO_STRATEGIES
        low_gain_streak = 0
        any_added = False
        before = snapshot(
            packed.chunks,
            anchors=anchors,
            entities=entities,
            requirements=requirements,
            coverage=coverage,
        )

        while len(expansions) < max(0, policy.max_expansions):
            strategy = pending.pop(0) if pending else None
            if strategy is not None and strategy.name in used_strategies:
                continue
            added_chunks: list[RetrievalChunk] = []
            added_tokens = 0
            expansion_reason = strategy.reason if strategy else "long context mode"
            expansion_name = strategy.name if strategy else "long_context_mode"

            if strategy is not None:
                used_strategies.add(strategy.name)
                context = ExpansionContext(
                    query=query,
                    chunks=chunks,
                    anchors=anchors,
                    missing_needles=coverage.missing_needles,
                    round_index=len(expansions) + 1,
                    limit=_expansion_chunks(self._settings),
                    max_points=_expansion_points(self._settings),
                    max_ms=_expansion_ms(self._settings),
                    cache=cache,
                )
                try:
                    expansion = await strategy.expand(context)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Expansion strategy failed",
                        strategy=strategy.name,
                        error=str(exc)[:200],
                    )
                    continue
                known = {_chunk_identity(chunk) for chunk in chunks}
                added_chunks = [
                    chunk
                    for chunk in expansion.chunks
                    if _chunk_identity(chunk) not in known
                ]
                if not added_chunks:
                    continue
                added_tokens = sum(
                    max(1, len(chunk.content or "") // _CHARS_PER_TOKEN)
                    for chunk in added_chunks
                )
                chunks = chunks + added_chunks
                any_added = True

            # Cada expansión con contenido nuevo sube un tier (hasta el tope).
            next_tier = budget.escalated(tier_index)
            if next_tier is not None:
                tier_index = next_tier
            packed, coverage = self._pack_and_measure(
                chunks, budget, tier_index, requirements, anchors
            )
            anchors_cov = anchor_coverage(anchors, packed.chunks)
            quality = await self._check(packed.chunks)
            apply_coverage_to_quality(
                quality, anchors=anchors_cov, requirements=coverage
            )
            after = snapshot(
                packed.chunks,
                anchors=anchors,
                entities=entities,
                requirements=requirements,
                coverage=coverage,
            )
            gain = compute_information_gain(
                before, after, added_tokens=added_tokens, gain_min=0.0
            )
            sufficient = self._sufficient(quality, coverage, policy)
            confident = self._confident(quality, coverage, policy, settings)
            record = ExpansionRecord(
                index=len(expansions) + 1,
                strategy=expansion_name,
                reason=expansion_reason,
                tier=tier_index,
                context_tokens=packed.used_tokens,
                added_chunks=len(added_chunks),
                added_tokens=added_tokens,
                gain=gain.to_public_dict(),
                sufficient=sufficient or confident,
                missing_requirements=tuple(
                    requirement.description for requirement in coverage.unanswered
                ),
            )
            expansions.append(record)
            timeline.append(
                {
                    "step": f"expansion_{record.index}",
                    "strategy": expansion_name,
                    "reason": expansion_reason,
                    "tokens": packed.used_tokens,
                    "delta": packed.used_tokens - timeline[-1]["tokens"],
                    "tier": tier_index,
                    "information_gain": round(gain.score, 4),
                }
            )
            before = after

            if sufficient:
                stop_reason = STOP_EVIDENCE_COMPLETE
                break
            if confident:
                stop_reason = STOP_CONFIDENCE
                break
            if (
                budget.cost_limit_tokens
                and packed.used_tokens >= int(budget.cost_limit_tokens * 0.95)
            ):
                stop_reason = STOP_COST_LIMIT
                break
            low_gain = gain.added_tokens > 0 and gain.score <= policy.gain_min
            if low_gain:
                low_gain_streak += 1
            else:
                low_gain_streak = 0
            if low_gain_streak >= max(1, int(settings.redundant_streak)):
                stop_reason = STOP_REDUNDANT_STREAK
                break
            if low_gain and pending:
                # Estrategia sin aporte: se prueba la siguiente, sin cortar.
                continue
            if tier_index >= budget.max_tier and not pending:
                stop_reason = STOP_MAX_TIER
                break
        else:
            stop_reason = STOP_MAX_EXPANSIONS

        if (
            stop_reason in (STOP_NO_STRATEGIES, STOP_REDUNDANT, STOP_MAX_EXPANSIONS)
            and tier_index < budget.max_tier
        ):
            # Long-context mode: todavía hay presupuesto y la evidencia sigue
            # incompleta; se re-empaqueta lo ya recuperado en tiers mayores.
            while tier_index < budget.max_tier:
                next_tier = budget.escalated(tier_index)
                if next_tier is None:
                    break
                tier_index = next_tier
                packed, coverage = self._pack_and_measure(
                    chunks, budget, tier_index, requirements, anchors
                )
                anchors_cov = anchor_coverage(anchors, packed.chunks)
                quality = await self._check(packed.chunks)
                apply_coverage_to_quality(
                    quality, anchors=anchors_cov, requirements=coverage
                )
                if self._sufficient(quality, coverage, policy):
                    stop_reason = STOP_LONG_CONTEXT
                    break
                if self._confident(quality, coverage, policy, settings):
                    stop_reason = STOP_CONFIDENCE
                    break
            if stop_reason == STOP_REDUNDANT and tier_index >= budget.max_tier:
                stop_reason = STOP_MAX_TIER

        if not any_added and stop_reason in (
            STOP_NO_STRATEGIES,
            STOP_MAX_TIER,
            STOP_REDUNDANT,
            STOP_REDUNDANT_STREAK,
        ):
            # Ninguna fuente nueva: no hay más material relevante que traer.
            stop_reason = STOP_NO_SOURCES

        final, _ = self._pack_and_measure(
            chunks, budget, tier_index, requirements, anchors
        )
        timeline.append(
            {
                "step": "stop",
                "strategy": "",
                "reason": stop_reason,
                "tokens": final.used_tokens,
                "delta": final.used_tokens - timeline[-1]["tokens"],
                "tier": tier_index,
            }
        )
        req_graph = build_requirement_graph(
            question=raw,
            requirements=requirements,
            chunks=final.chunks,
            runtime_inputs=list(views.examples),
        )
        compiled = compile_context(
            question=raw,
            chunks=final.chunks,
            requirements=requirements,
            requirement_graph=req_graph,
            user_inputs=list(views.examples),
        )
        return LongContextResult(
            retrieved=RetrievalContext(
                chunks=chunks,
                query_embedding=query.query_embedding,
                retrieval_latency_ms=0.0,
            ),
            packed=final,
            budget=budget,
            requirements=coverage,
            anchors=anchors_cov,
            quality=quality,
            expansions=expansions,
            stop_reason=stop_reason,
            initial_tokens=initial_tokens,
            final_tokens=final.used_tokens,
            shadow=shadow,
            views=views,
            timeline=timeline,
            requirement_graph=req_graph,
            compiled_context=compiled,
        )

    # ------------------------------------------------------------------
    def _pack_and_measure(
        self,
        chunks: list[RetrievalChunk],
        budget: AdaptiveContextBudget,
        tier_index: int,
        requirements: list[EvidenceRequirement],
        anchors: list[Any],
    ) -> tuple[PackResult, RequirementCoverage]:
        """Empaqueta, mide requirements y protege la evidencia de regla/campo.

        Si un requirement documentable quedó cubierto por fragmentos que aún no
        estaban marcados, se marcan y se re-empaqueta: el rerank y el
        presupuesto no pueden expulsarlos (misma política que MUST_KEEP).
        """
        packed = self._pack(chunks, budget, tier_index, requirements, anchors)
        coverage = evaluate_requirements(requirements, packed.chunks)
        if self._mark_requirement_evidence(chunks, requirements):
            packed = self._pack(chunks, budget, tier_index, requirements, anchors)
            coverage = evaluate_requirements(requirements, packed.chunks)
        return packed, coverage

    @staticmethod
    def _mark_requirement_evidence(
        chunks: list[RetrievalChunk],
        requirements: list[EvidenceRequirement],
        *,
        cap: int = 8,
    ) -> int:
        from src.rag.longcontext.must_keep import (
            is_requirement_evidence,
            mark_requirement_evidence,
        )
        from src.rag.longcontext.requirements import RequirementState

        marked_ids = {
            chunk.document_id for chunk in chunks if is_requirement_evidence(chunk)
        }
        marked = 0
        for requirement in requirements:
            if not requirement.documentable:
                continue
            if requirement.state not in (
                RequirementState.FOUND.value,
                RequirementState.PARTIAL.value,
            ):
                continue
            needles = [
                str(needle).lower() for needle in requirement.needles if str(needle).strip()
            ]
            if not needles:
                continue
            for index, chunk in enumerate(chunks):
                if marked >= cap:
                    return marked
                if chunk.document_id in marked_ids:
                    continue
                content = (chunk.content or "").lower()
                if any(needle in content for needle in needles):
                    chunks[index] = mark_requirement_evidence(
                        chunk, requirement=requirement.id
                    )
                    marked_ids.add(chunk.document_id)
                    marked += 1
        return marked

    # ------------------------------------------------------------------
    def _pack(
        self,
        chunks: list[RetrievalChunk],
        budget: AdaptiveContextBudget,
        tier_index: int,
        requirements: list[EvidenceRequirement],
        anchors: list[Any],
    ) -> PackResult:
        """Soft budget = tier; hard = siguiente tier (headroom de unidades).

        El tope duro real sigue siendo `usable_context` del modelo.
        """
        soft = budget.target_tokens(tier_index)
        next_index = min(tier_index + 1, budget.max_tier)
        next_tokens = budget.target_tokens(next_index)
        headroom = max(
            next_tokens,
            int(soft * (1.0 + float(self._settings.unit_headroom_ratio))),
        )
        hard = min(budget.usable_context, max(soft, headroom))
        return self._packager.pack(
            chunks,
            budget_tokens=soft,
            hard_budget_tokens=hard,
            preserve_units=self._settings.preserve_semantic_units,
            requirements=requirements,
            anchors=anchors,
        )

    def _initial_base_ok(self, chunks: list[RetrievalChunk]) -> bool:
        """La primera pasada no cierra con una base mínima de fragmentos.

        Coverage suficiente con pocos fragmentos no garantiza que el gate
        clásico (scores) vea evidencia: una expansión barata evita una
        abstención por NO_RETRIEVAL aguas abajo.
        """
        minimum = int(getattr(self._settings, "min_initial_chunks", 0) or 0)
        if minimum <= 0:
            return True
        return len(chunks or ()) >= minimum

    async def _check(self, chunks: list[RetrievalChunk]) -> Any | None:
        if self._evidence_check is None:
            return None
        try:
            return await self._evidence_check(chunks)
        except Exception as exc:  # noqa: BLE001 — check best-effort
            logger.warning("Evidence check failed", error=str(exc)[:200])
            return None

    @staticmethod
    def _sufficient(
        quality: Any | None,
        coverage: RequirementCoverage,
        policy: ProfilePolicy,
    ) -> bool:
        if quality is not None and not bool(getattr(quality, "sufficient", False)):
            return False
        if not requirements_satisfied(coverage, policy.requirement_min):
            return False
        return True

    @staticmethod
    def _confident(
        quality: Any | None,
        coverage: RequirementCoverage,
        policy: ProfilePolicy,
        settings: LongContextSettings,
    ) -> bool:
        """Confianza del evaluador >= umbral con requirements duros cubiertos."""
        if quality is None:
            return False
        try:
            score = float(getattr(quality, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return False
        if score < float(settings.confidence_min):
            return False
        return requirements_satisfied(coverage, policy.requirement_min)


def _expansion_chunks(settings: LongContextSettings) -> int:
    value = int(getattr(settings, "expansion_chunks", 0) or 0)
    return value if value > 0 else 6


def _expansion_points(settings: LongContextSettings) -> int:
    value = int(getattr(settings, "expansion_max_points", 0) or 0)
    return value if value > 0 else 6000


def _expansion_ms(settings: LongContextSettings) -> float:
    value = float(getattr(settings, "expansion_max_ms", 0.0) or 0.0)
    return value if value > 0 else 2000.0


def _chunk_identity(chunk) -> tuple[str, str]:
    """Identidad real de chunk (documento + chunk_id/unit_id o contenido)."""
    metadata = getattr(chunk, "metadata", None) or {}
    identity = str(metadata.get("chunk_id") or metadata.get("unit_id") or "")
    if not identity:
        identity = (getattr(chunk, "content", "") or "")[:80]
    return str(getattr(chunk, "document_id", "")), identity


class _NullStore:
    """Store vacío: las estrategias que necesitan store no hacen nada."""


__all__ = [
    "AdaptiveLongContextEngine",
    "ExpansionRecord",
    "LongContextResult",
    "STOP_CONFIDENCE",
    "STOP_COST_LIMIT",
    "STOP_EVIDENCE_COMPLETE",
    "STOP_EVIDENCE_INITIAL",
    "STOP_LONG_CONTEXT",
    "STOP_MAX_EXPANSIONS",
    "STOP_MAX_TIER",
    "STOP_NO_SOURCES",
    "STOP_NO_STRATEGIES",
    "STOP_REDUNDANT",
    "STOP_REDUNDANT_STREAK",
]
