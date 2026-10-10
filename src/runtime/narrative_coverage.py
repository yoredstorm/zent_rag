# =============================================================================
# Narrative Coverage Closure — cobertura explicativa, no autoridad.
# Un miss de top-k no prueba que el corpus no tenga el tema.
# Premise Closure no entra acá.
#
# La cobertura se mide por FRAME, no por bag of words:
#   entity  = entidad que restringe la pregunta («Record 2»)
#   aspect  = lo que se pregunta sobre esa entidad («cambio de fechas»)
# Encontrar la entidad NO cubre el aspecto. Un aspecto material faltante
# (MISSING o PARTIAL_MATERIAL) dispara búsqueda dirigida.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.intelligence.response.entities import asked_entities

COVERED = "COVERED"
PARTIAL = "PARTIAL"
PARTIAL_MATERIAL = "PARTIAL_MATERIAL"
MISSING = "MISSING"

#: Roles de un concepto. El aspecto es PRIMARY; la entidad que lo restringe,
#: QUALIFIER. CONTEXT y RELATION describen estructura, nunca material por sí.
PRIMARY = "PRIMARY"
QUALIFIER = "QUALIFIER"
CONTEXT = "CONTEXT"
RELATION = "RELATION"

#: Stop reasons del cierre de cobertura.
INITIAL_COMPLETE = "INITIAL_COMPLETE"
COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
COVERAGE_PARTIAL = "COVERAGE_PARTIAL"
MAX_ROUNDS = "MAX_ROUNDS"
BUDGET = "BUDGET"
NO_TARGET_QUERY = "NO_TARGET_QUERY"

SUPPORTED = "SUPPORTED"
NOT_FOUND_IN_CURRENT_RETRIEVAL = "NOT_FOUND_IN_CURRENT_RETRIEVAL"
NOT_FOUND_AFTER_COVERAGE_SEARCH = "NOT_FOUND_AFTER_COVERAGE_SEARCH"
CONFLICTING = "CONFLICTING"

_SPLIT = re.compile(r"\s*(?:,|;|\by\b|\band\b)\s*", re.IGNORECASE)
_LEAD = re.compile(
    r"^(?:cu[eé]ntame|expl[ií]came|decime|dime|contame|sobre|acerca|"
    r"qu[eé]\s+(?:significa|es)|en\s+general|el|la|los|las)\s+",
    re.IGNORECASE,
)
_RECORD = re.compile(r"\b(?:records?|registros?)\s*(\d{1,2})\b", re.IGNORECASE)
_ABSENCE = re.compile(
    r"[^.?!]*\b(?:no\s+contiene\s+informaci[oó]n|el\s+documento\s+no\s+contiene|"
    r"el\s+corpus\s+no\s+contiene|el\s+manual\s+no\s+contiene)\b[^.?!]*[.?!]?",
    re.IGNORECASE,
)
#: Conectores que quedan al quitar la entidad de una cláusula.
_EDGE_FILLER = (
    r"(?:en|el|la|los|las|del|de|al|sobre|para|con|por|un|una|"
    r"cuanto|respecto)"
)
_EDGE_RE = re.compile(rf"{_EDGE_FILLER}", re.IGNORECASE)
_STOP = frozenset(
    "de del la el los las en por para con una uno que sobre general".split()
)
_RANK = {MISSING: 0, PARTIAL: 1, PARTIAL_MATERIAL: 2, COVERED: 3}


@dataclass(frozen=True)
class NarrativeConcept:
    concept_id: str
    label: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeConceptFrame:
    """Entidad + aspecto + relación. No es un saco de palabras."""

    frame_id: str
    entity: str = ""
    aspect: str = ""
    qualifiers: tuple[str, ...] = ()
    relation: str = ""
    aliases: tuple[str, ...] = ()
    material_terms: tuple[str, ...] = ()
    role: str = PRIMARY

    @property
    def label(self) -> str:
        return self.aspect or self.entity


@dataclass(frozen=True)
class NarrativeConceptPlan:
    concepts: tuple[NarrativeConcept, ...] = ()
    frames: tuple[NarrativeConceptFrame, ...] = ()


