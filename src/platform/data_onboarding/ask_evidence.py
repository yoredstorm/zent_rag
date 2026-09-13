# =============================================================================
# Data Onboarding — etiquetas de evidencia para el paso Probar
# =============================================================================
from __future__ import annotations

KIND = {
    "document_chunk": "documento",
    "sql_result": "consulta",
    "api_response": "API",
    "tool_result": "herramienta",
    "semantic_definition": "definición",
    "approved_metric": "métrica",
    "human_verified_context": "verificado",
}


def _clip(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= 140:
        return compact
    return compact[:137] + "…"


def _one(item: object) -> str | None:
    if isinstance(item, str):
        text = item.strip()
        return text or None
    if not isinstance(item, dict):
        return None
    snippet = _clip(
        str(
            item.get("snippet")
            or item.get("content")
            or item.get("text")
            or item.get("excerpt")
            or ""
        )
    )
    source = str(item.get("source_name") or item.get("title") or "").strip()
    kind = KIND.get(str(item.get("type") or "").lower(), "")
    page = item.get("page")
    parts: list[str] = []
    if source:
        parts.append(source)
    if kind and kind.lower() not in {p.lower() for p in parts}:
        parts.append(kind)
    if page not in (None, ""):
        parts.append(f"pág. {page}")
    if snippet:
        parts.append(snippet)
    return " · ".join(parts) if parts else None


def format_ask_evidence(items: list | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        label = _one(item)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
        if len(out) >= 8:
            break
    return out
