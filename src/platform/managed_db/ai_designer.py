# =============================================================================
# AI Database Designer — prompt → proposal (nothing created until Approve)
# =============================================================================
from __future__ import annotations

import json
import re

from src.core.ports import LLMProvider

_FALLBACK = {
    "tables": [
        {
            "name": "Products",
            "fields": [
                {"name": "Name", "type": "Text", "required": True},
                {"name": "Price", "type": "Money"},
                {"name": "Stock", "type": "Integer"},
            ],
        },
        {
            "name": "Customers",
            "fields": [
                {"name": "Name", "type": "Text", "required": True},
                {"name": "Email", "type": "Email"},
            ],
        },
        {
            "name": "Sales",
            "fields": [
                {"name": "customer_id", "type": "Relation", "required": True},
                {"name": "sold_at", "type": "Date & Time"},
            ],
        },
        {
            "name": "Sale Items",
            "fields": [
                {"name": "sale_id", "type": "Relation", "required": True},
                {"name": "product_id", "type": "Relation", "required": True},
                {"name": "quantity", "type": "Integer"},
            ],
        },
    ],
    "relationships": [
        {"from_table": "Sales", "from_column": "customer_id", "to_table": "Customers", "to_column": "id"},
        {"from_table": "Sale Items", "from_column": "sale_id", "to_table": "Sales", "to_column": "id"},
        {"from_table": "Sale Items", "from_column": "product_id", "to_table": "Products", "to_column": "id"},
    ],
}


async def propose_schema(prompt: str, llm: LLMProvider | None = None) -> dict:
    if llm is None:
        return {**_FALLBACK, "prompt": prompt}
    try:
        response = await llm.generate(
            prompt=(
                "Design a PostgreSQL business schema as JSON with keys tables "
                "(name, fields[{name,type,required,unique}]) and relationships "
                "[{from_table,from_column,to_table,to_column}]. Types must be one of: "
                "Text, Long Text, Number, Money, Integer, Boolean, Date, Date & Time, "
                f"Identifier, Relation, JSON, Email, Phone.\n\nUser: {prompt}"
            ),
            system_prompt="Return JSON only. No markdown.",
            temperature=0.2,
        )
        text = getattr(response, "content", None) or str(response)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            parsed = json.loads(match.group(0))
            if parsed.get("tables"):
                return parsed
    except Exception:  # noqa: BLE001
        pass
    return {**_FALLBACK, "prompt": prompt}
