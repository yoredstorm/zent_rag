# =============================================================================
# Run evidence — una sola fuente lógica de evidencia durante el run.
# =============================================================================
# El problema que resuelve: el retrieval encontraba el fragmento correcto y la
# respuesta terminaba en «no hay evidencia suficiente» porque JEV juzgaba una
# versión peor de la evidencia que la que vio el generador (3000 chars en el
# historial, 1500 en el gate, 240 en el preview del evidence gate).
#
# Reglas:
#   SOURCE (documento disponible) != EVIDENCE (fragmento recuperado)
#                                != CLAIM (afirmación respaldada)
#
#   - El Registry conserva el contenido COMPLETO de cada fragmento y le asigna
#     un `evidence_id` estable (`E1`, `E2`, …) que siguen generador, JEV, citas
#     y «Ver flujo».
#   - La selección NO es `texto[:N]`: es presupuesto repartido por relevancia
#     (entidad exacta > nombre de fuente > entity pin > sección > léxico >
#     semántico). Un fragmento relevante que aparece después de mucho texto
#     irrelevante entra igual.
#   - La suficiencia es determinista y sólo publica lo medido: `unknown` no es
#     `0`.
# =============================================================================
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from src.core.domain.adaptive import EvidenceItem

#: Presupuesto por defecto del contexto de evidencia (chars) y topes por ítem.
DEFAULT_BUDGET_CHARS = 12_000
MIN_ITEM_CHARS = 400
MAX_ITEM_CHARS = 4_000

#: Acción recomendada por la suficiencia.
ACTION_GENERATE = "generate"
ACTION_RETRIEVE_MORE = "retrieve_more"
ACTION_ANSWER_WITH_LIMITS = "answer_with_limits"
ACTION_ABSTAIN = "abstain"
#: Acciones del gate de respuesta (mismo vocabulario que el runtime ejecuta).
ACTION_APPROVE = "approve"
ACTION_REVISE = "revise"

#: Razón de selección → orden de prioridad (menor = primero).
_MATCH_PRIORITY: dict[str, int] = {
    "exact_entity_match": 0,
    "source_name_match": 1,
    "entity_pin": 2,
    "section_match": 3,
    "lexical_match": 4,
    "semantic_match": 5,
}

_TOKEN_RE = re.compile(r"[\wÁÉÍÓÚÑáéíóúñ]{3,}", re.UNICODE)


def _content_tokens(text: str) -> set[str]:
    from src.rag.retrieval.classify import normalize_query

    return {token for token in _TOKEN_RE.findall(normalize_query(text or "")) if token}


def _item_key(item: EvidenceItem) -> str:
    """Identidad del fragmento: documento+chunk y, si falta, el contenido."""
    doc = str(item.document_id or item.source_id or "")
    chunk = str(item.chunk_id or "")
    if doc or chunk:
        return f"{doc}|{chunk}"
    digest = hashlib.sha256((item.content or "").encode("utf-8", "ignore")).hexdigest()[:16]
    return f"{item.source_type}|{digest}"


def _asked_entities(question: str) -> list[Any]:
    try:
        from src.intelligence.response.entities import asked_entities

        return asked_entities(question)
    except Exception:  # noqa: BLE001 — la selección nunca rompe por un import
        return []


def _coverage_text(item: EvidenceItem) -> str:
    """Texto para medir cobertura de entidades: fragmento + nombre de la fuente.

    El nombre importa: «categoría 31» puede no aparecer en el texto del chunk
    pero sí en `Cat31_dapp_C.pdf`, y ese es el documento que explica el campo.
    Es contención de texto, no una inferencia.
    """
    return f"{item.content or ''}\n{item.label}"


