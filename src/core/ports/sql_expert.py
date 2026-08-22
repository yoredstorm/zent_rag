from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from src.core.domain.services import DataSource


@dataclass
class SqlQueryResult:
    """Resultado de una consulta SQL generada por el experto."""

    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    truncated: bool = False  # True si se alcanzó el límite de filas
    cost: float | None = None  # Costo estimado del plan (EXPLAIN Total Cost)


@dataclass
class SqlValidationError(Exception):
    """Error de validación SQL (seguridad o esquema)."""

    message: str
    sql: str | None = None


class SqlExpert(ABC):
    """Genera y ejecuta SQL a partir de preguntas en lenguaje natural.

    Recibe el schema disponible (tablas, columnas, FKs) y una pregunta
    del usuario. Genera SQL validado, lo ejecuta contra una conexión
    read-only, y retorna los resultados.

    Domain-agnóstico: funciona para cualquier BD sin configuración manual.
    """

    @abstractmethod
    async def execute(
        self,
        organization_id: UUID,
        question: str,
        role: str,
        permissions: dict | None = None,
        user_id: UUID | None = None,
    ) -> SqlQueryResult:
        """Genera SQL, valida, ejecuta y retorna resultados.

        `permissions`: config opcional del tenant, p. ej.
        {"column_blocklist": {"customer": ["cost"]}, "table_blocklist": [...]}.
        `user_id`: identidad del actor para auditoría.
        """

    @abstractmethod
    async def validate_sql(
        self,
        sql: str,
        sources: list[DataSource],
        role: str,
        organization_id: UUID,
    ) -> str:
        """Valida que el SQL sea seguro y use solo el schema disponible.

        Lanza SqlValidationError si la query no es válida.
        """
