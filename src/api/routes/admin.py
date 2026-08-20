# =============================================================================
# Admin API — Gestión de Tablas (dev only; gated by RAG_ADMIN_ENABLED)
# =============================================================================
# Endpoints seguros para crear, poblar y eliminar tablas dinámicamente.
# Usa allowlist de nombres de tabla/columna para prevenir SQL Injection.
# Solo expuesto cuando RAG_ADMIN_ENABLED=true; no forma parte del portal B2B.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from src.agents.tools.sql_expert_postgres import _FORBIDDEN_KEYWORDS, _validate_sql_ast
from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import get_async_session

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

# Allowlist estricta: solo letras, números y guiones bajos; máximo 63 chars (PG limit)
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
# Palabras clave SQL reales — no se permite nombrar tablas/columnas con ellas
_RESERVED_WORDS = {
    "select", "insert", "update", "delete", "drop", "create", "alter",
    "table", "from", "where", "join", "union", "into", "values", "set",
    "grant", "revoke", "commit", "rollback", "begin", "transaction",
}
# Tablas del sistema protegidas contra escritura/lectura masiva
_PROTECTED_TABLES: set[str] = {
    "organizations",
    "users",
    "subscriptions",
    "plans",
    "api_keys",
    "request_quota",
    "usage_logs",
    "query_audit_log",
    "rate_limit_counters",
    "rag_evaluations",
    "documents",
    "alembic_version",
}


def _require_admin(request: Request):
    """Toda ruta /admin/* exige organization admin (sesión portal o scope admin:*)."""
    from src.api.security import require_organization_admin

    return require_organization_admin(request)


def _validate_identifier(value: str, label: str = "identifier") -> str:
    """Valida que un nombre de tabla/columna sea seguro."""
    if not _IDENTIFIER_RE.match(value):
        raise HTTPException(
            400, f"{label} inválido: '{value}'. Solo letras, números y _ (max 63 chars)."
        )
    if value.lower() in _RESERVED_WORDS:
        raise HTTPException(400, f"{label} '{value}' es palabra reservada SQL.")
    return value


def _check_not_protected(table_name: str) -> None:
    """Lanza 403 si la tabla es del sistema (protegida contra escritura)."""
    if table_name.lower() in _PROTECTED_TABLES:
        raise HTTPException(403, f"Tabla '{table_name}' es del sistema y no puede modificarse.")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class ColumnDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=63)
    type: str = Field(default="TEXT", min_length=1, max_length=50)
    nullable: bool = True
    is_pk: bool = False
    auto_increment: bool = False

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return _validate_identifier(v, "Nombre de columna")

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        allowed = {
            "TEXT", "VARCHAR", "INTEGER", "INT", "BIGINT", "SMALLINT",
            "SERIAL", "BIGSERIAL",
            "DECIMAL", "NUMERIC", "REAL", "DOUBLE PRECISION",
            "BOOLEAN", "BOOL", "TIMESTAMPTZ", "TIMESTAMP", "DATE",
            "UUID", "JSONB", "TEXT[]", "VARCHAR[]",
        }
        upper = v.upper().strip()
        if upper not in allowed and not re.match(r"^VARCHAR\(\d+\)$", upper, re.IGNORECASE):
            raise HTTPException(400, f"Tipo de columna no permitido: '{v}'")
        return v


class CreateTableRequest(BaseModel):
    table_name: str = Field(..., min_length=1, max_length=63)
    schema_name: str = Field(default="public", min_length=1, max_length=63)
    columns: list[ColumnDef] = Field(..., min_length=1, max_length=50)
    organization_aware: bool = Field(
        default=True,
        description="Añade automáticamente columna organization_id y FK a organizations",
    )

    @field_validator("table_name")
    @classmethod
    def check_table(cls, v: str) -> str:
        return _validate_identifier(v, "Nombre de tabla")

    @field_validator("schema_name")
    @classmethod
    def check_schema(cls, v: str) -> str:
        return _validate_identifier(v, "Nombre de schema")


class InsertRowsRequest(BaseModel):
    rows: list[dict[str, object]] = Field(..., min_length=1, max_length=1000)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@router.get("/tables", summary="Listar todas las tablas")