@dataclass(frozen=True)
class ConceptCoverage:
    concept_id: str
    label: str
    status: str
    epistemic: str
    aliases: tuple[str, ...] = ()
    role: str = PRIMARY
    entity: str = ""
    aspect: str = ""
    entity_status: str = ""
    aspect_status: str = ""
    material_gap: bool = False
    material_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageRoundDecision:
    search: bool
    query: str
    stop_reason: str
    coverage_search_skipped: str = ""


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).lower().strip()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in re.findall(r"[a-z]{4,}", _norm(text))
        if token not in _STOP
    )


def _clean_clause(clause: str) -> str:
    text = " ".join((clause or "").split())
    for _ in range(6):
        updated = _LEAD.sub("", text).strip(" .,:;¿?")
        if updated == text:
            break
        text = updated
    return text


def _alias_set(label: str, vocabulary: dict | None) -> tuple[str, ...]:
    """Vocabulario documental + aliases conocidos por packs de dominio."""
    merged: list[str] = []
    seen: set[str] = set()
    for alias in (*_aliases_for(label, vocabulary), *_pack_aliases(label)):
        text = " ".join(str(alias or "").split())
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            merged.append(text)
    return tuple(merged)


def _aliases_for(label: str, vocabulary: dict | None) -> tuple[str, ...]:
    if not vocabulary:
        return ()
    norm_label = _norm(label)
    found: list[str] = []
    seen: set[str] = set()
    for key, values in vocabulary.items():
        norm_key = _norm(str(key))
        if not norm_key or (norm_key != norm_label and norm_key not in norm_label and norm_label not in norm_key):
            continue
        for value in values or ():
            text = " ".join(str(value or "").split())
            folded = text.lower()
            if text and folded not in seen:
                seen.add(folded)
                found.append(text)
    return tuple(found)


def _pack_aliases(label: str) -> tuple[str, ...]:
    """Aliases conocidos por los packs de dominio cargados (metadata).

    La lógica genérica no conoce ATPCO: consulta el vocabulario enchufado.
    """
    try:
        from src.knowledge.enrichment.profiling import expand_aliases

        return expand_aliases(label)
    except Exception:  # noqa: BLE001 — sin packs sigue el vocabulario documental
        return ()


def _label_for(clause: str) -> str:
    cleaned = _clean_clause(clause)
    if not cleaned:
        return ""
    entities = asked_entities(cleaned)
    if len(entities) == 1:
        extra = [
            token
            for token in _tokens(cleaned)
            if token not in _tokens(entities[0].label)
        ]
        if not extra:
            return entities[0].label
    return cleaned


def _aspect_from_clause(cleaned: str, entity) -> str:
    """Aspecto de la cláusula: el texto sin la mención de la entidad.

    «cambio de fechas en el record 2» + entidad «record 2» → «cambio de fechas».
    """
    entity_words = set(_norm(getattr(entity, "label", "")).split())
    entity_words.add(_norm(getattr(entity, "value", "")))
    kept: list[str] = []
    for token in (cleaned or "").split():
        norm_token = _norm(token).strip(" .,:;¿?")
        if not norm_token:
            continue
        if norm_token in entity_words:
            continue
        kept.append(token)
    text = " ".join(kept)
    for _ in range(4):
        updated = re.sub(rf"^{_EDGE_RE.pattern}\s+", "", text).strip()
        updated = re.sub(rf"\s+{_EDGE_RE.pattern}$", "", updated).strip()
        if updated == text:
            break
        text = updated
    return text.strip(" .,:;¿?")


def _frame_for_clause(
    clause: str,
    index: int,
    *,
    vocabulary: dict | None,
) -> NarrativeConceptFrame | None:
    cleaned = _clean_clause(clause)
    if not cleaned:
        return None
    entities = asked_entities(cleaned)
    if len(entities) == 1:
        entity = entities[0]
        aspect = _aspect_from_clause(cleaned, entity)
        if aspect:
            aliases = _alias_set(aspect, vocabulary)
            return NarrativeConceptFrame(
                frame_id=f"F{index}",
                entity=entity.label,
                aspect=aspect,
                relation="aspect_of",
                aliases=aliases,
                material_terms=aliases,
                role=PRIMARY,
            )
        return NarrativeConceptFrame(
            frame_id=f"F{index}",
            entity=entity.label,
            role=PRIMARY,
        )
    label = _label_for(clause)
    if not label:
        return None
    aliases = _alias_set(label, vocabulary)
    return NarrativeConceptFrame(
        frame_id=f"F{index}",
        aspect=label,
        aliases=aliases,
        material_terms=aliases,
        role=PRIMARY,
    )


