# =============================================================================
# GenerationPackage — lo que el generador recibe, explícito y auditable
# =============================================================================
# Antes de llamar al modelo: pregunta, ejemplos del usuario, requirements,
# anchors exactos, bloques de contexto, contradicciones, faltantes y mapa de
# citas. `ready=True` sólo si no hay evidencia faltante relevante; si hay
# faltantes y ya no se puede seguir buscando, se genera con límites declarados.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
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
        }


def build_generation_package(
    *,
    question: str,
    views: Any | None = None,
    requirements: Any | None = None,
    selection: Any | None = None,
    contradictions: int = 0,
    extra_missing: tuple[str, ...] = (),
) -> GenerationPackage:
    """Arma el paquete final sin LLM: todo determinístico y trazable."""
    examples: tuple[str, ...] = ()
    exact_anchors: tuple[str, ...] = ()
    if views is not None:
        examples = tuple(str(value) for value in getattr(views, "examples", ()) or ())
        exact_anchors = tuple(
            str(value) for value in getattr(views, "exact_terms", ()) or ()
        )

    requirements_payload: list[dict[str, Any]] = []
    missing: list[str] = []
    conflicting: list[str] = []
    if requirements is not None and hasattr(requirements, "to_public_dict"):
        payload = requirements.to_public_dict()
        requirements_payload = list(payload.get("requirements") or ())
        missing = list(payload.get("pending") or ())
        for requirement in getattr(requirements, "requirements", ()) or ():
            if str(getattr(requirement, "state", "")) == "conflicting":
                conflicting.append(str(getattr(requirement, "description", "")))
    missing.extend(str(item) for item in extra_missing if str(item or "").strip())

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
    return GenerationPackage(
        question=str(question or ""),
        examples=examples,
        exact_anchors=exact_anchors,
        requirements=tuple(requirements_payload),
        missing_evidence=missing_evidence,
        contradictions=tuple(dict.fromkeys(conflicting)),
        context_blocks=tuple(blocks),
        citation_map=tuple(citations),
        ready=not missing_evidence,
        mode="generate" if not missing_evidence else "generate_with_limits",
    )


def allow_model_escalation(uncertainty: str) -> bool:
    """El modelo superior sólo se justifica con razonamiento, no por retrieval.

    `retrieval` => falta evidencia: primero buscar mejor con el mismo modelo.
    `reasoning` o `none` => la evidencia está completa; el hint puede aplicar.
    """
    return str(uncertainty or "").strip().lower() != "retrieval"


__all__ = ["GenerationPackage", "allow_model_escalation", "build_generation_package"]
