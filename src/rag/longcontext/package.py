# =============================================================================
# GenerationPackage — lo que el generador recibe, explícito y auditable
# =============================================================================
# Antes de llamar al modelo: pregunta, ejemplos del usuario, requirements,
# anchors exactos, bloques de contexto, contradicciones, faltantes y mapa de
# citas. `ready=True` sólo si no hay evidencia faltante relevante; si hay
# faltantes y ya no se puede seguir buscando, se genera con límites declarados.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(kw_only=True)
class GenerationPackage:
    question: str
    examples: tuple[str, ...] = ()
    exact_anchors: tuple[str, ...] = ()
    requirements: tuple[dict[str, Any], ...] = ()
    missing_evidence: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    context_blocks: tuple[dict[str, Any], ...] = ()
    citation_map: tuple[dict[str, Any], ...] = ()
    ready: bool = False
    mode: str = "generate"
    #: Estado canónico de evidencia (autoridad única). El generador y los
    #: validadores consumen ESTO; no recalculan coverage por su cuenta.
    evidence: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""
    #: Fase 13: contexto compilado estructurado (secciones reales, no chunks).
    compiled_context: dict[str, Any] = field(default_factory=dict)
    # --- Contrato de grounding y razonamiento derivado (§46) ----------------
    grounding_mode: str = ""
    grounding: dict[str, Any] = field(default_factory=dict)
    semantics: dict[str, Any] = field(default_factory=dict)
    runtime_inputs: tuple[str, ...] = ()
    runtime_patterns: tuple[str, ...] = ()
    domain_premises: tuple[dict[str, Any], ...] = ()
    derived_claims: tuple[dict[str, Any], ...] = ()
    allowed_operations: tuple[str, ...] = ()
    missing_premises: tuple[str, ...] = ()
    answerability: str = ""
    derivation: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(
        self,
        *,
        max_blocks: int = 12,
        max_citations: int = 12,
    ) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "mode": self.mode,
            "question": self.question[:400],
            "examples": list(self.examples)[:8],
            "examples_requires_source_match": False,
            "exact_anchors": list(self.exact_anchors)[:12],
            "requirements": [dict(item) for item in self.requirements[:12]],
            "missing_evidence": list(self.missing_evidence)[:8],
            "contradictions": list(self.contradictions)[:6],
            "context_blocks": [dict(item) for item in self.context_blocks[:max_blocks]],
            "citation_map": [dict(item) for item in self.citation_map[:max_citations]],
            "context_chars": sum(
                int(item.get("chars") or 0) for item in self.context_blocks
            ),
            "stop_reason": self.stop_reason or None,
            "evidence": dict(self.evidence),
            "compiled_context": dict(self.compiled_context),
            "grounding_mode": self.grounding_mode or None,
            "grounding": dict(self.grounding),
            "semantics": dict(self.semantics),
            "runtime_inputs": list(self.runtime_inputs)[:8],
            "runtime_patterns": list(self.runtime_patterns)[:8],
            "runtime_patterns_requires_literal_match": False,
            "domain_premises": [dict(item) for item in self.domain_premises[:8]],
            "derived_claims": [dict(item) for item in self.derived_claims[:6]],
            "allowed_operations": list(self.allowed_operations)[:12],
            "missing_premises": list(self.missing_premises)[:8],
            "answerability": self.answerability or None,
            "derivation": dict(self.derivation),
        }


