# =============================================================================
# Learn from successful questions — patrones SQL repetidos
# =============================================================================
# Si N consultas exitosas usan exactamente la misma lógica SQL, Zent SUGIERE
# crear una business metric reusable. Nunca convierte SQL generado en
# definición empresarial aprobada automáticamente.
# =============================================================================
from __future__ import annotations

import hashlib
import re
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.learning.improvements import ImprovementQueue

logger = get_logger(__name__)

_WS_RE = re.compile(r"\s+")


def normalize_sql(sql: str) -> str:
    return _WS_RE.sub(" ", (sql or "").strip().lower()).rstrip(";").strip()


class SqlPatternDetector:
    """Detecta consultas exitosas repetidas con la misma lógica SQL."""

    def __init__(self, improvements: ImprovementQueue, min_queries: int = 20) -> None:
        self._improvements = improvements
        self._min_queries = min_queries

    async def run(
        self,
        organization_id: UUID,
        *,
        days: int = 30,
    ) -> list[dict]:
        """Agrupa sql_audit_logs exitosos por SQL normalizado y sugiere métricas."""
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT question, generated_sql FROM sql_audit_logs "
                        "WHERE organization_id = :oid AND status = 'success' "
                        "AND generated_sql IS NOT NULL AND generated_sql <> '' "
                        "AND created_at >= now() - make_interval(days => :days) "
                        "LIMIT 2000"
                    ),
                    {"oid": organization_id, "days": days},
                )
            ).fetchall()
        finally:
            await session.close()

        groups: dict[str, dict] = {}
        for row in rows:
            key = hashlib.sha256(
                normalize_sql(row.generated_sql).encode("utf-8")
            ).hexdigest()
            group = groups.setdefault(
                key,
                {"sql": row.generated_sql, "count": 0, "questions": []},
            )
            group["count"] += 1
            if len(group["questions"]) < 5 and row.question:
                group["questions"].append(row.question)

        suggestions: list[dict] = []
        for group in groups.values():
            if group["count"] < self._min_queries:
                continue
            sample = group["questions"][0] if group["questions"] else "consulta SQL"
            await self._improvements.sync_from_metric_pattern(
                organization_id=organization_id,
                sql=group["sql"],
                question_sample=sample,
                query_count=group["count"],
            )
            suggestions.append(
                {
                    "question_sample": sample,
                    "query_count": group["count"],
                    "sql": group["sql"][:300],
                }
            )
        return suggestions
