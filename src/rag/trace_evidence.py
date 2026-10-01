"""Evidencia canónica — hits crudos, deduplicación real y conteos separados.

Capas de deduplicación (§5), siempre dentro de la misma fuente canónica:

1. exacta   — mismo `canonical_source_id` + página + `text_hash`, o mismo
              `evidence_id` original (las citas referencian al mismo fragmento).
2. solape   — mismo documento y página (±1) con textos esencialmente
              contenidos uno en otro (containment ≥ 0.8, Jaccard ≥ 0.7,
              ratio ≥ 0.85).
3. semántica— misma fuente y sección/ventana con similitud extrema
              (ratio ≥ 0.92 / Jaccard ≥ 0.85).

Nunca fusiona documentos distintos aunque el texto se parezca: la unidad de
comparación es la fuente canónica. Toda canónica conserva `raw_hits` para
auditar qué se fusionó y por qué.

Conteos: recuperado ≠ seleccionado ≠ utilizado ≠ citado (§6). Si el detalle
recibido viene truncado, `evidence_unique` queda `null` y
`collection = "partial"`; no se inventa.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.rag.trace_identity import (
    canonical_source_identity,
    derive_evidence_id,
    normalize_hash_text,
    normalize_text,
    resolve_display_name,
    text_fingerprint,
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

#: umbrales de fusión (documentados en docs/architecture/traceability-v2.md)
_OVERLAP_CONTAINMENT = 0.80
_OVERLAP_JACCARD = 0.70
_OVERLAP_RATIO = 0.85
_SEMANTIC_RATIO = 0.92
_SEMANTIC_JACCARD = 0.85
_MIN_TEXT_FOR_SIMILARITY = 40

_ITEM_LEGACY_KEYS = (
    "evidence_id",
    "document_id",
    "source_id",
    "chunk_id",
    "table",
    "row_ref",
    "document_name",
    "page",
    "section_path",
    "excerpt",
    "score",
    "rerank_score",
    "retrieval",
    "match",
    "status",
    "doc_index",
    "authority",
    "knowledge_type",
    "entity_pin",
    "used_in_answer",
    "cited",
)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_RE.findall(value.casefold()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _containment(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _section_text(raw: Mapping[str, Any]) -> str:
    section = raw.get("section_path")
    if isinstance(section, Sequence) and not isinstance(section, (str, bytes)):
        parts = [str(part).strip() for part in section if str(part).strip()]
        if parts:
            return " · ".join(parts[:6])
    return _text(raw.get("section") or raw.get("heading"))


# ---------------------------------------------------------------------------
# Recolección de hits crudos
# ---------------------------------------------------------------------------


def collect_raw_hits(
    flow: Mapping[str, Any], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reúne candidatos de TODAS las fuentes reales, sin fusionar todavía.

    Prioridad semántica: detalle del registry > selección > fuentes > citas >
    meta de steps. Un mismo fragmento puede llegar por varias vías; la
    deduplicación posterior lo unifica preservando cada hit.
    """
    raw: list[dict[str, Any]] = []

    def push(item: Any, origin: str) -> None:
        if isinstance(item, Mapping):
            merged = dict(item)
            merged.setdefault("_hit_origin", origin)
            raw.append(merged)

    evidence = _record(flow.get("evidence"))
    for key in ("items_detail", "items"):
        for item in _records(evidence.get(key)):
            push(item, "items_detail")
    for item in _records(flow.get("sources")):
        push(item, "sources")
    for key in ("citations",):
        for item in _records(evidence.get(key)):
            push(item, "evidence_citations")
    for item in _records(flow.get("citations")):
        push(item, "citations")
    for step in _records(flow.get("steps")):
        meta = _record(step.get("meta"))
        for item in _records(meta.get("evidence")):
            push(item, "tool_meta")
    # Los eventos canónicos se derivan de los steps; recolectarlos también
    # duplicaría cada hit (mismo fragmento visto desde dos vías de exposición).

    selection = _record(evidence.get("selection"))
    selected_ids = {
        _text(item) for item in (selection.get("evidence_ids") or []) if _text(item)
    }
    match_by_id = {
        _text(match.get("evidence_id")): match
        for match in _records(selection.get("matches"))
        if _text(match.get("evidence_id"))
    }
    for hit in raw:
        evidence_id = _text(hit.get("evidence_id"))
        match = match_by_id.get(evidence_id)
        if match is not None:
            hit.setdefault("match", match.get("match"))
            hit.setdefault("match_score", match.get("score"))
            hit.setdefault("match_complete", match.get("complete"))
        if evidence_id and evidence_id in selected_ids:
            hit.setdefault("selected", True)
    return raw


