# =============================================================================
# Long-Context Fase 2 — requirements, information gain y expansión progresiva
# =============================================================================
# TEST 4: pregunta simple se detiene con contexto chico.
# TEST 5: la explicación está en el chunk siguiente; el engine expande y la trae.
# TEST 6: la respuesta depende de tabla + nota posterior; recupera ambas.
# TEST 7: pregunta multi-documento; el contexto crece progresivamente.
# TEST 8: 500K disponibles, evidencia completa temprano; no se consumen.
# TEST 9: incompleto en 32K, completo al expandir; escala solo.
# TEST 10: modelo 128K nunca se supera, ni con maximum_quality.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.adaptive import EvidenceQuality
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.longcontext.coverage import anchor_coverage, requirements_satisfied
from src.rag.longcontext.engine import (
    STOP_EVIDENCE_COMPLETE,
    STOP_EVIDENCE_INITIAL,
    AdaptiveLongContextEngine,
)
from src.rag.longcontext.expansion import Expansion
from src.rag.longcontext.information import compute_information_gain, snapshot
from src.rag.longcontext.requirements import (
    RequirementState,
    build_requirements,
    evaluate_requirements,
)
from src.rag.longcontext.settings import LongContextSettings
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("11111111-1111-1111-1111-111111111111")


def _chunk(texto: str, score: float = 0.5, **metadata: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=texto, score=score, metadata=metadata
    )


class _Strategy:
    def __init__(self, name: str, reason: str, chunks: list[RetrievalChunk]) -> None:
        self.name = name
        self.reason = reason
        self._chunks = chunks

    async def expand(self, context) -> Expansion:
        return Expansion(name=self.name, reason=self.reason, chunks=list(self._chunks))


class _Retrieve:
    def __init__(self, results: dict[str, list[RetrievalChunk]] | None = None) -> None:
        self._results = results or {}
        self.calls: list[dict] = []

    async def __call__(self, spec: dict) -> RetrievalContext:
        self.calls.append(spec)
        key = str(spec.get("strategy") or "default")
        return RetrievalContext(chunks=list(self._results.get(key, [])))


def _checker(needles: list[str]):
    async def check(chunks: list[RetrievalChunk]) -> EvidenceQuality:
        joined = "\n".join(chunk.content or "" for chunk in chunks).lower()
        present = sum(1 for needle in needles if needle.lower() in joined)
        sufficient = present == len(needles)
        return EvidenceQuality(
            sufficient=sufficient,
            score=0.9 if sufficient else 0.3,
            reason="test",
            has_evidence=bool(chunks),
        )

    return check


def _always_sufficient():
    async def check(chunks: list[RetrievalChunk]) -> EvidenceQuality:
        return EvidenceQuality(sufficient=True, score=0.9, reason="test", has_evidence=True)

    return check


def _query(texto: str, **overrides) -> RetrievalQuery:
    params = {
        "query": texto,
        "organization_id": ORG,
        "top_k": 10,
        "effective_top_k": 10,
        "score_threshold": 0.0,
        "strategy": "hybrid",
        "query_embedding": [0.1, 0.2],
    }
    params.update(overrides)
    return RetrievalQuery(**params)


def _settings(**overrides) -> LongContextSettings:
    params = {"mode": "active", "default_context_window": 32000}
    params.update(overrides)
    return LongContextSettings(**params)


def _engine(
    *,
    settings: LongContextSettings,
    initial: RetrievalChunk,
    strategies: list[_Strategy],
    check=None,
    retrieve: _Retrieve | None = None,
) -> AdaptiveLongContextEngine:
    return AdaptiveLongContextEngine(
        retrieve_fn=retrieve or _Retrieve(),
        settings=settings,
        strategies=strategies,
        evidence_check=check or _always_sufficient(),
    )


