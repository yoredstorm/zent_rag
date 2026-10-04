# =============================================================================
# Information Gain — ¿la expansión agregó algo o sólo repitió?
# =============================================================================
# Antes de pasar de 64K a 128K hay que medir: tokens nuevos, documentos,
# secciones, anchors y requirements cubiertos, reducción de contradicciones y
# delta de confianza. Si sólo entra contenido redundante, la expansión se
# detiene. Determinista, sin LLM.
# =============================================================================
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from src.rag.longcontext.requirements import RequirementCoverage, evaluate_requirements

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True, kw_only=True)
class EvidenceSnapshot:
    tokens: frozenset[str] = frozenset()
    documents: frozenset[str] = frozenset()
    sections: frozenset[str] = frozenset()
    anchors: frozenset[str] = frozenset()
    entities: frozenset[str] = frozenset()
    requirements_found: frozenset[str] = frozenset()
    requirement_needles: frozenset[str] = frozenset()
    #: Fase 20: nodos del Semantic Fabric presentes en la evidencia.
    nodes: frozenset[str] = frozenset()
    coverage: float = 0.0
    anchor_coverage: float = 0.0
    confidence: float = 0.0
    contradictions: int = 0
    items: int = 0


@dataclass(frozen=True, kw_only=True)
class InformationGain:
    added_tokens: int = 0
    new_tokens: int = 0
    novelty: float = 0.0
    new_documents: int = 0
    new_sources: int = 0
    new_sections: int = 0
    new_anchors: int = 0
    new_entities: int = 0
    new_requirements: int = 0
    new_nodes: int = 0
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    requirement_coverage_delta: float = 0.0
    anchor_coverage_delta: float = 0.0
    confidence_delta: float = 0.0
    contradiction_delta: int = 0
    new_conflicts_resolved: int = 0
    duplicate_ratio: float = 0.0
    score: float = 0.0
    per_1k_tokens: float = 0.0
    redundant: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "added_tokens": self.added_tokens,
            "new_tokens": self.new_tokens,
            "novelty": round(self.novelty, 4),
            "duplicate_ratio": round(self.duplicate_ratio, 4),
            "new_documents": self.new_documents,
            "new_sources": self.new_sources,
            "new_sections": self.new_sections,
            "new_anchors": self.new_anchors,
            "new_entities": self.new_entities,
            "new_requirements": self.new_requirements,
            "new_nodes": self.new_nodes,
            "coverage_before": round(self.coverage_before, 4),
            "coverage_after": round(self.coverage_after, 4),
            "requirement_coverage_delta": round(self.requirement_coverage_delta, 4),
            "anchor_coverage_delta": round(self.anchor_coverage_delta, 4),
            "confidence_delta": round(self.confidence_delta, 4),
            "contradiction_delta": self.contradiction_delta,
            "new_conflicts_resolved": self.new_conflicts_resolved,
            "per_1k_tokens": round(self.per_1k_tokens, 4),
            "redundant": self.redundant,
        }


