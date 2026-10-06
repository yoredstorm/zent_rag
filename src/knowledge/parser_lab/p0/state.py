# =============================================================================
# P0 — KnowledgeState: un StructuredDocument pasado por Knowledge OS offline
# =============================================================================
# Misma cadena para A y B: Document Understanding, Semantic Reconstruction,
# Semantic Units, Knowledge Compiler (Rule Compiler embebido). Sin DB, sin LLM.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.domain.knowledge_v2 import StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.model import CompilationResult
from src.knowledge.compiler.pipeline import KnowledgeCompiler
from src.knowledge.parser_lab.p0.golden import COMPATIBLE_KINDS, normalize
from src.knowledge.understanding.engine import understand_document
from src.knowledge.understanding.units import build_retrieval_units


def _fact_text(fact: Any) -> str:
    parts = [
        str(getattr(fact, "subject", "") or ""),
        str(getattr(fact, "predicate", "") or ""),
        str(getattr(fact, "object_value", "") or ""),
    ]
    return " ".join(part for part in parts if part)


def _relationship_text(rel: Any) -> str:
    parts = [
        str(getattr(rel, "subject", "") or ""),
        str(getattr(rel, "predicate", "") or ""),
        str(getattr(rel, "object_value", "") or getattr(rel, "object", "") or ""),
    ]
    return " ".join(part for part in parts if part)


def candidate_rule_text(rule: Any) -> str:
    parts = [
        str(getattr(rule, "statement", "") or ""),
        str(getattr(rule, "subject", "") or ""),
    ]
    return " ".join(part for part in parts if part)


def canonical_rule_text(rule: Any) -> str:
    parts = [
        str(getattr(rule, "statement", "") or ""),
        str(getattr(rule, "subject", "") or ""),
        str(getattr(rule, "operator", "") or ""),
    ]
    for prop in (getattr(rule, "properties", {}) or {}).values():
        parts.append(str(getattr(prop, "name", "") or ""))
        value = getattr(prop, "value", None)
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value or ""))
        parts.append(str(getattr(prop, "matched_text", "") or ""))
    parts.extend(str(item) for item in (getattr(rule, "conditions", []) or []))
    parts.extend(str(item) for item in (getattr(rule, "consequences", []) or []))
    parts.extend(str(item) for item in (getattr(rule, "exceptions", []) or []))
    formula = getattr(rule, "formula", None)
    if formula is not None:
        parts.append(str(getattr(formula, "expression", "") or ""))
    enumeration = getattr(rule, "enumeration", None)
    if enumeration is not None:
        values = getattr(enumeration, "values", None) or getattr(enumeration, "allowed", None) or []
        parts.extend(str(item) for item in values)
    temporal = getattr(rule, "temporal", None)
    if temporal is not None:
        parts.append(str(getattr(temporal, "valid_from", "") or ""))
        parts.append(str(getattr(temporal, "valid_to", "") or ""))
    try:
        from src.knowledge.rule_compiler.evaluate import rule_premises

        for premise in rule_premises(rule):
            parts.append(str(getattr(premise, "statement", "") or ""))
    except Exception:  # noqa: BLE001 — premisas best-effort para matching
        pass
    return " ".join(part for part in parts if part)


def table_text(table: Any) -> str:
    parts = [str(getattr(table, "caption", "") or "")]
    parts.extend(str(cell) for cell in (getattr(table, "headers", ()) or ()))
    for row in getattr(table, "rows", ()) or ():
        parts.extend(str(cell) for cell in row)
    metadata = getattr(table, "metadata", {}) or {}
    for cell in metadata.get("cells") or []:
        parts.append(str(cell.get("text") or ""))
    return " ".join(part for part in parts if part)


def unit_text(unit: Any) -> str:
    parts = [
        str(getattr(unit, "unit_type", "") or ""),
        str(getattr(unit, "content", "") or ""),
        str(getattr(unit, "field_name", "") or ""),
    ]
    parts.extend(str(item) for item in (getattr(unit, "exact_literals", []) or []))
    for relation in getattr(unit, "relations", []) or []:
        parts.append(str(relation))
    return " ".join(part for part in parts if part)