async def list_tables(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    resolve_organization(request, x_organization_id)

    session = await get_async_session()
    try:
        rows = await session.execute(
            text(
                "SELECT t.table_schema, t.table_name, "
                "COALESCE(c.column_count, 0) AS column_count "
                "FROM information_schema.tables t "
                "LEFT JOIN ("
                "  SELECT table_schema, table_name, COUNT(*) AS column_count "
                "  FROM information_schema.columns "
                "  GROUP BY table_schema, table_name"
                ") c ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                "WHERE t.table_type = 'BASE TABLE' "
                "AND t.table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast') "
                "ORDER BY t.table_schema, t.table_name"
            )
        )
        tables = [
            {"schema": r.table_schema, "name": r.table_name, "columns": r.column_count}
            for r in rows.fetchall()
        ]
        return {"tables": tables, "total": len(tables)}
    finally:
        await session.close()


@router.post("/tables", status_code=201, summary="Crear una nueva tabla")
async def create_table(
    body: CreateTableRequest,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    organization_id = resolve_organization(request, x_organization_id)

    schema = _validate_identifier(body.schema_name, "Schema")
    table = body.table_name
    _check_not_protected(table)

    # Asegurar que el schema existe
    session = await get_async_session()
    try:
        await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS \"{schema}\""))

        col_defs: list[str] = []
        pk_cols: list[str] = []

        if body.organization_aware:
            col_defs.append("organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE")

        for col in body.columns:
            nullable = "NOT NULL" if not col.nullable else ""
            col_type = col.type.upper()

            if col.is_pk:
                pk_cols.append(f'"{col.name}"')
                if col.auto_increment and col_type in ("INTEGER", "INT", "BIGINT", "SERIAL", "BIGSERIAL"):
                    # SERIAL ya incluye NOT NULL implícito; PG crea la secuencia automáticamente
                    col_type = "SERIAL" if col_type in ("INTEGER", "INT") else "BIGSERIAL"
                    nullable = ""
                elif col.auto_increment:
                    col_type = "SERIAL"

            col_defs.append(f'"{col.name}" {col_type} {nullable}'.strip())

        if pk_cols:
            col_defs.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
        else:
            # Si el usuario no define PK, añadimos id auto-generado
            col_defs.insert(0, "id SERIAL PRIMARY KEY")

        ddl = f'CREATE TABLE "{schema}"."{table}" ({", ".join(col_defs)})'
        await session.execute(text(ddl))

        if body.organization_aware:
            await session.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS idx_{table}_organization '
                    f'ON "{schema}"."{table}" (organization_id)'
                )
            )

        await session.commit()
        logger.info("Table created", schema=schema, table=table)
        return {
            "status": "created",
            "schema": schema,
            "table": table,
            "columns": len(col_defs),
        }
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to create table", error=str(exc))
        raise HTTPException(500, "Error creando tabla")
    finally:
        await session.close()


@router.post("/tables/{schema_name}/{table_name}/rows", status_code=201, summary="Insertar filas")
async def insert_rows(
    schema_name: str,
    table_name: str,
    body: InsertRowsRequest,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    organization_id = resolve_organization(request, x_organization_id)

    schema = _validate_identifier(schema_name, "Schema")
    table = _validate_identifier(table_name, "Tabla")
    _check_not_protected(table)

    if not body.rows:
        raise HTTPException(400, "Se requiere al menos una fila")

    # Validar nombres de columna
    columns = list(body.rows[0].keys())
    for col_name in columns:
        _validate_identifier(col_name, "Columna")

    session = await get_async_session()
    try:
        # Verificar si la tabla tiene organization_id
        has_organization = False
        cols_result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": schema, "table": table},
        )
        existing_cols = {r.column_name for r in cols_result.fetchall()}
        if "organization_id" in existing_cols:
            has_organization = True

        # Insertar filas en batch
        all_cols = set(columns)
        if has_organization and "organization_id" not in all_cols:
            all_cols.add("organization_id")

        col_list = sorted(all_cols)
        placeholders = ", ".join(f":{c}" for c in col_list)
        quoted_cols = ", ".join(f'"{c}"' for c in col_list)

        inserted = 0
        for row in body.rows:
            params = {c: row.get(c) for c in col_list}
            if has_organization and "organization_id" not in row:
                params["organization_id"] = organization_id
            await session.execute(
                text(
                    f'INSERT INTO "{schema}"."{table}" ({quoted_cols}) '
                    f"VALUES ({placeholders})"
                ),
                params,
            )
            inserted += 1

        await session.commit()
        return {"status": "inserted", "rows": inserted, "schema": schema, "table": table}
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to insert rows", error=str(exc))
        raise HTTPException(500, "Error insertando filas")
    finally:
        await session.close()


