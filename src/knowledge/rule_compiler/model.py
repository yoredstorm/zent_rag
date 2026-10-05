# =============================================================================
# Semantic Rule Compiler — modelo formal de reglas documentales
# =============================================================================
# Representación domain-agnostic. Cada PROPIEDAD semántica importante lleva su
# propia evidencia (no un solo blob):
#
#   {
#     "operator": "POSITIONAL_MATCH",
#     "operator_evidence": ["ev_123"],
#     "anchor": "START",
#     "anchor_evidence": ["ev_456"],
#     "length_policy": "VALUE_MAY_BE_LONGER",
#     "length_policy_evidence": ["ev_789"]
#   }
#
# Separación estricta de capas:
#   OBSERVED  texto explícito de la fuente
#   INFERRED  interpretación semántica derivada del lenguaje
#   DERIVED   cómputo runtime (vive en DerivedClaim, NUNCA aquí)
#
# UNKNOWN es un valor de primera clase. Sin evidencia no hay política.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from src.core.domain.rule_semantics import (
    RULE_SEMANTICS_VERSION,
    ClaimLayer,
    ExtractionMethod,
    VerificationState,
)

RULE_COMPILER_VERSION = "semantic-rule-compiler-1"

#: Prefijo estable de ids de evidencia del compilador.
EVIDENCE_ID_PREFIX = "ev"


def stable_id(prefix: str, *parts: object) -> str:
    """Id determinista (mismo contenido -> mismo id, siempre)."""
    material = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{sha256(material.encode('utf-8')).hexdigest()[:24]}"


# -----------------------------------------------------------------------------
# Evidencia
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleEvidence:
    """Evidencia localizable de una propiedad o de la regla."""

    evidence_id: str
    locator: dict = field(default_factory=dict)
    excerpt: str = ""
    unit_id: str = ""
    source_key: str = ""
    layer: str = ClaimLayer.OBSERVED.value
    role: str = "support"
    method: str = ExtractionMethod.DETERMINISTIC.value
    strength: float = 0.7

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "locator": dict(self.locator),
            "excerpt": self.excerpt[:400],
            "unit_id": self.unit_id,
            "source_key": self.source_key,
            "layer": self.layer,
            "role": self.role,
            "method": self.method,
            "strength": round(float(self.strength), 4),
        }


# -----------------------------------------------------------------------------
# Propiedades semánticas
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleProperty:
    """Propiedad semántica con evidencia propia y estado de verificación.

    ``value`` puede ser escalar, lista o dict: la extensibilidad no exige
    cambiar el esquema cuando aparece una política nueva.
    """

    name: str
    value: Any = None
    value_kind: str = "scalar"  # scalar | list | mapping | range
    layer: str = ClaimLayer.INFERRED.value
    state: str = VerificationState.PROPOSED.value
    evidence: list[str] = field(default_factory=list)
    method: str = ExtractionMethod.DETERMINISTIC.value
    confidence: float = 0.7
    explicit: bool = True
    matched_text: str = ""
    missing_premises: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def known(self) -> bool:
        return self.value not in (None, "", [], {}, "UNKNOWN")

    @property
    def supported(self) -> bool:
        return self.state == VerificationState.SUPPORTED.value

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "value_kind": self.value_kind,
            "layer": self.layer,
            "state": self.state,
            "evidence": list(self.evidence),
            "method": self.method,
            "confidence": round(float(self.confidence), 4),
            "explicit": bool(self.explicit),
            "matched_text": self.matched_text[:240],
            "missing_premises": list(self.missing_premises),
            "note": self.note[:240],
        }


@dataclass(kw_only=True)
class RuleArgument:
    """Operando de la regla: rol explícito (preserva asimetría)."""

    name: str
    value: str = ""
    role: str = "operand"  # subject | left_operand | right_operand | pattern | value | unit
    unit: str | None = None
    evidence: list[str] = field(default_factory=list)
    layer: str = ClaimLayer.INFERRED.value

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "role": self.role,
            "unit": self.unit,
            "evidence": list(self.evidence),
            "layer": self.layer,
        }


@dataclass(kw_only=True)
class RuleScope:
    """Alcance declarado: sección, documento, versión, vigencia."""

    section_path: tuple[str, ...] = ()
    document_id: str = ""
    document_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    version_label: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    applies_to: tuple[str, ...] = ()
    priority: int | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "section_path": list(self.section_path),
            "document_id": self.document_id,
            "document_title": self.document_title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "version_label": self.version_label,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "applies_to": list(self.applies_to),
            "priority": self.priority,
            "evidence": list(self.evidence),
        }


