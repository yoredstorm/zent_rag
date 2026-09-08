# =============================================================================
# Data Onboarding — preguntas de prueba a partir del understanding
# =============================================================================
from __future__ import annotations


def build_question_pack(kind: str, understanding: dict) -> list[dict]:
    questions: list[dict] = []
    if kind in ("spreadsheets", "documents", "drive", "website", "api"):
        entity = (understanding.get("likely_entity") or "datos").lower()
        columns = understanding.get("columns") or []
        names = [c.get("physical_name") or c.get("business") or "" for c in columns]
        joined = " ".join(names).lower()
        if "precio" in joined or "price" in joined:
            questions.append(
                {
                    "id": "q-expensive",
                    "text": "¿Cuál es el producto más caro?",
                }
            )
        if "stock" in joined:
            questions.append(
                {
                    "id": "q-stock",
                    "text": "¿Cuántos productos tienen stock bajo?",
                }
            )
        questions.append(
            {
                "id": "q-count",
                "text": f"¿Cuántos registros de {entity} hay?",
            }
        )
        topics = understanding.get("topics") or []
        if topics:
            questions.append(
                {
                    "id": "q-topic",
                    "text": f"¿Qué dice el documento sobre {topics[0]}?",
                }
            )
    else:
        entities = understanding.get("entities") or []
        names = [e.get("display_name") or e.get("name") for e in entities if e]
        if any("product" in (n or "").lower() or "producto" in (n or "").lower() for n in names):
            questions.append({"id": "q-expensive", "text": "¿Cuál es el producto más caro?"})
        if any("sale" in (n or "").lower() or "venta" in (n or "").lower() for n in names):
            questions.append(
                {"id": "q-sales", "text": "¿Cuáles fueron las ventas totales el mes pasado?"}
            )
            questions.append(
                {"id": "q-category", "text": "¿Qué categoría vende más?"}
            )
        if names:
            questions.append(
                {
                    "id": "q-entity",
                    "text": f"¿Cuántos {names[0]} hay?",
                }
            )
    if not questions:
        questions.append({"id": "q-generic", "text": "¿Qué información hay en esta fuente?"})
    # unique by id
    seen: set[str] = set()
    out = []
    for q in questions:
        if q["id"] in seen:
            continue
        seen.add(q["id"])
        out.append(q)
    return out[:6]
