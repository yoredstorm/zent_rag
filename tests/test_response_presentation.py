# =============================================================================
# Experiencia de lectura — «una explicación humana bien editada».
# =============================================================================
# Regresión de PRESENTACIÓN (caso ATPCO «categoría 31 y byte 105»): la respuesta
# era correcta pero salía como una pared de texto: bloques largos, valores
# explicados en una sola frase, limitaciones por obligación, conceptos mezclados.
#
# Las pruebas evalúan CARACTERÍSTICAS de la respuesta (forma, capas, formato,
# límites declarados), no textos completos: el contenido lo escribe el modelo.
#
# Principios que estas pruebas protegen:
#   1. Correcto no significa legible.
#   2. Toda evidencia recuperada puede ser verdadera, pero no toda merece
#      aparecer en la respuesta.
#   3. Una idea principal por bloque visual.
#   4. La estructura sigue la pregunta, no un template fijo.
#   5. Presentation nunca cambia hechos.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.entities import RetrievalChunk
from src.core.domain.response import (
    DETAIL_BRIEF,
    DETAIL_DEEP,
    DETAIL_DETAILED,
    DETAIL_NORMAL,
    SECTION_DIRECT_ANSWER,
    SECTION_KEY_VALUES,
    SECTION_LIMITATIONS,
    ResponseProfile,
)
from src.intelligence.response.blueprints import (
    DIRECT_FACT,
    TECHNICAL_EXPLANATION,
    get_blueprint,
)
from src.intelligence.response.contract import (
    compose_contract,
    normalize_answer_text,
    normalize_markdown_escapes,
    normalize_sources_block,
    prompt_block,
    strip_section_labels,
)
from src.intelligence.response.entities import asked_concepts, ungrounded_hierarchy_claims
from src.intelligence.response.presentation import (
    LAYER_ANSWER,
    LAYER_CONCEPTS,
    LAYER_DETAIL,
    LAYER_LIMITS,
    LAYER_PRACTICAL,
    PresentationPolicy,
    build_presentation_policy,
    refresh_contract_presentation,
)
from src.intelligence.response.selector import select_blueprint
from src.intelligence.response.wiring import compose_for_request

PREGUNTA = "cuéntame sobre la categoría 31 y sobre el byte 105"

#: Evidencia del caso real (recortada): definición del campo y sus 5 valores.
EVIDENCIA_BYTE_105 = """Section 4.6.2
Fee Application (byte 105)

Once processing has determined the change fee amount, the data in the Fee
Application field (byte 105) will specify how to assess the change fee.

Value 1: From among all changed fare components, apply the highest change fee.
Value 2: From among all fare components, changed and unchanged, apply the highest change fee.
Value 3: Apply the change fee from the first changed fare component.
Value 4: Apply the sum of all change fees from all changed fare components.
Value 5: Apply the highest change fee from the fare components changed in this transaction.
"""

#: Material secundario: correcto, recuperado, pero no pedido por la pregunta.
EVIDENCIA_SECUNDARIA = """Section 4.2 Record 0
ALT GEN and Footnotes apply to the whole category 31 record set.
Record 3 permutations are validated against the major subcategory.

Category 31 defines voluntary changes to a ticketed fare.
"""


def _chunk(content: str, *, title: str, section: tuple[str, ...] = (), score: float = 0.6):
    return RetrievalChunk(
        document_id="00000000-0000-0000-0000-0000000000aa",
        content=content,
        score=score,
        metadata={
            "source_id": "00000000-0000-0000-0000-0000000000bb",
            "title": title,
            "section_path": list(section) or None,
        },
    )


def _policy(**overrides) -> PresentationPolicy:
    """Caso real: se recuperaron varios fragmentos y la respuesta usa unos pocos."""
    params = dict(
        question=PREGUNTA,
        evidence_text=EVIDENCIA_BYTE_105 + "\n\n" + EVIDENCIA_SECUNDARIA,
        evidence_titles=("Cat31_dapp_C.pdf", "Rec2_Cat10_dapp_C.pdf"),
        selected_count=4,
        omitted_count=4,
    )
    params.update(overrides)
    return build_presentation_policy(**params)


