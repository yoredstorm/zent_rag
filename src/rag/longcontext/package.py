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
) -> GenerationPackage:
    """Arma el paquete final sin LLM: todo determinístico y trazable.

    Si llega `evidence_state` (EvidenceState canónico), `missing_evidence` y el
    modo salen EXCLUSIVAMENTE de ahí. Los consumidores posteriores no pueden
    volver a decidir qué falta.
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
    )


def render_evidence_state_block(payload: dict[str, Any] | None) -> str:
    """Bloque canónico para el prompt: UNA decisión, sin instrucciones dobles.

    Acepta el público del paquete (`{"evidence": {...}}`) o el del estado.
    Nunca declara missing un EXAMPLE_VALUE: sólo `missing_documentable_evidence`.
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
        else:
            status = "FOUND" if anchor.get("found") else "MISSING"
        lines.append(f"{label}: {value} -> {status}")
    for entity in (evidence.get("entities_found") or [])[:6]:
        lines.append(f"Entity: {entity} -> FOUND")
    coverage = evidence.get("coverage")
    if isinstance(coverage, (int, float)):
        lines.append(f"Requirement coverage: {round(float(coverage) * 100)}%")
    missing = list(evidence.get("missing_documentable_evidence") or ())
    lines.append(
        "Missing documentable evidence: "
        + (", ".join(str(item) for item in missing[:8]) if missing else "none")
    )
    conflicts = list(evidence.get("conflicts") or ())
    lines.append(
        "Contradictions: " + (", ".join(str(item) for item in conflicts[:6]) if conflicts else "none")
    )
    lines.append(
        f"Generation mode: {str(evidence.get('generation_mode') or '').upper() or 'GENERATE'}"
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
    "GenerationPackage",
    "allow_model_escalation",
    "build_generation_package",
    "render_evidence_state_block",
    "validate_doc_citations",
]
