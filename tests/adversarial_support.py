# =============================================================================
# Adversarial benchmark — soporte (dominios sintéticos, sin ATPCO)
# =============================================================================
# Helpers para construir documentos/unidades y compilar reglas. Cada dominio
# usa vocabulario distinto: no se reutiliza el léxico de los tests anteriores.
# =============================================================================
from __future__ import annotations

from typing import Sequence
from uuid import UUID, uuid4

from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import (
    CanonicalRule,
    SemanticRuleCompiler,
)

ADVERSARIAL_DOC = uuid4()


def unit(
    kind: str,
    text: str,
    *,
    page: int = 1,
    section: Sequence[str] = ("General",),
    label: str = "",
    document_id: UUID | None = None,
) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{(label or text[:24])}",
        label=(label or text[:24]),
        text=text,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(
                document_id=document_id or ADVERSARIAL_DOC,
                document_title="Adversarial Manual",
                page=page,
                section_path=tuple(section),
            ),
            excerpt=text,
        ),
    )


def compile_units(*units: SemanticUnit, title: str = "Adversarial Manual"):
    return SemanticRuleCompiler().compile(
        document_id=str(ADVERSARIAL_DOC),
        document_title=title,
        organization_id=str(uuid4()),
        units=list(units),
    )


def rule_with(result, needle: str) -> CanonicalRule | None:
    for rule in result.canonical_rules:
        if needle.lower() in rule.statement.lower():
            return rule
    return None


def any_executable(result) -> list[CanonicalRule]:
    return [rule for rule in result.canonical_rules if rule.executable]
