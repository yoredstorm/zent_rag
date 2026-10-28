# =============================================================================
# P18.1-09 — knowledge_explorer_insight/v1 (read model determinista)
# =============================================================================
# Proyección de lectura sobre la autoridad existente: perfil documental,
# secciones, objetos canónicos y Evidence Ledger. No crea hechos, no escribe
# conocimiento y no llama a un LLM. Cada idea declarada debe abrir una fuente.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone

from src.knowledge.compiler.candidates import (
    assess_entity_candidate,
    looks_like_dialogue,
    looks_like_question,
)

CONTRACT = "knowledge_explorer_insight/v1"
MODEL_VERSION = "deterministic-explorer-1"

_GROUP_BY_GENRE: dict[str, list[tuple[set[str], str, str]]] = {
    "technical": [
        (
            {"field", "column", "table", "attribute", "record", "database"},
            "Campos, tablas y estructura",
            "Elementos de esquema con una ubicación verificable.",
        ),
        (
            {"business_rule", "rule", "constraint"},
            "Reglas y restricciones",
            "Restricciones declaradas con contexto normativo.",
        ),
        (
            {"concept", "term", "process", "procedure", "entity"},
            "Conceptos y procesos",
            "Términos definidos por el documento.",
        ),
    ],
    "narrative": [
        (
            {"concept", "term", "entity", "event"},
            "Personajes, temas y elementos",
            "Elementos reconocidos en la narración; se muestran como interpretación.",
        ),
        (
            {"business_rule", "rule", "constraint"},
            "Pasajes normativos o citas",
            "Afirmaciones que no se promueven automáticamente a reglas de negocio.",
        ),
    ],
    "policy": [
        (
            {"business_rule", "rule", "constraint"},
            "Obligaciones y reglas",
            "Obligaciones con contexto normativo y evidencia.",
        ),
        (
            {"concept", "term", "process", "entity"},
            "Conceptos y responsables",
            "Términos y actores definidos por la política.",
        ),
    ],
    "legal": [
        (
            {"business_rule", "rule", "constraint"},
            "Obligaciones contractuales",
            "Obligaciones, condiciones y restricciones del contrato.",
        ),
        (
            {"concept", "term", "entity"},
            "Partes y conceptos",
            "Términos definidos por el contrato.",
        ),
    ],
    "tabular": [
        (
            {"table"},
            "Tablas",
            "Tablas detectadas en el archivo.",
        ),
        (
            {"column", "field", "metric"},
            "Campos y métricas",
            "Columnas y métricas con valores localizables.",
        ),
    ],
}

_DEFAULT_GROUPS = [
    (
        {"concept", "term", "entity", "event"},
        "Conceptos",
        "Términos reconocidos con evidencia.",
    ),
    (
        {"business_rule", "rule", "constraint"},
        "Reglas",
        "Afirmaciones normativas con evidencia.",
    ),
    (
        {"field", "column", "table", "attribute"},
        "Estructura",
        "Campos y tablas con ubicación.",
    ),
]


def _uncertainty(status: str, has_evidence: bool) -> str:
    if not has_evidence:
        return "alta"
    if status in {"verified"}:
        return "baja"
    if status in {"discovered", "draft", "inferred"}:
        return "media"
    return "media"


def _group_for(genre: str, kind: str) -> tuple[str, str] | None:
    groups = _GROUP_BY_GENRE.get(genre, _DEFAULT_GROUPS)
    for kinds, label, summary in groups:
        if kind in kinds:
            return label, summary
    return None


def _visible_object(obj: dict) -> tuple[bool, str]:
    metadata = obj.get("metadata") or {}
    if metadata.get("explorer_visibility") == "hidden":
        return False, "oculto por revisión"
    name = str(obj.get("name") or obj.get("display_name") or "").strip()
    kind = str(obj.get("kind") or obj.get("type") or "concept")
    if looks_like_question(name) or looks_like_dialogue(name):
        return False, "pregunta o diálogo"
    if name.isdigit() and kind not in {"field", "column", "table", "record"}:
        return False, "número aislado"
    decision = assess_entity_candidate(name, kind=kind)
    if not decision.accepted:
        return False, decision.reason
    return True, ""