def extract_narrative_concepts(
    question: str,
    *,
    vocabulary: dict | None = None,
) -> NarrativeConceptPlan:
    """Temas que la pregunta pide explicar, con entidad y aspecto separados.

    La conjunción separa cláusulas. Una cláusula con una sola entidad y texto
    adicional se vuelve un frame entidad+aspecto: la entidad no cubre el
    aspecto. Los aliases salen del vocabulario aprendido (fabric) o del que
    ya vino en la evidencia. Acá no se inventa un diccionario de dominio.
    """
    clauses = [part.strip() for part in _SPLIT.split(question or "") if part.strip()]
    frames: list[NarrativeConceptFrame] = []
    seen: set[tuple[str, str]] = set()
    for clause in clauses:
        frame = _frame_for_clause(clause, len(frames) + 1, vocabulary=vocabulary)
        if frame is None:
            continue
        key = (_norm(frame.entity), _norm(frame.aspect))
        if key in seen:
            continue
        seen.add(key)
        frames.append(frame)
    if not frames:
        fallback = _clean_clause(question or "")
        if fallback:
            aliases = _alias_set(fallback, vocabulary)
            frames.append(
                NarrativeConceptFrame(
                    frame_id="F1",
                    aspect=fallback,
                    aliases=aliases,
                    material_terms=aliases,
                )
            )
    frames = frames[:6]
    concepts = tuple(
        NarrativeConcept(
            concept_id=frame.frame_id,
            label=frame.label,
            aliases=frame.aliases,
        )
        for frame in frames
        if frame.label
    )
    return NarrativeConceptPlan(concepts=concepts, frames=tuple(frames))


def _status_on_text(concept: NarrativeConcept, text: str) -> str:
    blob = _norm(text)
    if not blob:
        return MISSING
    label = _norm(concept.label)
    if label and label in blob:
        return COVERED
    for alias in concept.aliases:
        phrase = _norm(alias)
        if phrase and phrase in blob:
            return COVERED
    record = _RECORD.search(label)
    if record:
        found = _RECORD.search(blob)
        if found and found.group(1) == record.group(1):
            return COVERED
        return PARTIAL if found else MISSING
    needed = _tokens(concept.label)
    if not needed:
        return COVERED if re.search(rf"\b{re.escape(label)}\b", blob) else MISSING
    present = [token for token in needed if token in blob]
    if len(present) == len(needed):
        return COVERED
    if present:
        return PARTIAL
    return MISSING


def _aggregate_status(concept: NarrativeConcept, blobs: list[str]) -> str:
    status = MISSING
    for blob in blobs:
        found = _status_on_text(concept, blob)
        if _RANK[found] > _RANK[status]:
            status = found
        if status == COVERED:
            break
    return status


def _overall_for_frame(
    entity_status: str,
    aspect_status: str,
) -> tuple[str, bool]:
    """(status, material_gap) de un frame entidad+aspecto."""
    if aspect_status == COVERED and entity_status == COVERED:
        return COVERED, False
    if entity_status == COVERED and aspect_status == MISSING:
        # El caso reportado: hay Record 2 pero no el cambio de fechas.
        return PARTIAL_MATERIAL, True
    if entity_status == COVERED and aspect_status == PARTIAL:
        return PARTIAL_MATERIAL, True
    if aspect_status == COVERED and entity_status != COVERED:
        # El aspecto está, la restricción de entidad no: no es cobertura plena.
        return PARTIAL, True
    if aspect_status == MISSING:
        return MISSING, True
    material = aspect_status != COVERED or entity_status != COVERED
    return PARTIAL, material


def _epistemic(status: str, *, searched: bool) -> str:
    if status == COVERED:
        return SUPPORTED
    if searched:
        return NOT_FOUND_AFTER_COVERAGE_SEARCH
    return NOT_FOUND_IN_CURRENT_RETRIEVAL


def _as_text(item: object) -> str:
    if isinstance(item, str):
        return item
    title = str(getattr(item, "title", "") or "")
    section = " ".join(str(part) for part in (getattr(item, "section_path", ()) or ()))
    return f"{getattr(item, 'content', '')}\n{title}\n{section}"