def build_generation_package(
    *,
    question: str,
    views: Any | None = None,
    requirements: Any | None = None,
    selection: Any | None = None,
    contradictions: int = 0,
    extra_missing: tuple[str, ...] = (),
    evidence_state: Any | None = None,
    stop_reason: str = "",
    compiled_context: Any | None = None,
    grounded_reasoning: Any | None = None,
) -> GenerationPackage:
    """Arma el paquete final sin LLM: todo determinístico y trazable.

    Si llega `evidence_state` (EvidenceState canónico), `missing_evidence` y el
    modo salen EXCLUSIVAMENTE de ahí. Los consumidores posteriores no pueden
    volver a decidir qué falta.

    Si llega `grounded_reasoning` (motor de razonamiento grounded), el paquete
    transporta: modo de grounding, premisas del dominio, datos de runtime,
    claims derivados, operaciones permitidas y premisas faltantes.
    """
    examples: tuple[str, ...] = ()
    exact_anchors: tuple[str, ...] = ()
    if views is not None:
        examples = tuple(str(value) for value in getattr(views, "examples", ()) or ())
        exact_anchors = tuple(
            str(value) for value in getattr(views, "exact_terms", ()) or ()
        )

    evidence_public: dict[str, Any] = {}
    canonical_missing: list[str] = []
    canonical_conflicts: list[str] = []
    canonical_mode = ""
    if evidence_state is not None:
        evidence_public = (
            evidence_state.to_public_dict()
            if hasattr(evidence_state, "to_public_dict")
            else dict(evidence_state)
        )
        canonical_missing = list(
            evidence_public.get("missing_documentable_evidence") or ()
        )
        canonical_conflicts = list(evidence_public.get("conflicts") or ())
        canonical_mode = str(evidence_public.get("generation_mode") or "")
        if not examples:
            examples = tuple(
                str(value) for value in evidence_public.get("example_values") or ()
            )

    requirements_payload: list[dict[str, Any]] = []
    missing: list[str] = []
    conflicting: list[str] = []
    if evidence_state is None and requirements is not None and hasattr(
        requirements, "to_public_dict"
    ):
        payload = requirements.to_public_dict()
        requirements_payload = list(payload.get("requirements") or ())
        missing = list(payload.get("pending") or ())
        for requirement in getattr(requirements, "requirements", ()) or ():
            if str(getattr(requirement, "state", "")) == "conflicting":
                conflicting.append(str(getattr(requirement, "description", "")))
    elif isinstance(evidence_public.get("requirements"), list):
        requirements_payload = list(evidence_public.get("requirements") or ())
    missing.extend(str(item) for item in extra_missing if str(item or "").strip())
    if canonical_missing:
        missing = canonical_missing  # autoridad canónica: no se mezcla con legacy
        conflicting = canonical_conflicts or conflicting

    blocks: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    if selection is not None:
        for item, match in zip(
            list(getattr(selection, "items", ()) or ()),
            list(getattr(selection, "matches", ()) or ()),
        ):
            blocks.append(
                {
                    "evidence_id": str(getattr(item, "evidence_id", "") or ""),
                    "title": str(getattr(item, "title", "") or ""),
                    "page": getattr(item, "page", None),
                    "section_path": list(getattr(item, "section_path", ()) or ()),
                    "match": str(getattr(match, "match", "") or ""),
                    "chars": int(getattr(match, "chars", 0) or 0),
                }
            )
            citations.append(
                {
                    "evidence_id": str(getattr(item, "evidence_id", "") or ""),
                    "document_id": str(getattr(item, "document_id", "") or ""),
                    "source_id": str(getattr(item, "source_id", "") or ""),
                    "title": str(getattr(item, "title", "") or ""),
                    "page": getattr(item, "page", None),
                    "citation": str(getattr(item, "citation", "") or ""),
                }
            )

    if contradictions > 0:
        conflicting.append(f"{contradictions} fragmento(s) en conflicto")
    missing_evidence = tuple(dict.fromkeys(item for item in missing if item))
    mode = canonical_mode or (
        "generate_full" if not missing_evidence else "generate_with_limits"
    )
    ready = bool(evidence_public.get("evidence_complete")) if evidence_public else (
        not missing_evidence
    )

    # --- Contrato de grounding + razonamiento derivado (§46) ----------------
    grounding_public: dict[str, Any] = {}
    if grounded_reasoning is not None:
        try:
            grounding_public = (
                grounded_reasoning.to_public_dict()
                if hasattr(grounded_reasoning, "to_public_dict")
                else dict(grounded_reasoning)
            )
        except Exception:  # noqa: BLE001 — el paquete nunca se rompe por esto
            grounding_public = {}
    grounding_contract = (
        grounding_public.get("grounding")
        if isinstance(grounding_public.get("grounding"), dict)
        else {}
    )
    derivations_public = (
        grounding_public.get("derivations")
        if isinstance(grounding_public.get("derivations"), dict)
        else {}
    )
    runtime_inputs = tuple(
        str(value) for value in grounding_public.get("runtime_inputs") or ()
    )
    runtime_patterns = tuple(
        str(value) for value in grounding_public.get("runtime_patterns") or ()
    )
    missing_premises = tuple(
        str(value) for value in grounding_public.get("missing_premises") or ()
    )
    derived_claims = tuple(
        dict(item) for item in derivations_public.get("claims") or () if isinstance(item, dict)
    )
    domain_premises = tuple(
        dict(item) for item in grounding_public.get("premises") or () if isinstance(item, dict)
    )
    allowed_operations = tuple(
        str(value) for value in grounding_contract.get("allowed_operations") or ()
    )
    if not examples and runtime_inputs:
        examples = runtime_inputs
    ready = bool(ready and not missing_premises)
    return GenerationPackage(
        question=str(question or ""),
        examples=examples,
        exact_anchors=exact_anchors,
        requirements=tuple(requirements_payload),
        missing_evidence=missing_evidence,
        contradictions=tuple(dict.fromkeys(conflicting)),
        context_blocks=tuple(blocks),
        citation_map=tuple(citations),
        ready=ready and not missing_evidence,
        mode=mode,
        evidence=evidence_public,
        stop_reason=str(stop_reason or evidence_public.get("stop_reason") or ""),
        compiled_context=(
            compiled_context.to_public_dict()
            if hasattr(compiled_context, "to_public_dict")
            else dict(compiled_context or {})
        ),
        grounding_mode=str(grounding_contract.get("mode") or ""),
        grounding=dict(grounding_contract),
        semantics=(
            dict(grounding_public.get("semantics") or {})
            if isinstance(grounding_public.get("semantics"), dict)
            else {}
        ),
        runtime_inputs=runtime_inputs,
        runtime_patterns=runtime_patterns,
        domain_premises=domain_premises,
        derived_claims=derived_claims,
        allowed_operations=allowed_operations,
        missing_premises=missing_premises,
        answerability=str(grounding_public.get("answerability") or ""),
        derivation=dict(derivations_public),
    )


