# =============================================================================
# PhysicalResolver — business concepts → APPROVED (or INFERRED high) columns
# =============================================================================
# Never treat physical names as global truth. Critical missing mapping returns
# CONTEXT_MISSING with a Studio link. Raw inventory is not the primary SQL path.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.intelligence import AnswerabilityStatus
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_PRICE_HINTS = (
    "precio",
    "price",
    "unitprice",
    "unit price",
    "cuánto cuesta",
    "cuanto cuesta",
    "prc",
)
_COST_HINTS = ("costo", "cost", "cst")
_QTY_HINTS = ("cantidad", "quantity", "qty", "stock")
_ID_HINTS = ("código", "codigo", "code", "identifier", "id de")
_ACTIVE_HINTS = ("activo", "activos", "active")

_CRITICAL_ROLES = {"MEASURE", "IDENTIFIER"}


@dataclass
class ResolveResult:
    allowlist: dict[str, list[str]] = field(default_factory=dict)
    context_missing: bool = False
    message: str = ""
    studio_path: str = ""
    enum_predicates: list[dict] = field(default_factory=list)
    mapped_fields: list[dict] = field(default_factory=list)
    use_legacy: bool = False
    answerability: str | None = None


def _usable(field: dict) -> bool:
    if field.get("mapping_type") == "APPROVED_BY_SCHEMA_DESIGN":
        return True
    if field.get("status") == "approved" and field.get("mapped_column_id"):
        return True
    if field.get("provenance") == "REJECTED":
        return False
    if (
        field.get("mapped_column_id")
        and field.get("confidence") == "high"
        and field.get("status") != "rejected"
        and field.get("provenance") == "INFERRED"
    ):
        return True
    return False


def _norm(text: str) -> str:
    return (text or "").strip().lower()