# -----------------------------------------------------------------------------
# Requirements / coverage / gain (unidades)
# -----------------------------------------------------------------------------
class TestRequirements:
    def test_anchor_requirement_separates_found_from_missing(self) -> None:
        query = "consulta si FCLAS &&&F acepta QNNF0SME"
        requirements = build_requirements(query, anchors=[])
        from src.intelligence.response.anchors import extract_anchors

        requirements = build_requirements(query, anchors=extract_anchors(query))
        coverage = evaluate_requirements(
            requirements, [_chunk("FCLAS define la clase tarifaria.")]
        )
        by_id = {requirement.id: requirement for requirement in coverage.requirements}
        assert by_id["anchor:fclas"].state == RequirementState.FOUND.value
        assert by_id["anchor:&&&f"].state == RequirementState.MISSING.value
        assert coverage.coverage < 1.0

    def test_full_evidence_covers_requirements(self) -> None:
        from src.intelligence.response.anchors import extract_anchors

        query = "consulta si FCLAS &&&F acepta QNNF0SME"
        requirements = build_requirements(query, anchors=extract_anchors(query))
        coverage = evaluate_requirements(
            requirements,
            [
                _chunk(
                    "FCLAS define la clase. La máscara &&&F acepta QNNF0SME "
                    "según la regla de matching posicional."
                )
            ],
        )
        assert coverage.coverage >= 0.8
        assert requirements_satisfied(coverage, 0.6)

    def test_framing_words_do_not_block_clause_coverage(self) -> None:
        # «cuéntame sobre …» pide la explicación: no es premisa documental.
        requirements = build_requirements("cuéntame sobre el Record 2", anchors=[])
        coverage = evaluate_requirements(
            requirements, [_chunk("El Record 2 describe los campos del registro.")]
        )
        clauses = [
            requirement.state
            for requirement in coverage.requirements
            if requirement.kind == "clause"
        ]
        assert clauses
        assert all(state != RequirementState.MISSING.value for state in clauses)

    def test_plural_and_accent_tolerant_clause_matching(self) -> None:
        requirements = build_requirements(
            "el cambio de fechas del Record 2", anchors=[]
        )
        coverage = evaluate_requirements(
            requirements,
            [
                _chunk(
                    "La fecha efectiva y la fecha de descontinuación se "
                    "procesan en el Record 2."
                )
            ],
        )
        clause = next(
            requirement
            for requirement in coverage.requirements
            if requirement.kind == "clause"
        )
        # «fechas» cubre por «fecha»; «record» está: parcial, nunca MISSING.
        assert clause.state != RequirementState.MISSING.value

    def test_anchor_coverage_exact(self) -> None:
        from src.intelligence.response.anchors import extract_anchors

        anchors = extract_anchors("máscara &&&F del campo")
        cov = anchor_coverage(anchors, [_chunk("La máscara &&&F aplica.")])
        assert cov.found == len(anchors)
        assert cov.exact is True

    def test_information_gain_redundant_vs_new(self) -> None:
        texto = "contenido único sobre la regla de aplicación tarifaria"
        before = snapshot([_chunk(texto)])
        same = snapshot([_chunk(texto), _chunk(texto)])
        gain_same = compute_information_gain(before, same, added_tokens=40)
        nuevo = snapshot(
            [
                _chunk(texto),
                _chunk("otro documento explica la excepción del byte 105", source_id="s2"),
            ]
        )
        gain_new = compute_information_gain(before, nuevo, added_tokens=40)
        assert gain_same.new_tokens == 0
        assert gain_same.redundant is True
        assert gain_new.new_documents == 1
        assert gain_new.score > gain_same.score


