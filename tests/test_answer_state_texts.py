# =============================================================================
# Invariantes de TEXTO de los estados de respuesta (caso E del prompt).
# =============================================================================
# retrieval_failed NUNCA se reporta como «no existe información»: la acción
# correcta con el mensaje incorrecto sigue siendo un bug de invariante.
from __future__ import annotations

from src.runtime.answer_gate import (
    INSUFFICIENT_ANSWER,
    RETRIEVAL_UNAVAILABLE_ANSWER,
    resolve_answer_state,
    retrieval_unavailable_answer,
)
from src.runtime.answer_state import (
    ANSWER_STATE_DERIVED,
    ANSWER_STATE_INSUFFICIENT,
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
    select_answer_state,
)
from src.runtime.deterministic_authority import undetermined_authoritative_answer

#: Frases que afirman ausencia de datos: prohibidas para fallos operativos.
_CLAIMS_NO_DATA = (
    "no existe informaci",
    "no hay informaci",
    "no contiene la informaci",
    "no tengo suficiente informaci",
    "no hay evidencia",
    "las fuentes no contienen",
)


class TestRetrievalUnavailableText:
    def test_no_afirma_ausencia_de_datos(self) -> None:
        text = retrieval_unavailable_answer().lower()
        for phrase in _CLAIMS_NO_DATA:
            assert phrase not in text, f"retrieval_unavailable afirma: {phrase}"

    def test_explica_el_fallo_operativo(self) -> None:
        text = retrieval_unavailable_answer()
        assert "no llegó a ejecutarse" in text
        assert "búsqueda" in text

    def test_causa_se_agrega_sin_reemplazar_el_mensaje(self) -> None:
        text = retrieval_unavailable_answer("timeout del proveedor")
        assert text.startswith(RETRIEVAL_UNAVAILABLE_ANSWER)
        assert "Causa: timeout del proveedor." in text

    def test_es_distinto_de_insuficiencia(self) -> None:
        assert retrieval_unavailable_answer() != INSUFFICIENT_ANSWER
        # La insuficiencia sí puede hablar de falta de evidencia; el fallo
        # operativo no. La inversión es la prohibida.
        for phrase in _CLAIMS_NO_DATA:
            assert phrase not in retrieval_unavailable_answer().lower()


class TestResolveAnswerState:
    def test_retrieval_fallido_sin_evidencia_es_operativo(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            retrieval_reason="429",
            evidence_count=0,
        )
        assert state == ANSWER_STATE_RETRIEVAL_UNAVAILABLE
        assert message == retrieval_unavailable_answer("429")

    def test_retrieval_fallido_con_evidencia_no_es_operativo(self) -> None:
        state, _ = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            evidence_count=3,
        )
        assert state != ANSWER_STATE_RETRIEVAL_UNAVAILABLE

    def test_resultado_determinista_gana_a_fallo_operativo(self) -> None:
        state = select_answer_state(
            has_deterministic_result=True,
            retrieval_failed=True,
            evidence_count=0,
        )
        assert state == ANSWER_STATE_DERIVED

    def test_sin_evidencia_sin_fallo_es_insuficiencia(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=0,
        )
        assert state == ANSWER_STATE_INSUFFICIENT
        assert message == INSUFFICIENT_ANSWER


class TestUndeterminedText:
    def test_no_es_una_conclusion_binaria(self) -> None:
        text = undetermined_authoritative_answer()
        lowered = text.lower()
        assert "no pude completar" in lowered
        assert "no voy a afirmar" in lowered
        for phrase in _CLAIMS_NO_DATA:
            assert phrase not in lowered

    def test_causa_opcional(self) -> None:
        text = undetermined_authoritative_answer("grounding falló")
        assert "Causa: grounding falló." in text
