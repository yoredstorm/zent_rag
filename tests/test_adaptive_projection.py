# =============================================================================
# `adaptive` como proyección — writer único de claves engine-native (Fase C).
# =============================================================================
# Regla: `plan`, `quality`, `evidence`, `attempts` viven en `AgentRunState`
# (mismas referencias) y `adaptive` es proyección legacy. El único writer
# directo permitido es `_adaptive_publish` (la proyección); el resto publica
# por `_adaptive_write` (estado + proyección).
from __future__ import annotations

import re
from pathlib import Path

from src.agents.runtime.orchestrator import (
    ADAPTIVE_ENGINE_KEYS,
    _adaptive_publish,
    _adaptive_write,
)
from src.runtime.run_state import AgentRunState, RunIdentity

ROOT = Path(__file__).resolve().parents[1]


def _state() -> AgentRunState:
    return AgentRunState(identity=RunIdentity(run_id="run-1"))


class TestWriterUnico:
    def test_claves_engine_native_declaradas(self) -> None:
        # Las 4 originales siguen modeladas...
        assert {
            "plan",
            "quality",
            "evidence",
            "attempts",
        } <= ADAPTIVE_ENGINE_KEYS
        # ...y la migración completa cubre planning, preflight, evidencia,
        # decisiones, respuesta y traza.
        for key in (
            "query_views",
            "source_routing",
            "retrieval_failure",
            "anchor_roles",
            "uncertainty",
            "preflight_tier",
            "preflight_action",
            "preflight_model",
            "preflight_extra_round",
            "preflight_model_pinned",
            "llm_skipped",
            "canonical_rules",
            "coverage_gap",
            "passage_selection",
            "passages",
            "ctx_before",
            "ctx_after",
            "long_context_result",
            "long_context",
            "grounded_reasoning_pre",
            "grounded_reasoning",
            "evidence_state",
            "generation_package",
            "rule_retrieval",
            "authority_failure",
            "grounding",
            "citation_validation",
            "derived_guard",
            "answer_state",
            "citations",
            "fallbacks",
            "revision_used",
        ):
            assert key in ADAPTIVE_ENGINE_KEYS

    def test_escribe_estado_y_proyeccion_con_la_misma_referencia(self) -> None:
        adaptive: dict = {}
        state = _state()
        plan = object()
        _adaptive_write(adaptive, state, "plan", plan)
        assert adaptive["plan"] is plan
        assert state.plan.adaptive_plan is plan

        evidence, quality = object(), object()
        _adaptive_write(adaptive, state, "evidence", evidence)
        _adaptive_write(adaptive, state, "quality", quality)
        assert state.evidence.engine_evidence is evidence
        assert state.evidence.engine_quality is quality

    def test_attempts_comparte_la_lista_y_se_muta_in_place(self) -> None:
        adaptive: dict = {"attempts": []}
        state = _state()
        _adaptive_write(adaptive, state, "attempts", adaptive["attempts"])
        adaptive["attempts"].append("intento-1")
        assert state.evidence.retrieval_attempts == ["intento-1"]

    def test_clave_desconocida_solo_proyecta(self) -> None:
        adaptive: dict = {}
        state = _state()
        _adaptive_write(adaptive, state, "otra", 1)
        assert adaptive["otra"] == 1
        assert state.plan.adaptive_plan is None

    def test_mapeos_de_la_migracion_completa(self) -> None:
        adaptive: dict = {}
        state = _state()

        _adaptive_write(adaptive, state, "query_views", {"v": 1})
        assert state.plan.query_views == {"v": 1}
        _adaptive_write(adaptive, state, "preflight_tier", "PACK")
        assert state.plan.preflight["tier"] == "PACK"
        _adaptive_write(adaptive, state, "llm_skipped", True)
        assert state.plan.preflight["llm_skipped"] is True
        _adaptive_write(adaptive, state, "ctx_before", 42)
        assert state.evidence.ctx_before == 42
        _adaptive_write(adaptive, state, "answer_state", "DERIVED_RESULT")
        assert state.answer.public_state == "DERIVED_RESULT"
        _adaptive_write(adaptive, state, "citations", [{"index": 1}])
        assert state.answer.citations_public == [{"index": 1}]
        _adaptive_write(adaptive, state, "revision_used", True)
        assert state.trace.revision_used is True
        fallbacks: list = []
        _adaptive_write(adaptive, state, "fallbacks", fallbacks)
        assert state.trace.fallbacks is fallbacks
        _adaptive_write(adaptive, state, "grounded_reasoning", None)
        assert state.decisions.grounded_public is None
        _adaptive_write(adaptive, state, "evidence_state", {"state": "x"})
        assert state.evidence.canonical_state == {"state": "x"}

    def test_sin_estado_no_rompe(self) -> None:
        adaptive: dict = {}
        _adaptive_write(adaptive, None, "plan", "x")
        assert adaptive["plan"] == "x"


class TestProjection:
    def test_publish_regenera_las_cuatro_claves_desde_el_estado(self) -> None:
        state = _state()
        state.plan.adaptive_plan = {"plan": True}
        state.evidence.engine_evidence = {"evidence": True}
        state.evidence.engine_quality = {"quality": True}
        state.evidence.retrieval_attempts = [{"attempt": 1}]
        adaptive: dict = {}
        _adaptive_publish(state, adaptive)
        assert adaptive["plan"] == {"plan": True}
        assert adaptive["evidence"] == {"evidence": True}
        assert adaptive["quality"] == {"quality": True}
        assert adaptive["attempts"] == [{"attempt": 1}]

    def test_publish_no_pisa_con_none(self) -> None:
        state = _state()
        adaptive = {"plan": "vigente"}
        _adaptive_publish(state, adaptive)
        assert adaptive["plan"] == "vigente"


class TestWritersUnicosEnElRepo:
    def test_solo_la_proyeccion_escribe_las_claves_engine_native(self) -> None:
        keys = "|".join(sorted(ADAPTIVE_ENGINE_KEYS))
        pattern = re.compile(
            rf'adaptive\["(?:{keys})"\]\s*='
            r"|adaptive\.setdefault\("
            r"|adaptive\.update\("
        )
        offenders: list[str] = []
        for path in (ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            anchor = text.find("def _adaptive_publish(")
            end = -1
            if anchor != -1:
                tail = text.find("\ndef ", anchor + 10)
                end = len(text) if tail == -1 else tail
            for match in pattern.finditer(text):
                if anchor != -1 and anchor <= match.start() < end:
                    continue  # la proyección es el writer permitido
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
        assert not offenders, (
            "escrituras directas de claves migradas fuera de la proyección "
            f"(usar _adaptive_write): {offenders}"
        )