def _coverage_for_frame(
    frame: NarrativeConceptFrame,
    blobs: list[str],
    *,
    searched: bool,
) -> ConceptCoverage:
    if frame.entity and frame.aspect:
        entity_status = _aggregate_status(
            NarrativeConcept(frame.frame_id, frame.entity), blobs
        )
        aspect_terms = tuple(frame.aliases) + tuple(frame.material_terms)
        aspect_status = _aggregate_status(
            NarrativeConcept(frame.frame_id, frame.aspect, aspect_terms), blobs
        )
        status, material_gap = _overall_for_frame(entity_status, aspect_status)
        return ConceptCoverage(
            concept_id=frame.frame_id,
            label=frame.label,
            status=status,
            epistemic=_epistemic(status, searched=searched),
            aliases=frame.aliases,
            role=frame.role,
            entity=frame.entity,
            aspect=frame.aspect,
            entity_status=entity_status,
            aspect_status=aspect_status,
            material_gap=material_gap,
            material_terms=frame.material_terms,
        )
    if frame.entity:
        entity_status = _aggregate_status(
            NarrativeConcept(frame.frame_id, frame.entity), blobs
        )
        return ConceptCoverage(
            concept_id=frame.frame_id,
            label=frame.entity,
            status=entity_status,
            epistemic=_epistemic(entity_status, searched=searched),
            aliases=frame.aliases,
            role=frame.role,
            entity=frame.entity,
            entity_status=entity_status,
            material_gap=entity_status != COVERED,
            material_terms=frame.material_terms,
        )
    aspect_terms = tuple(frame.aliases) + tuple(frame.material_terms)
    aspect_status = _aggregate_status(
        NarrativeConcept(frame.frame_id, frame.aspect or frame.label, aspect_terms),
        blobs,
    )
    return ConceptCoverage(
        concept_id=frame.frame_id,
        label=frame.aspect or frame.label,
        status=aspect_status,
        epistemic=_epistemic(aspect_status, searched=searched),
        aliases=frame.aliases,
        role=frame.role,
        aspect=frame.aspect,
        aspect_status=aspect_status,
        material_gap=aspect_status != COVERED,
        material_terms=frame.material_terms,
    )


def measure_coverage(
    plan: NarrativeConceptPlan,
    texts: object,
    *,
    searched: bool = False,
) -> tuple[ConceptCoverage, ...]:
    """Cobertura del paquete recuperado. No afirma nada sobre el corpus entero.

    Devuelve una medición por frame: la entidad y el aspecto se miden por
    separado, y `status` es la cobertura material del frame.
    """
    blobs = [_as_text(item) for item in (texts or ())]
    if plan.frames:
        return tuple(
            _coverage_for_frame(frame, blobs, searched=searched)
            for frame in plan.frames
        )
    measured: list[ConceptCoverage] = []
    for concept in plan.concepts:
        status = _aggregate_status(concept, blobs)
        measured.append(
            ConceptCoverage(
                concept_id=concept.concept_id,
                label=concept.label,
                status=status,
                epistemic=_epistemic(status, searched=searched),
                aliases=concept.aliases,
                material_gap=status != COVERED,
            )
        )
    return tuple(measured)


def coverage_requires_search(
    concept_coverage: ConceptCoverage | object,
    concept_role: str = "",
) -> bool:
    """Un gap material dispara búsqueda dirigida.

    COVERED no busca. MISSING y PARTIAL_MATERIAL sí. PARTIAL sólo si es
    material para el rol (PRIMARY/RELATION) y hay gap de tokens.
    """
    role = str(concept_role or getattr(concept_coverage, "role", "") or PRIMARY)
    status = str(getattr(concept_coverage, "status", "") or "")
    if status == COVERED:
        return False
    if status == MISSING:
        return True
    if status == PARTIAL_MATERIAL:
        return True
    if status == PARTIAL:
        if role == QUALIFIER and not bool(
            getattr(concept_coverage, "material_gap", False)
        ):
            return False
        return bool(getattr(concept_coverage, "material_gap", False))
    return False


def _shares_term(heading: str, concept: object) -> bool:
    heading_tokens = set(_tokens(heading))
    if not heading_tokens:
        return False
    concept_tokens: set[str] = set()
    for field in ("label", "aspect", "entity"):
        concept_tokens.update(_tokens(str(getattr(concept, field, "") or "")))
    for alias in getattr(concept, "aliases", ()) or ():
        concept_tokens.update(_tokens(str(alias)))
    for term in getattr(concept, "material_terms", ()) or ():
        concept_tokens.update(_tokens(str(term)))
    return bool(heading_tokens & concept_tokens)


