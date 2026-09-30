# =============================================================================
# Adaptive loop — soft limits, unidades, stop conditions, tenant y paquete
# =============================================================================
# Cubre lo que hace que el bucle sea usable en producción:
#   - headroom: una unidad completa entra aunque supere el soft tier
#   - integridad: tabla/nota/sección no se parten arbitrariamente
#   - stop conditions: confidence, racha de redundancia, costo, no_more_sources
#   - complejidad inicial desde el plan (es un inicio, no un límite)
#   - timeline y headroom para «Ver flujo»
#   - overrides por tenant y paquete final de generación
#   - cache de run (no repetir barridos) y escalación de modelo por incertidumbre
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.adaptive import EvidenceItem, EvidenceQuality
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.longcontext.engine import (
    STOP_CONFIDENCE,
    STOP_REDUNDANT_STREAK,
    AdaptiveLongContextEngine,
)
from src.rag.longcontext.expansion import (
    ExactAnchorExpansion,
    Expansion,
    ExpansionCache,
    ExpansionContext,
)
from src.rag.longcontext.package import (
    allow_model_escalation,
    build_generation_package,
)
from src.rag.longcontext.packager import ContextPackager
from src.rag.longcontext.settings import (
    LongContextSettings,
    settings_from_org,
    start_tier_for_complexity,
)
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("11111111-1111-1111-1111-111111111111")


def _chunk(texto: str, score: float = 0.5, **metadata: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=texto, score=score, metadata=metadata
    )


def _settings(**overrides) -> LongContextSettings:
    params = {"mode": "active", "default_context_window": 32000}
    params.update(overrides)
    return LongContextSettings(**params)


# -----------------------------------------------------------------------------
# Soft limits y unidades semánticas
# -----------------------------------------------------------------------------
class TestSoftBudgetAndUnits:
    def test_section_kept_whole_with_headroom(self) -> None:
        """Sección de 150 tok con soft 100 y hard 200: entra completa."""
        section = _chunk(
            "x" * 600,
            retrieval="section_reconstructed",
            parent_id="p1",
            score=0.4,
        )
        result = ContextPackager().pack(
            [section],
            budget_tokens=100,
            hard_budget_tokens=200,
            preserve_units=True,
        )
        assert result.used_tokens == 150
        assert len(result.blocks) == 1
        assert result.blocks[0].unit_type == "section"
        assert result.overflow_tokens == 50  # headroom declarado, no oculto

    def test_section_dropped_without_headroom(self) -> None:
        section = _chunk(
            "x" * 600,
            retrieval="section_reconstructed",
            parent_id="p1",
            score=0.4,
        )
        result = ContextPackager().pack(
            [section],
            budget_tokens=100,
            hard_budget_tokens=100,
            preserve_units=True,
        )
        assert result.blocks == []
        assert result.used_tokens == 0

    def test_table_unit_preserved(self) -> None:
        tabla = _chunk(
            "Campo | Valor\nByte 105 | Fee application\n" + "y" * 400,
            parent_id="t1",
            score=0.3,
        )
        result = ContextPackager().pack(
            [tabla], budget_tokens=50, hard_budget_tokens=150, preserve_units=True
        )
        assert len(result.blocks) == 1
        assert result.blocks[0].unit_type == "table"
        assert "Byte 105" in result.blocks[0].chunk.content

    def test_big_section_still_capped_by_hard(self) -> None:
        enorme = _chunk(
            "z" * 4000,
            retrieval="section_reconstructed",
            parent_id="p9",
            score=0.2,
        )
        result = ContextPackager().pack(
            [enorme], budget_tokens=100, hard_budget_tokens=200, preserve_units=True
        )
        assert result.blocks == []  # 1000 tok no entran ni con headroom