def render_evidence_state_block(payload: dict[str, Any] | None) -> str:
    """Bloque canónico para el prompt: UNA decisión, sin instrucciones dobles.

    Acepta el público del paquete (`{"evidence": {...}}`) o el del estado.
    Nunca declara missing un EXAMPLE_VALUE ni una instancia de patrón: sólo
    `missing_documentable_evidence` y `missing_premises`.
    """
    if not isinstance(payload, dict):
        return ""
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else payload
    if not isinstance(evidence, dict) or not evidence:
        return ""
    anchors = [item for item in (evidence.get("anchors") or []) if isinstance(item, dict)]
    labels = {
        "rule_anchor": "Documented rule",
        "field_anchor": "Field",
        "reference": "Reference",
        "entity": "Entity",
        "example_value": "User input",
        "runtime_pattern": "Runtime pattern",
        "runtime_value": "User input",
    }
    lines = [
        "## EVIDENCE STATE (autoridad canónica del evidence engine; coverage legacy deshabilitado)"
    ]
    for anchor in anchors[:10]:
        role = str(anchor.get("role") or "")
        label = labels.get(role, "Anchor")
        value = str(anchor.get("value") or "")
        if role == "example_value":
            status = "EXAMPLE VALUE · source match required: NO"
        elif role == "runtime_pattern":
            status = "RUNTIME PATTERN · literal match required: NO · documented semantics required: YES"
        elif role == "runtime_value":
            status = "USER INPUT · source match required: NO"
        else:
            status = "FOUND" if anchor.get("found") else "MISSING"
        lines.append(f"{label}: {value} -> {status}")
    for entity in (evidence.get("entities_found") or [])[:6]:
        lines.append(f"Entity: {entity} -> FOUND")
    domain_coverage = evidence.get("domain_requirement_coverage")
    runtime_coverage = evidence.get("runtime_input_coverage")
    if isinstance(domain_coverage, (int, float)):
        lines.append(f"Domain requirement coverage: {round(float(domain_coverage) * 100)}%")
    if isinstance(runtime_coverage, (int, float)):
        lines.append(f"Runtime input coverage: {round(float(runtime_coverage) * 100)}%")
    missing = list(evidence.get("missing_documentable_evidence") or ())
    lines.append(
        "Missing documentable evidence: "
        + (", ".join(str(item) for item in missing[:8]) if missing else "none")
    )
    missing_premises = list(evidence.get("missing_premises") or ())
    if missing_premises:
        lines.append(
            "Missing domain premises: "
            + ", ".join(str(item) for item in missing_premises[:8])
        )
    conflicts = list(evidence.get("conflicts") or ())
    lines.append(
        "Contradictions: " + (", ".join(str(item) for item in conflicts[:6]) if conflicts else "none")
    )
    lines.append(
        f"Generation mode: {str(evidence.get('generation_mode') or '').upper() or 'GENERATE'}"
    )
    return "\n".join(lines)