# -----------------------------------------------------------------------------
# Engine (integración con fakes)
# -----------------------------------------------------------------------------
class TestAdaptiveLongContextEngine:
    @pytest.mark.asyncio
    async def test_simple_question_stops_small(self) -> None:
        """TEST 4: no se consumen 100K para una pregunta ya respondida."""
        initial = _chunk("Byte 105 | Fee application\nLa Tabla de campos lo define.")
        engine = _engine(
            settings=_settings(),
            initial=initial,
            strategies=[_Strategy("nunca", "no debería usarse", [_chunk("x")])],
            check=_always_sufficient(),
        )
        result = await engine.run(
            query=_query("¿qué es el byte 105?"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.stop_reason == STOP_EVIDENCE_INITIAL
        assert result.final_tokens <= 8192
        assert result.expansions == []
        assert result.budget.usable_context > 500_000  # disponible, no usado

    @pytest.mark.asyncio
    async def test_expands_to_next_chunk(self) -> None:
        """TEST 5: la explicación está en el chunk siguiente."""
        initial = _chunk("FCLAS se define en la sección 4.")
        siguiente = _chunk("La máscara &&&F acepta QNNF0SME según la regla.")
        engine = _engine(
            settings=_settings(requirement_min=0.0),
            initial=initial,
            strategies=[_Strategy("next_chunk", "faltaba el chunk siguiente", [siguiente])],
            check=_checker(["&&&f"]),
        )
        result = await engine.run(
            query=_query("consulta si FCLAS &&&F acepta QNNF0SME"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.stop_reason == STOP_EVIDENCE_COMPLETE
        ids = {chunk.document_id for chunk in result.packed.chunks}
        assert siguiente.document_id in ids
        assert result.expansions and result.expansions[0].gain["new_anchors"] >= 1

    @pytest.mark.asyncio
    async def test_expands_table_and_note(self) -> None:
        """TEST 6: tabla + nota posterior entran juntas."""
        initial = _chunk("El byte 105 se documenta en Tabla 9 y una nota.")
        tabla = _chunk("Tabla 9 | Byte 105 | Fee application")
        nota = _chunk("Nota 4: el byte 105 sólo aplica a tarifas publicadas.")
        engine = _engine(
            settings=_settings(),
            initial=initial,
            strategies=[
                _Strategy("tabla", "referencia a Tabla 9", [tabla]),
                _Strategy("nota", "nota asociada", [nota]),
            ],
            check=_checker(["tabla 9", "nota 4"]),
        )
        result = await engine.run(
            query=_query("¿qué tabla y nota complementan el byte 105?"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.stop_reason == STOP_EVIDENCE_COMPLETE
        ids = {chunk.document_id for chunk in result.packed.chunks}
        assert tabla.document_id in ids and nota.document_id in ids

    @pytest.mark.asyncio
    async def test_multi_document_grows_progressively(self) -> None:
        """TEST 7: multi-documento: varias expansiones antes de completar."""
        doc1 = _chunk("La regla base está en el documento A.", source_id="a")
        doc2 = _chunk("El documento B agrega la excepción.", source_id="b")
        doc3 = _chunk("El documento C cierra la comparación.", source_id="c")
        engine = _engine(
            settings=_settings(),
            initial=doc1,
            strategies=[
                _Strategy("doc_b", "faltaba documento B", [doc2]),
                _Strategy("doc_c", "faltaba documento C", [doc3]),
            ],
            check=_checker(["excepción", "comparación"]),
        )
        result = await engine.run(
            query=_query("excepción y comparación"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[doc1]),
        )
        assert result.stop_reason == STOP_EVIDENCE_COMPLETE
        assert len(result.expansions) == 2
        tokens = [record.context_tokens for record in result.expansions]
        assert tokens == sorted(tokens)  # el presupuesto crece, no salta
        assert result.final_tokens >= tokens[-1]

    @pytest.mark.asyncio
    async def test_500k_available_but_complete_early(self) -> None:
        """TEST 8: 500K+ disponibles y evidencia completa temprano; no se usa."""
        initial = _chunk("La respuesta corta está en un solo fragmento.")
        engine = _engine(
            settings=_settings(),
            initial=initial,
            strategies=[_Strategy("x", "no aplica", [_chunk("irrelevante")])],
            check=_always_sufficient(),
        )
        result = await engine.run(
            query=_query("¿cuál es la respuesta?"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.stop_reason == STOP_EVIDENCE_INITIAL
        assert result.final_tokens < 4000
        assert result.budget.target_tokens(result.budget.max_tier) > 500_000

    @pytest.mark.asyncio
    async def test_incomplete_at_32k_complete_after_escalation(self) -> None:
        """TEST 9: incompleto en 32K; al expandir, completo y se detiene."""
        initial = _chunk("Datos iniciales sin la explicación.")
        explicacion = _chunk("La explicación completa del caso aparece acá.")
        settings = _settings(
            start_tier=3,  # 32768
            max_expansions=2,
            expansion_chunks=2,
            requirement_min=0.0,
        )
        engine = _engine(
            settings=settings,
            initial=initial,
            strategies=[_Strategy("explicacion", "faltaba la explicación", [explicacion])],
            check=_checker(["explicación completa"]),
        )
        result = await engine.run(
            query=_query("¿cómo funciona el caso?"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.stop_reason == STOP_EVIDENCE_COMPLETE
        assert len(result.expansions) == 1
        assert result.expansions[0].tier > 3
        assert result.budget.target_tokens(result.expansions[0].tier) >= 65536

    @pytest.mark.asyncio
    async def test_model_128k_never_exceeded(self) -> None:
        """TEST 10: aunque maximum_quality pida más, el techo es el modelo."""
        initial = _chunk("inicio")
        extras = [_chunk(f"documento {index} con contenido nuevo", source_id=f"s{index}") for index in range(4)]
        engine = _engine(
            settings=_settings(profile="maximum_quality", max_expansions=4),
            initial=initial,
            strategies=[_Strategy("mas", "más contexto", extras)],
            check=_checker(["nunca aparece"]),
        )
        result = await engine.run(
            query=_query("pregunta sin respuesta"),
            model="gpt-4o-mini",  # 128K
            initial=RetrievalContext(chunks=[initial]),
        )
        assert result.budget.usable_context < 128_000
        assert result.final_tokens <= result.budget.usable_context
        for record in result.expansions:
            assert record.context_tokens <= result.budget.usable_context

    @pytest.mark.asyncio
    async def test_anchor_found_alone_does_not_stop(self) -> None:
        """Encontrar &&&F no alcanza: la evidencia sigue incompleta y expande."""
        initial = _chunk("La máscara &&&F aparece mencionada al pasar.")
        explicacion = _chunk(
            "Comportamiento posicional: los caracteres posteriores a && limitan "
            "la longitud del valor."
        )
        engine = _engine(
            settings=_settings(),  # requirement_min 0.6
            initial=initial,
            strategies=[_Strategy("explicacion", "faltaba el comportamiento", [explicacion])],
            check=_always_sufficient(),
        )
        result = await engine.run(
            query=_query("¿cómo funciona &&&F con caracteres posteriores?"),
            model="gpt-4.1",
            initial=RetrievalContext(chunks=[initial]),
        )
        assert len(result.expansions) >= 1
        assert result.stop_reason != STOP_EVIDENCE_INITIAL
