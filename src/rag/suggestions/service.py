# =============================================================================
# Suggested questions — Knowledge V2 (brief §35)
# =============================================================================
# Preguntas útiles generadas SOLO a partir de datos reales del corpus
# (reusa CorpusStudioService como fuente de verdad: docs, timeline, riesgos,
# tablas). Si una categoría no tiene soporte (ej. sin fechas → sin pregunta
# temporal), no se incluye. Cada una lleva intent + basis con conteos reales.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.platform.studio.service import CorpusStudioService


@dataclass(frozen=True, kw_only=True)
class SuggestedQuestion:
    text: str
    intent: str
    basis: str

    def to_dict(self) -> dict:
        return {"text": self.text, "intent": self.intent, "basis": self.basis}


class QuestionSuggestionService:
    """Genera preguntas de arranque basadas en evidencia del corpus."""

    def __init__(self) -> None:
        self._studio = CorpusStudioService()

    async def suggest(
        self,
        organization_id: UUID,
        corpus_id: UUID,
        *,
        limit: int = 8,
    ) -> list[SuggestedQuestion]:
        result = await self._studio.build(
            organization_id,
            corpus_id,
            artifacts=("executive_summary", "timeline", "risks", "key_facts"),
        )
        by_name = {a.name: a for a in result.artifacts}

        suggestions: list[SuggestedQuestion] = []

        docs = by_name.get("executive_summary", None)
        doc_items = docs.items if docs else ()
        titles = [item["title"] for item in doc_items if item.get("title")]
        if titles:
            primary = titles[0]
            suggestions.append(
                SuggestedQuestion(
                    text=f"¿Cuáles son las obligaciones o cláusulas principales de {primary}?",
                    intent="list",
                    basis=f"{len(titles)} documento(s) en el corpus",
                )
            )
            if len(titles) >= 2:
                suggestions.append(
                    SuggestedQuestion(
                        text="¿Existen contradicciones entre los documentos?",
                        intent="multi_document",
                        basis=f"{len(titles)} documento(s) detectados",
                    )
                )

        timeline = by_name.get("timeline", None)
        timeline_items = timeline.items if timeline else ()
        if timeline_items:
            suggestions.append(
                SuggestedQuestion(
                    text="¿Qué fechas críticas aparecen en las fuentes?",
                    intent="temporal",
                    basis=f"{len(timeline_items)} fecha(s) extraídas",
                )
            )

        risks = by_name.get("risks", None)
        risk_items = risks.items if risks else ()
        if risk_items:
            suggestions.append(
                SuggestedQuestion(
                    text="¿Cuáles son los riesgos principales según las fuentes?",
                    intent="analytical",
                    basis=f"{len(risk_items)} candidato(s) a riesgo",
                )
            )

        facts = by_name.get("key_facts", None)
        fact_items = facts.items if facts else ()
        if fact_items:
            suggestions.append(
                SuggestedQuestion(
                    text="¿Qué acuerdos o cifras clave contienen las tablas?",
                    intent="key_facts",
                    basis=f"{len(fact_items)} hecho(s) de tablas/figuras",
                )
            )

        return suggestions[:limit]
