# =============================================================================
# Diagnóstico de entendimiento sin LLM
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.understanding.retrieval import expand_exact
from src.rag.longcontext.source_router import profile_from_source, route_sources


def reprocess_report(before: StructuredDocument | None, after: StructuredDocument) -> dict:
    """Conteos antes y después. No reindexa ni embebe."""

    def counts(doc: StructuredDocument) -> dict:
        payload = doc.metadata.get("understanding") or doc.metadata.get("understanding_shadow") or {}
        return {
            "sections": doc.section_count,
            "tables": doc.table_count,
            "literals": len(payload.get("exact_literals") or []),
            "retrieval_units": payload.get("semantic_unit_count"),
        }

    return {"before": counts(before) if before is not None else None, "after": counts(after)}


def regression_gate(before_scores: dict, after_scores: dict) -> list[str]:
    """No acepta una bajada de recall cuando hay ground truth."""
    failed: list[str] = []
    for key in ("exact_literal_recall", "structure_recall", "table_recall", "field_recall"):
        if key in before_scores and key in after_scores and after_scores[key] < before_scores[key]:
            failed.append(key)
    return failed


def score_expected(document: StructuredDocument, expected: dict | None) -> dict:
    """Recall solo si hay ground truth. Sin manifiesto no inventa métricas."""
    if not isinstance(expected, dict) or not expected:
        return {}
    payload = document.metadata.get("understanding") or {}
    found_sections = [section.heading for section in document.sections if section.heading]
    found_literals = [item.get("value") for item in payload.get("exact_literals") or []]
    found_fields = [item.get("name") for item in payload.get("technical_fields") or []]
    scores: dict[str, float] = {}
    if expected.get("sections"):
        scores["structure_recall"] = _recall(found_sections, list(expected["sections"]))
    if expected.get("exact_literals"):
        scores["exact_literal_recall"] = _recall(found_literals, list(expected["exact_literals"]))
    if expected.get("fields"):
        scores["field_recall"] = _recall(found_fields, list(expected["fields"]))
    if "tables" in expected:
        wanted = int(expected["tables"])
        scores["table_recall"] = 1.0 if document.table_count == wanted else 0.0
    return scores


def diagnose_question(
    document: StructuredDocument,
    chunks: list,
    query: str,
    *,
    field_name: str | None = None,
    literal: str | None = None,
    example: str | None = None,
) -> dict:
    """Capas separadas. GENERATION no corre: no se culpa al modelo."""
    payload = document.metadata.get("understanding") or {}
    profile = payload.get("profile") or {}
    literals = payload.get("exact_literals") or []
    fields = payload.get("technical_fields") or []
    owned = next((item for item in literals if literal and item.get("value") == literal), None)
    field = next((item for item in fields if field_name and item.get("name") == field_name), None)
    expanded = expand_exact(chunks, literal) if literal else None
    parent = expanded.get("parent") if expanded else None
    child = expanded.get("child") if expanded else None
    route = _route(document, query, profile)
    preferred = bool(route.get("preferred"))
    ingestion_ok = bool(document.sections or literals or fields)
    if literal and field_name:
        ingestion_ok = bool(
            owned
            and owned.get("block_id")
            and owned.get("section_id")
            and owned.get("field_name") == field_name
            and owned.get("page")
        )
    layers = {
        "INGESTION": "PASS" if ingestion_ok else "FAIL",
        "SOURCE_ROUTING": "PASS" if preferred else "FAIL",
        "EXACT_RETRIEVAL": "PASS" if (literal and child is not None) or (not literal and chunks) else "FAIL",
        "STRUCTURAL_EXPANSION": "PASS"
        if parent is not None and (not field_name or field_name in (parent.content or ""))
        else "FAIL",
        "EVIDENCE": "PASS"
        if child is not None and child.metadata.get("block_ids")
        else "FAIL",
        "GENERATION": "SKIPPED",
    }
    return {
        "layers": layers,
        "source_route": route,
        "field": field,
        "literal": owned,
        "example": {
            "value": example,
            "role": "EXAMPLE_VALUE",
            "source_match_required": False,
        }
        if example
        else None,
        "child_unit": child.metadata.get("retrieval_unit") if child is not None else None,
        "child_block_ids": child.metadata.get("block_ids") if child is not None else None,
        "parent_heading": parent.metadata.get("heading") if parent is not None else None,
        "parent_unit": parent.metadata.get("retrieval_unit") if parent is not None else None,
    }


def find_literal(document: StructuredDocument, chunks: list, needle: str) -> dict:
    payload = document.metadata.get("understanding") or {}
    owned = next(
        (item for item in payload.get("exact_literals") or [] if item.get("value") == needle),
        None,
    )
    expanded = expand_exact(chunks, needle)
    child = expanded.get("child") if expanded else None
    parent = expanded.get("parent") if expanded else None
    units = payload.get("retrieval_units") or []
    unit = next(
        (
            item
            for item in units
            if needle in (item.get("exact_literals") or [])
            and item.get("unit_type") != "SECTION"
        ),
        None,
    )
    return {
        "found": owned is not None or child is not None,
        "document": document.title,
        "page": (owned or {}).get("page") if owned else (child.page_start if child else None),
        "section_id": (owned or {}).get("section_id") if owned else None,
        "field_name": (owned or {}).get("field_name") if owned else None,
        "block_id": (owned or {}).get("block_id") if owned else None,
        "retrieval_unit": unit or (child.metadata.get("unit_id") if child else None),
        "parent_unit": parent.metadata.get("unit_id") if parent is not None else None,
        "parent_heading": parent.metadata.get("heading") if parent is not None else None,
    }


def _route(document: StructuredDocument, query: str, profile: dict) -> dict:
    name = str(profile.get("normalized_filename") or document.title or "document")
    title = str(profile.get("title") or document.title or "")
    terms = list(profile.get("section_paths") or []) + list(profile.get("field_vocabulary") or [])
    source = profile_from_source(
        str(document.source_id or document.id),
        name,
        title=title,
        document_type=str(profile.get("document_type") or ""),
        section_terms=terms,
        summary=str(profile.get("content_summary") or ""),
    )
    route = route_sources(query, [source])
    return route.to_public_dict()


def _recall(found: list, expected: list) -> float:
    if not expected:
        return 0.0
    haystack = {str(item) for item in found}
    hits = sum(1 for item in expected if str(item) in haystack)
    return round(hits / len(expected), 4)
