# =============================================================================
# TEST CRÍTICO — la documentación prueba la regla, no el valor del usuario
# =============================================================================
# Pregunta de regresión:
#   "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que el
#    farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
#
# Esperado (contrato de grounding):
#   Record 2  -> entidad contextual (documentable)
#   FCLAS     -> field anchor (documentable)
#   &&&F      -> runtime pattern (exige SEMÁNTICA documentada, no literalidad)
#   QNNF0SME  -> user example (NO exige match en fuentes)
# El pipeline completa la evidencia con la GRAMÁTICA y deja QNNF0SME como input
# para que el motor evalúe el patrón contra ese valor.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.adaptive import EvidenceQuality
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.longcontext.coverage import anchor_coverage, requirements_satisfied
from src.rag.longcontext.engine import STOP_EVIDENCE_COMPLETE, AdaptiveLongContextEngine
from src.rag.longcontext.expansion import Expansion
from src.rag.longcontext.requirements import build_requirements, evaluate_requirements
from src.rag.longcontext.roles import AnchorRole
from src.rag.longcontext.settings import LongContextSettings
from src.rag.longcontext.views import build_query_views
from src.rag.retrieval.models import RetrievalQuery

CRITICAL_QUESTION = (
    "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que "
    "el farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
)

ORG = UUID("11111111-1111-1111-1111-111111111111")

RULE_EVIDENCE = (
    "Record 2: FCLAS indica la clase tarifaria del fare basis. La máscara &&&F "
    "exige que el fare basis tenga la longitud indicada: los caracteres "
    "posteriores a && restringen el tamaño y la posición. El símbolo & "
    "representa una posición alfanumérica; el matching es posicional."
)


def _chunk(texto: str, score: float = 0.5, **metadata: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=texto, score=score, metadata=metadata
    )


def _views():
    return build_query_views(CRITICAL_QUESTION)


class TestCriticalQuestionAnalysis:
    def test_roles_assigned(self) -> None:
        views = _views()
        roles = {
            str(getattr(anchor, "value", "")): str(getattr(anchor, "role", ""))
            for anchor in views.anchors
        }
        assert roles["FCLAS"] == AnchorRole.FIELD_ANCHOR.value
        assert roles["&&&F"] == AnchorRole.RUNTIME_PATTERN.value
        assert roles["QNNF0SME"] == AnchorRole.EXAMPLE_VALUE.value
        assert views.examples == ("QNNF0SME",)
        assert views.runtime_patterns == ("&&&F",)

    def test_contextual_entity_record_2(self) -> None:
        labels = [entity.label for entity in _views().entities]
        assert any("record 2" in label.lower() for label in labels)

    def test_three_channels(self) -> None:
        views = _views()
        assert "&&&F" not in views.semantic  # el embedding no ve la máscara
        assert "FCLAS" in views.semantic
        for term in ("FCLAS", "&&&F", "QNNF0SME"):
            assert term in views.exact_terms
        for term in ("FCLAS", "QNNF0SME"):
            assert term in views.lexical_terms

    def test_requirements_do_not_demand_user_value(self) -> None:
        views = _views()
        requirements = build_requirements(
            CRITICAL_QUESTION,
            list(views.anchors),
            list(views.entities),
            examples=list(views.examples),
        )
        coverage = evaluate_requirements(
            requirements,
            [_chunk(RULE_EVIDENCE, source_id="s1")],
        )
        # La regla, el campo y record 2 están; QNNF0SME no aparece y NO importa.
        assert requirements_satisfied(coverage, 0.6) is True
        assert coverage.examples == ("QNNF0SME",)
        assert "QNNF0SME" not in coverage.missing_needles
        assert coverage.all_hard_found is True

    def test_anchor_coverage_is_role_aware(self) -> None:
        views = _views()
        cov = anchor_coverage(list(views.anchors), [_chunk(RULE_EVIDENCE)])
        # FCLAS documentable; &&&F es runtime pattern (no exige literal);
        # QNNF0SME no entra en el denominador.
        assert cov.requested == 1
        assert cov.found == 1
        assert cov.coverage == 1.0
        assert cov.rule_found == 0
        assert cov.field_found == 1
        assert cov.runtime_patterns == ("&&&F",)
        assert cov.examples == ("QNNF0SME",)

    def test_field_missing_does_block(self) -> None:
        # La contracara: si falta el CAMPO, la evidencia no está completa.
        views = _views()
        requirements = build_requirements(
            CRITICAL_QUESTION,
            list(views.anchors),
            list(views.entities),
            examples=list(views.examples),
        )
        coverage = evaluate_requirements(
            requirements,
            [_chunk("La máscara &&&F exige longitud fija.", source_id="s1")],
        )
        assert requirements_satisfied(coverage, 0.6) is False
        assert any("FCLAS" in needle for needle in coverage.missing_needles)