@dataclass(kw_only=True)
class RuleTemporalSpec:
    relation: str = "UNKNOWN"
    value: str = ""
    upper: str = ""
    unit: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "relation": self.relation,
            "value": self.value,
            "upper": self.upper,
            "unit": self.unit,
            "evidence": list(self.evidence),
        }


@dataclass(kw_only=True)
class RuleFormulaSpec:
    target: str = ""
    expression: str = ""
    operands: dict = field(default_factory=dict)
    unit: str = ""
    rounding: str = ""
    precision: int | None = None
    prerequisites: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "expression": self.expression,
            "operands": dict(self.operands),
            "unit": self.unit,
            "rounding": self.rounding,
            "precision": self.precision,
            "prerequisites": list(self.prerequisites),
            "evidence": list(self.evidence),
        }


@dataclass(kw_only=True)
class RuleEnumerationSpec:
    allowed: list[str] = field(default_factory=list)
    prohibited: list[str] = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allowed": list(self.allowed[:64]),
            "prohibited": list(self.prohibited[:64]),
            "mapping": {str(key)[:80]: str(value)[:160] for key, value in list(self.mapping.items())[:64]},
            "evidence": list(self.evidence),
        }


# -----------------------------------------------------------------------------
# Candidato
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class CandidateRule:
    """Regla PROPUESTA: todavía no es conocimiento canónico ejecutable."""

    candidate_id: str
    statement: str
    subject: str = ""
    kind: str = "NORMATIVE_RULE"
    modality: str = "NONE"
    polarity: str = "UNKNOWN"
    operator: str = ""
    arguments: list[RuleArgument] = field(default_factory=list)
    properties: dict[str, RuleProperty] = field(default_factory=dict)
    conditions: list[str] = field(default_factory=list)
    consequences: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    scope: RuleScope = field(default_factory=RuleScope)
    temporal: RuleTemporalSpec = field(default_factory=RuleTemporalSpec)
    formula: RuleFormulaSpec = field(default_factory=RuleFormulaSpec)
    enumeration: RuleEnumerationSpec = field(default_factory=RuleEnumerationSpec)
    evidence: list[RuleEvidence] = field(default_factory=list)
    corroborating: list[RuleEvidence] = field(default_factory=list)
    relations: dict = field(default_factory=dict)
    ambiguities: list[str] = field(default_factory=list)
    missing_premises: list[str] = field(default_factory=list)
    confidence: float = 0.7
    extraction_method: str = ExtractionMethod.DETERMINISTIC.value
    verification_state: str = VerificationState.PROPOSED.value
    version: str = RULE_COMPILER_VERSION

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.evidence_id for item in self.evidence))

    def evidence_text(self) -> str:
        return "\n".join(item.excerpt for item in self.evidence if item.excerpt)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "statement": self.statement[:600],
            "subject": self.subject,
            "kind": self.kind,
            "modality": self.modality,
            "polarity": self.polarity,
            "operator": self.operator,
            "arguments": [item.to_dict() for item in self.arguments],
            "properties": {name: item.to_dict() for name, item in self.properties.items()},
            "conditions": list(self.conditions[:8]),
            "consequences": list(self.consequences[:8]),
            "exceptions": list(self.exceptions[:8]),
            "scope": self.scope.to_dict(),
            "temporal": self.temporal.to_dict(),
            "formula": self.formula.to_dict(),
            "enumeration": self.enumeration.to_dict(),
            "source_evidence": list(self.evidence_ids[:24]),
            "corroborating": [item.to_dict() for item in self.corroborating[:16]],
            "relations": dict(self.relations),
            "ambiguities": list(self.ambiguities[:12]),
            "missing_premises": list(self.missing_premises[:12]),
            "confidence": round(float(self.confidence), 4),
            "extraction_method": self.extraction_method,
            "verification_state": self.verification_state,
            "verification_required": True,
            "reason": self._reason(),
            "version": self.version,
        }

    def _reason(self) -> str:
        """Explicación breve y auditable (nunca cadena de pensamiento)."""
        parts = [f"{self.kind} {self.modality}"]
        policy = self.properties.get("length.policy")
        if policy is not None and policy.known:
            parts.append(f"length_policy={policy.value}")
        match = self.properties.get("matching.operator")
        if match is not None and match.known:
            parts.append(f"matching={match.value}")
        if self.exceptions:
            parts.append(f"exceptions={len(self.exceptions)}")
        return "; ".join(parts)[:300]


