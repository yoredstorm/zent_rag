from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from src.domain.services import DataSource


@dataclass
class SqlQueryResult:
    """Resultado de una consulta SQL generada por el experto."""

    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None


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
        tenant_id: UUID,
        question: str,
        role: str,
    ) -> SqlQueryResult:
        """Genera SQL, valida, ejecuta y retorna resultados."""
        ...

    @abstractmethod
    async def validate_sql(
        self,
        sql: str,
        sources: list[DataSource],
        role: str,
    ) -> None:
        """Valida que el SQL sea seguro y use solo el schema disponible.

        Lanza SqlValidationError si la query no es válida.
        """
        ...