@dataclass
class EvidenceRegistry:
    """Evidencia recuperada del run, con ids estables y contenido completo."""

    items: list[EvidenceItem] = field(default_factory=list)
    _by_key: dict[str, str] = field(default_factory=dict, repr=False)
    #: Refs ya vistas (compatibilidad con el dedupe por `ref` de search_knowledge).
    refs: set[str] = field(default_factory=set, repr=False)

    @property
    def size(self) -> int:
        return len(self.items)

    def is_empty(self) -> bool:
        return not self.items

    def chars(self) -> int:
        return sum(len(item.content or "") for item in self.items)

    def ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.items if item.evidence_id)

    def get(self, evidence_id: str) -> EvidenceItem | None:
        for item in self.items:
            if item.evidence_id == evidence_id:
                return item
        return None

    def add(self, items: Iterable[EvidenceItem]) -> tuple[list[EvidenceItem], int]:
        """Registra evidencia nueva. Devuelve (items registrados, cuántos nuevos)."""
        registrados: list[EvidenceItem] = []
        nuevos = 0
        for item in items:
            key = _item_key(item)
            existing = self._by_key.get(key)
            if existing is not None:
                registrados.append(self.get(existing) or item)
                continue
            evidence_id = item.evidence_id or f"E{len(self.items) + 1}"
            registrado = replace(item, evidence_id=evidence_id)
            self.items.append(registrado)
            self._by_key[key] = evidence_id
            registrados.append(registrado)
            nuevos += 1
        return registrados, nuevos

    def add_from_meta(
        self,
        meta: Mapping[str, Any] | None,
        *,
        source_type: str = "qdrant",
    ) -> tuple[list[EvidenceItem], int]:
        """Registra la evidencia estructurada que reporta una tool.

        Acepta el `meta["evidence"]` de `search_knowledge` (con `content`) y
        cualquier lista de dicts equivalente. Nunca inventa contenido: un ítem
        sin `content` ni `excerpt` se ignora (es una fuente, no evidencia).
        """
        crudos = (meta or {}).get("evidence") if isinstance(meta, Mapping) else None
        if not isinstance(crudos, list):
            return [], 0
        items: list[EvidenceItem] = []
        for raw in crudos:
            if not isinstance(raw, Mapping):
                continue
            content = str(raw.get("content") or raw.get("excerpt") or "")
            if not content.strip():
                continue
            section_path = raw.get("section_path")
            if isinstance(section_path, str):
                section_path = (section_path,)
            items.append(
                EvidenceItem(
                    source_type=str(raw.get("source_type") or source_type),
                    content=content,
                    score=float(raw.get("score") or 0.0),
                    source_id=str(raw.get("source_id") or "") or None,
                    document_id=str(raw.get("document_id") or "") or None,
                    chunk_id=str(raw.get("chunk_id") or "") or None,
                    table=str(raw.get("table") or "") or None,
                    title=str(raw.get("title") or "") or None,
                    page=raw.get("page") if isinstance(raw.get("page"), int) else None,
                    section_path=tuple(str(part) for part in (section_path or ()) if part),
                    retrieval_method=str(raw.get("retrieval") or ""),
                    entity_pin=bool(raw.get("entity_pin")),
                    authority=str(raw.get("authority") or "") or None,
                    knowledge_type=str(raw.get("knowledge_type") or "") or None,
                    metadata={
                        "ref": str(raw.get("ref") or ""),
                        "doc_index": raw.get("doc_index"),
                    },
                )
            )
            ref = str(raw.get("ref") or raw.get("document_id") or "")
            if ref:
                self.refs.add(ref)
        registrados, nuevos = self.add(items)
        return registrados, nuevos

    def add_chunks(self, chunks: Sequence[Any], *, retrieval_method: str = "") -> int:
        """Registra `RetrievalChunk` del motor de retrieval (camino RAG)."""
        items: list[EvidenceItem] = []
        for chunk in chunks or ():
            metadata = getattr(chunk, "metadata", None) or {}
            content = str(getattr(chunk, "content", "") or "")
            if not content.strip():
                continue
            section_path = metadata.get("section_path")
            if isinstance(section_path, str):
                section_path = (section_path,)
            document_id = str(getattr(chunk, "document_id", "") or "")
            items.append(
                EvidenceItem(
                    source_type="qdrant",
                    content=content,
                    score=float(getattr(chunk, "score", 0.0) or 0.0),
                    source_id=str(metadata.get("source_id") or "") or None,
                    document_id=document_id or None,
                    chunk_id=str(metadata.get("chunk_id") or document_id or "") or None,
                    title=str(
                        metadata.get("filename")
                        or metadata.get("title")
                        or metadata.get("external_id")
                        or metadata.get("source")
                        or ""
                    )
                    or None,
                    page=metadata.get("page_start")
                    if isinstance(metadata.get("page_start"), int)
                    else None,
                    section_path=tuple(str(part) for part in (section_path or ()) if part),
                    retrieval_method=str(
                        retrieval_method or metadata.get("retrieval") or ""
                    ),
                    entity_pin=str(metadata.get("retrieval") or "").startswith("entity"),
                    authority=str(metadata.get("authority") or "") or None,
                    knowledge_type=str(metadata.get("knowledge_type") or "") or None,
                )
            )
        _, nuevos = self.add(items)
        return nuevos

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for item in self.items:
            digest.update(_item_key(item).encode("utf-8", "ignore"))
        return digest.hexdigest()[:12]

    def all_items(self) -> tuple[EvidenceItem, ...]:
        return tuple(self.items)

    def replace_all(self, items: Sequence[EvidenceItem]) -> None:
        """Reemplaza la evidencia del run conservando los ids ya asignados."""
        self.items = []
        self._by_key = {}
        self.add(items)

    def to_public_dict(
        self,
        *,
        limit: int = 24,
        cited_ids: Iterable[str] = (),
        selected_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Bloque para «Ver flujo»: SOURCE != EVIDENCE, y status explícito.

        `doc_index` es el número `[Doc N]` que el generador vio para ese
        fragmento (orden de la SELECCIÓN); si no entró al contexto, se omite —
        nunca se inventa un índice.
        """
        cited = set(cited_ids)
        order = {evidence_id: index + 1 for index, evidence_id in enumerate(selected_ids or ())}
        public = []
        for item in self.items[:limit]:
            payload = item.to_public_dict()
            doc_index = order.get(item.evidence_id)
            if doc_index is not None:
                payload["doc_index"] = doc_index
            payload["cited"] = item.evidence_id in cited
            payload["status"] = "USED" if doc_index is not None else "RETRIEVED"
            public.append(payload)
        return {
            "count": len(self.items),
            "chars": self.chars(),
            "items": public,
        }


@dataclass
class EvidenceMatch:
    """Por qué un fragmento entró al contexto (dato, no opinión)."""

    evidence_id: str
    match: str
    priority: int
    score: float
    chars: int
    content: str
    #: El fragmento entró completo (False = sólo la cola que cabía del presupuesto).
    complete: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "match": self.match,
            "score": round(self.score, 4),
            "chars": self.chars,
            "complete": self.complete,
        }
        return payload


@dataclass
class EvidenceSelection:
    """Evidencia elegida para el prompt/gate, con su presupuesto repartido."""

    items: list[EvidenceItem] = field(default_factory=list)
    matches: list[EvidenceMatch] = field(default_factory=list)
    chars: int = 0
    budget_chars: int = DEFAULT_BUDGET_CHARS
    dropped: list[str] = field(default_factory=list)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.items)

    @property
    def empty(self) -> bool:
        return not self.items

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "selected": len(self.items),
            "chars": self.chars,
            "budget_chars": self.budget_chars,
            "evidence_ids": list(self.ids)[:24],
            "matches": [match.to_public_dict() for match in self.matches][:24],
            "dropped_count": len(self.dropped),
        }


def _source_needles(entity: Any) -> list[str]:
    value = str(getattr(entity, "value", "") or "").strip().lower()
    if not value:
        return []
    needles = [value]
    if getattr(entity, "kind", "") == "categoría":
        needles.extend([f"cat{value}", f"cat {value}", f"cat_{value}"])
    return needles


def classify_item(item: EvidenceItem, question: str, entities: Sequence[Any]) -> str:
    """Clasifica un fragmento por la señal MÁS fuerte que lo trae, sin LLM."""
    from src.intelligence.response.entities import entity_covered

    content = _coverage_text(item)
    if entities and all(entity_covered(entity, content) for entity in entities):
        return "exact_entity_match"
    nombre = f"{item.title or ''} {item.source_id or ''}".lower()
    if entities and any(
        needle in nombre.replace("-", " ").replace("_", " ")
        for entity in entities
        for needle in _source_needles(entity)
    ):
        return "source_name_match"
    if item.entity_pin or item.retrieval_method.startswith("entity"):
        return "entity_pin"
    section = " ".join(str(part) for part in item.section_path)
    section_numbers = set(re.findall(r"\d+(?:\.\d+)*", section))
    question_numbers = set(re.findall(r"\d+(?:\.\d+)*", question))
    if section and section_numbers & question_numbers:
        return "section_match"
    question_tokens = _content_tokens(question)
    if question_tokens and len(question_tokens & _content_tokens(content)) >= 2:
        return "lexical_match"
    return "semantic_match"


def rank_evidence(
    items: Sequence[EvidenceItem],
    question: str,
) -> list[tuple[EvidenceItem, str, int]]:
    """Orden de prioridad determinista: señal fuerte primero, score dentro del grupo."""
    entities = _asked_entities(question)
    ranked: list[tuple[EvidenceItem, str, int]] = []
    for order, item in enumerate(items):
        match = classify_item(item, question, entities)
        priority = _MATCH_PRIORITY.get(match, 9)
        ranked.append((item, match, priority * 1000 + order))
    ranked.sort(key=lambda entry: (entry[2], -float(entry[0].score or 0.0)))
    return [(item, match, _MATCH_PRIORITY.get(match, 9)) for item, match, _ in ranked]


def select_evidence(
    items: Sequence[EvidenceItem],
    question: str,
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    max_item_chars: int = MAX_ITEM_CHARS,
    min_item_chars: int = MIN_ITEM_CHARS,
    max_items: int = 12,
) -> EvidenceSelection:
    """Selección con presupuesto repartido por relevancia (nunca `texto[:N]`).

    Cada fragmento entra completo hasta `max_item_chars`; el presupuesto sobrante
    pasa al siguiente por prioridad. Un fragmento que no cabe con al menos
    `min_item_chars` se salta (se registra en `dropped`), no se corta a medias.
    """
    budget = max(0, int(budget_chars))
    selected: list[EvidenceItem] = []
    matches: list[EvidenceMatch] = []
    dropped: list[str] = []
    used = 0
    for item, match, priority in rank_evidence(items, question):
        if len(selected) >= max(1, int(max_items)):
            dropped.append(item.evidence_id or item.label)
            continue
        content = (item.content or "").strip()
        cost = min(len(content), max(0, int(max_item_chars)))
        remaining = budget - used
        if remaining < int(min_item_chars):
            dropped.append(item.evidence_id or item.label)
            continue
        if cost > remaining:
            if remaining < int(min_item_chars):
                dropped.append(item.evidence_id or item.label)
                continue
            cost = remaining
        selected.append(item)
        matches.append(
            EvidenceMatch(
                evidence_id=item.evidence_id,
                match=match,
                priority=priority,
                score=float(item.score or 0.0),
                chars=cost,
                content=content[:cost],
                complete=cost >= len(content),
            )
        )
        used += cost
    return EvidenceSelection(
        items=selected,
        matches=matches,
        chars=used,
        budget_chars=budget,
        dropped=dropped,
    )


def render_evidence(
    selection: EvidenceSelection,
    *,
    doc_tag: str = "Doc",
    tag_style: str = "doc",
) -> str:
    """Bloque de evidencia para el prompt: un fragmento por ítem, completo.

    `tag_style="citations"` mantiene la marca `[Doc: N]` que el camino RAG usa
    para citar, y deja la procedencia (`ev:E2`, sección, match) fuera del
    corchete para no romper el parseo de citas existente.
    """
    blocks: list[str] = []
    for index, (item, match) in enumerate(zip(selection.items, selection.matches), start=1):
        procedencia = [
            part
            for part in (
                item.title,
                f"sección {'.'.join(str(p) for p in item.section_path)}" if item.section_path else "",
                f"p.{item.page}" if item.page is not None else "",
                f"ev:{item.evidence_id}" if item.evidence_id else "",
                match.match,
            )
            if part
        ]
        if tag_style == "citations":
            header = f"[{doc_tag}: {index}] " + " · ".join(procedencia)
        else:
            header = f"[{doc_tag} {index}]"
            if procedencia:
                header += " " + " · ".join(procedencia)
        blocks.append(f"{header}\n{match.content}")
    return "\n\n".join(blocks)


def evidence_index_block(
    selection: EvidenceSelection,
    *,
    max_chars: int = 1_200,
) -> str:
    """Índice compacto (evidence_id → fuente/sección/match) para JEV y el flujo.

    Permite verificar contra la MISMA evidencia que vio el generador sin repetir
    todo el texto: los ids y la localización son los mismos.
    """
    lines: list[str] = []
    used = 0
    for item, match in zip(selection.items, selection.matches):
        parts = [f"{item.evidence_id or '?'}"]
        if item.title:
            parts.append(str(item.title)[:60])
        if item.section_path:
            parts.append(".".join(str(part) for part in item.section_path))
        if item.page is not None:
            parts.append(f"p.{item.page}")
        parts.append(match.match)
        line = " · ".join(parts)
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class EvidenceSufficiency:
    """Evaluación explícita ANTES de generar. Sólo publica lo medido."""

    has_evidence: bool
    supporting_chunks: int
    recommended_action: str
    reason: str
    entity_coverage: float | None = None
    exact_entity_match: bool | None = None
    entities_asked: tuple[str, ...] = ()
    entities_covered: tuple[str, ...] = ()
    missing_entities: tuple[str, ...] = ()
    top_score: float = 0.0
    conflicting_chunks: int | None = None

    @property
    def generate(self) -> bool:
        return self.recommended_action in {ACTION_GENERATE, ACTION_ANSWER_WITH_LIMITS}

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "has_evidence": self.has_evidence,
            "supporting_chunks": self.supporting_chunks,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "top_score": round(float(self.top_score or 0.0), 4),
        }
        if self.entity_coverage is not None:
            payload["entity_coverage"] = round(float(self.entity_coverage), 4)
            payload["entities_asked"] = list(self.entities_asked)[:6]
            payload["entities_covered"] = list(self.entities_covered)[:6]
            if self.missing_entities:
                payload["missing_entities"] = list(self.missing_entities)[:6]
        if self.exact_entity_match is not None:
            payload["exact_entity_match"] = self.exact_entity_match
        if self.conflicting_chunks is not None:
            payload["conflicting_chunks"] = self.conflicting_chunks
        return payload


def assess_sufficiency(
    items: Sequence[EvidenceItem],
    question: str,
    *,
    retrieval_rounds_left: int = 0,
) -> EvidenceSufficiency:
    """¿Alcanza la evidencia para responder lo que se preguntó?

    Determinista: entidades de la pregunta (regex + contención) contra el texto
    recuperado. No opina sobre la redacción ni usa LLM.
    """
    from src.intelligence.response.entities import entity_covered

    top_score = max((float(item.score or 0.0) for item in items), default=0.0)
    if not items:
        action = ACTION_RETRIEVE_MORE if retrieval_rounds_left > 0 else ACTION_ABSTAIN
        return EvidenceSufficiency(
            has_evidence=False,
            supporting_chunks=0,
            recommended_action=action,
            reason="empty",
            top_score=0.0,
        )
    entities = _asked_entities(question)
    if not entities:
        return EvidenceSufficiency(
            has_evidence=True,
            supporting_chunks=len(items),
            recommended_action=ACTION_GENERATE,
            reason="no_entities_asked",
            top_score=top_score,
        )
    joined = "\n".join(_coverage_text(item) for item in items)
    asked = tuple(entity.label for entity in entities)
    covered = tuple(entity.label for entity in entities if entity_covered(entity, joined))
    missing = tuple(label for label in asked if label not in covered)
    coverage = len(covered) / len(asked) if asked else None
    exact = not missing
    if exact:
        action, reason = ACTION_GENERATE, "exact_entity_match"
    elif covered:
        action = ACTION_GENERATE
        reason = "partial_entity_coverage"
    elif retrieval_rounds_left > 0:
        action, reason = ACTION_RETRIEVE_MORE, "entity_not_in_evidence"
    else:
        action, reason = ACTION_ABSTAIN, "entity_not_in_evidence"
    return EvidenceSufficiency(
        has_evidence=True,
        supporting_chunks=len(items),
        recommended_action=action,
        reason=reason,
        entity_coverage=coverage,
        exact_entity_match=exact,
        entities_asked=asked,
        entities_covered=covered,
        missing_entities=missing,
        top_score=top_score,
    )


def observe_sufficiency(sufficiency: EvidenceSufficiency) -> None:
    """Métrica de suficiencia (fail-soft: la observabilidad nunca rompe el run)."""
    try:
        import src.infrastructure.observability.metrics as m

        m.zent_evidence_sufficiency_total.labels(
            action=sufficiency.recommended_action or "unknown",
            reason=sufficiency.reason or "unknown",
        ).inc()
        m.zent_evidence_selection_total.inc()
    except Exception:  # noqa: BLE001
        pass


def observe_selection(selection: EvidenceSelection) -> None:
    """Chars de evidencia efectivamente enviados (medidos, no estimados)."""
    try:
        import src.infrastructure.observability.metrics as m

        m.zent_evidence_selected_chars.observe(max(0, int(selection.chars)))
    except Exception:  # noqa: BLE001
        pass


def citations_payload(
    selection: EvidenceSelection,
    *,
    cited_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Citas ligadas a `evidence_id`: renumerar no rompe la procedencia."""
    cited = set(cited_ids)
    payload: list[dict[str, Any]] = []
    for index, (item, match) in enumerate(zip(selection.items, selection.matches), start=1):
        payload.append(
            {
                "index": index,
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "document_name": item.title,
                "page": item.page,
                "section_path": [str(part) for part in item.section_path],
                "locator": item.label,
                "relevance": round(float(item.score or 0.0), 4),
                "match": match.match,
                "cited": item.evidence_id in cited,
            }
        )
    return payload


def run_evidence_text(
    items: Sequence[EvidenceItem],
    *,
    max_chars: int = 60_000,
) -> str:
    """TODA la evidencia recuperada por el run, para chequeos deterministas.

    Un chequeo que compara la respuesta contra el contexto («¿la fuente dice
    esto?») necesita el universo completo: el modelo pudo ver un fragmento en una
    ronda anterior que ya no está en la selección vigente. Comparar contra la
    selección produce falsos positivos (y un pedido de corrección que empeora la
    respuesta).
    """
    partes: list[str] = []
    usado = 0
    for item in items:
        content = item.content or ""
        if not content:
            continue
        bloque = f"[{item.evidence_id} | {item.label}]\n{content}"
        if usado + len(bloque) > max(1000, int(max_chars)):
            break
        partes.append(bloque)
        usado += len(bloque)
    return "\n\n".join(partes)


def evidence_state_text(
    items: Sequence[EvidenceItem],
    question: str,
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> tuple[str, EvidenceSelection]:
    """Texto de evidencia para un juez (JEV): la MISMA selección del generador.

    Devuelve `(texto, selección)`. Sin fragmentos devuelve `("", selección vacía)`.
    """
    selection = select_evidence(items, question, budget_chars=budget_chars)
    if selection.empty:
        return "", selection
    return render_evidence(selection), selection


__all__ = [
    "ACTION_ABSTAIN",
    "ACTION_ANSWER_WITH_LIMITS",
    "ACTION_APPROVE",
    "ACTION_GENERATE",
    "ACTION_RETRIEVE_MORE",
    "ACTION_REVISE",
    "DEFAULT_BUDGET_CHARS",
    "MAX_ITEM_CHARS",
    "MIN_ITEM_CHARS",
    "EvidenceMatch",
    "EvidenceRegistry",
    "EvidenceSelection",
    "EvidenceSufficiency",
    "assess_sufficiency",
    "citations_payload",
    "classify_item",
    "evidence_index_block",
    "evidence_state_text",
    "observe_selection",
    "observe_sufficiency",
    "rank_evidence",
    "render_evidence",
    "run_evidence_text",
    "select_evidence",
]