# ---------------------------------------------------------------------------
# Normalización de un hit
# ---------------------------------------------------------------------------


def normalize_hit(
    raw: Mapping[str, Any],
    *,
    index: int,
    organization_id: str | None = None,
    knowledge_base_id: str | None = None,
) -> dict[str, Any]:
    identity = canonical_source_identity(
        raw, organization_id=organization_id, knowledge_base_id=knowledge_base_id
    )
    name = resolve_display_name(
        raw, canonical_source_id=identity.get("canonical_source_id")
    )
    excerpt = normalize_text(
        raw.get("excerpt") or raw.get("content") or raw.get("snippet")
    )[:600]
    section = _section_text(raw)
    page = _int_or_none(raw.get("page"))
    if page is None:
        page = _int_or_none(raw.get("page_start"))
    raw_evidence_id = _text(raw.get("evidence_id")) or None
    chunk_id = _text(raw.get("chunk_id")) or None
    derived = derive_evidence_id(
        canonical_source_id=identity.get("canonical_source_id"),
        page=page,
        section=section or None,
        text=excerpt or None,
        chunk_id=chunk_id,
        raw_evidence_id=raw_evidence_id,
    )
    # El id provisto por el registry se preserva (es el que citan las citas);
    # el fingerprint determinístico se expone aparte para correlacionar corridas.
    evidence_id = raw_evidence_id or derived["evidence_id"]
    cited = True if raw.get("cited") is True else False
    used_for_generation = True if raw.get("used_for_generation") is True else False
    doc_index = _int_or_none(raw.get("doc_index"))
    status = _text(raw.get("status")).upper()
    selected = True if raw.get("selected") is True else False
    if used_for_generation or doc_index is not None:
        selected = True
    selected = selected or status in {"USED", "CITED", "SELECTED"} or bool(raw.get("match"))
    if cited:
        used: bool | None = True
    elif used_for_generation or doc_index is not None or status in {"USED", "CITED"}:
        used = True
    elif status in {"RETRIEVED", "CANDIDATE", "DISCARDED", "DROPPED"}:
        used = False
    else:
        used = None

    return {
        "hit_id": f"hit:{index}",
        "origin": _text(raw.get("_hit_origin")) or None,
        "raw_evidence_id": raw_evidence_id,
        "evidence_id": evidence_id,
        "evidence_fingerprint": derived["evidence_id"],
        "evidence_id_basis": "provided" if raw_evidence_id else derived["basis"],
        "evidence_id_stable": True if raw_evidence_id else derived["stable"],
        "canonical_source_id": identity.get("canonical_source_id"),
        "identity_basis": identity.get("identity_basis"),
        "identity_weak": bool(identity.get("weak")),
        "document_id": _text(raw.get("document_id")) or None,
        "source_id": _text(raw.get("source_id")) or None,
        "chunk_id": chunk_id,
        "table": _text(raw.get("table")) or None,
        "row_ref": _text(raw.get("row_ref")) or None,
        "page": page,
        "page_end": _int_or_none(raw.get("page_end")),
        "section_path": section or None,
        "document_name": name["value"],
        "display_name": name["value"] or name.get("label"),
        "name_origin": name["origin"],
        "name_missing": bool(name["missing"]),
        "excerpt": excerpt or None,
        "text_hash": text_fingerprint(excerpt),
        "score": _number(raw.get("score")),
        "rerank_score": _number(raw.get("rerank_score")),
        "retrieval": _text(raw.get("retrieval") or raw.get("retrieval_method")) or None,
        "match": _text(raw.get("match")) or None,
        "match_score": _number(raw.get("match_score")),
        "status": status or None,
        "doc_index": doc_index,
        "authority": _text(raw.get("authority")) or None,
        "knowledge_type": _text(raw.get("knowledge_type")) or None,
        "entity_pin": True if raw.get("entity_pin") is True else None,
        "selected": selected or None,
        "used": used,
        "cited": True if cited else None,
    }


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------


