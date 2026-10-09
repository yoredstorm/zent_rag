# =============================================================================
# Narrative Coverage Closure — cobertura explicativa, no autoridad.
# Un miss de top-k no prueba que el corpus no tenga el tema.
# Premise Closure no entra acá.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.intelligence.response.entities import asked_entities

COVERED = "COVERED"
PARTIAL = "PARTIAL"
MISSING = "MISSING"

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
_STOP = frozenset(
    "de del la el los las en por para con una uno que sobre general".split()
)
_RANK = {MISSING: 0, PARTIAL: 1, COVERED: 2}


@dataclass(frozen=True)
class NarrativeConcept:
    concept_id: str
    label: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeConceptPlan:
    concepts: tuple[NarrativeConcept, ...] = ()


@dataclass(frozen=True)
class ConceptCoverage:
    concept_id: str
    label: str
    status: str
    epistemic: str
    aliases: tuple[str, ...] = ()


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


def extract_narrative_concepts(
    question: str,
    *,
    vocabulary: dict | None = None,
) -> NarrativeConceptPlan:
    """Temas que la pregunta pide explicar. La conjunción separa conceptos."""
    clauses = [part.strip() for part in _SPLIT.split(question or "") if part.strip()]
    labels: list[str] = []
    for clause in clauses:
        label = _label_for(clause)
        if not label:
            continue
        if any(_norm(label) == _norm(existing) for existing in labels):
            continue
        labels.append(label)
    if not labels:
        fallback = _clean_clause(question or "")
        if fallback:
            labels.append(fallback)
    concepts = tuple(
        NarrativeConcept(
            concept_id=f"C{index}",
            label=label,
            aliases=_aliases_for(label, vocabulary),
        )
        for index, label in enumerate(labels[:6], start=1)
    )
    return NarrativeConceptPlan(concepts=concepts)


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


def measure_coverage(
    plan: NarrativeConceptPlan,
    texts: object,
    *,
    searched: bool = False,
) -> tuple[ConceptCoverage, ...]:
    """Cobertura del paquete recuperado. No afirma nada sobre el corpus entero."""
    blobs = [_as_text(item) for item in (texts or ())]
    measured: list[ConceptCoverage] = []
    for concept in plan.concepts:
        status = MISSING
        for blob in blobs:
            found = _status_on_text(concept, blob)
            if _RANK[found] > _RANK[status]:
                status = found
            if status == COVERED:
                break
        measured.append(
            ConceptCoverage(
                concept_id=concept.concept_id,
                label=concept.label,
                status=status,
                epistemic=_epistemic(status, searched=searched),
                aliases=concept.aliases,
            )
        )
    return tuple(measured)


def _shares_term(heading: str, concept: NarrativeConcept) -> bool:
    heading_tokens = set(_tokens(heading))
    if not heading_tokens:
        return False
    concept_tokens = set(_tokens(concept.label))
    for alias in concept.aliases:
        concept_tokens.update(_tokens(alias))
    return bool(heading_tokens & concept_tokens)


def build_coverage_query(
    concept: NarrativeConcept,
    *,
    anchors: tuple[str, ...] = (),
    headings: tuple[str, ...] = (),
) -> str:
    """Query dirigida. Terminología exacta, después aliases, después headings."""
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = " ".join(str(value or "").split())
        folded = _norm(text)
        if text and folded not in seen:
            seen.add(folded)
            parts.append(text)

    for anchor in anchors:
        add(anchor)
    add(concept.label)
    for alias in concept.aliases:
        add(alias)
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
    """Como máximo una ronda extra, y solo si queda paso para buscar y generar."""
    missing = [item for item in measured if item.status == MISSING]
    if not missing:
        return CoverageRoundDecision(False, "", "initial_sufficient")
    if int(rounds_done) >= int(max_rounds):
        return CoverageRoundDecision(False, "", "max_rounds")
    if over_budget or int(remaining_steps) < 2:
        return CoverageRoundDecision(False, "", "budget", "budget")
    chunks = [
        build_coverage_query(
            NarrativeConcept(item.concept_id, item.label, item.aliases),
            anchors=anchors,
            headings=headings,
        )
        for item in missing
    ]
    words: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for word in chunk.split():
            folded = word.lower()
            if folded not in seen:
                seen.add(folded)
                words.append(word)
    return CoverageRoundDecision(True, " ".join(words), "coverage_retrieval")


def limitation_sentence(measured: tuple[ConceptCoverage, ...] | list[ConceptCoverage]) -> str:
    missing = [item.label for item in measured if item.status == MISSING]
    if not missing:
        return ""
    covered = [item.label for item in measured if item.status == COVERED]
    if len(covered) == 1 and len(missing) == 1:
        return (
            f"Encontré respaldo suficiente para explicar {covered[0]}, "
            f"pero no encontré evidencia suficiente sobre {missing[0]} "
            "en las fuentes disponibles para este agente."
        )
    listed = ", ".join(missing)
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
