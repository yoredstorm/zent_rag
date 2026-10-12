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
        assert ADAPTIVE_ENGINE_KEYS == {"plan", "quality", "evidence", "attempts"}

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
        pattern = re.compile(r'adaptive\["(?:plan|quality|evidence|attempts)"\]\s*=')
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
            "escrituras directas de claves engine-native fuera de la proyección "
            f"(usar _adaptive_write): {offenders}"
        )
