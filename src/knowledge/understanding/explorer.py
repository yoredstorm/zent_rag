# =============================================================================
# P18.1-09 — knowledge_explorer_insight/v1 (read model determinista)
# =============================================================================
# Proyección de lectura sobre la autoridad existente: perfil documental,
# secciones, objetos canónicos y Evidence Ledger. No crea hechos, no escribe
# conocimiento y no llama a un LLM. Cada idea declarada debe abrir una fuente.
# =============================================================================
from __future__ import annotations

import re
from datetime import datetime, timezone

from src.knowledge.compiler.candidates import (
    assess_entity_candidate,
    looks_like_dialogue,
    looks_like_question,
)
from src.knowledge.understanding.passages import build_passage_understanding
from src.knowledge.understanding.versions import SOURCE_PROFILE_VERSION

CONTRACT = "knowledge_explorer_insight/v2"
MODEL_VERSION = "deterministic-explorer-2"

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


_HEADING_NAMES = {
    "presentación",
    "presentacion",
    "introducción",
    "introduccion",
    "prólogo",
    "prologo",
    "capítulo",
    "capitulo",
    "índice",
    "indice",
}
_NORMATIVE_TEXT = re.compile(
    r"\b(debe|deben|deberá|deberan|obligatorio|obligatoria|prohibido|"
    r"prohibida|must|shall|required|forbidden|no\s+debe)\b",
    re.IGNORECASE,
)