@router.get("/tables/{schema_name}/{table_name}/columns", summary="Columnas de una tabla (detalle)")
async def get_columns(
    schema_name: str,
    table_name: str,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    resolve_organization(request, x_organization_id)

    schema = _validate_identifier(schema_name, "Schema")
    table = _validate_identifier(table_name, "Tabla")
    _check_not_protected(table)

    session = await get_async_session()
    try:
        rows = await session.execute(
            text(
                "SELECT c.column_name, c.data_type, c.is_nullable, c.column_default, c.ordinal_position, "
                "CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_pk "
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
                "WHERE c.table_schema = :schema AND c.table_name = :table "
                "ORDER BY c.ordinal_position"
            ),
            {"schema": schema, "table": table},
        )
        columns = [
            {
                "name": r.column_name,
                "type": r.data_type,
                "nullable": r.is_nullable == "YES",
                "default": r.column_default,
                "is_pk": r.is_pk,
                "position": r.ordinal_position,
            }
            for r in rows.fetchall()
        ]
        return {"schema": schema, "table": table, "columns": columns}
    finally:
        await session.close()


@router.get("/tables/{schema_name}/{table_name}/rows", summary="Listar filas de una tabla")
async def list_rows(
    schema_name: str,
    table_name: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    resolve_organization(request, x_organization_id)

    schema = _validate_identifier(schema_name, "Schema")
    table = _validate_identifier(table_name, "Tabla")
    _check_not_protected(table)

    session = await get_async_session()
    try:
        # Obtener columnas
        cols_result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": schema, "table": table},
        )
        cols = [r.column_name for r in cols_result.fetchall()]

        # Contar filas
        count_result = await session.execute(
            text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        )
        total = count_result.scalar() or 0

        # Orden: usar created_at si existe, si no, sin orden
        order_clause = "ORDER BY created_at DESC NULLS LAST" if "created_at" in cols else ""

        # Obtener filas
        rows_result = await session.execute(
            text(
                f'SELECT * FROM "{schema}"."{table}" '
                f"{order_clause} "
                f"LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        rows = []
        for row in rows_result.fetchall():
            row_dict = {}
            for i, col in enumerate(cols):
                val = row[i]
                row_dict[col] = str(val) if val is not None else None
            rows.append(row_dict)

        return {"columns": cols, "rows": rows, "total": total, "limit": limit, "offset": offset}
    finally:
        await session.close()


@router.delete("/tables/{schema_name}/{table_name}", summary="Eliminar una tabla")
async def drop_table(
    schema_name: str,
    table_name: str,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import resolve_organization

    _require_admin(request)
    resolve_organization(request, x_organization_id)

    schema = _validate_identifier(schema_name, "Schema")
    table = _validate_identifier(table_name, "Tabla")
    _check_not_protected(table)

    session = await get_async_session()
    try:
        await session.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'))
        await session.commit()
        return {"status": "dropped", "schema": schema, "table": table}
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to drop table", error=str(exc))
        raise HTTPException(500, "Error eliminando tabla")
    finally:
        await session.close()


@router.post("/sql", summary="Ejecutar SQL directo (solo SELECT, admin verificado)")
async def execute_sql(request: Request, x_organization_id: str = Header(default="", alias="X-Organization-Id")):
    """Ejecuta SQL raw de solo lectura. Exige sesión autenticada con rol admin.

    Seguridad:
    - Deshabilitado en producción (ENVIRONMENT == "production").
    - Requiere Bearer token validado por el BillingMiddleware
      (portal session del dueño del organization, o API token con scope `admin:*`).
    - El X-Organization-Id, si viene, debe coincidir con el organization de la sesión.
    - El SQL se valida por AST (sqlglot): solo SELECT/EXPLAIN/SHOW.
    - Cada ejecución queda registrada en logs estructurados para auditoría.
    """
    settings = get_settings()
    if settings.ENVIRONMENT == "production":
        raise HTTPException(403, "SQL directo no disponible en producción")

    # La autenticación corre en TenantMiddleware (Bearer obligatorio para
    # rutas no públicas). Verificamos rol admin sobre el contexto resuelto.
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        raise HTTPException(
            401,
            "Autenticación requerida (Authorization: Bearer <token>)",
        )

    is_admin = ctx.is_organization_admin()
    if not is_admin:
        raise HTTPException(
            403,
            "Se requiere rol admin para ejecutar SQL directo",
        )

    if x_organization_id:
        try:
            header_organization = UUID(x_organization_id)
        except ValueError:
            raise HTTPException(400, "X-Organization-Id inválido")
        if header_organization != ctx.organization_id:
            raise HTTPException(
                403, "X-Organization-Id no coincide con la sesión autenticada"
            )

    body = await request.json()
    query = body.get("query", "").strip()

    if not query:
        raise HTTPException(400, "Query requerida")

    if len(query) > 8000:
        raise HTTPException(400, "Query demasiado larga (max 8000 chars)")

    # Validar con sqlglot AST — bloquea CTE bypass (WITH x AS DELETE...)
    # EXPLAIN y SHOW los parsea sqlglot como "command" genérico — los tratamos aparte
    import sqlglot

    from src.core.ports.sql_expert import SqlValidationError

    # Bloquear palabras/patrones prohibidos en TODOS los statements
    if _FORBIDDEN_KEYWORDS.search(query):
        raise HTTPException(403, "Forbidden SQL keyword detected")

    # Rechazar multi-statement (defensa en profundidad; no depender del driver)
    try:
        parsed_statements = sqlglot.parse(query, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as exc:
        raise HTTPException(403, "Invalid SQL syntax")
    if len(parsed_statements) > 1:
        raise HTTPException(403, "Multi-statement SQL is not allowed")

    _explain_match = re.match(r"^\s*EXPLAIN\b(.+)$", query, re.IGNORECASE)
    _show_match = re.match(r"^\s*SHOW\b", query, re.IGNORECASE)

    if _show_match:
        pass
    elif _explain_match:
        inner = _explain_match.group(1).strip()
        if not inner:
            raise HTTPException(400, "EXPLAIN requiere una query interna")
        try:
            _validate_sql_ast(inner)
        except SqlValidationError as exc:
            raise HTTPException(403, f"Invalid SQL inside EXPLAIN: {exc}")
    else:
        try:
            _validate_sql_ast(query)
        except SqlValidationError as exc:
            raise HTTPException(403, str(exc))

    logger.info(
        "Admin SQL executed",
        organization_id=str(ctx.organization_id),
        user_id=str(getattr(ctx, "user_id", None) or "anonymous"),
        auth_type=ctx.auth_type,
        query_preview=query[:500],
    )

    settings = get_settings()
    timeout_seconds = settings.RAG_SQL_TIMEOUT_SECONDS
    session = await get_async_session()
    try:
        await session.execute(
            text(f"SET LOCAL statement_timeout = '{timeout_seconds}s'")
        )
        result = await session.execute(text(query))
        if result.returns_rows:
            cols = list(result.keys())
            rows = []
            for row in result.fetchmany(500):
                rows.append({c: str(row[i]) if row[i] is not None else None for i, c in enumerate(cols)})
            return {"columns": cols, "rows": rows, "count": len(rows)}
        return {"message": "Query ejecutada (sin resultados)", "affected": result.rowcount}
    except Exception as exc:
        logger.error("Admin SQL execution failed", error=str(exc), exc_info=True)
        raise HTTPException(500, "Error SQL")
    finally:
        await session.close()
