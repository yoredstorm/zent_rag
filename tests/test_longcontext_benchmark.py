# =============================================================================
# Long-Context Benchmark — métricas antes/después sin infraestructura
# =============================================================================
# "Antes" = contexto base del retrieval (lo que el pipeline viejo habría visto).
# "Después" = contexto empaquetado por el motor adaptativo.
# Corre offline con fakes: mismo engine, mismos caminos, cero LLM.
# Ejecutar: .venv\Scripts\python -m pytest tests/test_longcontext_benchmark.py -s -q
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.adaptive import EvidenceQuality
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.longcontext.engine import AdaptiveLongContextEngine
from src.rag.longcontext.expansion import Expansion
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


def _checker(needles: tuple[str, ...]):
    async def check(chunks: list[RetrievalChunk]) -> EvidenceQuality:
        joined = "\n".join(chunk.content or "" for chunk in chunks).lower()
        complete = all(needle.lower() in joined for needle in needles)
        return EvidenceQuality(
            sufficient=complete,
            score=0.85 if complete else 0.25,
            reason="benchmark",
            has_evidence=bool(chunks),
        )

    return check


def _engine(
    settings: LongContextSettings,
    strategies: list[_Strategy],
    needles: tuple[str, ...] = (),
) -> AdaptiveLongContextEngine:
    async def _retrieve(spec):  # pragma: no cover - benchmark no re-consulta
        return RetrievalContext(chunks=[])

    return AdaptiveLongContextEngine(
        retrieve_fn=_retrieve,
        settings=settings,
        strategies=strategies,
        evidence_check=_checker(needles),
    )


def _query(texto: str) -> RetrievalQuery:
    return RetrievalQuery(
        query=texto,
        organization_id=ORG,
        query_embedding=[0.1, 0.2],
        score_threshold=0.0,
    )


@pytest.mark.asyncio
async def test_benchmark_antes_despues(capsys: pytest.CaptureFixture) -> None:
    simple = _chunk("FCLAS es la clase tarifaria; la respuesta ya está contenida.")
    mask_initial = _chunk("FCLAS aparece sin explicar la máscara.")
    mask_exact = _chunk(
        "La máscara &&&F acepta QNNF0SME: explicación completa de la regla."
    )
    doc1 = _chunk("Regla base del documento A.", source_id="a")
    doc2 = _chunk("Excepción del documento B.", source_id="b")
    doc3 = _chunk("Comparación final del documento C.", source_id="c")

    escenarios = [
        (
            "simple_lookup",
            _query("¿qué es FCLAS?"),
            "gpt-4.1",
            _engine(
                LongContextSettings(mode="active", requirement_min=0.0),
                [_Strategy("noop", "no aplica", [simple])],
                needles=(),
            ),
            [simple],
        ),
        (
            "technical_mask",
            _query("consulta si FCLAS &&&F acepta QNNF0SME"),
            "gpt-4.1",
            _engine(
                LongContextSettings(mode="active", requirement_min=0.0),
                [_Strategy("explicacion", "faltaba la explicación", [mask_exact])],
                needles=("explicación completa",),
            ),
            [mask_initial],
        ),
        (
            "multi_document",
            _query("excepción y comparación"),
            "gpt-4.1",
            _engine(
                LongContextSettings(mode="active", requirement_min=0.0),
                [
                    _Strategy("doc_b", "faltaba el documento B", [doc2]),
                    _Strategy("doc_c", "faltaba el documento C", [doc3]),
                ],
                needles=("excepción", "comparación"),
            ),
            [doc1],
        ),
        (
            "128k_cap",
            _query("máximo contexto"),
            "gpt-4o-mini",
            _engine(
                LongContextSettings(
                    mode="active",
                    profile="maximum_quality",
                    requirement_min=0.0,
                    max_expansions=3,
                ),
                [
                    _Strategy("mas", "más contexto", [mask_exact]),
                    _Strategy("mas2", "más contexto", [doc2]),
                ],
                needles=("nunca aparece",),
            ),
            [mask_initial],
        ),
    ]

    filas: list[str] = []
    for nombre, query, modelo, engine, inicial in escenarios:
        result = await engine.run(
            query=query,
            model=modelo,
            initial=RetrievalContext(chunks=inicial),
        )
        before = sum(max(1, len(chunk.content) // 4) for chunk in inicial)
        gain_total = sum(
            float((record.gain or {}).get("score") or 0.0)
            for record in result.expansions
        )
        filas.append(
            f"{nombre:<18} antes={before:>6} tok  despues={result.final_tokens:>7} tok  "
            f"expansiones={len(result.expansions):<3} gain_total={gain_total:.3f}  "
            f"stop={result.stop_reason}"
        )
        # El tope REAL del modelo nunca se supera.
        assert result.final_tokens <= result.budget.usable_context
        if nombre == "simple_lookup":
            assert result.expansions == []
            assert result.final_tokens <= 8192
        if nombre == "technical_mask":
            assert result.expansions
            assert result.final_tokens > before
            assert result.stop_reason == "evidence_complete"
        if nombre == "multi_document":
            assert len(result.expansions) >= 2
        if nombre == "128k_cap":
            assert result.final_tokens <= result.budget.usable_context < 128_000

    with capsys.disabled():
        print("\n=== Long-Context benchmark (offline) ===")
        for fila in filas:
            print(fila)
        print("=== fin ===")
