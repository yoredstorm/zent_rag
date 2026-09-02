# =============================================================================
# Data Profiling — perfil de columnas/tablas de una fuente SQL
# =============================================================================
# Detecta tipos, PK/FK, null rates, cardinalidad y candidatos PII/sensibles
# ANTES de exponer datos a los agentes (fase previa a la ingestión).
# =============================================================================
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Heurísticas de candidatos PII por nombre de columna.
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"email|correo", re.I)),
    ("phone", re.compile(r"phone|telefono|celular|movil|phone_number", re.I)),
    ("national_id", re.compile(r"rut|dni|cedula|passport|nid", re.I)),
    ("secret", re.compile(r"password|passwd|secret|token|api_key|credential", re.I)),
    ("payment_card", re.compile(r"card|credit|payment_method|bin_", re.I)),
    ("address", re.compile(r"address|direccion|domicilio|calle", re.I)),
    ("birth_date", re.compile(r"birth|nacimiento|fecha_nac", re.I)),
    ("health", re.compile(r"health|salud|medical|clinical|diagnost", re.I)),
]

# Heurísticas de campos sensibles de negocio.
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cost", re.compile(r"cost|salario|salary|sueldo", re.I)),
    ("revenue", re.compile(r"revenue|ingreso|factura", re.I)),
    ("pii_related", re.compile(r"insured|coverage|beneficiario", re.I)),
]


def _flags_for_column(name: str) -> tuple[list[str], bool]:
    pii = [label for label, pattern in _PII_PATTERNS if pattern.search(name)]
    sensitive = any(pattern.search(name) for _label, pattern in _SENSITIVE_PATTERNS)
    return pii, sensitive


async def profile_table(
    session: AsyncSession, schema: str, table: str
) -> dict:
    """Perfila una tabla: metadata de columnas + null rates + cardinalidad.

    Devuelve {"name", "columns": [...]} con un dict por columna:
    name, data_type, nullable, is_pk, is_fk, null_rate, cardinality,
    pii_flags[], sensitive.
    """
    columns = (
        await session.execute(
            text(
                "SELECT c.column_name, c.data_type, c.is_nullable, "
                "CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_pk, "
                "CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END AS is_fk "
                "FROM information_schema.columns c "
                "LEFT JOIN ("
                "  SELECT ku.table_schema, ku.table_name, ku.column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage ku "
                "    ON tc.constraint_name = ku.constraint_name "
                "  WHERE tc.constraint_type = 'PRIMARY KEY'"
                ") pk ON c.table_schema = pk.table_schema "
                "     AND c.table_name = pk.table_name "
                "     AND c.column_name = pk.column_name "
                "LEFT JOIN ("
                "  SELECT kcu.table_schema, kcu.table_name, kcu.column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage kcu "
                "    ON tc.constraint_name = kcu.constraint_name "
                "  WHERE tc.constraint_type = 'FOREIGN KEY'"
                ") fk ON c.table_schema = fk.table_schema "
                "     AND c.table_name = fk.table_name "
                "     AND c.column_name = fk.column_name "
                "WHERE c.table_schema = :schema AND c.table_name = :table "
                "ORDER BY c.ordinal_position"
            ),
            {"schema": schema, "table": table},
        )
    ).fetchall()

    if not columns:
        return {"name": table, "columns": []}

    cols = []
    for col in columns:
        pii, sensitive = _flags_for_column(col.column_name)
        null_rate: float | None = None
        cardinality: int | None = None
        try:
            from src.connectors.sql.schema_discovery import quote_ident

            col_ident = quote_ident(col.column_name)
            table_ident = quote_ident(table)
            schema_ident = quote_ident(schema)
            stats = (
                await session.execute(
                    # Identificadores sanitizados por quote_ident (regex estricta);
                    # provienen de information_schema, nunca del cliente.
                    text(  # noqa: S608
                        "SELECT count(*) AS total, "
                        f"count({col_ident}) AS non_null, "
                        f"count(DISTINCT {col_ident}) AS distinct_count "
                        f"FROM {schema_ident}.{table_ident}"
                    )
                )
            ).fetchone()
            total = int(stats.total or 0)
            if total:
                null_rate = round(
                    100.0 * (total - int(stats.non_null or 0)) / total, 2
                )
            cardinality = int(stats.distinct_count or 0)
        except Exception:
            # Tabla sin permisos o columna especial: null_rate/cardinality inciertos.
            pass
        cols.append(
            {
                "name": col.column_name,
                "data_type": col.data_type,
                "nullable": col.is_nullable == "YES",
                "is_pk": bool(col.is_pk),
                "is_fk": bool(col.is_fk),
                "null_rate": null_rate,
                "cardinality": cardinality,
                "pii_flags": pii,
                "sensitive": sensitive,
            }
        )
    return {"name": table, "columns": cols}