def build_explorer_insight(
    *,
    source: dict,
    document: dict | None,
    objects: list[dict],
    evidence: list[dict],
    generated_at: str | None = None,
) -> dict:
    metadata = (document or {}).get("metadata") or {}
    understanding = metadata.get("understanding") or {}
    profile = understanding.get("profile") or {}
    report = understanding.get("report") or {}
    genre = str(profile.get("document_genre") or "unknown")
    genre_confidence = profile.get("genre_confidence")

    evidence_by_object: dict[str, list[dict]] = {}
    for item in evidence:
        canonical_id = item.get("canonical_id")
        if canonical_id:
            evidence_by_object.setdefault(str(canonical_id), []).append(item)

    visible: list[dict] = []
    hidden = 0
    hidden_reasons: dict[str, int] = {}
    for obj in objects:
        ok, reason = _visible_object(obj)
        if not ok:
            hidden += 1
            hidden_reasons[reason] = hidden_reasons.get(reason, 0) + 1
            continue
        visible.append(obj)

    topics: dict[str, dict] = {}
    insights: list[dict] = []
    for obj in visible[:200]:
        kind = str(obj.get("kind") or obj.get("type") or "concept")
        group = _group_for(genre, kind)
        if group is None:
            continue
        label, summary = group
        topic = topics.setdefault(
            label,
            {
                "id": _slug(label),
                "label": label,
                "summary": summary,
                "scope": "documento",
                "source_locator": None,
                "verification_state": "mixed",
                "insights": [],
                "count": 0,
            },
        )
        evidence_items = evidence_by_object.get(str(obj.get("id")), [])
        first = evidence_items[0] if evidence_items else {}
        has_evidence = bool(first.get("excerpt"))
        name = str(obj.get("name") or obj.get("display_name") or "").strip()
        description = str(obj.get("description") or "").strip()
        claim_text = description[:400] if description else f"Hallazgo «{name}» sin descripción sustentada."
        insight = {
            "kind": kind,
            "object_id": str(obj.get("id")) if obj.get("id") else None,
            "name": name,
            "claim_text": claim_text,
            "grounded_excerpt": (first.get("excerpt") or None) if has_evidence else None,
            "evidence_ids": [
                str(item.get("id")) for item in evidence_items if item.get("id")
            ][:8],
            "source_locator": {
                "page": first.get("page"),
                "section_path": first.get("section_path") or [],
                "locator": first.get("locator"),
            },
            "verification_state": obj.get("status") or "discovered",
            "uncertainty": _uncertainty(str(obj.get("status") or ""), has_evidence),
            "confidence": obj.get("confidence"),
            "why_related": f"Agrupado por tipo «{kind}» dentro de este documento.",
        }
        topic["insights"].append(insight)
        topic["count"] += 1
        insights.append(insight)
        locator = insight["source_locator"]
        if topic["source_locator"] is None and locator.get("page"):
            topic["source_locator"] = {
                "page": locator.get("page"),
                "section_path": locator.get("section_path") or [],
            }

    warnings: list[dict] = []
    if not objects:
        warnings.append(
            {
                "code": "NO_OBJECTS",
                "message": "Todavía no hay hallazgos canónicos para esta fuente.",
                "severity": "warning",
            }
        )
    elif not visible:
        warnings.append(
            {
                "code": "ONLY_LOW_UTILITY",
                "message": "Los hallazgos detectados no tienen autonomía semántica suficiente; puedes revisar los pasajes.",
                "severity": "warning",
            }
        )
    if hidden:
        warnings.append(
            {
                "code": "HIDDEN_CANDIDATES",
                "message": f"{hidden} candidatos de baja utilidad se conservan en revisión, no en la vista principal.",
                "severity": "info",
                "reasons": hidden_reasons,
            }
        )
    if genre == "unknown":
        warnings.append(
            {
                "code": "GENRE_UNKNOWN",
                "message": "No hay una clasificación de género suficientemente sustentada.",
                "severity": "warning",
            }
        )
    if visible and not any(item.get("grounded_excerpt") for item in insights):
        warnings.append(
            {
                "code": "NO_OPENABLE_EVIDENCE",
                "message": "No hay una descripción fiable; los hallazgos existen pero no tienen un pasaje abrible.",
                "severity": "warning",
            }
        )

    ordered_topics = sorted(
        topics.values(), key=lambda item: (-item["count"], item["label"])
    )[:6]
    for topic in ordered_topics:
        topic["insights"] = topic["insights"][:40]

    source_fingerprint = (document or {}).get("content_hash") or source.get("content_hash")
    return {
        "contract": CONTRACT,
        "model_version": MODEL_VERSION,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "source_id": str(source.get("id") or source.get("source_id") or ""),
            "document_id": str((document or {}).get("id") or "") or None,
            "name": source.get("name"),
            "source_type": source.get("type"),
            "status": source.get("status"),
            "genre": genre,
            "genre_confidence": genre_confidence,
            "genre_evidence": profile.get("genre_evidence") or [],
            "document_type": profile.get("document_type"),
            "pages": report.get("pages") or (document or {}).get("page_count"),
            "sections": report.get("sections") or (document or {}).get("section_count"),
            "tables": report.get("tables") or (document or {}).get("table_count"),
            "characters": None,
        },
        "summary": _summary(genre, visible, insights, warnings),
        "topics": ordered_topics,
        "insights": insights[:200],
        "warnings": warnings,
        "provenance": {
            "source_fingerprint": source_fingerprint,
            "source_profile_version": profile.get("profile_version"),
            "contract": CONTRACT,
            "method": "deterministic",
            "authority": "read_model",
        },
        "counts": {
            "objects_total": len(objects),
            "objects_visible": len(visible),
            "objects_hidden": hidden,
            "insights": len(insights),
            "topics": len(ordered_topics),
        },
    }


def _summary(
    genre: str,
    visible: list[dict],
    insights: list[dict],
    warnings: list[dict],
) -> str:
    if not visible:
        return "Solo se identificaron secciones y pasajes; no podemos afirmar temas con certeza."
    grounded = sum(1 for item in insights if item.get("grounded_excerpt"))
    genre_label = {
        "narrative": "narrativa",
        "technical": "técnica",
        "policy": "política",
        "legal": "legal",
        "tabular": "tabular",
        "mixed": "mixta",
        "educational": "educativa",
        "unknown": "sin género confirmado",
    }.get(genre, genre)
    text = (
        f"Documento de naturaleza {genre_label}. "
        f"ZENT encontró {len(visible)} hallazgos visibles; "
        f"{grounded} tienen un pasaje abrible."
    )
    if any(item.get("code") == "GENRE_UNKNOWN" for item in warnings):
        text += " La clasificación de género es provisional."
    return text


def _slug(value: str) -> str:
    return (
        "".join(char.lower() if char.isalnum() else "-" for char in value)
        .strip("-")
        .replace("--", "-")[:60]
        or "tema"
    )


__all__ = ["CONTRACT", "MODEL_VERSION", "build_explorer_insight"]
