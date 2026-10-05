# =============================================================================
# Semantic Rule Compiler — orquestador
# =============================================================================
# DOCUMENT RULE UNDERSTANDING / SEMANTIC RULE COMPILER
#
#   raw document -> (Document Understanding existente)
#   units/threads -> CandidateRule (propiedades + provenance distribuida)
#   -> verify (por propiedad) -> CanonicalRule + RuleConflict
#
# Determinista y puro. El LLM puede proponer (extraction_method=llm_proposed)
# pero NO establece semántica en silencio: toda propuesta pasa por verify.
# =============================================================================
from __future__ import annotations

from typing import Any, Sequence

from src.core.domain.rule_semantics import VerificationState

from .candidates import build_candidates, candidate_public_stats
from .merge import merge_distributed_rules
from .model import (
    RULE_COMPILER_VERSION,
    CandidateRule,
    CanonicalRule,
    RuleCompilation,
)
from .verify import detect_rule_conflicts, verify_candidate


class SemanticRuleCompiler:
    """Compila reglas documentales de cualquier dominio a CanonicalRule."""

    version = RULE_COMPILER_VERSION

    def compile(
        self,
        *,
        document_id: str = "",
        document_title: str = "",
        organization_id: str = "",
        units: Sequence[Any] = (),
        rule_candidates: Sequence[Any] = (),
        extra_items: Sequence[Any] = (),
        max_candidates: int = 400,
    ) -> RuleCompilation:
        candidates, indexes = build_candidates(
            document_id=document_id,
            document_title=document_title,
            units=units,
            rule_candidates=rule_candidates,
            extra_items=extra_items,
            max_candidates=max_candidates,
        )
        canonical: list[CanonicalRule] = []
        seen_ids: set[str] = set()
        for candidate in candidates:
            rule = verify_candidate(candidate)
            if not rule.rule_id or rule.rule_id in seen_ids:
                continue
            seen_ids.add(rule.rule_id)
            canonical.append(rule)

        # Reglas distribuidas: unir fragmentos compatibles (símbolo en una
        # página, política de longitud en otra, operador en una tercera).
        canonical = merge_distributed_rules(canonical)
        conflicts, canonical = detect_rule_conflicts(canonical)
        by_state: dict[str, int] = {}
        for rule in canonical:
            by_state[rule.verification_state] = by_state.get(rule.verification_state, 0) + 1

        statistics = {
            "candidates": candidate_public_stats(candidates),
            "indexes": indexes.to_public(),
            "by_state": by_state,
            "conflicts": len(conflicts),
            "unresolved_conflicts": sum(1 for conflict in conflicts if not conflict.resolved),
            "executable": sum(1 for rule in canonical if rule.executable),
        }
        return RuleCompilation(
            organization_id=str(organization_id or ""),
            document_id=str(document_id or ""),
            document_title=str(document_title or ""),
            candidates=candidates,
            canonical_rules=canonical,
            conflicts=conflicts,
            statistics=statistics,
            version=self.version,
        )

    # ------------------------------------------------------------------ LLM
    @staticmethod
    def propose_candidate(
        payload: dict,
        *,
        document_id: str = "",
        document_title: str = "",
        evidence: Sequence[Any] = (),
    ) -> CandidateRule:
        """Acepta structured output del LLM como PROPUESTA, nunca canónica.

        El payload se sanea: campos desconocidos se ignoran; la semántica
        propuesta queda en properties con extraction_method=llm_proposed y
        verification_required=True. `reason` es corto y auditable.
        """
        from src.core.domain.rule_semantics import ClaimLayer, ExtractionMethod

        from .model import RuleEvidence, RuleProperty, stable_id

        text = " ".join(str(payload.get("statement") or payload.get("text") or "").split())
        subject = str(payload.get("subject") or "").strip()
        candidate_id = stable_id(
            "cand", document_id, subject.lower(), text.lower()[:400], "llm"
        )
        candidate = CandidateRule(
            candidate_id=candidate_id,
            statement=text[:2000],
            subject=subject[:200],
            kind=str(payload.get("rule_type") or payload.get("kind") or "NORMATIVE_RULE"),
            modality=str(payload.get("modality") or "NONE"),
            operator=str(payload.get("operator") or ""),
            confidence=max(0.0, min(1.0, float(payload.get("confidence") or 0.5))),
            extraction_method=ExtractionMethod.LLM_PROPOSED.value,
            ambiguities=[str(value) for value in payload.get("ambiguities") or ()][:12],
            missing_premises=[str(value) for value in payload.get("missing_premises") or ()][:12],
        )
        for entry in evidence:
            candidate.evidence.append(entry)
        if not candidate.evidence and payload.get("source_evidence"):
            for index, ref in enumerate(payload.get("source_evidence") or ()):
                candidate.evidence.append(
                    RuleEvidence(
                        evidence_id=str(ref.get("evidence_id") if isinstance(ref, dict) else ref) or f"llm:{index}",
                        excerpt=str(payload.get("statement") or "")[:400],
                        layer=ClaimLayer.OBSERVED.value,
                        role="llm_reference",
                        method=ExtractionMethod.LLM_PROPOSED.value,
                        strength=0.5,
                    )
                )
        semantics = payload.get("semantics") if isinstance(payload.get("semantics"), dict) else {}
        for name, value in semantics.items():
            candidate.properties[str(name)] = RuleProperty(
                name=str(name),
                value=value,
                layer=ClaimLayer.INFERRED.value,
                state=VerificationState.PROPOSED.value,
                evidence=[item.evidence_id for item in candidate.evidence][:4],
                method=ExtractionMethod.LLM_PROPOSED.value,
                confidence=candidate.confidence,
                explicit=False,
                note="propuesta por LLM; requiere verificación",
            )
        if payload.get("reason"):
            candidate.missing_premises.append("verification_required")
        return candidate


__all__ = ["SemanticRuleCompiler"]