def _source_group_key(hit: Mapping[str, Any]) -> str:
    canonical = _text(hit.get("canonical_source_id"))
    if canonical:
        return canonical
    for key in ("document_id", "source_id"):
        value = _text(hit.get(key))
        if value:
            return f"weak:{key}:{value}"
    name = normalize_hash_text(hit.get("document_name"))
    return f"name:{name}" if name else "name:"


def _match_kind(a: Mapping[str, Any], b: Mapping[str, Any]) -> str | None:
    """Clasifica dos hits como mismo fragmento lógico y con qué capa."""
    if _source_group_key(a) != _source_group_key(b):
        return None
    raw_a, raw_b = _text(a.get("raw_evidence_id")), _text(b.get("raw_evidence_id"))
    if raw_a and raw_a == raw_b:
        return "exact"
    chunk_a, chunk_b = _text(a.get("chunk_id")), _text(b.get("chunk_id"))
    if chunk_a and chunk_a == chunk_b:
        return "exact"
    page_a, page_b = a.get("page"), b.get("page")
    hash_a, hash_b = a.get("text_hash"), b.get("text_hash")
    if hash_a and hash_a == hash_b and page_a == page_b:
        return "exact"
    text_a, text_b = _text(a.get("excerpt")), _text(b.get("excerpt"))
    if not text_a or not text_b:
        # Sin texto sólo se fusiona metadata idéntica con ubicación explícita;
        # dos fragmentos vacíos del mismo documento no son el mismo fragmento.
        if (
            page_a is not None
            and page_a == page_b
            and a.get("section_path")
            and a.get("section_path") == b.get("section_path")
        ):
            return "exact"
        return None
    if len(text_a) < _MIN_TEXT_FOR_SIMILARITY or len(text_b) < _MIN_TEXT_FOR_SIMILARITY:
        return None
    tokens_a, tokens_b = _tokens(text_a), _tokens(text_b)
    same_page = page_a is not None and page_a == page_b
    near_page = (
        isinstance(page_a, int)
        and isinstance(page_b, int)
        and abs(page_a - page_b) <= 1
    )
    ratio = _ratio(text_a, text_b)
    jaccard = _jaccard(tokens_a, tokens_b)
    if same_page and (
        _containment(tokens_a, tokens_b) >= _OVERLAP_CONTAINMENT
        or jaccard >= _OVERLAP_JACCARD
        or ratio >= _OVERLAP_RATIO
    ):
        return "overlap"
    same_section = bool(a.get("section_path")) and a.get("section_path") == b.get("section_path")
    if (same_page or near_page) and (
        ratio >= _SEMANTIC_RATIO or (same_section and jaccard >= _SEMANTIC_JACCARD)
    ):
        return "semantic"
    if same_section and ratio >= _SEMANTIC_RATIO:
        return "semantic"
    return None


def _merge_group(group: list[dict[str, Any]], *, kinds: list[str | None]) -> dict[str, Any]:
    def richness(hit: Mapping[str, Any]) -> tuple[float, int, int]:
        score = _number(hit.get("score")) or 0.0
        rerank = _number(hit.get("rerank_score")) or 0.0
        filled = sum(
            1
            for value in hit.values()
            if value not in (None, "", [], {})
        )
        text_len = len(_text(hit.get("excerpt")))
        return (score + rerank, filled, text_len)

    ordered = sorted(group, key=richness, reverse=True)
    lead = dict(ordered[0])
    for other in ordered[1:]:
        for key, value in other.items():
            if value in (None, "", [], {}):
                continue
            if lead.get(key) in (None, "", [], {}):
                lead[key] = value
    excerpt = max((_text(hit.get("excerpt")) for hit in ordered), key=len, default="")
    lead["excerpt"] = excerpt or None
    lead["used"] = True if any(hit.get("used") is True for hit in ordered) else (
        False if any(hit.get("used") is False for hit in ordered) else None
    )
    lead["cited"] = True if any(hit.get("cited") is True for hit in ordered) else None
    lead["selected"] = True if any(hit.get("selected") is True for hit in ordered) else None
    scores = [_number(hit.get("score")) for hit in ordered]
    lead["score"] = max((value for value in scores if value is not None), default=None)
    reranks = [_number(hit.get("rerank_score")) for hit in ordered]
    lead["rerank_score"] = max(
        (value for value in reranks if value is not None), default=None
    )
    methods = [hit.get("retrieval") for hit in ordered if hit.get("retrieval")]
    lead["retrieval"] = methods[0] if methods else None
    lead["raw_hits"] = [
        {
            "hit_id": hit["hit_id"],
            "evidence_id": hit.get("raw_evidence_id") or hit.get("evidence_id"),
            "chunk_id": hit.get("chunk_id"),
            "page": hit.get("page"),
            "score": _number(hit.get("score")),
            "rerank_score": _number(hit.get("rerank_score")),
            "retrieval": hit.get("retrieval"),
            "status": hit.get("status"),
            "doc_index": hit.get("doc_index"),
            "origin": hit.get("origin"),
            "used": hit.get("used") is True,
            "cited": hit.get("cited") is True,
            "merged_as": kinds[index] if index and kinds[index] else "representative",
        }
        for index, hit in enumerate(group)
    ]
    merged_kinds = {kind for kind in kinds if kind in {"exact", "overlap", "semantic"}}
    if "exact" in merged_kinds:
        dedup_kind = "exact"
    elif "overlap" in merged_kinds:
        dedup_kind = "overlap"
    elif "semantic" in merged_kinds:
        dedup_kind = "semantic"
    else:
        dedup_kind = "none"
    lead["merged_count"] = len(group) - 1
    lead["dedup_kind"] = dedup_kind
    lead["hit_count"] = len(group)
    return lead


