# =============================================================================
# SQL Intent Router — decide si la pregunta es analítica (SQL) o documental
# =============================================================================
# Pipeline Text-to-SQL: el router evita correr el SQL Expert (LLM caro)
# para preguntas documentales. Señales léxicas genéricas (sin negocio
# vertical) + confirmación LLM barata solo en la banda dudosa.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.config import get_settings
from src.core.ports import LLMProvider
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Señales de pregunta analítica (agregación, ranking, fechas, entidades).
_AGGREGATION_PATTERNS = (
    r"\bcu[áa]nto\w*\b",
    r"\bcu[áa]ntas\b",
    r"\bcu[áa]ntos\b",
    r"\btotal\b",
    r"\bsuma\b",
    r"\bpromedio\b",
    r"\bmedia\b",
    r"\bmonto\b",
    r"\bimporte\b",
    r"\bingresos?\b",
    r"\bventas?\b",
    r"\bgastos?\b",
    r"\bcosto\w*\b",
    r"\bganancias?\b",
    r"\bestad[íi]sticas?\b",
)
_RANKING_PATTERNS = (
    r"\bm[áa]s\s+(vendido\w*|comprado\w*|frecuente\w*|popular\w*|caro\w*|barato\w*)",
    r"\bmenos\s+(vendido\w*|comprado\w*)",
    r"\bmejores?\b",
    r"\bpeores?\b",
    r"\btop\s*\d+",
    r"\branking\b",
    r"\br[áa]nking\b",
)
_DATE_PATTERNS = (
    r"\besta\s+semana\b",
    r"\beste\s+mes\b",
    r"\beste\s+trimestre\b",
    r"\beste\s+a[ñn]o\b",
    r"\b[úu]ltim\w+\s+(semana|mes|d[íi]as?|a[ñn]os?|trimestre)\b",
    r"\bmes\s+pasado\b",
    r"\bsemana\s+pasada\b",
    r"\ba[ñn]o\s+pasado\b",
    r"\bhoy\b",
    r"\bayer\b",
)
_ENTITY_PATTERNS = (
    r"\bclientes?\b",
    r"\bproductos?\b",
    r"\bpedidos?\b",
    r"\b[óo]rdenes\b",
    r"\bproveedores?\b",
    r"\bempleados?\b",
    r"\bfacturas?\b",
    r"\bcompras?\b",
    r"\bstock\b",
    r"\binventario\b",
    r"\bcategor[íi]as?\b",
    r"\btransacciones?\b",
)
# Señales de pregunta documental (baja el score SQL).
_RAG_PATTERNS = (
    r"\bpol[íi]tica\w*\b",
    r"\bqu[ée]\s+es\b",
    r"\bqu[ée]\s+significa\b",
    r"\bexplica\w*\b",
    r"\bdocumento\w*\b",
    r"\bmanual\b",
    r"\bgu[íi]a\b",
    r"\bc[óo]mo\s+funciona\b",
)

_ROUTER_PROMPT = """Classify the user question. Answer with ONLY one word.
SQL = the question asks for numbers, counts, sums, totals, rankings,
comparisons or data from business records (sales, customers, products).
RAG = the question asks about policies, documentation, definitions or
explanations.

Question: {question}

Answer:"""


class SqlIntentRouter:
    """Router heurístico + confirmación LLM opcional en banda dudosa."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        *,
        threshold: float | None = None,
        llm_confirm_enabled: bool | None = None,
    ) -> None:
        self._llm = llm_provider
        settings = get_settings()
        self._threshold = (
            threshold if threshold is not None else settings.RAG_SQL_ROUTER_THRESHOLD
        )
        self._llm_enabled = (
            llm_confirm_enabled
            if llm_confirm_enabled is not None
            else settings.RAG_SQL_ROUTER_LLM_ENABLED
        )

    @staticmethod
    def heuristic_score(question: str) -> float:
        """Score 0..1 de intención SQL por señales léxicas genéricas."""
        text = (question or "").lower()
        signals = 0
        signals += sum(
            1 for pattern in _AGGREGATION_PATTERNS if re.search(pattern, text)
        )
        signals += sum(
            1 for pattern in _RANKING_PATTERNS if re.search(pattern, text)
        )
        signals += sum(1 for pattern in _DATE_PATTERNS if re.search(pattern, text))
        signals += sum(1 for pattern in _ENTITY_PATTERNS if re.search(pattern, text))
        rag_signals = sum(
            1 for pattern in _RAG_PATTERNS if re.search(pattern, text)
        )

        score = min(signals * 0.4, 1.0)
        score = max(score - rag_signals * 0.35, 0.0)
        return score

    async def is_sql_intent(
        self,
        organization_id: UUID,
        question: str,
        role: str,
    ) -> bool:
        """Decide si la pregunta debe pasar por el SQL Expert."""
        score = self.heuristic_score(question)
        if score >= self._threshold:
            return True
        if score <= self._threshold - 0.25:
            return False

        # Banda dudosa: confirmación LLM barata (desactivable).
        if not self._llm_enabled or self._llm is None:
            return score >= self._threshold

        try:
            resp = await self._llm.generate(
                prompt=_ROUTER_PROMPT.format(question=question[:500]),
                max_tokens=4,
                temperature=0.0,
            )
            verdict = (resp.content or "").strip().upper()
            is_sql = verdict.startswith("SQL")
            logger.info(
                "SQL intent router LLM confirm",
                organization_id=str(organization_id),
                heuristic_score=round(score, 2),
                verdict=verdict[:8],
            )
            return is_sql
        except Exception as exc:
            logger.warning("SQL router LLM confirm failed, using heuristic", error=str(exc))
            return score >= self._threshold
