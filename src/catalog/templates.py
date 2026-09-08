# =============================================================================
# Semantic entity templates — proposed slots, never forced
# =============================================================================
from __future__ import annotations

TEMPLATES: dict[str, list[dict[str, str]]] = {
    "Product": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Name", "role": "DESCRIPTION"},
        {"slot": "Description", "role": "DESCRIPTION"},
        {"slot": "Price", "role": "MEASURE"},
        {"slot": "Cost", "role": "MEASURE"},
        {"slot": "Stock", "role": "MEASURE"},
        {"slot": "Category", "role": "CATEGORY"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Customer": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Name", "role": "DESCRIPTION"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Sale": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Date", "role": "DATE"},
        {"slot": "Amount", "role": "MEASURE"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Invoice": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Date", "role": "DATE"},
        {"slot": "Amount", "role": "MEASURE"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Employee": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Name", "role": "DESCRIPTION"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Supplier": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Name", "role": "DESCRIPTION"},
    ],
    "Order": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Date", "role": "DATE"},
        {"slot": "Status", "role": "STATUS"},
        {"slot": "Amount", "role": "MEASURE"},
    ],
    "Inventory": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Stock", "role": "MEASURE"},
        {"slot": "Status", "role": "STATUS"},
    ],
    "Category": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Name", "role": "DESCRIPTION"},
    ],
    "Payment": [
        {"slot": "Identifier", "role": "IDENTIFIER"},
        {"slot": "Amount", "role": "MEASURE"},
        {"slot": "Date", "role": "DATE"},
        {"slot": "Status", "role": "STATUS"},
    ],
}


def template_for(entity_name: str) -> dict | None:
    key = (entity_name or "").strip()
    slots = TEMPLATES.get(key)
    if not slots:
        return None
    return {"entity": key, "slots": slots}