_POLICY_KEYS = {
    "question",
    "detail",
    "evidence_text",
    "evidence_titles",
    "selected_count",
    "omitted_count",
    "missing_information",
    "unresolved",
    "source_conflict",
}


def _contract(**overrides):
    selection = select_blueprint(question=overrides.get("question", PREGUNTA))
    policy = overrides.get("presentation")
    if policy is None:
        policy = _policy(**{k: v for k, v in overrides.items() if k in _POLICY_KEYS})
    return compose_contract(
        question=overrides.get("question", PREGUNTA),
        selection=selection,
        presentation=policy,
        **{
            key: value
            for key, value in overrides.items()
            if key in {"unresolved", "missing_information", "source_conflict", "profile"}
        },
    )


# ---------------------------------------------------------------------------
# §1, §3 — La regresión: el prompt empujaba la pared de texto
# ---------------------------------------------------------------------------


def test_repro_el_prompt_ya_no_prohibe_estructurar_la_respuesta() -> None:
    """La contradicción original: habilitar headings/bullets y pedir «una sola
    explicación conectada, no son listas de puntos» con tope duro de encabezados."""
    block = prompt_block(_contract())

    # Lo que producía la pared de texto ya no está.
    assert "no son secciones rotuladas ni una lista de puntos" not in block
    assert "no más de dos o tres" not in block
    # Y en su lugar hay un ritmo explícito por capas.
    assert "capa 1" in block.lower()
    assert "una idea por" in block.lower()
    # Los encabezados son adaptativos: el presupuesto lo fija el caso.
    assert "encabezados" in block.lower()
    assert str(_policy().headings_budget) in block


def test_repro_limitaciones_no_se_piden_por_obligacion() -> None:
    """`technical_explanation` traía `limitations` fijo: se escribía siempre."""
    assert SECTION_LIMITATIONS not in get_blueprint(TECHNICAL_EXPLANATION).sections
    contract = _contract()
    assert contract.show_limitations is False
    assert SECTION_LIMITATIONS not in contract.sections
    block = prompt_block(contract)
    assert "no agregues una sección de límites" in block.lower()


def test_limitaciones_si_son_materiales() -> None:
    contract = _contract(missing_information=("el valor 4 no está en las fuentes",))
    assert contract.show_limitations is True
    assert SECTION_LIMITATIONS in contract.sections
    assert "el valor 4 no está en las fuentes" in prompt_block(contract)


# ---------------------------------------------------------------------------
# §4, §5 — Ritmo de la información por capas
# ---------------------------------------------------------------------------


def test_ritmo_por_capas_ordenado_y_sin_huecos() -> None:
    policy = _policy()
    assert policy.layers[0] == LAYER_ANSWER
    assert policy.layers[-1] == LAYER_PRACTICAL
    assert LAYER_CONCEPTS in policy.layers
    assert LAYER_DETAIL in policy.layers
    # La capa de límites sólo entra cuando es material.
    assert LAYER_LIMITS not in policy.layers
    assert LAYER_LIMITS in _policy(missing_information=("falta X",)).layers


def test_dato_simple_no_lleva_capas_de_mas() -> None:
    policy = build_presentation_policy(question="¿Cuál es el código de Carrier?")
    assert policy.multi_concept is False
    assert policy.headings_budget <= 1
    assert policy.layers == (LAYER_ANSWER, LAYER_PRACTICAL) or policy.layers[0] == LAYER_ANSWER
    assert LAYER_CONCEPTS not in policy.layers


# ---------------------------------------------------------------------------
# §6, §11 — Conceptos múltiples y relevancia para la respuesta
# ---------------------------------------------------------------------------


def test_multi_concepto_separa_categoria_31_y_byte_105() -> None:
    policy = _policy()
    assert policy.multi_concept is True
    assert policy.concepts == ("categoría 31", "byte 105")
    # Dos conceptos piden al menos un encabezado por concepto (más el de valores).
    assert policy.headings_budget >= 3
    block = prompt_block(_contract())
    assert "cada concepto con su propio encabezado" in block.lower()


