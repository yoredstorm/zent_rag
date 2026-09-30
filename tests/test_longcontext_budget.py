# =============================================================================
# Long-Context Fase 1 — presupuesto adaptativo, registry y empaquetado
# =============================================================================
# TEST 4: consulta simple arranca en tiers chicos (no consume 100K).
# TEST 8: 500K disponibles no se usan si la evidencia completa temprano
#         (el tope lo decide el engine; acá se verifica que el presupuesto no
#         empuja el contexto hacia arriba por sí solo).
# TEST 10: modelo 128K nunca se supera, ni con maximum_quality.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.budget import compute_context_budget, with_profile
from src.rag.longcontext.packager import (
    PRIORITY_BACKGROUND,
    PRIORITY_MUST_KEEP,
    ContextPackager,
)
from src.rag.longcontext.registry import resolve_model_capability
from src.rag.longcontext.settings import LongContextSettings


def _settings(**overrides) -> LongContextSettings:
    params = {
        "mode": "active",
        "default_context_window": 32000,
        "output_reserve": 2048,
        "system_reserve": 3000,
        "tool_reserve": 1500,
        "safety_margin": 2048,
    }
    params.update(overrides)
    return LongContextSettings(**params)


def _chunk(texto: str, score: float = 0.5, **metadata: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content=texto,
        score=score,
        metadata=metadata,
    )


class TestLongContextSettings:
    def test_shadow_should_apply(self) -> None:
        assert LongContextSettings(mode="shadow").should_apply(uuid4()) is True

    def test_off_should_not_apply(self) -> None:
        assert LongContextSettings(mode="off").should_apply(uuid4()) is False

    def test_invalid_profile_falls_back_to_balanced(self) -> None:
        settings = LongContextSettings(profile="bogus")
        assert settings.effective_profile == "balanced"


class TestModelRegistry:
    def test_builtin_known_model(self) -> None:
        cap = resolve_model_capability("gpt-4.1")
        assert cap.context_window == 1_047_576
        assert cap.supports_long_context is True
        assert cap.source == "builtin"

    def test_litellm_provider_prefix_matches(self) -> None:
        cap = resolve_model_capability("openai/gpt-4o-mini")
        assert cap.context_window == 128_000

    def test_config_override_wins(self) -> None:
        cap = resolve_model_capability(
            "modelo-raro",
            overrides={"modelo-raro": 999_000},
        )
        assert cap.context_window == 999_000
        assert cap.source == "config"

    def test_unknown_model_uses_configured_default(self) -> None:
        cap = resolve_model_capability("modelo-raro", default_window=65_536)
        assert cap.context_window == 65_536
        assert cap.source == "default"

    def test_never_assumes_1m(self) -> None:
        cap = resolve_model_capability("modelo-raro", default_window=32_000)
        assert cap.context_window == 32_000


class TestAdaptiveBudget:
    def test_small_start_tier_for_simple_question(self) -> None:
        budget = compute_context_budget(model="gpt-4.1", settings=_settings())
        assert budget.target_tokens(budget.start_tier) in (4096, 8192)
        assert budget.usable_context <= 1_047_576

    def test_usable_context_subtracts_reserves(self) -> None:
        budget = compute_context_budget(model="gpt-4o-mini", settings=_settings())
        expected = 128_000 - (2048 + 3000 + 1500 + 2048)
        assert budget.usable_context == expected

    def test_conversation_tokens_shrink_usable(self) -> None:
        base = compute_context_budget(model="gpt-4o-mini", settings=_settings())
        convo = compute_context_budget(
            model="gpt-4o-mini",
            settings=_settings(),
            conversation_tokens=10_000,
        )
        assert convo.usable_context == base.usable_context - 10_000

    def test_model_128k_never_exceeded(self) -> None:
        settings = _settings(profile="maximum_quality")
        budget = compute_context_budget(model="gpt-4o-mini", settings=settings)
        assert budget.usable_context < 128_000
        assert budget.target_tokens(budget.max_tier) <= budget.usable_context
        assert budget.clamp(500_000) == budget.usable_context

    def test_request_and_tenant_limits_apply(self) -> None:
        budget = compute_context_budget(
            model="gpt-4.1",
            settings=_settings(),
            request_limit=16_000,
            tenant_limit=64_000,
        )
        assert budget.hard_limit == 16_000
        assert budget.usable_context <= 16_000

    def test_escalation_stops_at_max_tier(self) -> None:
        budget = compute_context_budget(model="gpt-4o-mini", settings=_settings())
        index = budget.start_tier
        visits = 0
        while True:
            nxt = budget.escalated(index)
            if nxt is None:
                break
            index = nxt
            visits += 1
            assert visits <= 12
        assert budget.target_tokens(index) <= budget.usable_context

    def test_economy_expands_less_than_balanced(self) -> None:
        economy = compute_context_budget(
            model="gpt-4.1", settings=_settings(profile="economy")
        )
        balanced = compute_context_budget(
            model="gpt-4.1", settings=_settings(profile="balanced")
        )
        assert economy.max_tier <= balanced.max_tier
        assert economy.policy.max_expansions < balanced.policy.max_expansions

    def test_maximum_quality_gain_zero_but_bounded(self) -> None:
        budget = compute_context_budget(
            model="gpt-4.1", settings=_settings(profile="maximum_quality")
        )
        assert budget.policy.gain_min == 0.0
        assert budget.max_tier <= len(budget.tiers) - 1
        assert budget.usable_context <= budget.hard_limit

    def test_profile_override_recomputes_policy(self) -> None:
        settings = _settings()
        budget = compute_context_budget(model="gpt-4.1", settings=settings)
        tuned = with_profile(budget, settings, "economy")
        assert tuned.profile == "economy"
        assert tuned.policy.max_expansions < budget.policy.max_expansions