def _visible_object(obj: dict, document: dict | None = None) -> tuple[bool, str]:
    metadata = obj.get("metadata") or {}
    if metadata.get("explorer_visibility") == "hidden":
        return False, "oculto por revisión"
    name = str(obj.get("name") or obj.get("display_name") or "").strip()
    kind = str(obj.get("kind") or obj.get("type") or "concept")
    if looks_like_question(name) or looks_like_dialogue(name):
        return False, "pregunta o diálogo"
    if name.isdigit() and kind not in {"field", "column", "table", "record"}:
        return False, "número aislado"
    profile = ((document or {}).get("metadata") or {}).get("understanding", {}).get("profile") or {}
    genre = str(profile.get("document_genre") or "unknown")
    if name.casefold() in _HEADING_NAMES and genre in {"narrative", "unknown"}:
        return False, "encabezado de sección"
    if kind in {"business_rule", "rule"} and not _NORMATIVE_TEXT.search(str(obj.get("description") or "")):
        return False, "regla sin contexto normativo"
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
    documents: list[dict] | None = None,
    read_stats: dict | None = None,
    blocks: list[dict] | None = None,
) -> dict:
    metadata = (document or {}).get("metadata") or {}
    understanding = metadata.get("understanding") or {}
    profile = understanding.get("profile") or {}
    report = understanding.get("report") or {}
    genre = str(profile.get("document_genre") or "unknown")
    genre_confidence = profile.get("genre_confidence")
    documents = documents or ([document] if document else [])
    passage_view = (
        build_passage_understanding(
            document=document,
            blocks=blocks or [],
            genre=genre,
        )
        if blocks
        else {
            "method": "none",
            "narrative_signal": False,
            "structure": [],
            "passages": [],
            "participants": [],
            "themes": [],
            "relations": [],
            "mentions_scanned": 0,
        }
    )

    # La evidencia más fuerte primero. No se elige "la primera" por fecha como
    # si fuera la mejor: eso mezclaba causalidad de consulta con calidad.
    evidence = sorted(
        evidence,
        key=lambda item: (
            float(item.get("strength") or 0),
            str(item.get("created_at") or ""),
        ),
        reverse=True,
    )
    evidence_by_object: dict[str, list[dict]] = {}
    seen_evidence: set[str] = set()
    for item in evidence:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen_evidence:
            continue
        if item_id:
            seen_evidence.add(item_id)
        canonical_id = item.get("canonical_id")
        if canonical_id:
            evidence_by_object.setdefault(str(canonical_id), []).append(item)

    visible: list[dict] = []
    hidden = 0
    hidden_reasons: dict[str, int] = {}
    seen_objects: set[str] = set()
    for obj in objects:
        object_id = str(obj.get("id") or "")
        if object_id and object_id in seen_objects:
            continue
        if object_id:
            seen_objects.add(object_id)
        ok, reason = _visible_object(obj, document)
        if not ok:
            hidden += 1
            hidden_reasons[reason] = hidden_reasons.get(reason, 0) + 1
            continue
        visible.append(obj)

    # Deduplicación de presentación por identidad semántica dentro de la
    # fuente. No borra filas: oculta duplicados de la vista y los cuenta.
    deduped: list[dict] = []
    seen_identity: set[tuple[str, str]] = set()
    for obj in visible:
        kind = str(obj.get("kind") or obj.get("type") or "concept").lower()
        name = str(obj.get("name") or obj.get("display_name") or "").strip().casefold()
        identity = (kind, " ".join(name.split()))
        if identity in seen_identity:
            hidden += 1
            hidden_reasons["duplicado de presentación"] = hidden_reasons.get("duplicado de presentación", 0) + 1
            continue
        seen_identity.add(identity)
        deduped.append(obj)
    visible = deduped

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
            "evidence_ids": [str(item.get("id")) for item in evidence_items if item.get("id")][:8],
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

    proposals: list[dict] = []
    for participant in passage_view.get("participants") or []:
        proposals.append(
            {
                "kind": "character",
                "object_id": None,
                "name": participant["label"],
                "claim_text": (
                    f"Participa en diálogos y aparece en {participant['mentions']} "
                    "pasajes. Es una propuesta derivada del texto, no un objeto "
                    "canónico verificado."
                ),
                "grounded_excerpt": participant.get("excerpt") or None,
                "evidence_ids": [],
                "source_locator": {
                    "page": participant.get("page"),
                    "section_path": [],
                    "locator": None,
                },
                "verification_state": "proposed",
                "uncertainty": "media",
                "confidence": None,
                "why_related": "Atribución de diálogo detectada en el pasaje.",
                "method": passage_view.get("method"),
            }
        )
    for theme in passage_view.get("themes") or []:
        proposals.append(
            {
                "kind": "theme",
                "object_id": None,
                "name": theme["label"],
                "claim_text": (
                    f"Se repite en {theme['mentions']} pasajes. Es un elemento "
                    "del relato, no una afirmación verificada."
                ),
                "grounded_excerpt": theme.get("excerpt") or None,
                "evidence_ids": [],
                "source_locator": {
                    "page": theme.get("page"),
                    "section_path": [],
                    "locator": None,
                },
                "verification_state": "proposed",
                "uncertainty": "alta",
                "confidence": None,
                "why_related": "Término recurrente en pasajes del documento.",
                "method": passage_view.get("method"),
            }
        )
    if proposals:
        topics["passages"] = {
            "id": "passages",
            "label": "Personajes y elementos propuestos",
            "summary": (
                "Detectados por contexto de pasajes. Son propuestas abribles, "
                "no conocimiento verificado ni hechos del dominio."
            ),
            "scope": "documento",
            "source_locator": next(
                (
                    {
                        "page": item["source_locator"]["page"],
                        "section_path": [],
                    }
                    for item in proposals
                    if item["source_locator"]["page"]
                ),
                None,
            ),
            "verification_state": "proposed",
            "insights": proposals,
            "count": len(proposals),
        }
        insights.extend(proposals)

    warnings: list[dict] = []
    if proposals:
        warnings.append(
            {
                "code": "PROPOSALS_NOT_VERIFIED",
                "message": (f"{len(proposals)} elementos se proponen desde pasajes; no son hechos verificados."),
                "severity": "info",
            }
        )
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
                "message": (
                    "Los hallazgos detectados no tienen autonomía semántica suficiente; puedes revisar los pasajes."
                ),
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
    if visible and not any(
        item.get("grounded_excerpt") and item.get("verification_state") != "proposed" for item in insights
    ):
        warnings.append(
            {
                "code": "NO_OPENABLE_EVIDENCE",
                "message": "No hay una descripción fiable; los hallazgos existen pero no tienen un pasaje abrible.",
                "severity": "warning",
            }
        )

    ordered_topics = sorted(topics.values(), key=lambda item: (-item["count"], item["label"]))[:6]
    for topic in ordered_topics:
        topic["insights"] = topic["insights"][:40]

    stats = read_stats or {}
    objects_total = int(stats.get("objects_total") or len(objects))
    evidence_total = int(stats.get("evidence_total") or len(evidence))
    documents_total = int(stats.get("documents_total") or len(documents))
    objects_truncated = bool(stats.get("objects_truncated")) or objects_total > len(objects)
    evidence_truncated = bool(stats.get("evidence_truncated")) or evidence_total > len(evidence)
    documents_truncated = bool(stats.get("documents_truncated")) or documents_total > len(documents)
    passages_available = int(
        stats.get("passages_available") or sum(1 for item in evidence if str(item.get("excerpt") or "").strip())
    )
    truncated = objects_truncated or evidence_truncated or documents_truncated or bool(stats.get("blocks_truncated"))
    if truncated:
        warnings.append(
            {
                "code": "READ_TRUNCATED",
                "message": (
                    "Esta lectura no cubre todo el documento; los conteos indican qué se leyó y qué quedó fuera."
                ),
                "severity": "warning",
            }
        )

    source_fingerprint = (document or {}).get("content_hash") or source.get("content_hash")
    profile_version = str(profile.get("profile_version") or "")
    is_stale = not profile_version or profile_version != SOURCE_PROFILE_VERSION or genre == "unknown"
    limitations: list[str] = []
    if is_stale:
        limitations.append(
            "El perfil del documento es anterior o incompleto; la clasificación puede cambiar al reprocesarlo."
        )
    if proposals:
        limitations.append(
            "Los personajes y temas propuestos se derivan de pasajes y no son hechos verificados ni objetos canónicos."
        )
    if truncated:
        limitations.append("La lectura fue parcial; los conteos indican qué falta.")
    if documents_total > len(documents):
        limitations.append(f"La fuente contiene {documents_total} documentos; esta vista prioriza {len(documents)}.")
    if not evidence:
        limitations.append("No hay pasajes abribles registrados para esta fuente.")
    document_views = [
        {
            "document_id": str(item.get("id") or ""),
            "title": item.get("title"),
            "content_hash": item.get("content_hash"),
            "pages": item.get("page_count"),
            "sections": item.get("section_count"),
            "tables": item.get("table_count"),
            "status": item.get("status"),
            "updated_at": item.get("updated_at"),
            "primary": index == 0,
        }
        for index, item in enumerate(documents[:20])
    ]
    return {
        "contract": CONTRACT,
        "model_version": MODEL_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
            "document_count": documents_total,
            "pages": report.get("pages") or (document or {}).get("page_count"),
            "sections": report.get("sections") or (document or {}).get("section_count"),
            "tables": report.get("tables") or (document or {}).get("table_count"),
            "characters": None,
        },
        "documents": document_views,
        "structure": passage_view.get("structure") or [],
        "passages": passage_view.get("passages") or [],
        "narrative_proposals": {
            "method": passage_view.get("method"),
            "narrative_signal": bool(passage_view.get("narrative_signal")),
            "participants": passage_view.get("participants") or [],
            "themes": passage_view.get("themes") or [],
            "relations": passage_view.get("relations") or [],
        },
        "summary": _summary(
            genre,
            visible,
            [item for item in insights if item.get("verification_state") != "proposed"],
            warnings,
            proposals=proposals,
        ),
        "topics": ordered_topics,
        "insights": insights[:200],
        "warnings": warnings,
        "limitations": limitations,
        "provenance": {
            "source_fingerprint": source_fingerprint,
            "document_id": str((document or {}).get("id") or "") or None,
            "source_profile_version": profile_version or None,
            "model_version": MODEL_VERSION,
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "evaluation_state": "not_evaluated",
            "is_stale": is_stale,
            "contract": CONTRACT,
            "method": "deterministic",
            "authority": "read_model",
        },
        "pagination": {
            "documents": {
                "total": documents_total,
                "returned": len(document_views),
                "truncated": documents_truncated,
            },
            "objects": {
                "total": objects_total,
                "returned": len(objects),
                "truncated": objects_truncated,
                "next_cursor": stats.get("objects_next_cursor"),
            },
            "evidence": {
                "total": evidence_total,
                "returned": len(evidence),
                "truncated": evidence_truncated,
                "next_cursor": stats.get("evidence_next_cursor"),
            },
        },
        "counts": {
            "objects_total": objects_total,
            "objects_returned": len(objects),
            "objects_visible": len(visible),
            "objects_hidden": hidden,
            "objects_not_evaluated": max(0, objects_total - len(objects)),
            "evidence_total": evidence_total,
            "evidence_returned": len(evidence),
            "passages_available": passages_available,
            "revisions": hidden,
            "proposed_participants": len(passage_view.get("participants") or []),
            "proposed_themes": len(passage_view.get("themes") or []),
            "proposals": len(proposals),
            "insights": len(insights),
            "topics": len(ordered_topics),
            "documents_total": documents_total,
            "truncated": truncated,
        },
        "read_model": stats.get("timing") or {},
    }


def _summary(
    genre: str,
    visible: list[dict],
    insights: list[dict],
    warnings: list[dict],
    *,
    proposals: list[dict] | None = None,
) -> str:
    proposal_count = len(proposals or [])
    if not visible:
        text = "Solo se identificaron secciones y pasajes."
        if proposal_count:
            text += f" ZENT propone {proposal_count} elementos desde esos pasajes; no son hechos verificados."
        else:
            text += " No podemos afirmar temas con certeza."
        return text
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
    if proposal_count:
        text += f" Además, {proposal_count} elementos se proponen desde pasajes y no están verificados."
    if any(item.get("code") == "GENRE_UNKNOWN" for item in warnings):
        text += " La clasificación de género es provisional."
    return text


def _slug(value: str) -> str:
    return (
        "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-").replace("--", "-")[:60] or "tema"
    )


__all__ = ["CONTRACT", "MODEL_VERSION", "build_explorer_insight"]
