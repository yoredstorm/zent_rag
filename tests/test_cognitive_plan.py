# =============================================================================
# Cognitive Plan — planificación determinista de necesidades de conocimiento.
# =============================================================================
from __future__ import annotations

import json

from src.runtime.cognitive_plan import KnowledgeNeed, build_cognitive_plan


def test_saludo_no_necesita_retrieval() -> None:
    plan = build_cognitive_plan("Hola, buenos días")
    assert plan.needs == (KnowledgeNeed.NO_RETRIEVAL,)
    assert plan.requires_knowledge is False
    assert plan.steps[0].reason


def test_literal_exacto_activa_exact_lookup() -> None:
    plan = build_cognitive_plan("¿Qué significa el Byte 105 de Category 31?")
    assert KnowledgeNeed.EXACT_LOOKUP in plan.needs
    assert KnowledgeNeed.SEMANTIC_SEARCH in plan.needs
    assert plan.requires_knowledge is True


def test_temporal_y_regla() -> None:
    plan = build_cognitive_plan(
        "¿Qué cambió en la regla X respecto a la versión anterior?"
    )
    assert KnowledgeNeed.TEMPORAL_LOOKUP in plan.needs
    assert KnowledgeNeed.RULE_LOOKUP in plan.needs


def test_comparacion_agregacion_y_cruce_de_documentos() -> None:
    plan = build_cognitive_plan(
        "Compara el total de la columna 7 entre la versión 2024 y 2025"
    )
    assert KnowledgeNeed.COMPARISON in plan.needs
    assert KnowledgeNeed.AGGREGATION in plan.needs
    assert KnowledgeNeed.CROSS_DOCUMENT_REASONING in plan.needs


def test_calculo_y_herramienta_y_memoria() -> None:
    plan = build_cognitive_plan(
        "Calcula el porcentaje y envía un correo; recuerda la conversación anterior"
    )
    assert KnowledgeNeed.CALCULATION in plan.needs
    assert KnowledgeNeed.EXTERNAL_TOOL in plan.needs
    assert KnowledgeNeed.MEMORY in plan.needs


def test_payload_publico_serializable() -> None:
    payload = build_cognitive_plan("¿Aplica la regla 12?").to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["complexity"] in {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert payload["requires_knowledge"] is True