class TestContextPackager:
    def test_must_keep_first_even_with_low_score(self) -> None:
        exacto = RetrievalChunk(
            document_id=uuid4(),
            content="El patrón &&&F aplica.",
            score=0.0,
            metadata={"must_keep": "true"},
        )
        alto = _chunk("contenido de apoyo", score=0.99)
        result = ContextPackager().pack(
            [alto, exacto], budget_tokens=100
        )
        assert result.blocks[0].chunk.document_id == exacto.document_id
        assert result.blocks[0].priority == PRIORITY_MUST_KEEP

    def test_exact_duplicates_deduped(self) -> None:
        texto = "línea repetida idéntica en dos fragmentos del corpus"
        result = ContextPackager().pack(
            [_chunk(texto), _chunk(texto)], budget_tokens=1000
        )
        assert len(result.blocks) == 1
        assert result.deduped == 1

    def test_near_duplicates_deduped_within_scope(self) -> None:
        fuente = {"source_id": "s1"}
        a = _chunk(
            "el byte 105 define la aplicación de la tarifa base por clase",
            **fuente,
        )
        b = _chunk(
            "el byte 105 define la aplicación de tarifa base por clase",
            **fuente,
        )
        result = ContextPackager().pack([a, b], budget_tokens=1000)
        assert len(result.blocks) == 1
        assert result.deduped == 1

    def test_section_reconstruction_prefers_single_section(self) -> None:
        left = _chunk(
            "4.6.2 Fee Application\nEl byte 105 indica si la tarifa",
            parent_id="p1",
            chunk_index="0",
            source_id="s1",
        )
        right = _chunk(
            "la tarifa se aplica a la clase",
            parent_id="p1",
            chunk_index="1",
            source_id="s1",
        )
        result = ContextPackager().pack([left, right], budget_tokens=1000)
        assert result.reconstructed == 1
        assert len(result.blocks) == 1
        assert "4.6.2" in result.blocks[0].chunk.content
        assert result.blocks[0].chunk.metadata.get("reconstructed") == "true"

    def test_background_dropped_before_support(self) -> None:
        apoyo = _chunk("contenido relevante de apoyo", score=0.9)
        fondo = _chunk("x" * 400, score=0.0)
        result = ContextPackager().pack([apoyo, fondo], budget_tokens=50)
        ids = {block.chunk.document_id for block in result.blocks}
        assert apoyo.document_id in ids
        assert fondo.document_id not in ids
        assert result.blocks[0].priority != PRIORITY_BACKGROUND

    def test_metadata_preserved_per_block(self) -> None:
        chunk = _chunk(
            "contenido",
            chunk_id="c1",
            source_id="s1",
            filename="doc.pdf",
            page_start="7",
        )
        result = ContextPackager().pack([chunk], budget_tokens=1000)
        meta = result.blocks[0].metadata
        assert meta["chunk_id"] == "c1"
        assert meta["filename"] == "doc.pdf"
        assert meta["page"] == "7"