# -----------------------------------------------------------------------------
# Regla canónica
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class CanonicalRule:
    """Regla verificada, con provenance por propiedad. Solo SUPPORTED ejecuta."""

    rule_id: str
    statement: str
    subject: str = ""
    kind: str = "NORMATIVE_RULE"
    modality: str = "NONE"
    polarity: str = "UNKNOWN"
    operator: str = ""
    arguments: list[RuleArgument] = field(default_factory=list)
    properties: dict[str, RuleProperty] = field(default_factory=dict)
    conditions: list[str] = field(default_factory=list)
    consequences: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    scope: RuleScope = field(default_factory=RuleScope)
    temporal: RuleTemporalSpec = field(default_factory=RuleTemporalSpec)
    formula: RuleFormulaSpec = field(default_factory=RuleFormulaSpec)
    enumeration: RuleEnumerationSpec = field(default_factory=RuleEnumerationSpec)
    provenance: list[RuleEvidence] = field(default_factory=list)
    corroborating: list[RuleEvidence] = field(default_factory=list)
    relations: dict = field(default_factory=dict)
    confidence: float = 0.7
    extraction_method: str = ExtractionMethod.DETERMINISTIC.value
    verification_state: str = VerificationState.PROPOSED.value
    executable: bool = False
    ambiguities: list[str] = field(default_factory=list)
    missing_premises: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    version: str = RULE_COMPILER_VERSION
    semantics_version: str = RULE_SEMANTICS_VERSION

    @property
    def supported(self) -> bool:
        return self.verification_state == VerificationState.SUPPORTED.value

    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.evidence_id for item in self.provenance))

    def property_evidence(self, name: str) -> list[str]:
        prop = self.properties.get(name)
        return list(prop.evidence) if prop is not None else []

    def evidence_text(self) -> str:
        return "\n".join(item.excerpt for item in self.provenance if item.excerpt)

    def to_dict(self, *, include_evidence: bool = True) -> dict:
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "statement": self.statement[:1000],
            "subject": self.subject,
            "kind": self.kind,
            "modality": self.modality,
            "polarity": self.polarity,
            "operator": self.operator,
            "arguments": [item.to_dict() for item in self.arguments],
            "properties": {name: item.to_dict() for name, item in self.properties.items()},
            "conditions": list(self.conditions[:12]),
            "consequences": list(self.consequences[:12]),
            "exceptions": list(self.exceptions[:12]),
            "scope": self.scope.to_dict(),
            "temporal": self.temporal.to_dict(),
            "formula": self.formula.to_dict(),
            "enumeration": self.enumeration.to_dict(),
            "confidence": round(float(self.confidence), 4),
            "extraction_method": self.extraction_method,
            "verification_state": self.verification_state,
            "executable": bool(self.executable),
            "ambiguities": list(self.ambiguities[:12]),
            "missing_premises": list(self.missing_premises[:12]),
            "conflicts_with": list(self.conflicts_with[:12]),
            "supersedes": list(self.supersedes[:12]),
            "evidence_ids": list(self.evidence_ids()[:32]),
            "version": self.version,
            "semantics_version": self.semantics_version,
        }
        if include_evidence:
            payload["provenance"] = [item.to_dict() for item in self.provenance[:32]]
            payload["corroborating"] = [item.to_dict() for item in self.corroborating[:16]]
        payload["relations"] = dict(self.relations)
        return payload

    def to_public_dict(self) -> dict:
        """Vista para observabilidad y prompt: sin cadenas internas."""
        return {
            "rule_id": self.rule_id,
            "subject": self.subject,
            "statement": self.statement[:400],
            "kind": self.kind,
            "modality": self.modality,
            "operator": self.operator,
            "verification_state": self.verification_state,
            "executable": bool(self.executable),
            "confidence": round(float(self.confidence), 4),
            "properties": {
                name: {"value": prop.value, "state": prop.state, "evidence": prop.evidence[:6]}
                for name, prop in self.properties.items()
                if prop.known
            },
            "exceptions": list(self.exceptions[:6]),
            "missing_premises": list(self.missing_premises[:8]),
            "conflicts_with": list(self.conflicts_with[:6]),
            "evidence_ids": list(self.evidence_ids()[:12]),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CanonicalRule":
        """Rehidrata desde metadata persistida (retrieval → grounded engine)."""
        data = dict(payload or {})
        properties: dict[str, RuleProperty] = {}
        for name, prop in (data.get("properties") or {}).items():
            if isinstance(prop, dict):
                properties[name] = RuleProperty(
                    name=str(prop.get("name") or name),
                    value=prop.get("value"),
                    value_kind=str(prop.get("value_kind") or "scalar"),
                    layer=str(prop.get("layer") or ClaimLayer.INFERRED.value),
                    state=str(prop.get("state") or VerificationState.PROPOSED.value),
                    evidence=[str(value) for value in prop.get("evidence") or ()],
                    method=str(prop.get("method") or ExtractionMethod.DETERMINISTIC.value),
                    confidence=float(prop.get("confidence") or 0.7),
                    explicit=bool(prop.get("explicit", True)),
                    matched_text=str(prop.get("matched_text") or ""),
                    missing_premises=[str(value) for value in prop.get("missing_premises") or ()],
                    note=str(prop.get("note") or ""),
                )
        arguments = [
            RuleArgument(
                name=str(item.get("name") or ""),
                value=str(item.get("value") or ""),
                role=str(item.get("role") or "operand"),
                unit=item.get("unit"),
                evidence=[str(value) for value in item.get("evidence") or ()],
                layer=str(item.get("layer") or ClaimLayer.INFERRED.value),
            )
            for item in (data.get("arguments") or ())
            if isinstance(item, dict)
        ]
        scope_data = dict(data.get("scope") or {})
        temporal_data = dict(data.get("temporal") or {})
        formula_data = dict(data.get("formula") or {})
        enum_data = dict(data.get("enumeration") or {})
        provenance = [
            RuleEvidence(
                evidence_id=str(item.get("evidence_id") or ""),
                locator=dict(item.get("locator") or {}),
                excerpt=str(item.get("excerpt") or ""),
                unit_id=str(item.get("unit_id") or ""),
                source_key=str(item.get("source_key") or ""),
                layer=str(item.get("layer") or ClaimLayer.OBSERVED.value),
                role=str(item.get("role") or "support"),
                method=str(item.get("method") or ExtractionMethod.DETERMINISTIC.value),
                strength=float(item.get("strength") or 0.7),
            )
            for item in (data.get("provenance") or ())
            if isinstance(item, dict)
        ]
        corroborating = [
            RuleEvidence(
                evidence_id=str(item.get("evidence_id") or ""),
                locator=dict(item.get("locator") or {}),
                excerpt=str(item.get("excerpt") or ""),
                unit_id=str(item.get("unit_id") or ""),
                source_key=str(item.get("source_key") or ""),
                layer=str(item.get("layer") or ClaimLayer.OBSERVED.value),
                role=str(item.get("role") or "illustration"),
                method=str(item.get("method") or ExtractionMethod.DETERMINISTIC.value),
                strength=float(item.get("strength") or 0.5),
            )
            for item in (data.get("corroborating") or ())
            if isinstance(item, dict)
        ]
        return cls(
            rule_id=str(data.get("rule_id") or ""),
            statement=str(data.get("statement") or ""),
            subject=str(data.get("subject") or ""),
            kind=str(data.get("kind") or "NORMATIVE_RULE"),
            modality=str(data.get("modality") or "NONE"),
            polarity=str(data.get("polarity") or "UNKNOWN"),
            operator=str(data.get("operator") or ""),
            arguments=arguments,
            properties=properties,
            conditions=[str(value) for value in data.get("conditions") or ()],
            consequences=[str(value) for value in data.get("consequences") or ()],
            exceptions=[str(value) for value in data.get("exceptions") or ()],
            scope=RuleScope(
                section_path=tuple(str(value) for value in scope_data.get("section_path") or ()),
                document_id=str(scope_data.get("document_id") or ""),
                document_title=str(scope_data.get("document_title") or ""),
                page_start=scope_data.get("page_start"),
                page_end=scope_data.get("page_end"),
                version_label=scope_data.get("version_label"),
                effective_from=scope_data.get("effective_from"),
                effective_to=scope_data.get("effective_to"),
                applies_to=tuple(str(value) for value in scope_data.get("applies_to") or ()),
                priority=scope_data.get("priority"),
                evidence=[str(value) for value in scope_data.get("evidence") or ()],
            ),
            temporal=RuleTemporalSpec(
                relation=str(temporal_data.get("relation") or "UNKNOWN"),
                value=str(temporal_data.get("value") or ""),
                upper=str(temporal_data.get("upper") or ""),
                unit=str(temporal_data.get("unit") or ""),
                evidence=[str(value) for value in temporal_data.get("evidence") or ()],
            ),
            formula=RuleFormulaSpec(
                target=str(formula_data.get("target") or ""),
                expression=str(formula_data.get("expression") or ""),
                operands=dict(formula_data.get("operands") or {}),
                unit=str(formula_data.get("unit") or ""),
                rounding=str(formula_data.get("rounding") or ""),
                precision=formula_data.get("precision"),
                prerequisites=[str(value) for value in formula_data.get("prerequisites") or ()],
                evidence=[str(value) for value in formula_data.get("evidence") or ()],
            ),
            enumeration=RuleEnumerationSpec(
                allowed=[str(value) for value in enum_data.get("allowed") or ()],
                prohibited=[str(value) for value in enum_data.get("prohibited") or ()],
                mapping={str(key): str(value) for key, value in (enum_data.get("mapping") or {}).items()},
                evidence=[str(value) for value in enum_data.get("evidence") or ()],
            ),
            provenance=provenance,
            corroborating=corroborating,
            relations=dict(data.get("relations") or {}),
            confidence=float(data.get("confidence") or 0.7),
            extraction_method=str(data.get("extraction_method") or ExtractionMethod.DETERMINISTIC.value),
            verification_state=str(data.get("verification_state") or VerificationState.PROPOSED.value),
            executable=bool(data.get("executable", False)),
            ambiguities=[str(value) for value in data.get("ambiguities") or ()],
            missing_premises=[str(value) for value in data.get("missing_premises") or ()],
            conflicts_with=[str(value) for value in data.get("conflicts_with") or ()],
            supersedes=[str(value) for value in data.get("supersedes") or ()],
            version=str(data.get("version") or RULE_COMPILER_VERSION),
            semantics_version=str(data.get("semantics_version") or RULE_SEMANTICS_VERSION),
        )


# -----------------------------------------------------------------------------
# Conflictos y resultado
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleConflict:
    """Dos reglas canónicas incompatibles. No se elige en silencio."""

    conflict_id: str
    property_name: str
    rule_a_id: str
    rule_b_id: str
    value_a: Any = None
    value_b: Any = None
    reason: str = ""
    resolution: str | None = None
    resolution_basis: str = ""
    materiality: str = "MEDIUM"
    evidence: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.resolution)

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "property": self.property_name,
            "rule_a": self.rule_a_id,
            "rule_b": self.rule_b_id,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "reason": self.reason[:300],
            "resolution": self.resolution,
            "resolution_basis": self.resolution_basis[:300],
            "materiality": self.materiality,
            "evidence": list(self.evidence[:12]),
        }


