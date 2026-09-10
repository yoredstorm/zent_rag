# =============================================================================
# Data Onboarding — preguntas de prueba a partir del understanding
# =============================================================================
from __future__ import annotations


def _facts(understanding: dict) -> list[dict]:
    return understanding.get("facts") or []


def _document_questions(understanding: dict) -> list[dict]:
    questions: list[dict] = []
    facts = _facts(understanding)
    types = [f.get("fact_type") for f in facts]
    keys = " ".join(
        (f.get("key") or "").lower().replace("í", "i").replace("ó", "o")
        for f in facts
    )
    if "party" in types:
        questions.append({"id": "q-parties", "text": "¿Quiénes son las partes de este documento?"})
    if "date" in types and "fecha de termino" in keys:
        questions.append({"id": "q-term", "text": "¿Cuál es la fecha de término o vencimiento?"})
    if "date" in types and "fecha de inicio" in keys:
        questions.append({"id": "q-start", "text": "¿Cuál es la fecha de inicio o vigencia?"})
    if "amount" in types:
        questions.append({"id": "q-amount", "text": "¿Cuánto se paga y con qué periodicidad?"})
    if "clause" in types and ("renovac" in keys or "prorrog" in keys):
        questions.append({"id": "q-renew", "text": "¿Cómo se renueva el contrato?"})
    topics = understanding.get("topics") or []
    if topics:
        questions.append({"id": "q-topic", "text": f"¿Qué dice el documento sobre {topics[0]}?"})
    if not questions:
        questions.append({"id": "q-content", "text": "¿Qué información clave contiene este documento?"})
    return _unique(questions)


def _tabular_questions(kind: str, understanding: dict) -> list[dict]:
    questions: list[dict] = []
    entity = (understanding.get("likely_entity") or "datos").lower()
    columns = understanding.get("columns") or []
    names = [c.get("physical_name") or c.get("business") or "" for c in columns]
    joined = " ".join(names).lower()
    if "precio" in joined or "price" in joined:
        questions.append(
            {"id": "q-expensive", "text": "¿Cuál es el producto más caro?"}
        )
    if "stock" in joined:
        questions.append(
            {"id": "q-stock", "text": "¿Cuántos productos tienen stock bajo?"}
        )
    if columns:
        questions.append(
            {"id": "q-count", "text": f"¿Cuántos registros de {entity} hay?"}
        )
    topics = understanding.get("topics") or []
    if topics:
        questions.append(
            {"id": "q-topic", "text": f"¿Qué dice el documento sobre {topics[0]}?"}
        )
    return _unique(questions)


def _database_questions(understanding: dict) -> list[dict]:
    questions: list[dict] = []
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
            {"id": "q-entity", "text": f"¿Cuántos {names[0]} hay?"}
        )
    return _unique(questions)


def _unique(questions: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for q in questions:
        if q["id"] in seen:
            continue
        seen.add(q["id"])
        out.append(q)
    return out[:6]


def build_question_pack(kind: str, understanding: dict) -> list[dict]:
    if kind == "documents":
        questions = _document_questions(understanding)
    elif kind == "database":
        questions = _database_questions(understanding)
    else:
        questions = _tabular_questions(kind, understanding)
    if not questions:
        questions.append({"id": "q-generic", "text": "¿Qué información hay en esta fuente?"})
    return _unique(questions)
