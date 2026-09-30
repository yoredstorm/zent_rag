# =============================================================================
# Regresión del pipeline técnico — source routing, starvation, roles y fuentes
# =============================================================================
# Caso real (sólo como test, JAMÁS hardcodeado en producción):
#
#   "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que
#    el farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
#
# Lo que estos tests blindan:
#   - aliases de «record 2» para nombres de fuente (Rec2_Rules, Rec2_Cat10...)
#   - SourceRouter genérico: reglas de record 2 primero; categorías no pedidas
#     con score menor
#   - exact retrieval POR ANCHOR: 20 chunks con FCLAS no tapan el &&&F
#   - EXAMPLE_VALUE no exige match (coverage_note no lo declara ausente)
#   - source_priority con COMPORTAMIENTO real (PASS A), no sólo la variable
#   - Fuentes finales = evidencia USED, no candidatos
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.intelligence.response.references import (
    alias_in_source_name,
    reference_aliases,
)
from src.rag.longcontext.coverage import build_evidence_state
from src.rag.longcontext.exact_search import ExactAnchorSpec, ExactRetriever
from src.rag.longcontext.roles import AnchorRole
from src.rag.longcontext.source_router import profile_from_source, route_sources
from src.rag.retrieval.hybrid import HybridRetriever
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("11111111-1111-1111-1111-111111111111")

QUESTION = (
    "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que "
    "el farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
)

SOURCES = [
    "Rec2_Rules_dapp_C.pdf",
    "Rec2_Cat10_dapp_C.pdf",
    "Cat33_dapp_C.pdf",
    "Cat12_dapp_examples_C.pdf",
]


def _chunk(texto: str, score: float = 0.5, **metadata) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=texto, score=score, metadata=metadata
    )


# -----------------------------------------------------------------------------
# 1-2. Aliases y router genérico
# -----------------------------------------------------------------------------
class TestReferenceAliases:
    def test_record_2_aliases(self) -> None:
        aliases = reference_aliases("record", "2")
        for expected in ("record 2", "record2", "record_2", "record-2", "rec 2", "rec2", "rec_2", "rec-2"):
            assert expected in aliases, expected
        assert alias_in_source_name("rec 2", "Rec2_Rules_dapp_C.pdf")
        assert alias_in_source_name("record2", "Rec2_Rules_dapp_C.pdf")

    def test_alias_does_not_match_other_number(self) -> None:
        # «cat 1» no debe matchear Cat15
        assert not alias_in_source_name("cat 1", "Cat15_dapp.pdf")
        assert alias_in_source_name("cat 10", "Cat10_dapp.pdf")

    def test_other_structural_kinds(self) -> None:
        assert alias_in_source_name("byte 105", "Byte105_fees.pdf")
        assert alias_in_source_name("tbl 961", "TBL_961_data.xlsx")
        assert alias_in_source_name("category 31", "Cat31_dapp_C.pdf")


class TestSourceRouterRegression:
    def _route(self):
        profiles = [profile_from_source(str(uuid4()), name) for name in SOURCES]
        return route_sources(QUESTION, profiles)

    def test_rules_source_is_top_preferred(self) -> None:
        route = self._route()
        names = [entry.name for entry in route.preferred]
        assert names, "record 2 debe producir al menos una fuente preferida"
        assert names[0].startswith("Rec2_Rules")

    def test_unrequested_categories_score_lower(self) -> None:
        route = self._route()
        preferred_names = [entry.name for entry in route.preferred]
        everything = list(route.preferred) + list(route.candidates)
        by_name = {entry.name: entry.score for entry in everything}
        rules_score = by_name["Rec2_Rules_dapp_C.pdf"]
        assert by_name["Rec2_Cat10_dapp_C.pdf"] < rules_score
        assert by_name["Cat33_dapp_C.pdf"] < rules_score
        assert by_name["Cat12_dapp_examples_C.pdf"] < rules_score
        # Las exclusivamente de categorías no pedidas no son preferidas.
        assert not any(name.startswith("Cat33") for name in preferred_names)
        assert not any(name.startswith("Cat12") for name in preferred_names)

    def test_reasons_explain_the_ranking(self) -> None:
        route = self._route()
        top = route.preferred[0].to_public_dict()
        assert any("record 2" in reason for reason in top.get("reasons", []))
        assert route.references, "record 2 debe quedar como SourceReference"

    def test_category_query_penalizes_other_category(self) -> None:
        profiles = [profile_from_source(str(uuid4()), name) for name in SOURCES]
        route = route_sources("¿qué dice la categoría 31?", profiles)
        everything = list(route.preferred) + list(route.candidates)
        by_name = {entry.name: entry.score for entry in everything}
        # Ninguna fuente declara cat 31: todas las categorías ajenas quedan
        # penalizadas y NO entran como preferidas.
        assert not route.preferred
        assert by_name["Rec2_Cat10_dapp_C.pdf"] < 0
        assert by_name["Cat33_dapp_C.pdf"] < 0


