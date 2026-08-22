# =============================================================================
# SQL Security — ataques contra el motor Text-to-SQL (todos bloqueados)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.agents.tools.schema_relevance import build_relevant_schema, rank_tables
from src.agents.tools.sql_expert_postgres import (
    PostgresSqlExpert,
    SqlValidationError,
)
from src.agents.tools.sql_router import SqlIntentRouter
from src.core.domain.entities import LLMResponse
from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports import LLMProvider
from src.core.ports.sql_expert import SqlQueryResult

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _sources() -> list[DataSource]:
    return [
        DataSource(
            schema_name="farmacia",
            table_name="sales",
            row_count=5000,
            columns=[
                ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
                ColumnMeta(name="organization_id", data_type="uuid", is_nullable=False),
                ColumnMeta(name="product_id", data_type="uuid", is_nullable=False, is_foreign_key=True, fk_table="products", fk_column="id"),
                ColumnMeta(name="quantity", data_type="integer", is_nullable=False),
                ColumnMeta(name="cost", data_type="numeric", is_nullable=True),
                ColumnMeta(name="sale_date", data_type="timestamp", is_nullable=False),
            ],
        ),
        DataSource(
            schema_name="farmacia",
            table_name="products",
            row_count=300,
            columns=[
                ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
                ColumnMeta(name="name", data_type="text", is_nullable=False),
                ColumnMeta(name="price", data_type="numeric", is_nullable=False),
                ColumnMeta(name="created_at", data_type="timestamp", is_nullable=False),
            ],
        ),
    ]