#: Instrucciones del contrato de grounding para el generador (§47).
GROUNDING_PROMPT_INSTRUCTIONS = (
    "USER-PROVIDED VALUES are valid scenario data: apply them against the "
    "grounded rules; do NOT search them as source evidence.",
    "DOMAIN-SPECIFIC FACTS AND RULES must be supported by retrieved evidence.",
    "DETERMINISTIC OPERATIONS on grounded premises and user inputs are allowed.",
    "DERIVED CONCLUSIONS are valid when their premises are grounded and the "
    "derivation is stated; the conclusion itself does not need to appear in sources.",
    "GENERAL MODEL KNOWLEDGE must not silently fill missing domain semantics; "
    "if a DOMAIN PREMISE is missing, state exactly which one.",
)

#: Instrucciones específicas de resultados deterministas (no negociables).
AUTHORITATIVE_RESULT_INSTRUCTIONS = (
    "These results were computed by code from verified canonical rules and "
    "SATISFIED premises. Explain them and cite their evidence.",
    "DO NOT reinterpret, recompute or invert them (MATCH is not NO_MATCH).",
    "DO NOT introduce a new premise that changes the result.",
    "If you find an apparent contradiction between a result and its evidence, "
    "do not choose one: mark INTERNAL_GROUNDING_CONFLICT and explain the "
    "conflict.",
)


def render_authoritative_results(payload: dict[str, Any] | None) -> str:
    """Bloque AUTHORITATIVE DERIVED RESULTS para el prompt final.

    Solo claims deterministas y SUPPORTED: el generador puede explicarlos y
    citarlos; no puede cambiarlos.
    """
    if not isinstance(payload, dict):
        return ""
    derivations = (
        payload.get("derivations")
        if isinstance(payload.get("derivations"), dict)
        else payload.get("derivation")
        if isinstance(payload.get("derivation"), dict)
        else {}
    )
    claims = [
        item
        for item in (payload.get("derived_claims") or derivations.get("claims") or [])
        if isinstance(item, dict)
    ]
    authoritative = [
        claim
        for claim in claims
        if claim.get("deterministic")
        and str(claim.get("verification_status") or "") == "SUPPORTED"
    ]
    if not authoritative:
        return ""
    lines = [
        "## AUTHORITATIVE DERIVED RESULTS "
        "(deterministic; explain and cite, never reinterpret)"
    ]
    for claim in authoritative[:6]:
        result = claim.get("result")
        statement = str(claim.get("statement") or "")[:240]
        operation = str(claim.get("operation") or "")
        rule_ids = [str(value) for value in claim.get("canonical_rule_ids") or () if value]
        inputs = [str(value) for value in claim.get("user_inputs") or () if value]
        refs = [str(value) for value in claim.get("evidence_refs") or () if value]
        lines.append(f"- RESULT: {result} | operation: {operation} | {statement}")
        if inputs:
            lines.append("  runtime inputs: " + ", ".join(inputs[:5]))
        if rule_ids:
            lines.append("  canonical rules: " + ", ".join(rule_ids[:4]))
        if refs:
            lines.append("  evidence: " + ", ".join(refs[:6]))
    unresolved = [
        str(value)
        for value in payload.get("missing_premises") or ()
        if str(value or "").strip()
    ]
    if unresolved:
        lines.append(
            "UNRESOLVED REQUIREMENTS (state exactly these; never default): "
            + ", ".join(unresolved[:6])
        )
    for instruction in AUTHORITATIVE_RESULT_INSTRUCTIONS:
        lines.append(f"- {instruction}")
    return "\n".join(lines)