@dataclass
class KnowledgeState:
    """Estado de conocimiento offline de un lado del A/B."""

    label: str
    document: StructuredDocument
    understood: StructuredDocument
    compiled: CompilationResult
    units: list[Any] = field(default_factory=list)

    @classmethod
    def build(cls, document: StructuredDocument, *, label: str) -> "KnowledgeState":
        filename = str(
            (document.metadata or {}).get("filename")
            or document.external_id
            or "document.pdf"
        )
        understood = understand_document(document, filename=filename)
        compiled = KnowledgeCompiler.build(understood)
        units = build_retrieval_units(understood)
        return cls(
            label=label,
            document=document,
            understood=understood,
            compiled=compiled,
            units=units,
        )

    # -- payload ------------------------------------------------------------

    @property
    def payload(self) -> dict[str, Any]:
        return (self.understood.metadata or {}).get("understanding") or {}

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return list(self.payload.get("definitions") or [])

    @property
    def document_text(self) -> str:
        return "\n".join(block.text or "" for block in self.understood.blocks)

    @property
    def rules(self) -> list[Any]:
        return list(self.compiled.canonical_rules)

    # -- haystacks ----------------------------------------------------------

    def haystacks_for(self, golden_type: str) -> list[tuple[str, Any, str]]:
        kinds = COMPATIBLE_KINDS.get(golden_type, ("unit",))
        haystacks: list[tuple[str, Any, str]] = []
        if "definition" in kinds:
            for definition in self.definitions:
                text = f"{definition.get('term') or ''} {definition.get('definition') or ''}"
                haystacks.append((text, definition, "definition"))
        if "fact" in kinds:
            for fact in self.compiled.facts:
                haystacks.append((_fact_text(fact), fact, "fact"))
        if "relationship" in kinds:
            for rel in self.compiled.relationships:
                haystacks.append((_relationship_text(rel), rel, "relationship"))
        if "rule_candidate" in kinds:
            for rule in self.compiled.rules:
                haystacks.append((candidate_rule_text(rule), rule, "rule_candidate"))
        if "canonical_rule" in kinds:
            for rule in self.rules:
                haystacks.append((canonical_rule_text(rule), rule, "canonical_rule"))
        if "table" in kinds:
            for table in self.document.tables:
                haystacks.append((table_text(table), table, "table"))
        if "unit" in kinds:
            for unit in self.units:
                haystacks.append((unit_text(unit), unit, "unit"))
        if "block" in kinds:
            for block in self.understood.blocks:
                haystacks.append((block.text or "", block, "block"))
        return haystacks

    def produced_haystacks_for(self, golden_type: str) -> list[tuple[str, Any, str]]:
        """Objetos finales (sin units/blocks) para precision."""
        return [
            item
            for item in self.haystacks_for(golden_type)
            if item[2] not in {"unit", "block"}
        ]

    # -- provenance ---------------------------------------------------------

    @staticmethod
    def rule_locators(rule: Any) -> list[dict[str, Any]]:
        locators: list[dict[str, Any]] = []
        for evidence in getattr(rule, "provenance", []) or []:
            locator = getattr(evidence, "locator", {}) or {}
            if locator:
                locators.append(dict(locator))
        return locators

    @classmethod
    def rule_has_locator(cls, rule: Any) -> bool:
        keys = ("page", "page_number", "page_start", "section_path", "block_id")
        return any(
            any(locator.get(key) for key in keys) for locator in cls.rule_locators(rule)
        )

    @classmethod
    def rule_pages(cls, rule: Any) -> set[int]:
        pages: set[int] = set()
        for locator in cls.rule_locators(rule):
            for key in ("page", "page_number", "page_start"):
                value = locator.get(key)
                if isinstance(value, int):
                    pages.add(value)
        return pages

    @staticmethod
    def has_formula_block(state: "KnowledgeState") -> bool:
        return any(
            block.kind is StructuredBlockKind.FORMULA
            for block in state.understood.blocks
        )


__all__ = [
    "KnowledgeState",
    "candidate_rule_text",
    "canonical_rule_text",
    "normalize",
    "table_text",
    "unit_text",
]