def test_relevancia_para_la_respuesta_deja_afuera_lo_secundario() -> None:
    """Record 0, ALT GEN y Footnotes son ciertos, pero no son la respuesta."""
    policy = _policy(
        evidence_text=EVIDENCIA_BYTE_105 + "\n\n" + EVIDENCIA_SECUNDARIA,
        evidence_titles=("Cat31_dapp_C.pdf", "Rec2_Cat10_dapp_C.pdf"),
        selected_count=3,
        omitted_count=2,
    )
    assert policy.secondary_count >= 1
    assert policy.content_omitted == 2
    block = prompt_block(_contract(presentation=policy))
    assert "no expliques el material secundario" in block.lower()
    # La evidencia sigue en el run: la política sólo decide qué se explica.
    assert policy.to_public_dict()["content_omitted"] == 2


def test_conceptos_genericos_sin_hardcodear_dominio() -> None:
    assert asked_concepts("cuéntame sobre reembolsos y garantías") == (
        "reembolsos",
        "garantías",
    )
    policy = build_presentation_policy(question="cuéntame sobre reembolsos y garantías")
    assert policy.multi_concept is True


# ---------------------------------------------------------------------------
# §8, §9, §10 — Enumeraciones, encabezados y blueprint
# ---------------------------------------------------------------------------


def test_cinco_valores_piden_lista_no_una_frase() -> None:
    policy = _policy()
    assert policy.needs_list is True
    assert policy.enumeration_count >= 5
    block = prompt_block(_contract())
    assert "viñetas" in block.lower() or "lista" in block.lower()
    assert SECTION_KEY_VALUES in get_blueprint(TECHNICAL_EXPLANATION).sections


def test_los_valores_pueden_ir_en_tabla_si_la_comparacion_ayuda() -> None:
    """El default no veta tablas: el blueprint decide cuándo aportan (§7)."""
    contract = _contract(profile=ResponseProfile(use_tables=True))
    assert contract.formatting["table"] is True
    assert "tabla" in prompt_block(contract).lower()
    vetado = _contract(profile=ResponseProfile(use_tables=False))
    assert vetado.formatting["table"] is False
    assert "no usar: tablas" in prompt_block(vetado)


def test_encoder_budget_crece_con_la_complejidad_no_con_un_tope_fijo() -> None:
    simple = build_presentation_policy(question="¿qué es el record 4?")
    compuesto = build_presentation_policy(
        question="cuéntame sobre la categoría 31 y el byte 105",
        evidence_text=EVIDENCIA_BYTE_105,
    )
    profundo = build_presentation_policy(
        question="explícame a fondo la categoría 31 y el byte 105 y sus valores",
        evidence_text=EVIDENCIA_BYTE_105,
        detail=DETAIL_DEEP,
    )
    assert simple.headings_budget < compuesto.headings_budget
    assert compuesto.headings_budget <= profundo.headings_budget


# ---------------------------------------------------------------------------
# §13 — Presentation no cambia hechos: nada de jerarquías inventadas
# ---------------------------------------------------------------------------


def test_jerarquia_de_valores_inventada_se_detecta() -> None:
    respuesta = (
        "El byte 105 define cómo aplicar el cargo. "
        "La jerarquía de valores, de mayor a menor prioridad, es: 3, 2, 5, 4, 1."
    )
    flagged = ungrounded_hierarchy_claims(respuesta, EVIDENCIA_BYTE_105)
    assert flagged, "una jerarquía no dicha por la fuente debe quedar marcada"


def test_jerarquia_respaldada_por_la_fuente_no_se_marca() -> None:
    evidencia = (
        EVIDENCIA_BYTE_105
        + "\nValues are evaluated in priority order: the system applies the "
        "highest priority value first.\n"
    )
    respuesta = "Los valores se evalúan en orden de prioridad según la fuente."
    assert ungrounded_hierarchy_claims(respuesta, evidencia) == []


def test_el_prompt_prohibe_convertir_una_lista_en_jerarquia() -> None:
    block = prompt_block(_contract())
    assert "no conviertas" in block.lower()
    assert "jerarquía" in block.lower() or "prioridad" in block.lower()


# ---------------------------------------------------------------------------
# §14, §15 — Estructura del caso byte 105 y cierre conversacional
# ---------------------------------------------------------------------------