class PhysicalResolver:
    """Resolve business AST / question tokens against governed catalog fields."""

    def __init__(self, store: PostgresCatalogStore | None = None) -> None:
        self._store = store or PostgresCatalogStore()

    async def resolve_question(
        self,
        organization_id: UUID,
        question: str,
        *,
        source_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ResolveResult:
        await self._store.ensure_tables()
        fields = await self._store.list_fields_all(
            organization_id, limit=2000, workspace_id=workspace_id
        )
        q = _norm(question)
        enums = await self._enum_predicates(organization_id, q, source_id)
        if not fields:
            if enums:
                allowlist: dict[str, list[str]] = {}
                for pred in enums:
                    key = pred.get("qualified")
                    if key and pred.get("column"):
                        allowlist.setdefault(key, [])
                        if pred["column"] not in allowlist[key]:
                            allowlist[key].append(pred["column"])
                return ResolveResult(allowlist=allowlist, enum_predicates=enums)
            if self._needs_critical(q):
                return self._missing(
                    "Zent necesita saber qué campo es el precio",
                    source_id,
                    concept="precio",
                )
            return ResolveResult(use_legacy=True)

        entities = {
            e["id"]: e
            for e in await self._store.list_entities(organization_id, limit=1000)
        }
        needed = self._needed_concepts(q)
        mapped: list[dict] = []
        missing: list[str] = []
        for concept, hints in needed.items():
            hit = self._match_field(fields, hints)
            if hit is None or not _usable(hit):
                if concept in {"precio", "identificador"}:
                    missing.append(concept)
                continue
            mapped.append(hit)

        if missing:
            label = missing[0]
            copy = (
                "Zent necesita saber qué campo es el precio"
                if label == "precio"
                else f"Zent necesita saber qué campo es {label}"
            )
            return self._missing(copy, source_id, concept=label)

        allowlist: dict[str, list[str]] = {}
        details: list[dict] = []
        for fld in mapped:
            physical = await self._physical_for_field(organization_id, fld)
            if physical is None:
                continue
            key = physical["qualified"]
            allowlist.setdefault(key, [])
            if physical["column"] not in allowlist[key]:
                allowlist[key].append(physical["column"])
            entity = entities.get(str(fld.get("entity_id")) or "")
            details.append(
                {
                    **fld,
                    "entity_name": (entity or {}).get("name"),
                    "qualified_table": key,
                    "column_name": physical["column"],
                }
            )

        for pred in enums:
            key = pred.get("qualified")
            if key and pred.get("column"):
                allowlist.setdefault(key, [])
                if pred["column"] not in allowlist[key]:
                    allowlist[key].append(pred["column"])

        if not allowlist and self._needs_critical(q):
            return self._missing(
                "Zent necesita saber qué campo es el precio",
                source_id,
                concept="precio",
            )
        if not allowlist:
            return ResolveResult(use_legacy=True)
        return ResolveResult(
            allowlist=allowlist,
            mapped_fields=details,
            enum_predicates=enums,
        )

    def _missing(self, message: str, source_id: UUID | None, concept: str) -> ResolveResult:
        path = "/knowledge/understanding"
        if source_id:
            path = f"{path}?source_id={source_id}"
        return ResolveResult(
            context_missing=True,
            message=message,
            studio_path=path,
            answerability=AnswerabilityStatus.CONTEXT_MISSING.value,
        )

    @staticmethod
    def _needs_critical(question: str) -> bool:
        return any(h in question for h in _PRICE_HINTS + _COST_HINTS + _QTY_HINTS)

    @staticmethod
    def _needed_concepts(question: str) -> dict[str, tuple[str, ...]]:
        needed: dict[str, tuple[str, ...]] = {}
        if any(h in question for h in _PRICE_HINTS):
            needed["precio"] = ("unitprice", "unit price", "price", "precio", "prc")
        if any(h in question for h in _COST_HINTS):
            needed["costo"] = ("unitcost", "cost", "costo", "cst")
        if any(h in question for h in _QTY_HINTS):
            needed["cantidad"] = ("quantity", "qty", "stock", "cantidad")
        if any(h in question for h in _ID_HINTS):
            needed["identificador"] = ("code", "codigo", "código", "identifier")
        return needed

    @staticmethod
    def _match_field(fields: list[dict], hints: tuple[str, ...]) -> dict | None:
        best: dict | None = None
        best_score = 0
        for fld in fields:
            blob = " ".join(
                [
                    _norm(fld.get("name") or ""),
                    _norm(fld.get("description") or ""),
                    " ".join(_norm(s) for s in (fld.get("synonyms") or [])),
                ]
            )
            score = sum(1 for h in hints if h.replace(" ", "") in blob.replace(" ", ""))
            if score > best_score:
                best = fld
                best_score = score
        return best if best_score else None

    async def _physical_for_field(
        self, organization_id: UUID, field: dict
    ) -> dict | None:
        col_id = field.get("mapped_column_id")
        if not col_id:
            if field.get("mapping_type") == "APPROVED_BY_SCHEMA_DESIGN":
                entities = {
                    str(e["id"]): e
                    for e in await self._store.list_entities(organization_id, limit=1000)
                }
                entity = entities.get(str(field.get("entity_id") or ""))
                table = (entity or {}).get("name") or ""
                column = field.get("name") or ""
                if table and column:
                    return {
                        "qualified": f"public.{table}",
                        "column": column,
                        "table": {"table_name": table, "schema_name": "public"},
                    }
            return None
        column = await self._store.get_column(organization_id, UUID(str(col_id)))
        if column is None:
            return None
        table = await self._store.get_table(organization_id, UUID(column["table_id"]))
        if table is None:
            return None
        schema = table.get("schema_name") or ""
        name = table.get("table_name") or ""
        qualified = f"{schema}.{name}" if schema else name
        return {"qualified": qualified, "column": column["column_name"], "table": table}

    async def _enum_predicates(
        self, organization_id: UUID, question: str, source_id: UUID | None
    ) -> list[dict]:
        if not any(h in question for h in _ACTIVE_HINTS):
            return []
        sources = []
        if source_id:
            sources = [source_id]
        else:
            sources = [UUID(s["id"]) for s in await self._store.list_sources(organization_id)]
        out: list[dict] = []
        for sid in sources:
            for table in await self._store.list_tables(organization_id, sid, limit=500):
                cols = await self._store.list_columns(organization_id, UUID(table["id"]))
                for col in cols:
                    values = await self._store.list_enum_values(
                        organization_id, UUID(col["id"])
                    )
                    for val in values:
                        meaning = _norm(val.get("documented_meaning") or "")
                        if val.get("status") != "approved" or not meaning:
                            continue
                        if "active" in meaning or "activo" in meaning:
                            schema = table.get("schema_name") or ""
                            qualified = (
                                f"{schema}.{table['table_name']}"
                                if schema
                                else table["table_name"]
                            )
                            out.append(
                                {
                                    "qualified": qualified,
                                    "column": col["column_name"],
                                    "value": val["value"],
                                    "meaning": val["documented_meaning"],
                                }
                            )
        return out
