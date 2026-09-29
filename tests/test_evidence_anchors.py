# =============================================================================
# Evidencia con anchors — suficiencia, clasificación y query refinada
# =============================================================================
# Caso real: la pregunta nombra FCLAS &&&F, la evidencia habla de Record 2 pero
# no de esos tokens. La suficiencia decía «generate» y el generador rellenaba.
from __future__ import annotations

from src.agents.runtime.agent_runtime import (
    _refined_retrieval_query,
    _uncovered_labels,
)
from src.core.domain.adaptive import EvidenceItem
from src.runtime.evidence import (
    ACTION_ANSWER_WITH_LIMITS,
    ACTION_GENERATE,
    ACTION_RETRIEVE_MORE,
    assess_sufficiency,
    classify_item,
    question_needles,
    rank_evidence,
)

PREGUNTA = "¿qué significa FCLAS &&&F en el Record 2?"


def _item(content: str, score: float = 0.5) -> EvidenceItem:
    return EvidenceItem(source_type="document", content=content, score=score)


class TestSuficienciaConAnchors:
    def test_anchors_faltantes_con_rondas_pide_otra_busqueda(self) -> None:
        items = [_item("Record 2 fare class matching overview. Booking code field.")]

        suficiencia = assess_sufficiency(items, PREGUNTA, retrieval_rounds_left=2)

        assert suficiencia.recommended_action == ACTION_RETRIEVE_MORE
        assert suficiencia.reason == "anchor_not_in_evidence"
        assert "sigla FCLAS" in suficiencia.missing_anchors
        assert "mascara &&&F" in suficiencia.missing_anchors
        publico = suficiencia.to_public_dict()
        assert publico["missing_anchors"] == ["sigla FCLAS", "mascara &&&F"]

    def test_anchors_faltantes_sin_rondas_responde_con_limites(self) -> None:
        items = [_item("Record 2 fare class matching overview.")]

        suficiencia = assess_sufficiency(items, PREGUNTA, retrieval_rounds_left=0)

        assert suficiencia.recommended_action == ACTION_ANSWER_WITH_LIMITS
        assert suficiencia.reason == "anchor_not_in_evidence"

    def test_anchors_cubiertos_genera(self) -> None:
        items = [
            _item(
                "Record 2: FCLAS es el campo de fare class. El patrón &&&F exige "
                "F en la cuarta posición del fare basis."
            )
        ]

        suficiencia = assess_sufficiency(items, PREGUNTA, retrieval_rounds_left=0)

        assert suficiencia.recommended_action == ACTION_GENERATE
        assert suficiencia.reason == "exact_entity_match"
        assert suficiencia.missing_anchors == ()

    def test_pregunta_sin_entidades_ni_anchors_mantiene_comportamiento(self) -> None:
        suficiencia = assess_sufficiency([_item("texto general")], "¿cómo funciona?")

        assert suficiencia.recommended_action == ACTION_GENERATE
        assert suficiencia.reason == "no_entities_asked"

    def test_entidad_cubierta_y_anchor_faltante_pide_otra_busqueda(self) -> None:
        items = [_item("Record 2: fare class matching table")]

        suficiencia = assess_sufficiency(items, PREGUNTA, retrieval_rounds_left=1)

        assert suficiencia.recommended_action == ACTION_RETRIEVE_MORE
        assert suficiencia.missing_entities == ()

    def test_sin_evidencia_sigue_absteniendo(self) -> None:
        suficiencia = assess_sufficiency([], PREGUNTA, retrieval_rounds_left=0)

        assert suficiencia.recommended_action == "abstain"


class TestClasificacionConAnchors:
    def test_fragmento_que_cubre_los_anchors_es_exact_anchor_match(self) -> None:
        item = _item("FCLAS: fare class field. Patrón &&&F posicional.")

        assert classify_item(item, PREGUNTA, []) == "exact_anchor_match"

    def test_el_fragmento_de_anchors_gana_al_de_entidad(self) -> None:
        ruido = _item("Record 2 general overview", score=0.9)
        real = _item("FCLAS y &&&F explicados", score=0.1)

        orden = rank_evidence([ruido, real], PREGUNTA)

        assert orden[0][0] is real
        assert orden[0][1] == "exact_anchor_match"
        assert orden[1][1] == "exact_entity_match"

    def test_sin_anchors_la_clasificacion_no_cambia(self) -> None:
        from src.intelligence.response.entities import asked_entities

        item = _item("byte 105 fee application")
        pregunta = "¿qué dice el byte 105?"

        assert (
            classify_item(item, pregunta, asked_entities(pregunta))
            == "exact_entity_match"
        )


class TestNeedlesYQueryRefinada:
    def test_question_needles_incluye_la_mascara(self) -> None:
        needles = question_needles(PREGUNTA)

        assert "&&&F" in needles
        assert any(needle.lower() == "fclas" for needle in needles)

    def test_uncovered_labels_incluye_anchors(self) -> None:
        labels = _uncovered_labels(PREGUNTA, "texto sin nada")

        assert "sigla FCLAS" in labels
        assert "mascara &&&F" in labels

    def test_la_query_refinada_lleva_los_tokens_del_anchor(self) -> None:
        query = _refined_retrieval_query(PREGUNTA, ["sigla FCLAS", "mascara &&&F"])

        assert "FCLAS" in query
        assert "&&&F" in query