def test_estructura_objetivo_del_caso_byte_105() -> None:
    contract = _contract()
    block = prompt_block(contract)
    # Respuesta primero, conceptos separados, valores enumerados, práctica al final.
    assert block.index("capa 1") < block.index("capa 2") < block.index("capa 3")
    assert "categoría 31" in block  # los conceptos pedidos viajan al prompt
    assert "byte 105" in block
    # El cierre conversacional es opcional y nace del contenido.
    assert "ofrecé una continuación" in block.lower()
    assert "¿hay algo más" not in block.lower()


def test_cierre_solo_cuando_hay_continuacion_natural() -> None:
    con_material = _policy(omitted_count=3, evidence_text=EVIDENCIA_BYTE_105 + EVIDENCIA_SECUNDARIA)
    sin_material = build_presentation_policy(question="¿cuál es el código de Carrier?")
    assert con_material.followup_allowed is True
    assert sin_material.followup_allowed is False
    assert "ofrecé una continuación" not in prompt_block(_contract(presentation=sin_material)).lower()


def test_el_perfil_por_defecto_ya_es_legible() -> None:
    """La buena experiencia por defecto no depende de configurar un preset."""
    contract = compose_contract(
        question=PREGUNTA,
        profile=ResponseProfile(),
        selection=select_blueprint(question=PREGUNTA),
        presentation=_policy(),
    )
    assert contract.detail in {DETAIL_NORMAL, DETAIL_DETAILED}
    assert contract.formatting["headings"] is True
    assert contract.formatting["bullets"] is True
    assert contract.formatting["bold_key_concepts"] is True
    # La tabla no se veta por defecto: la habilitan los casos comparables.
    assert contract.formatting["table"] is True
    assert contract.evidence["citations_required"] is True
    assert contract.preserve_domain_terms is True
    block = prompt_block(contract)
    assert "negritas" in block.lower()
    assert "cita la fuente" in block.lower()


def test_perfil_conciso_sigue_siendo_conciso() -> None:
    from src.intelligence.response.profile import RESPONSE_PROFILE_PRESETS

    contract = compose_contract(
        question="¿Cuál es el código de Carrier?",
        profile=RESPONSE_PROFILE_PRESETS["concise"],
        selection=select_blueprint(question="¿Cuál es el código de Carrier?"),
    )
    assert contract.detail == DETAIL_BRIEF
    assert contract.sections == (SECTION_DIRECT_ANSWER,)
    assert "no usar: encabezados, tablas" in prompt_block(contract)


# ---------------------------------------------------------------------------
# §16 — Markdown: los escapes del modelo no llegan al usuario
# ---------------------------------------------------------------------------


def test_escapado_de_markdown_se_normaliza() -> None:
    crudo = "\\*\\*Categoría 31\\*\\* define los cambios voluntarios. \\_Nota\\_ final."
    limpio, corregidos = normalize_markdown_escapes(crudo)
    assert "**Categoría 31**" in limpio
    assert "\\*" not in limpio
    assert corregidos == 6
    # Idempotente y sin tocar texto legítimo.
    otra_vez, corregidos_otra_vez = normalize_markdown_escapes(limpio)
    assert otra_vez == limpio and corregidos_otra_vez == 0
    assert normalize_markdown_escapes("Ruta C:\\Users\\demo")[0] == "Ruta C:\\Users\\demo"


def test_la_higiene_de_respuesta_normaliza_y_reporta() -> None:
    result = normalize_answer_text("\\*\\*Fee Application\\*\\* decide el cargo.")
    assert result.text == "**Fee Application** decide el cargo."
    assert result.markdown_escapes_fixed == 4
    assert result.labels_stripped == 0
    # Sigue quitando los rótulos internos del contrato.
    rotulado = "**direct_answer:** El byte 105 es Fee Application."
    assert strip_section_labels(rotulado)[0] == "El byte 105 es Fee Application."


# ---------------------------------------------------------------------------
# §17 — Fuentes: separadas y legibles, nunca concatenadas
# ---------------------------------------------------------------------------


def test_bloque_de_fuentes_concatenado_se_ordena_como_lista() -> None:
    texto = (
        "El byte 105 es Fee Application [1].\n\n"
        "**Fuentes**Cat31_dapp_C.pdfRec2_Cat10_dapp_C.pdf"
    )
    limpio, cambiado = normalize_sources_block(
        texto, titles=("Cat31_dapp_C.pdf", "Rec2_Cat10_dapp_C.pdf")
    )
    assert cambiado is True
    assert "- Cat31_dapp_C.pdf" in limpio
    assert "- Rec2_Cat10_dapp_C.pdf" in limpio
    assert "Cat31_dapp_C.pdfRec2" not in limpio