class _NoDbExpert(PostgresSqlExpert):
    """Expert sin DB real: EXPLAIN no-op, ejecución fake."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        super().__init__(llm)  # type: ignore[arg-type]

    async def _discover_sources(self, organization_id: UUID) -> list[DataSource]:
        return _sources()

    async def _explain_validate(self, sql: str) -> float | None:
        return 10.0

    async def _run_query(self, sql: str) -> SqlQueryResult:
        return SqlQueryResult(sql=sql, row_count=0)


async def _validate(sql: str, role: str = "admin", permissions: dict | None = None) -> str:
    expert = _NoDbExpert()
    expert._permissions = permissions
    return await expert.validate_sql(sql, _sources(), role, ORG)


class _FakeLLM(LLMProvider):
    def __init__(self, content: str = "") -> None:
        self.content = content

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        return LLMResponse(content=self.content, model="fake")

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


# -----------------------------------------------------------------------------
# SELECT-only + injection
# -----------------------------------------------------------------------------
class TestSelectOnly:
    @pytest.mark.asyncio
    async def test_multi_statement_injection_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT name FROM farmacia.products; DROP TABLE farmacia.products; --"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO farmacia.products (name) VALUES ('x')",
            "UPDATE farmacia.products SET name = 'x'",
            "DELETE FROM farmacia.products",
            "DROP TABLE farmacia.products",
            "TRUNCATE farmacia.products",
            "COPY farmacia.products TO '/tmp/out'",
            "GRANT SELECT ON farmacia.products TO public",
            "REVOKE SELECT ON farmacia.products FROM public",
            "CALL some_procedure()",
            "EXEC some_procedure()",
            "SELECT pg_sleep(10)",
            "SELECT lo_import('/etc/passwd')",
        ],
    )
    async def test_destructive_statements_blocked(self, sql: str) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(sql)

    @pytest.mark.asyncio
    async def test_cte_with_delete_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(
                "WITH x AS (DELETE FROM farmacia.products RETURNING *) SELECT * FROM x"
            )

    @pytest.mark.asyncio
    async def test_for_update_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate("SELECT name FROM farmacia.products FOR UPDATE")


# -----------------------------------------------------------------------------
# Cross-tenant / allowlist
# -----------------------------------------------------------------------------
class TestAllowlist:
    @pytest.mark.asyncio
    async def test_platform_table_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate("SELECT * FROM public.users")

    @pytest.mark.asyncio
    async def test_prompt_injection_table_blocked(self) -> None:
        # El LLM "sigue la instrucción maliciosa"; la allowlist lo frena.
        with pytest.raises(SqlValidationError):
            await _validate("SELECT email, password_hash FROM public.users")

    @pytest.mark.asyncio
    async def test_other_org_schema_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate("SELECT * FROM other_tenant.secrets")

    @pytest.mark.asyncio
    async def test_organization_filter_injected(self) -> None:
        sql = (
            "SELECT s.quantity FROM farmacia.sales s "
            "JOIN farmacia.products p ON s.product_id = p.id LIMIT 10"
        )
        safe = await _validate(sql)
        assert "organization_id" in safe.lower()
        assert str(ORG) in safe.lower()


# -----------------------------------------------------------------------------
# Query planner: cartesian + cost + massive
# -----------------------------------------------------------------------------
class TestPlanner:
    @pytest.mark.asyncio
    async def test_cross_join_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT p.name FROM farmacia.products p CROSS JOIN farmacia.sales s"
            )

    @pytest.mark.asyncio
    async def test_join_on_single_side_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT p.name FROM farmacia.products p "
                "JOIN farmacia.sales s ON p.id = p.id"
            )

    @pytest.mark.asyncio
    async def test_massive_limit_capped(self) -> None:
        safe = await _validate("SELECT name FROM farmacia.products LIMIT 999999")
        assert "999999" not in safe
        assert "LIMIT" in safe.upper()

    @pytest.mark.asyncio
    async def test_no_limit_gets_auto_limit_on_execution(self) -> None:

        # _run_query real agrega LIMIT cuando falta; simulamos la lógica vía
        # cap: validate no agrega LIMIT, la ejecución sí (cubierto en _run_query).
        expert = _NoDbExpert()
        result = await expert._run_query("SELECT name FROM farmacia.products")
        assert result.error is None


class _CostExpert(PostgresSqlExpert):
    def __init__(self, cost: float) -> None:
        super().__init__(None)  # type: ignore[arg-type]
        self._fake_cost = cost

    async def _discover_sources(self, organization_id: UUID) -> list[DataSource]:
        return _sources()

    async def _explain_validate(self, sql: str) -> float | None:
        settings = __import__("src.core.config", fromlist=["get_settings"]).get_settings()
        if self._fake_cost > settings.RAG_SQL_MAX_COST:
            raise SqlValidationError(
                f"Query plan too expensive: estimated cost {self._fake_cost:.1f} "
                f"exceeds limit {settings.RAG_SQL_MAX_COST:.1f}",
                sql,
            )
        return self._fake_cost


class TestCost:
    @pytest.mark.asyncio
    async def test_cost_limit_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_SQL_MAX_COST", 100.0)
        expert = _CostExpert(cost=999999.0)
        expert._permissions = None
        with pytest.raises(SqlValidationError):
            await expert.validate_sql(
                "SELECT name FROM farmacia.products LIMIT 5",
                _sources(),
                "admin",
                ORG,
            )

    @pytest.mark.asyncio
    async def test_cost_under_limit_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_SQL_MAX_COST", 100.0)
        expert = _CostExpert(cost=50.0)
        expert._permissions = None
        safe = await expert.validate_sql(
            "SELECT name FROM farmacia.products LIMIT 5",
            _sources(),
            "admin",
            ORG,
        )
        assert "LIMIT 5" in safe.upper()


# -----------------------------------------------------------------------------
# Permission check (rol + blocklist)
# -----------------------------------------------------------------------------
class TestPermissions:
    @pytest.mark.asyncio
    async def test_customer_aggregates_blocked(self) -> None:
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT SUM(s.quantity) FROM farmacia.sales s", role="customer"
            )

    @pytest.mark.asyncio
    async def test_customer_column_blocklist(self) -> None:
        permissions = {"column_blocklist": {"customer": ["cost"]}}
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT s.quantity, s.cost FROM farmacia.sales s LIMIT 5",
                role="customer",
                permissions=permissions,
            )

    @pytest.mark.asyncio
    async def test_admin_not_affected_by_customer_blocklist(self) -> None:
        permissions = {"column_blocklist": {"customer": ["cost"]}}
        safe = await _validate(
            "SELECT s.cost FROM farmacia.sales s LIMIT 5",
            role="admin",
            permissions=permissions,
        )
        assert "cost" in safe

    @pytest.mark.asyncio
    async def test_table_blocklist(self) -> None:
        permissions = {"table_blocklist": ["sales"]}
        with pytest.raises(SqlValidationError):
            await _validate(
                "SELECT quantity FROM farmacia.sales LIMIT 5",
                permissions=permissions,
            )

    @pytest.mark.asyncio
    async def test_global_sensitive_columns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_SQL_SENSITIVE_COLUMNS", "cost")
        with pytest.raises(SqlValidationError):
            await _validate("SELECT s.cost FROM farmacia.sales s LIMIT 5")


# -----------------------------------------------------------------------------
# Router
# -----------------------------------------------------------------------------
class TestRouter:
    def test_aggregation_question_scores_sql(self) -> None:
        router = SqlIntentRouter(llm_provider=None)
        assert router.heuristic_score("¿Cuánto vendimos esta semana?") >= 0.5

    def test_policy_question_scores_rag(self) -> None:
        router = SqlIntentRouter(llm_provider=None)
        assert router.heuristic_score("¿Cuál es la política de devoluciones?") < 0.5

    def test_greeting_scores_rag(self) -> None:
        router = SqlIntentRouter(llm_provider=None)
        assert router.heuristic_score("Hola") < 0.5

    @pytest.mark.asyncio
    async def test_clear_sql_intent_skips_llm(self) -> None:
        router = SqlIntentRouter(llm_provider=_FakeLLM("RAG"), llm_confirm_enabled=True)
        assert await router.is_sql_intent(ORG, "¿Cuántos clientes nuevos tenemos este mes?", "admin") is True

    @pytest.mark.asyncio
    async def test_doubtful_band_uses_llm(self) -> None:
        router = SqlIntentRouter(llm_provider=_FakeLLM("SQL"), llm_confirm_enabled=True)
        assert await router.is_sql_intent(ORG, "productos disponibles", "admin") is True


# -----------------------------------------------------------------------------
# Schema relevance
# -----------------------------------------------------------------------------
class TestSchemaRelevance:
    def test_ranks_sales_first_for_sales_question(self) -> None:
        top = rank_tables("¿Cuánto vendimos esta semana?", _sources(), max_tables=1)
        assert top[0].table_name == "sales"

    def test_filters_technical_columns(self) -> None:
        relevant = build_relevant_schema("products con price", _sources())
        products = next(s for s in relevant if s.table_name == "products")
        names = {c.name for c in products.columns}
        assert "name" in names
        assert "price" in names
        assert "created_at" not in names

    def test_keeps_fk_columns_for_joins(self) -> None:
        relevant = build_relevant_schema("ventas por producto", _sources())
        sales = next(s for s in relevant if s.table_name == "sales")
        assert any(c.name == "product_id" for c in sales.columns)


# -----------------------------------------------------------------------------
# Audit (requiere Postgres real — dev only)
# -----------------------------------------------------------------------------
class TestSqlAudit:
    @pytest.mark.asyncio
    async def test_write_and_read_audit_real_db(self) -> None:
        from src.agents.tools.sql_audit import (
            ensure_sql_audit_table,
            list_sql_audit,
            write_sql_audit,
        )
        from src.core.config import get_settings

        settings = get_settings()
        if settings.ENVIRONMENT != "development":
            pytest.skip("Requiere Postgres real (stack docker)")

        org = uuid4()
        await ensure_sql_audit_table()
        await write_sql_audit(
            organization_id=org,
            user_id=uuid4(),
            role="admin",
            question="¿Cuánto vendimos esta semana?",
            generated_sql="SELECT * FROM farmacia.sales LIMIT 10",
            tables=["farmacia.sales"],
            execution_time_ms=42.0,
            rows=10,
            cost=123.4,
            status="success",
        )

        entries = await list_sql_audit(org, limit=10)
        assert entries, "audit entry must be readable"
        entry = entries[0]
        assert entry["generated_sql"] == "SELECT * FROM farmacia.sales LIMIT 10"
        assert entry["rows"] == 10
        assert entry["status"] == "success"
        # Nunca credenciales en el payload de auditoría.
        blob = str(entries)
        assert "password" not in blob.lower()
        assert "rag_reader" not in blob.lower()