def build_coverage_query(
    concept: object,
    *,
    anchors: tuple[str, ...] = (),
    headings: tuple[str, ...] = (),
) -> str:
    """Query dirigida al aspecto faltante, con la entidad como restricción.

    Nunca repite la pregunta original. Terminología exacta del aspecto, sus
    aliases documentales y, después, los headings recuperados que comparten
    términos. No inventa secciones.
    """
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = " ".join(str(value or "").split())
        folded = _norm(text)
        if text and folded not in seen:
            seen.add(folded)
            parts.append(text)

    entity = " ".join(str(getattr(concept, "entity", "") or "").split())
    aspect = " ".join(str(getattr(concept, "aspect", "") or "").split())
    label = " ".join(str(getattr(concept, "label", "") or "").split())
    if not aspect and not entity:
        aspect = label

    for anchor in anchors:
        add(anchor)
    add(entity)
    add(aspect)
    for alias in getattr(concept, "aliases", ()) or ():
        add(str(alias))
    for term in getattr(concept, "material_terms", ()) or ():
        add(str(term))
    for heading in headings:
        if _shares_term(heading, concept):
            add(heading)
    return " ".join(parts)


def decide_coverage_round(
    measured: tuple[ConceptCoverage, ...] | list[ConceptCoverage],
    *,
    rounds_done: int,
    max_rounds: int,
    remaining_steps: int,
    anchors: tuple[str, ...] = (),
    headings: tuple[str, ...] = (),
    over_budget: bool = False,
) -> CoverageRoundDecision:
    """Como máximo una ronda extra, y solo si queda paso para buscar y generar.

    MISSING y PARTIAL_MATERIAL son material. PARTIAL sólo si su rol lo hace
    material. COVERED nunca busca.
    """
    needs_search = [
        item
        for item in measured
        if coverage_requires_search(item, getattr(item, "role", ""))
    ]
    if not needs_search:
        return CoverageRoundDecision(False, "", INITIAL_COMPLETE)
    if int(rounds_done) >= int(max_rounds):
        return CoverageRoundDecision(False, "", MAX_ROUNDS)
    if over_budget or int(remaining_steps) < 2:
        return CoverageRoundDecision(False, "", BUDGET, BUDGET)
    chunks = [
        build_coverage_query(item, anchors=anchors, headings=headings)
        for item in needs_search
    ]
    # Dedupe por frase completa: cortar por palabra rompe "Eff Date"/"Disc Date".
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        text = " ".join(chunk.split())
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    query = " ".join(parts)
    if not query.strip():
        return CoverageRoundDecision(False, "", NO_TARGET_QUERY, NO_TARGET_QUERY)
    reason = (
        PARTIAL_MATERIAL
        if any(
            item.status == PARTIAL_MATERIAL
            or (item.status == PARTIAL and item.material_gap)
            for item in needs_search
        )
        else COVERAGE_PARTIAL
    )
    return CoverageRoundDecision(True, query, reason)


def limitation_sentence(measured: tuple[ConceptCoverage, ...] | list[ConceptCoverage]) -> str:
    gaps = [
        item
        for item in measured
        if item.status in {MISSING, PARTIAL_MATERIAL}
    ]
    if not gaps:
        return ""
    if len(gaps) == 1:
        item = gaps[0]
        aspect = item.aspect or item.label
        if item.entity and item.entity_status == COVERED:
            return (
                f"Encontré respaldo suficiente sobre {item.entity}, "
                f"pero no encontré evidencia suficiente sobre {aspect} "
                "en las fuentes disponibles para este agente."
            )
        return (
            f"No encontré evidencia suficiente sobre {aspect} "
            "en las fuentes disponibles para este agente."
        )
    listed = ", ".join(item.aspect or item.label for item in gaps)
    return (
        "No encontré respaldo suficiente en las fuentes disponibles "
        f"sobre {listed}."
    )