def test_fuentes_ya_legibles_no_se_tocan() -> None:
    texto = "El byte 105 es Fee Application [1].\n\n**Fuentes**\n- Cat31_dapp_C.pdf"
    limpio, cambiado = normalize_sources_block(texto, titles=("Cat31_dapp_C.pdf",))
    assert cambiado is False
    assert limpio == texto


def test_el_prompt_pide_citas_inline_y_no_una_lista_final() -> None:
    block = prompt_block(_contract())
    assert "no escribas una sección «fuentes»" in block.lower()


# ---------------------------------------------------------------------------
# §18, §19 — El gate de presentación como editor
# ---------------------------------------------------------------------------


def test_taxonomia_de_presentacion_ampliada() -> None:
    from src.runtime.answer_gate import (
        PRESENTATION_REVISION_REASONS,
        REVISION_REASON_FEEDBACK,
    )

    for reason in (
        "wall_of_text",
        "poor_chunking",
        "buried_answer",
        "irrelevant_detail",
        "bad_enumeration_format",
        "unnecessary_limitations",
    ):
        assert reason in REVISION_REASON_FEEDBACK
        assert reason in PRESENTATION_REVISION_REASONS
        assert reason not in {"missing_evidence", "unsupported_claim"}


def test_wall_of_text_pide_revision_nunca_abstencion() -> None:
    from src.runtime.answer_gate import judge_answer

    class _Editor:
        async def judge(self, *, state, questions, context=None):
            return {
                "model": "jev-editor",
                "answers": {
                    "answer_grounded": {"type": "noul", "noul": 0.95},
                    "answer_complete": {"type": "noul", "noul": 0.9},
                    "answer_quality": {"type": "score", "score": 2.0},
                    "structure": {"type": "score", "score": 1.0},
                    "revision_reason": {"type": "choice", "choice": "wall_of_text"},
                },
            }

    import asyncio

    from src.core.domain.adaptive import EvidenceItem

    result = asyncio.run(
        judge_answer(
            engine=_Editor(),
            mode="on",
            user_request=PREGUNTA,
            draft="Un bloque enorme.",
            evidence=[
                EvidenceItem(
                    source_type="qdrant",
                    content=EVIDENCIA_BYTE_105,
                    title="Cat31_dapp_C.pdf",
                )
            ],
            settings=object(),
        )
    )
    assert result.verdict == "revise"
    assert result.grounding_verdict == "SUPPORTED"
    assert result.presentation_verdict == "needs_revision"
    assert result.presentation_revision_reason == "wall_of_text"
    assert "párrafo" in result.feedback.lower() or "bloques" in result.feedback.lower()


def test_el_step_del_gate_expone_el_motivo_de_presentacion() -> None:
    from src.runtime.answer_gate import AnswerGateResult

    step = AnswerGateResult(
        verdict="revise",
        mode="on",
        provider="jev",
        presentation_revision_reason="buried_answer",
    ).to_step()
    assert step["presentation_revision_reason"] == "buried_answer"