# -----------------------------------------------------------------------------
# Stop conditions
# -----------------------------------------------------------------------------
class TestStopConditions:
    @pytest.mark.asyncio
    async def test_confidence_threshold_stops(self) -> None:
        """Evaluador inseguro pero confiado (score alto) cierra el bucle."""
        chunk = _chunk("consulta simple respondida en el fragmento.")

        async def check(chunks):
            return EvidenceQuality(
                sufficient=False,
                score=0.92,
                reason="judge-inseguro-pero-confiado",
                has_evidence=bool(chunks),
            )

        engine = AdaptiveLongContextEngine(
            retrieve_fn=_empty_retrieve,
            settings=_settings(requirement_min=0.0, confidence_min=0.7),
            strategies=[],
            evidence_check=check,
        )
        result = await engine.run(
            query=_query("consulta simple"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[chunk]),
        )
        assert result.stop_reason == STOP_CONFIDENCE
        assert result.timeline[-1]["reason"] == STOP_CONFIDENCE

    @pytest.mark.asyncio
    async def test_redundant_streak_stops(self) -> None:
        """Dos expansiones sin gain real cortan el bucle."""
        inicial = _chunk("contenido base sobre la regla", source_id="s1")
        redundante_1 = _chunk("contenido base sobre la regla", source_id="s1")
        redundante_2 = _chunk("contenido base sobre la regla", source_id="s1")

        async def check(chunks):
            return EvidenceQuality(
                sufficient=False, score=0.2, reason="test", has_evidence=bool(chunks)
            )

        engine = AdaptiveLongContextEngine(
            retrieve_fn=_empty_retrieve,
            settings=_settings(requirement_min=0.0, gain_min=0.05, redundant_streak=2),
            strategies=[
                _Strategy("dup1", "repite", [redundante_1]),
                _Strategy("dup2", "repite", [redundante_2]),
            ],
            evidence_check=check,
        )
        result = await engine.run(
            query=_query("regla"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[inicial]),
        )
        assert result.stop_reason == STOP_REDUNDANT_STREAK
        assert len(result.expansions) == 2

    @pytest.mark.asyncio
    async def test_cost_limit_caps_context(self) -> None:
        inicial = _chunk("x" * 2000)
        engine = AdaptiveLongContextEngine(
            retrieve_fn=_empty_retrieve,
            settings=_settings(requirement_min=0.0),
            strategies=[],
            evidence_check=None,
        )
        result = await engine.run(
            query=_query("consulta costosa"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[inicial]),
            cost_limit_tokens=8000,
        )
        assert result.budget.cost_limit_tokens == 8000
        assert result.budget.hard_limit <= 8000
        assert result.final_tokens <= result.budget.usable_context


# -----------------------------------------------------------------------------
# Complejidad inicial, timeline y headroom
# -----------------------------------------------------------------------------
class TestInitialBudgetAndTimeline:
    def test_start_tier_by_complexity(self) -> None:
        settings = _settings()
        assert start_tier_for_complexity(settings, path="fast") == 0
        assert start_tier_for_complexity(
            settings, path="standard", complexity="technical_reasoning"
        ) >= settings.tier_index_for_tokens(32768)
        assert start_tier_for_complexity(
            settings, path="standard", multi_document=True
        ) >= settings.tier_index_for_tokens(32768)

    def test_tenant_initial_budget_wins(self) -> None:
        settings = settings_from_org(
            {"adaptive_context": {"initial_budget": 64000}},
            _settings(),
        )
        assert start_tier_for_complexity(settings, path="fast") == (
            settings.tier_index_for_tokens(65536)
        )

    @pytest.mark.asyncio
    async def test_technical_question_starts_bigger_but_can_grow(self) -> None:
        chunk = _chunk("explicación completa del caso técnico y su regla")
        engine = AdaptiveLongContextEngine(
            retrieve_fn=_empty_retrieve,
            settings=_settings(requirement_min=0.0),
            strategies=[],
            evidence_check=None,
        )
        result = await engine.run(
            query=_query("explicación del caso"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[chunk]),
            complexity="technical_reasoning",
        )
        first_hop = result.timeline[0]
        assert result.budget.target_tokens(first_hop["tier"]) >= 32768

    @pytest.mark.asyncio
    async def test_timeline_and_headroom_reported(self) -> None:
        inicial = _chunk("base")
        extra = _chunk("detalle nuevo que amplía el contexto de la regla")

        async def check(chunks):
            joined = "\n".join(c.content for c in chunks)
            return EvidenceQuality(
                sufficient="detalle nuevo" in joined,
                score=0.8,
                reason="test",
                has_evidence=True,
            )

        engine = AdaptiveLongContextEngine(
            retrieve_fn=_empty_retrieve,
            settings=_settings(requirement_min=0.0),
            strategies=[_Strategy("extra", "faltaba detalle", [extra])],
            evidence_check=check,
        )
        result = await engine.run(
            query=_query("detalle"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[inicial]),
        )
        public = result.to_public_dict()
        assert public["timeline"][0]["step"] == "initial_retrieval"
        assert public["timeline"][-1]["reason"] == result.stop_reason
        tokens = [step["tokens"] for step in public["timeline"]]
        assert tokens == sorted(tokens)
        assert public["headroom_tokens"] == (
            result.budget.usable_context - result.final_tokens
        )