def dedupe_hits(hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Fusiona hits en evidencias canónicas preservando la auditoría."""
    groups: list[dict[str, Any]] = []
    stats = {"exact": 0, "overlap": 0, "semantic": 0, "merged": 0}
    exact_index: dict[tuple[str, str], int] = {}

    for hit in hits:
        source = _source_group_key(hit)
        target: int | None = None
        kind: str | None = None
        raw_id = _text(hit.get("raw_evidence_id"))
        if raw_id:
            target = exact_index.get((source, f"raw:{raw_id}"))
            if target is not None:
                kind = "exact"
        if target is None:
            text_hash = _text(hit.get("text_hash"))
            if text_hash:
                target = exact_index.get(
                    (source, f"text:{hit.get('page')}:{hit.get('section_path')}:{text_hash}")
                )
                if target is not None:
                    kind = "exact"
        if target is None:
            for index, group in enumerate(groups):
                if _source_group_key(group["lead"]) != source:
                    continue
                candidate_kind = _match_kind(group["lead"], hit)
                if candidate_kind is not None:
                    target = index
                    kind = candidate_kind
                    break
        if target is None:
            groups.append({"lead": dict(hit), "hits": [hit], "kinds": [None]})
            index = len(groups) - 1
        else:
            group = groups[target]
            group["hits"].append(hit)
            group["kinds"].append(kind)
            group["lead"] = _merge_group(group["hits"], kinds=group["kinds"])
            index = target
        if kind is not None:
            stats[kind] += 1
            stats["merged"] += 1
        if raw_id:
            exact_index[(source, f"raw:{raw_id}")] = index
        text_hash = _text(hit.get("text_hash"))
        if text_hash:
            exact_index[
                (source, f"text:{hit.get('page')}:{hit.get('section_path')}:{text_hash}")
            ] = index

    canonicals: list[dict[str, Any]] = []
    for group in groups:
        canonical = _merge_group(group["hits"], kinds=group["kinds"])
        canonicals.append(canonical)
    return {"canonical": canonicals, "stats": stats}


_REFERENCE_ORIGINS = {"citations", "evidence_citations"}


def _identity_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identidad de observación: dos hits con la misma clave son el MISMO hit
    visto por otra vía (no una recuperación distinta)."""
    source = _source_group_key(hit)
    raw_id = _text(hit.get("raw_evidence_id"))
    if raw_id:
        return ("raw", source, raw_id)
    chunk = _text(hit.get("chunk_id"))
    if chunk:
        return ("chunk", source, chunk)
    text_hash = _text(hit.get("text_hash"))
    if text_hash:
        return ("text", source, hit.get("page"), text_hash)
    return ("hit", hit.get("hit_id"))


def _absorb(target: dict[str, Any], extra: Mapping[str, Any]) -> None:
    """Propaga flags de una observación duplicada sin contarla como evidencia."""
    if extra.get("cited") is True:
        target["cited"] = True
    if extra.get("used") is True:
        target["used"] = True
    if extra.get("selected") is True:
        target["selected"] = True
    current_score = _number(target.get("score"))
    extra_score = _number(extra.get("score"))
    if extra_score is not None and (current_score is None or extra_score > current_score):
        target["score"] = extra_score
    if not _text(target.get("excerpt")) and _text(extra.get("excerpt")):
        target["excerpt"] = extra.get("excerpt")
        target["text_hash"] = extra.get("text_hash")


def _legacy_item(canonical: Mapping[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key in _ITEM_LEGACY_KEYS:
        value = canonical.get(key)
        if value in (None, "", []):
            continue
        item[key] = value
    if canonical.get("canonical_source_id"):
        item["canonical_source_id"] = canonical["canonical_source_id"]
    item["merged_count"] = canonical.get("merged_count", 0)
    item["dedup_kind"] = canonical.get("dedup_kind") or "none"
    if canonical.get("used") is not None:
        item["used_in_answer"] = canonical["used"] is True
    return item


def _document_groups(canonicals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for canonical in canonicals:
        key = _source_group_key(canonical)
        if key not in groups:
            groups[key] = {
                "document_key": key,
                "canonical_source_id": canonical.get("canonical_source_id"),
                "identity_basis": canonical.get("identity_basis"),
                "identity_weak": bool(canonical.get("identity_weak")),
                "document_id": canonical.get("document_id"),
                "source_id": canonical.get("source_id"),
                "document_name": canonical.get("document_name") or "",
                "display_name": canonical.get("display_name"),
                "name_origin": canonical.get("name_origin"),
                "name_missing": bool(canonical.get("name_missing")),
                "evidence_count": 0,
                "used_count": 0,
                "cited_count": 0,
                "items": [],
            }
            order.append(key)
        group = groups[key]
        if not group.get("document_name") and canonical.get("document_name"):
            group["document_name"] = canonical["document_name"]
        if not group.get("document_id") and canonical.get("document_id"):
            group["document_id"] = canonical["document_id"]
        group["evidence_count"] += 1
        if canonical.get("used") is True:
            group["used_count"] += 1
        if canonical.get("cited") is True:
            group["cited_count"] += 1
        group["items"].append(_legacy_item(canonical))
    return [groups[key] for key in order]


def build_evidence_section(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    *,
    organization_id: str | None = None,
    knowledge_base_id: str | None = None,
) -> dict[str, Any]:
    """Construye la sección `evidence` completa (v2) + proyección v1.

    Devuelve además `diagnostics`: observaciones de identidad/colección para que
    el orquestador las convierta en items de diagnóstico.
    """
    diagnostics: list[dict[str, Any]] = []
    raw = collect_raw_hits(flow, events)
    retrieval_raw = [
        item
        for item in raw
        if _text(item.get("_hit_origin")) not in _REFERENCE_ORIGINS
    ]
    reference_raw = [
        item
        for item in raw
        if _text(item.get("_hit_origin")) in _REFERENCE_ORIGINS
    ]
    hits = [
        normalize_hit(
            item,
            index=index,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
        )
        for index, item in enumerate(retrieval_raw, start=1)
    ]
    references = [
        normalize_hit(
            item,
            index=len(hits) + index,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
        )
        for index, item in enumerate(reference_raw, start=1)
    ]
    # Una cita es una referencia, no una recuperación: se fusiona con su hit.
    by_evidence_id = {
        _text(hit.get("evidence_id")): hit for hit in hits if hit.get("evidence_id")
    }
    identity_index: dict[tuple[Any, ...], dict[str, Any]] = {
        _identity_key(hit): hit for hit in hits
    }
    for reference in references:
        match = by_evidence_id.get(
            _text(reference.get("raw_evidence_id"))
            or _text(reference.get("evidence_id"))
        ) or identity_index.get(_identity_key(reference))
        if match is not None:
            _absorb(match, reference)
        else:
            reference["origin"] = "citation_only"
            hits.append(reference)

    collapsed: list[dict[str, Any]] = []
    collapsed_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    for hit in hits:
        key = _identity_key(hit)
        existing = collapsed_index.get(key)
        if existing is None:
            collapsed_index[key] = hit
            collapsed.append(hit)
        else:
            _absorb(existing, hit)
    retrieved_measured = len(collapsed)
    dedup = dedupe_hits(collapsed)
    canonicals: list[dict[str, Any]] = dedup["canonical"]
    stats = dedup["stats"]

    for canonical in canonicals:
        if not canonical.get("canonical_source_id"):
            diagnostics.append(
                {
                    "code": "CANONICAL_SOURCE_ID_MISSING",
                    "evidence_id": canonical.get("evidence_id"),
                }
            )
        elif canonical.get("identity_weak"):
            diagnostics.append(
                {
                    "code": "CANONICAL_SOURCE_WEAK_IDENTITY",
                    "evidence_id": canonical.get("evidence_id"),
                    "identity_basis": canonical.get("identity_basis"),
                }
            )
        if not canonical.get("evidence_id"):
            diagnostics.append(
                {
                    "code": "EVIDENCE_ID_MISSING",
                    "document_id": canonical.get("document_id"),
                    "page": canonical.get("page"),
                }
            )
        if canonical.get("name_missing"):
            diagnostics.append(
                {
                    "code": "SOURCE_NAME_MISSING",
                    "canonical_source_id": canonical.get("canonical_source_id"),
                }
            )
        if canonical.get("used") is True and not canonical.get("excerpt"):
            diagnostics.append(
                {
                    "code": "EVIDENCE_EXCERPT_MISSING",
                    "evidence_id": canonical.get("evidence_id"),
                }
            )
    if stats["merged"]:
        diagnostics.append(
            {
                "code": "EVIDENCE_DEDUPLICATED",
                "deduplicated": stats["merged"],
                "exact": stats["exact"],
                "overlap": stats["overlap"],
                "semantic": stats["semantic"],
            }
        )

    declared = _record(_record(flow.get("evidence")).get("counts"))
    declared_retrieved = _int_or_none(declared.get("evidence_retrieved"))
    collected = retrieved_measured
    if declared_retrieved is not None:
        collection_complete = collected >= declared_retrieved
        retrieved = max(declared_retrieved, collected)
    else:
        collection_complete = True
        retrieved = collected
    unique = len(canonicals) if collection_complete else None
    deduplicated = (retrieved - len(canonicals)) if collection_complete else None

    selection = _record(_record(flow.get("evidence")).get("selection"))
    declared_selected = None
    if isinstance(selection.get("evidence_ids"), Sequence) and not isinstance(
        selection.get("evidence_ids"), (str, bytes)
    ):
        declared_selected = len(
            [_text(item) for item in selection.get("evidence_ids") or [] if _text(item)]
        )
    used_measured = sum(1 for item in canonicals if item.get("used") is True)
    cited_measured = sum(1 for item in canonicals if item.get("cited") is True)
    selected_measured = sum(1 for item in canonicals if item.get("selected") is True)
    documents = _document_groups(canonicals)
    documents_retrieved = (
        _int_or_none(declared.get("documents_consulted"))
        or len(documents)
    )
    documents_used = _int_or_none(declared.get("documents_used"))
    if documents_used is None:
        documents_used = sum(1 for doc in documents if doc["used_count"] > 0)
    used = _int_or_none(declared.get("evidence_used"))
    if used is None:
        used = used_measured
    cited = _int_or_none(declared.get("evidence_cited"))
    if cited is None:
        cited = cited_measured
    selected = declared_selected if declared_selected is not None else selected_measured

    if not collection_complete:
        diagnostics.append(
            {
                "code": "EVIDENCE_COLLECTION_PARTIAL",
                "collected": collected,
                "declared_retrieved": declared_retrieved,
            }
        )
    if declared_retrieved is not None and collected > declared_retrieved:
        diagnostics.append(
            {
                "code": "EVIDENCE_COLLECTION_EXCEEDS_DECLARED",
                "collected": collected,
                "declared_retrieved": declared_retrieved,
            }
        )
    if not canonicals and declared_retrieved:
        diagnostics.append(
            {"code": "EVIDENCE_DETAIL_UNAVAILABLE", "declared_retrieved": declared_retrieved}
        )

    counts = {
        "documents_retrieved": documents_retrieved,
        "documents_used": documents_used,
        "evidence_retrieved": retrieved,
        "evidence_deduplicated": deduplicated,
        "evidence_unique": unique,
        "evidence_selected": selected,
        "evidence_used": used,
        "evidence_cited": cited,
        # Espejo v1 (mismo valor, nombres históricos).
        "documents_consulted": documents_retrieved,
    }

    citations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    raw_citations = _records(flow.get("citations")) or _records(
        _record(flow.get("evidence")).get("citations")
    )
    for index, citation in enumerate(raw_citations, start=1):
        citations.append(
            {
                "index": _int_or_none(citation.get("index")) or index,
                "evidence_id": _text(citation.get("evidence_id")) or None,
                "document_id": _text(citation.get("document_id")) or None,
                "chunk_id": _text(citation.get("chunk_id")) or None,
                "document_name": _text(
                    citation.get("document_name") or citation.get("title")
                )
                or None,
                "page": _int_or_none(citation.get("page")),
                "section_path": citation.get("section_path")
                if isinstance(citation.get("section_path"), list)
                else None,
                "locator": _text(citation.get("locator")) or None,
                "relevance": _number(
                    citation.get("relevance")
                    if citation.get("relevance") is not None
                    else citation.get("score")
                ),
                "match": _text(citation.get("match")) or None,
                "cited": citation.get("cited") is not False,
            }
        )
    cited_references = [item for item in citations if item["cited"]]
    cited_ids = {item["evidence_id"] for item in cited_references if item["evidence_id"]}
    canonical_ids = {item.get("evidence_id") for item in canonicals if item.get("evidence_id")}
    dangling = sorted(cited_ids - canonical_ids)
    if dangling and collection_complete:
        diagnostics.append(
            {"code": "CITATION_DANGLING", "evidence_ids": dangling[:8]}
        )
    references_collapsed = len(cited_references) - len(cited_ids)
    if references_collapsed > 0:
        diagnostics.append(
            {
                "code": "CITATION_REFERENCES_COLLAPSED",
                "references": len(cited_references),
                "unique": len(cited_ids),
                "collapsed": references_collapsed,
            }
        )

    return {
        "counts": counts,
        "collection": "complete" if collection_complete else "partial",
        "raw_hits_count": collected,
        "raw_hits": [
            {
                key: hit.get(key)
                for key in (
                    "hit_id",
                    "raw_evidence_id",
                    "evidence_id",
                    "canonical_source_id",
                    "document_id",
                    "chunk_id",
                    "page",
                    "section_path",
                    "status",
                    "score",
                    "rerank_score",
                    "retrieval",
                    "origin",
                    "selected",
                    "used",
                    "cited",
                    "merged_into",
                )
                if hit.get(key) is not None
            }
            for hit in collapsed
        ],
        "canonical_evidence": [
            {
                key: canonical.get(key)
                for key in (
                    "evidence_id",
                    "evidence_fingerprint",
                    "canonical_source_id",
                    "document_id",
                    "source_id",
                    "chunk_id",
                    "page",
                    "page_end",
                    "section_path",
                    "document_name",
                    "display_name",
                    "name_origin",
                    "excerpt",
                    "text_hash",
                    "score",
                    "rerank_score",
                    "retrieval",
                    "match",
                    "status",
                    "doc_index",
                    "authority",
                    "knowledge_type",
                    "entity_pin",
                    "selected",
                    "used",
                    "cited",
                    "merged_count",
                    "dedup_kind",
                    "hit_count",
                    "raw_hits",
                )
                if canonical.get(key) is not None
            }
            for canonical in canonicals
        ],
        "documents": _document_groups(canonicals),
        "items": [_legacy_item(canonical) for canonical in canonicals],
        "sources": [
            {
                "document_key": doc["document_key"],
                "canonical_source_id": doc["canonical_source_id"],
                "document_id": doc["document_id"],
                "source_id": doc["source_id"],
                "document_name": doc["document_name"] or None,
                "display_name": doc.get("display_name"),
                "name_origin": doc["name_origin"],
                "name_missing": doc["name_missing"],
                "identity_basis": doc["identity_basis"],
                "identity_weak": doc["identity_weak"],
                "evidence_count": doc["evidence_count"],
                "used_count": doc["used_count"],
                "cited_count": doc["cited_count"],
            }
            for doc in documents
        ],
        "dedup": {
            "merged": stats["merged"],
            "exact": stats["exact"],
            "overlap": stats["overlap"],
            "semantic": stats["semantic"],
        },
        "citations": citations,
        "citations_summary": {
            "references": len(citations),
            "cited_references": len(cited_references),
            "unique_cited": len(cited_ids),
            "collapsed": references_collapsed,
            "dangling": dangling[:8],
        },
        "diagnostics": diagnostics,
    }


__all__ = [
    "build_evidence_section",
    "collect_raw_hits",
    "dedupe_hits",
    "normalize_hit",
]