# ---------------------------------------------------------------------------
# §20 — Batería de escenarios (comportamiento, no texto exacto)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caso,pregunta,kwargs,check",
    [
        (
            "A: ¿qué es X?",
            "¿qué es la categoría 31?",
            {},
            lambda c, p: c.detail in {DETAIL_BRIEF, DETAIL_NORMAL}
            and c.formatting.get("table") is False
            and SECTION_LIMITATIONS not in c.sections,
        ),
        (
            "B: X y Y",
            "cuéntame sobre la categoría 31 y sobre el byte 105",
            {"evidence_text": EVIDENCIA_BYTE_105},
            lambda c, p: p.multi_concept and p.headings_budget >= 3,
        ),
        (
            "C: campo con 5 valores",
            "¿qué significa el byte 105?",
            {"evidence_text": EVIDENCIA_BYTE_105},
            lambda c, p: p.needs_list and SECTION_KEY_VALUES in c.sections,
        ),
        (
            "D: simple con evidencia secundaria",
            "¿qué es la categoría 31?",
            {
                "evidence_text": EVIDENCIA_BYTE_105 + EVIDENCIA_SECUNDARIA,
                "omitted_count": 4,
            },
            lambda c, p: p.content_omitted == 4 and p.secondary_count >= 1,
        ),
        (
            "E: evidencia completa",
            "cuéntame sobre la categoría 31 y sobre el byte 105",
            {"evidence_text": EVIDENCIA_BYTE_105},
            lambda c, p: c.show_limitations is False
            and SECTION_LIMITATIONS not in c.sections,
        ),
        (
            "F: evidencia parcial",
            "cuéntame sobre la categoría 31 y sobre el byte 105",
            {"missing_information": ("el byte 105 no aparece",)},
            lambda c, p: c.show_limitations is True and SECTION_LIMITATIONS in c.sections,
        ),
    ],
)
def test_bateria_de_escenarios(caso, pregunta, kwargs, check) -> None:
    policy = build_presentation_policy(
        question=pregunta,
        evidence_text=kwargs.get("evidence_text", ""),
        selected_count=2,
        omitted_count=kwargs.get("omitted_count", 0),
        missing_information=kwargs.get("missing_information", ()),
        detail=DETAIL_DETAILED,
    )
    contract = compose_contract(
        question=pregunta,
        selection=select_blueprint(question=pregunta),
        presentation=policy,
        missing_information=kwargs.get("missing_information", ()),
    )
    assert check(contract, policy), caso


def test_wiring_expone_la_politica_en_el_contrato_publico() -> None:
    """§21: el flujo muestra qué se explicó y qué quedó afuera, sin scores."""
    import asyncio

    plan = asyncio.run(
        compose_for_request(
            question=PREGUNTA,
            mode="rules",
            presentation=build_presentation_policy(
                question=PREGUNTA,
                evidence_text=EVIDENCIA_BYTE_105,
                selected_count=3,
                omitted_count=5,
            ),
        )
    )
    public = plan.to_public_dict()
    presentation = public["contract"]["presentation"]
    assert presentation["concepts"] == ["categoría 31", "byte 105"]
    assert presentation["content_selected"] == 3
    assert presentation["content_omitted"] == 5
    assert presentation["layers"]


def test_refresh_de_presentacion_conserva_el_contrato() -> None:
    """El contrato se compone antes del retrieval: la política se enriquece al
    llegar la evidencia sin perder blueprint, perfil ni detalle."""
    contract = _contract()
    enriquecida = build_presentation_policy(
        question=PREGUNTA,
        evidence_text=EVIDENCIA_BYTE_105 + EVIDENCIA_SECUNDARIA,
        evidence_titles=("Cat31_dapp_C.pdf",),
        selected_count=2,
        omitted_count=3,
    )
    actualizado = refresh_contract_presentation(contract, enriquecida)
    assert actualizado.blueprint == contract.blueprint
    assert actualizado.detail == contract.detail
    assert actualizado.presentation["content_omitted"] == 3
    assert actualizado.presentation["needs_list"] is True


def test_chunks_del_motor_tambien_alimentan_la_politica() -> None:
    chunks = [
        _chunk(EVIDENCIA_BYTE_105, title="Cat31_dapp_C.pdf", section=("4.6.2",)),
        _chunk(EVIDENCIA_SECUNDARIA, title="Rec2_Cat10_dapp_C.pdf"),
    ]
    policy = build_presentation_policy(
        question=PREGUNTA,
        evidence_text="\n".join(chunk.content for chunk in chunks),
        evidence_titles=tuple(str((chunk.metadata or {}).get("title")) for chunk in chunks),
        selected_count=len(chunks),
    )
    assert policy.multi_concept is True
    assert policy.needs_list is True
    assert "categoría 31" in policy.concepts


def test_direct_fact_no_recibe_ritmo_largo() -> None:
    selection = select_blueprint(question="¿Cuál es el código de Carrier?")
    assert selection.blueprint == DIRECT_FACT
    contract = compose_contract(question="¿Cuál es el código de Carrier?", selection=selection)
    assert contract.sections == (SECTION_DIRECT_ANSWER,)
    assert contract.layers[0] == LAYER_ANSWER
    assert "capa 3" not in prompt_block(contract)