# -----------------------------------------------------------------------------
# Tenant, caché y paquete final
# -----------------------------------------------------------------------------
class TestTenantAndCache:
    def test_tenant_overrides(self) -> None:
        base = _settings()
        tuned = settings_from_org(
            {
                "adaptive_context": {
                    "quality_profile": "quality",
                    "soft_budget_levels": [8000, 16000, 32000],
                    "min_information_gain": 0.2,
                    "max_expansion_rounds": 2,
                    "preserve_semantic_units": False,
                    "reserve_output_tokens": 1024,
                }
            },
            base,
        )
        assert tuned.effective_profile == "quality"
        assert tuned.tiers == (8000, 16000, 32000)
        assert tuned.gain_min == pytest.approx(0.2)
        assert tuned.max_expansions == 2
        assert tuned.preserve_semantic_units is False
        assert tuned.output_reserve == 1024

    def test_tenant_disabled_shuts_loop(self) -> None:
        tuned = settings_from_org(
            {"adaptive_context": {"enabled": False}}, _settings()
        )
        assert tuned.enabled() is False

    @pytest.mark.asyncio
    async def test_cache_avoids_rescanning_needles(self) -> None:
        calls: list[list[str]] = []

        class _Store:
            async def scan_text_literal(self, *, needles, **kwargs):
                calls.append(list(needles))
                return RetrievalContext(
                    chunks=[_chunk("La máscara &&&F aplica al fare basis")]
                )

        cache = ExpansionCache()
        strategy = ExactAnchorExpansion(_Store())
        context = ExpansionContext(
            query=_query("consulta &&&F"),
            chunks=[],
            missing_needles=("&&&F",),
            cache=cache,
        )
        first = await strategy.expand(context)
        second = await strategy.expand(context)
        assert first.chunks
        assert second.chunks == []
        assert calls == [["&&&F"]]  # el segundo intento no re-barrió

    def test_model_escalation_gate(self) -> None:
        assert allow_model_escalation("retrieval") is False
        assert allow_model_escalation("reasoning") is True
        assert allow_model_escalation("none") is True


class TestGenerationPackage:
    def _views(self):
        from src.rag.longcontext.views import build_query_views

        return build_query_views("consulta si FCLAS &&&F acepta QNNF0SME")

    def test_package_ready_and_citation_map(self) -> None:
        views = self._views()
        selection = _FakeSelection()
        package = build_generation_package(
            question="consulta si FCLAS &&&F acepta QNNF0SME",
            views=views,
            requirements=None,
            selection=selection,
        )
        public = package.to_public_dict()
        assert public["ready"] is True
        assert public["mode"] == "generate_full"
        assert public["examples"] == ["QNNF0SME"]
        assert public["examples_requires_source_match"] is False
        assert public["citation_map"]
        assert public["context_chars"] > 0

    def test_package_with_missing_evidence(self) -> None:
        views = self._views()
        package = build_generation_package(
            question="consulta",
            views=views,
            requirements=None,
            selection=_FakeSelection(),
            extra_missing=("falta la definición del comodín",),
        )
        public = package.to_public_dict()
        assert public["ready"] is False
        assert public["mode"] == "generate_with_limits"
        assert public["missing_evidence"] == ["falta la definición del comodín"]


class _Strategy:
    def __init__(self, name: str, reason: str, chunks: list[RetrievalChunk]) -> None:
        self.name = name
        self.reason = reason
        self._chunks = chunks

    async def expand(self, context) -> Expansion:
        return Expansion(name=self.name, reason=self.reason, chunks=list(self._chunks))


class _FakeSelection:
    def __init__(self) -> None:
        item = EvidenceItem(
            source_type="document",
            content="FCLAS y &&&F documentados en el fare basis",
            score=0.8,
            evidence_id="E1",
            title="manual.pdf",
            page=4,
            citation="[Doc: 1]",
        )
        match = type(
            "Match",
            (),
            {"match": "exact_anchor_match", "chars": 120, "priority": 0},
        )()
        self.items = [item]
        self.matches = [match]


async def _empty_retrieve(spec: dict) -> RetrievalContext:
    return RetrievalContext(chunks=[])


def _query(texto: str) -> RetrievalQuery:
    return RetrievalQuery(
        query=texto,
        organization_id=ORG,
        query_embedding=[0.1, 0.2],
        score_threshold=0.0,
    )