# -----------------------------------------------------------------------------
# 3. Starvation: per-anchor con semántica REAL del store
# -----------------------------------------------------------------------------
class _RealSemanticsStore:
    """Emula scan_text_literal: ANY needle + limit + orden de scroll."""

    def __init__(self, corpus: list[RetrievalChunk]) -> None:
        self.corpus = corpus
        self.calls: list[dict] = []

    async def scan_text_literal(self, *, needles, limit=5, source_ids=None, **kwargs):
        self.calls.append({"needles": list(needles), "limit": limit, "sources": source_ids})
        agujas = [str(n).lower() for n in needles if str(n or "").strip()]
        found = [
            chunk
            for chunk in self.corpus
            if any(aguja in (chunk.content or "").lower() for aguja in agujas)
        ]
        return RetrievalContext(chunks=found[: max(1, int(limit))], retrieval_latency_ms=1.0)


class TestExactStarvation:
    def _corpus(self) -> list[RetrievalChunk]:
        corpus = [
            _chunk(f"FCLAS aparece en el documento previo numero {i}.") for i in range(20)
        ]
        corpus.append(
            _chunk("FCLAS indica la clase; la máscara &&&F exige longitud fija.")
        )
        return corpus

    def _query(self, **overrides) -> RetrievalQuery:
        params = {
            "query": QUESTION,
            "organization_id": ORG,
            "query_embedding": [0.1],
            "score_threshold": 0.0,
        }
        params.update(overrides)
        return RetrievalQuery(**params)

    @pytest.mark.asyncio
    async def test_rule_anchor_found_despite_20_field_hits(self) -> None:
        store = _RealSemanticsStore(self._corpus())
        retriever = ExactRetriever(store)
        specs = [
            ExactAnchorSpec(value="FCLAS", role=AnchorRole.FIELD_ANCHOR.value, needles=("FCLAS", "fclas")),
            ExactAnchorSpec(value="&&&F", role=AnchorRole.RULE_ANCHOR.value, needles=("&&&F",)),
        ]
        context = await retriever.retrieve(self._query(), specs)
        contents = " ".join(chunk.content for chunk in context.chunks)
        assert "&&&F" in contents, "el cupo de FCLAS no puede tapar la regla"
        rule_chunks = [
            chunk
            for chunk in context.chunks
            if str((chunk.metadata or {}).get("exact_role") or "")
            == AnchorRole.RULE_ANCHOR.value
        ]
        assert rule_chunks and rule_chunks[0].metadata.get("must_keep") == "true"

    @pytest.mark.asyncio
    async def test_single_or_scan_would_starve(self) -> None:
        """El bug original: un OR global con limit=4 nunca llega al chunk 21."""
        store = _RealSemanticsStore(self._corpus())
        legacy = await store.scan_text_literal(
            needles=["FCLAS", "&&&F"], limit=4
        )
        assert legacy.chunks and not any("&&&F" in c.content for c in legacy.chunks)

    @pytest.mark.asyncio
    async def test_preferred_sources_searched_first(self) -> None:
        preferred = uuid4()
        store = _RealSemanticsStore(self._corpus())
        retriever = ExactRetriever(store)
        specs = [ExactAnchorSpec(value="&&&F", role=AnchorRole.RULE_ANCHOR.value, needles=("&&&F",))]
        await retriever.retrieve(
            self._query(preferred_source_ids=[preferred]), specs
        )
        assert store.calls
        assert store.calls[0]["sources"] == [preferred]


# -----------------------------------------------------------------------------
# 4. EXAMPLE_VALUE: ni en missing ni en coverage_note
# -----------------------------------------------------------------------------
class TestExampleValueRegression:
    def test_qnnf0sme_is_not_missing_evidence(self) -> None:
        evidence = (
            "Record 2: FCLAS indica la clase tarifaria del fare basis. La máscara "
            "&&&F exige que el fare basis tenga la longitud indicada y los "
            "caracteres posteriores restringen el tamaño."
        )
        state = build_evidence_state(QUESTION, [evidence])
        assert "QNNF0SME" not in state.missing_anchors
        assert "QNNF0SME" not in state.missing_entities
        assert all(
            "QNNF0SME" not in description for description in state.missing_requirements
        )
        example_values = [str(anchor.value) for anchor in state.example_values]
        assert "QNNF0SME" in example_values

    def test_coverage_note_does_not_declare_example_missing(self) -> None:
        from src.intelligence.response.entities import coverage_note

        evidence = (
            "Record 2: FCLAS indica la clase tarifaria. El patrón &&&F posicional "
            "del fare basis."
        )
        note = coverage_note(QUESTION, evidence)
        assert "QNNF0SME" not in note

    def test_evidence_can_be_complete_without_example(self) -> None:
        evidence = (
            "Record 2: FCLAS indica la clase tarifaria del fare basis. La máscara "
            "&&&F exige que el fare basis tenga la longitud indicada; los "
            "caracteres posteriores a && restringen el tamaño."
        )
        state = build_evidence_state(QUESTION, [evidence])
        assert not state.missing_anchors
        assert not state.missing_entities