class TestCriticalQuestionRuntimeGate:
    def test_user_example_does_not_trigger_anchor_gap(self) -> None:
        from src.core.domain.adaptive import EvidenceItem
        from src.runtime.evidence import ACTION_GENERATE, assess_sufficiency

        items = [
            EvidenceItem(source_type="document", content=RULE_EVIDENCE, score=0.8)
        ]
        sufficiency = assess_sufficiency(items, CRITICAL_QUESTION, retrieval_rounds_left=0)

        assert "QNNF0SME" not in sufficiency.missing_anchors
        assert "QNNF0SME" in sufficiency.examples_asked
        assert sufficiency.recommended_action == ACTION_GENERATE
        assert sufficiency.to_public_dict()["examples_requires_source_match"] is False


class _Strategy:
    name = "regla_documentada"
    reason = "faltaba la regla del campo FCLAS"

    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks

    async def expand(self, context) -> Expansion:
        return Expansion(name=self.name, reason=self.reason, chunks=list(self._chunks))


def _checker(needles: tuple[str, ...]):
    async def check(chunks: list[RetrievalChunk]) -> EvidenceQuality:
        joined = "\n".join(chunk.content or "" for chunk in chunks).lower()
        complete = all(needle.lower() in joined for needle in needles)
        return EvidenceQuality(
            sufficient=complete,
            score=0.8 if complete else 0.2,
            reason="critical-test",
            has_evidence=bool(chunks),
        )

    return check


def _engine(strategies) -> AdaptiveLongContextEngine:
    async def _retrieve(spec):  # pragma: no cover
        return RetrievalContext(chunks=[])

    return AdaptiveLongContextEngine(
        retrieve_fn=_retrieve,
        settings=LongContextSettings(mode="active"),
        strategies=strategies,
        evidence_check=_checker(("&&&f",)),
    )


def _query() -> RetrievalQuery:
    return RetrievalQuery(
        query=CRITICAL_QUESTION,
        organization_id=ORG,
        query_embedding=[0.1, 0.2],
        score_threshold=0.0,
    )


class TestCriticalQuestionEngine:
    @pytest.mark.asyncio
    async def test_pipeline_completes_without_example_in_sources(self) -> None:
        inicial = _chunk("Record 2 define los campos del boleto de pasajero.")
        regla = _chunk(RULE_EVIDENCE, source_id="s1")
        engine = _engine([_Strategy([regla])])

        result = await engine.run(
            query=_query(),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[inicial]),
        )

        # La evidencia quedó completa SIN que QNNF0SME exista en las fuentes.
        assert result.stop_reason == STOP_EVIDENCE_COMPLETE
        ids = {chunk.document_id for chunk in result.packed.chunks}
        assert regla.document_id in ids
        assert result.requirements.examples == ("QNNF0SME",)
        assert result.requirements.examples_found == ()
        assert result.requirements.all_hard_found is True
        assert "QNNF0SME" not in result.requirements.missing_needles
        # La máscara viaja intacta en el canal exacto.
        assert result.views is not None
        assert "&&&F" in result.views.exact_terms
        # La evidencia de regla queda marcada como requirement evidence.
        marcados = [
            chunk
            for chunk in result.packed.chunks
            if str((chunk.metadata or {}).get("requirement_evidence") or "").lower()
            == "true"
        ]
        assert marcados, "la regla debe quedar protegida como requirement evidence"

    @pytest.mark.asyncio
    async def test_user_value_never_drives_expansion(self) -> None:
        # Estrategia que sólo traería el valor del usuario (si se buscara):
        solo_valor = _chunk("QNNF0SME aparece en un ejemplo de boleto.")
        inicial = _chunk("Record 2 sin la regla todavía.")
        engine = _engine([_Strategy([solo_valor])])

        result = await engine.run(
            query=_query(),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[inicial]),
        )

        # Aunque la estrategia devolvió QNNF0SME, la evidencia dura sigue
        # incompleta: el sistema NO declara completo por encontrar el valor.
        assert result.stop_reason != STOP_EVIDENCE_COMPLETE
        assert result.requirements.all_hard_found is False