def render_grounding_block(payload: dict[str, Any] | None) -> str:
    """Bloque de razonamiento grounded para el prompt (resultado primero)."""
    if not isinstance(payload, dict):
        return ""
    grounding = payload.get("grounding") if isinstance(payload.get("grounding"), dict) else {}
    derivations = (
        payload.get("derivations")
        if isinstance(payload.get("derivations"), dict)
        else payload.get("derivation")
        if isinstance(payload.get("derivation"), dict)
        else {}
    )
    claims = [
        item
        for item in (
            payload.get("derived_claims") or derivations.get("claims") or []
        )
        if isinstance(item, dict)
    ]
    runtime_inputs = [str(item) for item in payload.get("runtime_inputs") or ()]
    runtime_patterns = [str(item) for item in payload.get("runtime_patterns") or ()]
    missing_premises = [str(item) for item in payload.get("missing_premises") or ()]
    answerability = str(payload.get("answerability") or "")
    semantics = payload.get("semantics") if isinstance(payload.get("semantics"), dict) else {}
    mode = str(grounding.get("mode") or payload.get("grounding_mode") or "")
    if not any((claims, runtime_inputs, runtime_patterns, missing_premises, mode)):
        return ""
    lines = ["## GROUNDED REASONING (contrato de grounding; autoridad canónica)"]
    authoritative_block = render_authoritative_results(payload)
    if authoritative_block:
        lines.append("")
        lines.append(authoritative_block)
    if mode:
        lines.append(f"Grounding mode: {mode.upper()}")
    intent = str(semantics.get("intent") or "")
    if intent:
        lines.append(f"Query intent: {intent}")
    if runtime_inputs:
        lines.append(
            "Runtime inputs (valid scenario data; do NOT search as source evidence): "
            + ", ".join(runtime_inputs[:6])
        )
    if runtime_patterns:
        lines.append(
            "Runtime patterns (instance needs documented semantics, NOT literal presence): "
            + ", ".join(runtime_patterns[:6])
        )
    supported = [
        claim
        for claim in claims
        if str(claim.get("verification_status")) == "SUPPORTED"
        and not claim.get("deterministic")
    ]
    for claim in supported[:4]:
        statement = str(claim.get("statement") or "")
        result = claim.get("result")
        operation = str(claim.get("operation") or "")
        lines.append(f"DERIVED RESULT ({operation}): {statement} -> {result}")
        refs = [str(ref) for ref in claim.get("evidence_refs") or () if ref]
        if refs:
            lines.append("  premises cited: " + ", ".join(refs[:6]))
    unsupported = [
        claim
        for claim in claims
        if str(claim.get("verification_status")) not in ("SUPPORTED",)
    ]
    for claim in unsupported[:2]:
        lines.append(
            "UNVERIFIED CLAIM (do not assert): "
            + str(claim.get("statement") or "")[:160]
        )
    if missing_premises:
        lines.append(
            "MISSING DOMAIN PREMISES (state exactly this; do not fill from model knowledge): "
            + ", ".join(missing_premises[:6])
        )
    if answerability:
        lines.append(f"Answerability: {answerability}")
    for instruction in GROUNDING_PROMPT_INSTRUCTIONS:
        lines.append(f"- {instruction}")
    if supported:
        lines.append(
            "- RESULT FIRST: start with the derived result (YES/NO/MATCH/NO_MATCH/value); "
            "explain it afterwards citing the grounded premises."
        )
    return "\n".join(lines)


_DOC_TAG_RE = re.compile(r"\[Doc:\s*(\d+)\]")


def validate_doc_citations(
    answer: str,
    citation_map: Any,
) -> list[int]:
    """Citas `[Doc: N]` fuera del mapa final del paquete. Vacío = válidas.

    Sólo `cited_source ∈ citation_map` es citable; una fuente candidata que no
    llegó al paquete no puede aparecer como referencia.
    """
    total = len(list(citation_map or ()))
    invalid: set[int] = set()
    for raw in _DOC_TAG_RE.findall(answer or ""):
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if index < 1 or index > total:
            invalid.add(index)
    return sorted(invalid)


def allow_model_escalation(uncertainty: str) -> bool:
    """El modelo superior sólo se justifica con razonamiento, no por retrieval.

    `retrieval` => falta evidencia: primero buscar mejor con el mismo modelo.
    `reasoning` o `none` => la evidencia está completa; el hint puede aplicar.
    """
    return str(uncertainty or "").strip().lower() != "retrieval"


__all__ = [
    "AUTHORITATIVE_RESULT_INSTRUCTIONS",
    "GROUNDING_PROMPT_INSTRUCTIONS",
    "GenerationPackage",
    "allow_model_escalation",
    "build_generation_package",
    "render_authoritative_results",
    "render_evidence_state_block",
    "render_grounding_block",
    "validate_doc_citations",
]
