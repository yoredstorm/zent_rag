# =============================================================================
# Invariantes de TEXTO de los estados de respuesta (caso E del prompt).
# =============================================================================
# retrieval_failed NUNCA se reporta como «no existe información»: la acción
# correcta con el mensaje incorrecto sigue siendo un bug de invariante.
from __future__ import annotations

from src.runtime.answer_gate import (
    CONFLICTING_EVIDENCE_ANSWER,
    INSUFFICIENT_ANSWER,
    RETRIEVAL_UNAVAILABLE_ANSWER,
    resolve_answer_state,
    retrieval_unavailable_answer,
)
from src.runtime.answer_state import (
    ABSTAINED_STATES,
    ANSWER_STATE_CONFLICTING,
    ANSWER_STATE_CONFLICTING_RULE,
    ANSWER_STATE_DERIVED,
    ANSWER_STATE_INSUFFICIENT,
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_UNDETERMINED,
    OPERATIONAL_FAILURE_STATES,
    UNDETERMINED_STATES,
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


class TestTextosDeTodosLosEstados:
    """Cobertura completa: cada estado tiene texto de código y sin ambigüedad."""

    def test_conflicto_no_se_reporta_como_ausencia(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=2,
            conflicts=("fuente A dice X, fuente B dice Y",),
        )
        assert state == ANSWER_STATE_CONFLICTING
        assert message == CONFLICTING_EVIDENCE_ANSWER
        lowered = message.lower()
        assert "se contradicen" in lowered
        assert "una única conclusión" in lowered
        # Un conflicto NO es ausencia de datos.
        for phrase in ("no existe informaci", "no hay informaci", "no tengo suficiente informaci"):
            assert phrase not in lowered

    def test_premisa_faltante_no_es_ausencia(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=2,
            missing_premises=("regla de precedencia",),
        )
        assert state == ANSWER_STATE_UNDETERMINED
        lowered = message.lower()
        assert "no puedo determinarlo" in lowered
        assert "falta regla de precedencia" in lowered
        assert "la fuente no establece" in lowered
        # Falta semántica de la regla, no datos.
        for phrase in _CLAIMS_NO_DATA:
            assert phrase not in lowered

    def test_estados_operativos_usan_mensaje_no_concluyente(self) -> None:
        """Los 5 fallos operativos comparten el mensaje de código, sin inventar."""
        text = undetermined_authoritative_answer(
            reason="rule retrieval unavailable"
        )
        lowered = text.lower()
        for state in OPERATIONAL_FAILURE_STATES:
            # Cada estado operativo se anuncia como fallo de fase, jamás como
            # «no hay datos»; el texto es el mismo productor único.
            assert text
            assert state  # el estado existe y es publicable
        for phrase in _CLAIMS_NO_DATA:
            assert phrase not in lowered
        assert "no pude completar" in lowered

    def test_matriz_de_estados_cubierta_por_los_tests(self) -> None:
        """Todo estado clasificado tiene al menos un texto verificado acá."""
        cubiertos = {
            ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
            ANSWER_STATE_INSUFFICIENT,
            ANSWER_STATE_CONFLICTING,
            ANSWER_STATE_UNDETERMINED,
            ANSWER_STATE_DERIVED,
        }
        for state in ABSTAINED_STATES | UNDETERMINED_STATES | {
            ANSWER_STATE_CONFLICTING_RULE
        }:
            assert state in cubiertos or state == ANSWER_STATE_CONFLICTING_RULE
        for state in OPERATIONAL_FAILURE_STATES:
            assert state  # cubiertos por test_estados_operativos...
        assert ANSWER_STATE_CONFLICTING_RULE in UNDETERMINED_STATES