@dataclass(kw_only=True)
class RuleCompilation:
    """Salida del compilador semántico para un documento."""

    organization_id: str = ""
    document_id: str = ""
    document_title: str = ""
    candidates: list[CandidateRule] = field(default_factory=list)
    canonical_rules: list[CanonicalRule] = field(default_factory=list)
    conflicts: list[RuleConflict] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)
    version: str = RULE_COMPILER_VERSION

    @property
    def executable_rules(self) -> list[CanonicalRule]:
        return [rule for rule in self.canonical_rules if rule.executable]

    def to_dict(self, *, include_candidates: bool = False) -> dict:
        payload: dict[str, Any] = {
            "version": self.version,
            "organization_id": self.organization_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "counts": {
                "candidates": len(self.candidates),
                "canonical_rules": len(self.canonical_rules),
                "executable": len(self.executable_rules),
                "conflicts": len(self.conflicts),
            },
            "by_state": self.statistics.get("by_state", {}),
            "canonical_rules": [rule.to_public_dict() for rule in self.canonical_rules[:48]],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts[:24]],
            "statistics": dict(self.statistics),
        }
        if include_candidates:
            payload["candidates"] = [rule.to_dict() for rule in self.candidates[:64]]
        return payload


__all__ = [
    "CandidateRule",
    "CanonicalRule",
    "EVIDENCE_ID_PREFIX",
    "RULE_COMPILER_VERSION",
    "RuleArgument",
    "RuleCompilation",
    "RuleConflict",
    "RuleEnumerationSpec",
    "RuleEvidence",
    "RuleFormulaSpec",
    "RuleProperty",
    "RuleScope",
    "RuleTemporalSpec",
    "stable_id",
]