# -----------------------------------------------------------------------------
# 5. source_priority con COMPORTAMIENTO real (PASS A)
# -----------------------------------------------------------------------------
class _RoutingStore:
    """Store con dos fuentes: A tiene la regla, B sólo ruido."""

    def __init__(self, source_a: UUID, source_b: UUID) -> None:
        self.source_a = source_a
        self.source_b = source_b
        self.search_sources: list[list[UUID] | None] = []

    async def search(self, *, source_ids=None, **kwargs) -> RetrievalContext:
        self.search_sources.append(list(source_ids) if source_ids else None)
        if source_ids and self.source_a in source_ids:
            return RetrievalContext(
                chunks=[
                    _chunk(
                        "FCLAS y &&&F: regla posicional del fare basis.",
                        score=0.9,
                        source_id=str(self.source_a),
                    )
                ],
                retrieval_latency_ms=1.0,
            )
        if source_ids and self.source_b in source_ids:
            return RetrievalContext(
                chunks=[
                    _chunk("ruido de otra categoría", score=0.8, source_id=str(self.source_b))
                ],
                retrieval_latency_ms=1.0,
            )
        return RetrievalContext(chunks=[], retrieval_latency_ms=1.0)

    async def search_sparse(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=[], retrieval_latency_ms=1.0)


class TestSourcePriorityBehavior:
    @pytest.mark.asyncio
    async def test_preferred_source_avoids_global_search(self) -> None:
        source_a, source_b = uuid4(), uuid4()
        store = _RoutingStore(source_a, source_b)
        retriever = HybridRetriever(vector_store=store)

        context = await retriever.retrieve(
            RetrievalQuery(
                query=QUESTION,
                organization_id=ORG,
                query_embedding=[0.1],
                score_threshold=0.0,
                preferred_source_ids=[source_a],
                source_ids=[source_a, source_b],
            )
        )

        contents = " ".join(chunk.content for chunk in context.chunks)
        assert "&&&F" in contents
        assert store.search_sources[0] == [source_a]
        # B no se buscó: la preferida resolvió (PASS A, sin fallback).
        assert all(sources != [source_b] for sources in store.search_sources)

    @pytest.mark.asyncio
    async def test_empty_preferred_falls_back_to_global(self) -> None:
        source_a, source_b = uuid4(), uuid4()

        class _EmptyA(_RoutingStore):
            async def search(self, *, source_ids=None, **kwargs) -> RetrievalContext:
                self.search_sources.append(list(source_ids) if source_ids else None)
                if source_ids and self.source_a in source_ids:
                    return RetrievalContext(chunks=[], retrieval_latency_ms=1.0)
                return await super().search(source_ids=source_ids, **kwargs)

        store = _EmptyA(source_a, source_b)
        retriever = HybridRetriever(vector_store=store)
        await retriever.retrieve(
            RetrievalQuery(
                query=QUESTION,
                organization_id=ORG,
                query_embedding=[0.1],
                score_threshold=0.0,
                preferred_source_ids=[source_a],
                source_ids=[source_a, source_b],
            )
        )
        assert any(sources == [source_a, source_b] for sources in store.search_sources)


# -----------------------------------------------------------------------------
# 6. Fuentes finales = sólo evidencia USED
# -----------------------------------------------------------------------------
class TestFinalSources:
    def test_collect_sources_skips_candidates(self) -> None:
        from src.runtime.agent_flow import collect_sources

        steps = [
            {
                "type": "tool_call",
                "meta": {
                    "evidence": [
                        {"ref": "d1", "status": "USED", "title": "Rec2_Rules.pdf"},
                        {"ref": "d2", "status": "CANDIDATE", "title": "Cat33.pdf"},
                    ]
                },
            }
        ]
        sources = collect_sources(steps)
        titles = {source["title"] for source in sources}
        assert titles == {"Rec2_Rules.pdf"}
