# =============================================================================
# CSV/Excel import into managed database
# =============================================================================
from __future__ import annotations

from src.platform.managed_db.builder import FRIENDLY_TYPES, _ident


def infer_columns(headers: list[str], sample_rows: list[list[str]]) -> list[dict]:
    proposals: list[dict] = []
    for idx, header in enumerate(headers):
        values = [str(row[idx]) for row in sample_rows if idx < len(row)]
        friendly = _guess(header, values)
        proposals.append(
            {
                "source": header,
                "name": _label(header),
                "type": friendly,
                "unique": _looks_code(header),
            }
        )
    return proposals


def _label(header: str) -> str:
    mapping = {
        "codigo": "Product Code",
        "descripcion": "Description",
        "precio": "Price",
        "stock": "Stock",
    }
    key = (header or "").strip().lower()
    if key in mapping:
        return mapping[key]
    return header.replace("_", " ").title() or "Column"


def _guess(header: str, values: list[str]) -> str:
    key = (header or "").lower()
    if key in {"precio", "price", "amount", "monto"}:
        return "Money"
    if key in {"stock", "qty", "cantidad"}:
        return "Integer"
    if key in {"email"}:
        return "Email"
    if all(_is_int(v) for v in values if v):
        return "Integer"
    if all(_is_num(v) for v in values if v):
        return "Number"
    return "Text"


def _looks_code(header: str) -> bool:
    return (header or "").lower() in {"codigo", "code", "sku", "id"}


def _is_int(value: str) -> bool:
    try:
        int(str(value).replace(",", ""))
        return True
    except ValueError:
        return False


def _is_num(value: str) -> bool:
    try:
        float(str(value).replace(",", ""))
        return True
    except ValueError:
        return False


def create_table_proposal(table_name: str, columns: list[dict]) -> dict:
    return {
        "tables": [
            {
                "name": table_name,
                "fields": [
                    {
                        "name": col["name"],
                        "type": col["type"] if col["type"] in FRIENDLY_TYPES else "Text",
                        "unique": bool(col.get("unique")),
                    }
                    for col in columns
                ],
            }
        ],
        "relationships": [],
    }


def insert_sql(table_name: str, columns: list[dict], rows: list[list[str]]) -> str:
    tbl = _ident(table_name)
    names = [_ident(c["name"]) for col in columns for c in [col]]
    cols = ", ".join(f'"{n}"' for n in names)
    values = []
    for row in rows:
        rendered = []
        for i, _col in enumerate(columns):
            raw = row[i] if i < len(row) else ""
            rendered.append("'" + str(raw).replace("'", "''") + "'")
        values.append("(" + ", ".join(rendered) + ")")
    return f'INSERT INTO "{tbl}" ({cols}) VALUES ' + ", ".join(values)  # noqa: S608 — `_ident` sanitizes names, literals escape quotes