def snapshot(
    items: list[Any] | tuple[Any, ...],
    *,
    anchors: list[Any] | tuple[Any, ...] = (),
    entities: list[Any] | tuple[Any, ...] = (),
    requirements: list[Any] | tuple[Any, ...] = (),
    coverage: RequirementCoverage | None = None,
    confidence: float = 0.0,
    contradictions: int = 0,
) -> EvidenceSnapshot:
    """Foto determinista de la evidencia actual para comparar expansiones."""
    tokens: set[str] = set()
    documents: set[str] = set()
    sections: set[str] = set()
    nodes: set[str] = set()
    joined_parts: list[str] = []
    for item in items or ():
        content = html.unescape(str(getattr(item, "content", "") or ""))
        joined_parts.append(content.lower())
        tokens.update(_TOKEN_RE.findall(content.lower()))
        metadata = getattr(item, "metadata", None) or {}
        node_values = metadata.get("fabric_node_ids") or ()
        if isinstance(node_values, str):
            node_values = [node_values]
        for value in node_values:
            text = str(value or "")
            if text:
                nodes.add(text)
        document = str(
            getattr(item, "source_id", None)
            or metadata.get("source_id")
            or metadata.get("document_id")
            or ""
        )
        if document:
            documents.add(document)
        section = str(
            metadata.get("parent_id")
            or metadata.get("section_id")
            or metadata.get("section_path")
            or ""
        )
        if section:
            sections.add(section)
    joined = "\n".join(joined_parts)

    anchor_values: set[str] = set()
    for anchor in anchors or ():
        value = str(getattr(anchor, "value", "") or "")
        needles = [str(needle) for needle in getattr(anchor, "needles", ()) if needle]
        if value and any(needle.lower() in joined for needle in needles or [value]):
            anchor_values.add(value)

    entity_values: set[str] = set()
    for entity in entities or ():
        label = str(getattr(entity, "label", "") or "")
        variants = [
            str(variant) for variant in getattr(entity, "variants", ()) if variant
        ] or [label]
        if label and any(variant.lower() in joined for variant in variants):
            entity_values.add(label)

    anchors_total = len(list(anchors or ()))
    anchor_coverage = len(anchor_values) / anchors_total if anchors_total else 0.0

    evaluated = coverage
    if evaluated is None and requirements:
        evaluated = evaluate_requirements(requirements, items)
    found_requirements: set[str] = set()
    needles: set[str] = set()
    coverage_value = 0.0
    if evaluated is not None:
        coverage_value = evaluated.coverage
        for requirement in evaluated.requirements:
            for needle in requirement.needles:
                value = str(needle or "").strip().lower()
                if value:
                    needles.add(value)
            if requirement.state == "found":
                found_requirements.add(requirement.id)
    return EvidenceSnapshot(
        tokens=frozenset(tokens),
        documents=frozenset(documents),
        sections=frozenset(sections),
        anchors=frozenset(anchor_values),
        entities=frozenset(entity_values),
        requirements_found=frozenset(found_requirements),
        requirement_needles=frozenset(needles),
        nodes=frozenset(nodes),
        coverage=coverage_value,
        anchor_coverage=anchor_coverage,
        confidence=float(confidence or 0.0),
        contradictions=int(contradictions or 0),
        items=len(items or ()),
    )


def compute_information_gain(
    before: EvidenceSnapshot,
    after: EvidenceSnapshot,
    *,
    added_tokens: int,
    gain_min: float = 0.0,
) -> InformationGain:
    """Ganancia ponderada de una expansión. `redundant` respeta `gain_min`."""
    added = max(0, int(added_tokens))
    new_tokens = len(after.tokens - before.tokens)
    novelty = new_tokens / added if added > 0 else 0.0
    new_documents = len(after.documents - before.documents)
    new_sections = len(after.sections - before.sections)
    new_anchors = len(after.anchors - before.anchors)
    new_entities = len(after.entities - before.entities)
    new_requirements = len(after.requirements_found - before.requirements_found)
    new_nodes = len(after.nodes - before.nodes)
    coverage_delta = max(0.0, after.coverage - before.coverage)
    anchor_coverage_delta = max(0.0, after.anchor_coverage - before.anchor_coverage)
    confidence_delta = after.confidence - before.confidence
    contradiction_delta = before.contradictions - after.contradictions

    score = 0.0
    if added > 0:
        score += 0.30 * min(1.0, new_anchors / 2)
        score += 0.25 * min(1.0, coverage_delta / 0.5)
        score += 0.10 * min(1.0, new_documents / 2)
        score += 0.10 * min(1.0, new_sections / 3)
        score += 0.05 * min(1.0, new_entities / 2)
        score += 0.05 * max(0.0, min(1.0, confidence_delta / 0.3))
        score += 0.10 * novelty
        if contradiction_delta > 0:
            score += 0.05 * min(1.0, contradiction_delta)
        score = min(1.0, score)
    redundant = added == 0 or score <= max(0.0, float(gain_min))
    return InformationGain(
        added_tokens=added,
        new_tokens=new_tokens,
        novelty=novelty,
        new_documents=new_documents,
        new_sources=new_documents,
        new_sections=new_sections,
        new_anchors=new_anchors,
        new_entities=new_entities,
        new_requirements=new_requirements,
        new_nodes=new_nodes,
        coverage_before=before.coverage,
        coverage_after=after.coverage,
        requirement_coverage_delta=coverage_delta,
        anchor_coverage_delta=anchor_coverage_delta,
        confidence_delta=confidence_delta,
        contradiction_delta=contradiction_delta,
        new_conflicts_resolved=max(0, contradiction_delta),
        duplicate_ratio=(max(0.0, 1.0 - novelty) if added > 0 else 1.0),
        score=score,
        per_1k_tokens=(score / (added / 1000)) if added > 0 else 0.0,
        redundant=redundant,
    )


__all__ = [
    "EvidenceSnapshot",
    "InformationGain",
    "compute_information_gain",
    "snapshot",
]