def apply_coverage_limitation(answer: str, measured: object) -> str:
    """Saca la ausencia de corpus. Deja el límite sobre lo recuperado."""
    sentence = limitation_sentence(tuple(measured))
    if not sentence:
        return answer or ""
    cleaned = _ABSENCE.sub(" ", answer or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ;")
    if sentence.lower() in cleaned.lower():
        return cleaned
    if cleaned:
        return f"{cleaned.rstrip('. ')}. {sentence}"
    return sentence


def ensure_concept_representation(selected, all_items, concepts) -> list:
    """Un concepto con evidencia no puede quedar fuera porque otro tema llena el top."""
    chosen = list(selected or [])
    for concept in concepts:
        if any(_status_on_text(concept, _as_text(item)) != MISSING for item in chosen):
            continue
        candidates = [
            item
            for item in all_items or ()
            if _status_on_text(concept, _as_text(item)) == COVERED
        ]
        if not candidates:
            candidates = [
                item
                for item in all_items or ()
                if _status_on_text(concept, _as_text(item)) == PARTIAL
            ]
        if not candidates:
            continue
        best = max(candidates, key=lambda item: float(getattr(item, "score", 0.0) or 0.0))
        if all(getattr(best, "evidence_id", id(best)) != getattr(item, "evidence_id", id(item)) for item in chosen):
            chosen.append(best)
    return chosen


def vocabulary_from_activation(question: str, aspect_labels: tuple[str, ...] | list[str]) -> dict:
    """Aliases del aspecto = labels que el fabric activó. Sin lista fija."""
    labels = tuple(str(label).strip() for label in aspect_labels or () if str(label).strip())
    if not labels:
        return {}
    plan = extract_narrative_concepts(question)
    vocabulary: dict[str, tuple[str, ...]] = {}
    for frame in plan.frames:
        key = frame.aspect or ("" if frame.entity else frame.label)
        if key:
            vocabulary[key] = labels
    return vocabulary


def prefer_aspect_items(
    selected,
    concepts,
    *,
    keep_uncovered: int | None = None,
) -> list:
    """El aspecto pedido va primero. REORDENA, no recorta.

    `select_evidence` ya recortó por presupuesto y tope: truncar acá borraba
    los pasajes que explican el aspecto (p. ej. «date override» para
    «cambio de fechas») aunque estuvieran seleccionados. Un ítem es relevante
    si cubre el concepto o si comparte tokens con sus aliases documentales.
    `keep_uncovered` queda sólo por compatibilidad explícita.
    """
    chosen = list(selected or [])
    watched = [concept for concept in concepts or () if getattr(concept, "aliases", ())]
    if not chosen or not watched:
        return chosen

    def relevant(item: object) -> bool:
        text = _as_text(item)
        text_tokens = set(_tokens(text))
        for concept in watched:
            if _status_on_text(concept, text) != MISSING:
                return True
            terms = set(_tokens(concept.label))
            for alias in concept.aliases:
                terms.update(_tokens(alias))
            if terms & text_tokens:
                return True
        return False

    front: list = []
    back: list = []
    for item in chosen:
        (front if relevant(item) else back).append(item)
    if not front:
        return chosen
    if keep_uncovered is not None:
        return front + back[: max(0, int(keep_uncovered))]
    return front + back


def narrative_coverage_applies(question: str) -> bool:
    """Las consultas ejecutables siguen en Premise Closure, no acá."""
    from src.runtime.deterministic_authority import requires_deterministic_decision

    return not requires_deterministic_decision(question or "")


def coverage_needs_jev(*, conflicts: int = 0, ambiguous: bool = False) -> bool:
    """Un concepto faltante no dispara JEV. Conflicto o ambigüedad sí."""
    return bool(int(conflicts or 0) > 0 or ambiguous)


def headings_from_items(items) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for item in items or ():
        for part in getattr(item, "section_path", ()) or ():
            text = " ".join(str(part).split())
            folded = text.lower()
            if text and folded not in seen:
                seen.add(folded)
                found.append(text)
        title = " ".join(str(getattr(item, "title", "") or "").split())
        if title and title.lower() not in seen:
            seen.add(title.lower())
            found.append(title)
    return tuple(found[:12])


def vocabulary_from_items(items) -> dict[str, tuple[str, ...]]:
    """Aliases que ya vienen en la evidencia. No inventa terminología de dominio."""
    merged: dict[str, list[str]] = {}
    for item in items or ():
        meta = getattr(item, "metadata", None) or {}
        raw = meta.get("aliases") if isinstance(meta, dict) else None
        if isinstance(raw, dict):
            pairs = raw.items()
        else:
            continue
        for key, values in pairs:
            bucket = merged.setdefault(str(key), [])
            seq = values if isinstance(values, (list, tuple)) else (values,)
            for value in seq:
                text = " ".join(str(value or "").split())
                if text and text not in bucket:
                    bucket.append(text)
    return {key: tuple(values) for key, values in merged.items()}
