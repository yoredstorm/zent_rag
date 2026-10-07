# =============================================================================
# Query-local rules — compilación provisional SEGURA en tiempo de consulta
# =============================================================================
# Una limitación de INGESTA no puede volver inútil toda la consulta si la
# evidencia recuperada contiene la premisa. Este módulo recompila, con el
# MISMO compilador determinista y los MISMOS gates:
#
#   evidencia recuperada
#     -> CandidateRule (determinista, sin LLM)
#     -> verify_candidate (evidencia localizable + marcador verificado)
#     -> merge_distributed_rules (símbolo + matching + longitud)
#     -> CanonicalRule marcada QUERY_LOCAL
#
# Reglas inviolables:
#   - NUNCA se persiste como verdad global (el caller solo la usa en el run);
#   - solo se devuelven reglas SUPPORTED por la evidencia recuperada;
#   - si el compilador no logra cerrar la premisa, el gap se reporta, no se
#     rellena con heurística ad-hoc.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from src.core.domain.rule_semantics import VerificationState
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

QUERY_LOCAL_RULES_VERSION = "query-local-rules-1"

#: Marca en `relations` que distingue una regla provisional de una persistida.
QUERY_LOCAL_MARKER = "QUERY_LOCAL"


@dataclass(kw_only=True)
class QueryLocalCompilation:
    rules: list[Any] = field(default_factory=list)
    candidates: int = 0
    supported: int = 0
    executable: int = 0
    rejected: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
    version: str = QUERY_LOCAL_RULES_VERSION

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "candidates": self.candidates,
            "supported": self.supported,
            "executable": self.executable,
            "rejected": self.rejected,
            "conflicts": self.conflicts,
            "rules": [
                {
                    "rule_id": str(getattr(rule, "rule_id", "")),
                    "subject": str(getattr(rule, "subject", ""))[:120],
                    "state": str(getattr(rule, "verification_state", "")),
                    "executable": bool(getattr(rule, "executable", False)),
                    "missing_premises": list(getattr(rule, "missing_premises", ()) or ())[:8],
                }
                for rule in self.rules[:12]
            ],
            "errors": list(self.errors[:4]),
        }


def _item_text(item: Any) -> str:
    for attribute in ("content", "text", "statement", "excerpt"):
        value = getattr(item, attribute, None)
        if value:
            return str(value)
    if isinstance(item, dict):
        for key in ("content", "text", "statement", "excerpt"):
            if item.get(key):
                return str(item[key])
    return ""


def _item_metadata(item: Any) -> dict:
    metadata = getattr(item, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(item, dict) and isinstance(item.get("metadata"), dict):
        return dict(item["metadata"])
    return {}


def evidence_items_to_context(items: Sequence[Any]) -> list[dict]:
    """Evidencia heterogénea (chunks/EvidenceHit) -> items del compilador."""
    entries: list[dict] = []
    for index, item in enumerate(items or ()):
        text = " ".join(_item_text(item).split())
        if not text:
            continue
        metadata = _item_metadata(item)
        section_path = (
            getattr(item, "section_path", None)
            or metadata.get("section_path")
            or ()
        )
        page = getattr(item, "page", None)
        if page is None:
            page = metadata.get("page")
        document_id = str(
            getattr(item, "document_id", None) or metadata.get("document_id") or ""
        )
        source_id = str(
            getattr(item, "source_id", None) or metadata.get("source_id") or ""
        )
        evidence_id = str(
            getattr(item, "evidence_id", None)
            or metadata.get("evidence_id")
            or metadata.get("chunk_id")
            or f"query-local-evidence:{index}"
        )
        entries.append(
            {
                "item_id": evidence_id,
                "kind": str(metadata.get("kind") or metadata.get("unit_kind") or "evidence"),
                "label": str(metadata.get("label") or text[:80]),
                "text": text[:4000],
                "evidence_id": evidence_id,
                "locator": {
                    "document_id": document_id,
                    "source_id": source_id,
                    "page": page,
                    "section_path": list(section_path or ()),
                    "locator": str(metadata.get("locator") or f"query-local/{index}"),
                },
                "section_path": tuple(section_path or ()),
                "page": page,
                "block_id": str(metadata.get("block_id") or ""),
                "attributes": {"query_local": True},
            }
        )
    return entries


_CONFLICT_DIMENSIONS = (
    "length.policy",
    "matching.operator",
    "comparison.operator",
    "temporal.relation",
)


def _symbols_of(rule: Any) -> set[str]:
    symbols: set[str] = set()
    for name in getattr(rule, "properties", {}) or {}:
        if name.startswith("matching.symbol.") and not name.endswith(".alphabet"):
            symbols.add(name.rsplit(".", 1)[-1])
    return symbols


def _known_dimension(rule: Any, dimension: str) -> str | None:
    prop = (getattr(rule, "properties", {}) or {}).get(dimension)
    if prop is None or not getattr(prop, "known", False):
        return None
    return str(getattr(prop, "value", "") or "")


def mark_grammar_conflicts(rules: Sequence[Any]) -> int:
    """Conflictos de gramática en la compilación query-local.

    Dos reglas del mismo alcance que declaran valores incompatibles en la misma
    dimensión (length.policy, matching.operator, ...) no pueden decidir: ambas
    quedan CONFLICTING y no ejecutables. No inventa resolución.
    """
    count = 0
    rule_list = list(rules)
    for index, rule_a in enumerate(rule_list):
        for rule_b in rule_list[index + 1 :]:
            if getattr(rule_a, "exceptions", None) or getattr(rule_b, "exceptions", None):
                continue
            symbols_a, symbols_b = _symbols_of(rule_a), _symbols_of(rule_b)
            if symbols_a and symbols_b and not (symbols_a & symbols_b):
                continue
            for dimension in _CONFLICT_DIMENSIONS:
                value_a = _known_dimension(rule_a, dimension)
                value_b = _known_dimension(rule_b, dimension)
                if value_a is None or value_b is None or value_a == value_b:
                    continue
                for rule, other in ((rule_a, rule_b), (rule_b, rule_a)):
                    rule.verification_state = VerificationState.CONFLICTING.value
                    rule.executable = False
                    if other.rule_id not in rule.conflicts_with:
                        rule.conflicts_with.append(other.rule_id)
                    if "conflict" not in rule.missing_premises:
                        rule.missing_premises.append("conflict")
                count += 1
    return count


def compile_query_local_rules(
    items: Sequence[Any],
    *,
    document_id: str = "",
    document_title: str = "",
    organization_id: str = "",
    max_candidates: int = 80,
) -> QueryLocalCompilation:
    """PROPOSED -> VERIFY contra la evidencia -> SUPPORTED_QUERY_LOCAL.

    La marca es explícita en `relations[QUERY_LOCAL_MARKER]`; el caller decide
    si la usa para responder SOLO este run. Nunca escribe en Postgres.
    """
    compilation = QueryLocalCompilation()
    entries = evidence_items_to_context(items)
    if not entries:
        return compilation
    try:
        from src.knowledge.rule_compiler.candidates import build_candidates
        from src.knowledge.rule_compiler.merge import merge_distributed_rules
        from src.knowledge.rule_compiler.verify import verify_candidate

        candidates, _indexes = build_candidates(
            document_id=document_id,
            document_title=document_title,
            units=(),
            rule_candidates=(),
            extra_items=entries,
            max_candidates=max_candidates,
        )
        compilation.candidates = len(candidates)
        verified = []
        for candidate in candidates:
            try:
                rule = verify_candidate(candidate)
            except Exception:  # noqa: BLE001 — un candidato roto no frena el run
                compilation.rejected += 1
                continue
            if not rule.rule_id:
                compilation.rejected += 1
                continue
            if rule.verification_state != VerificationState.SUPPORTED.value:
                compilation.rejected += 1
                continue
            verified.append(rule)
        merged = merge_distributed_rules(verified) if verified else []
        compilation.conflicts = mark_grammar_conflicts(merged)
        # Clúster por unidad de evidencia: una unidad autocontenida (definición
        # + matching + longitud en un mismo chunk) conserva su propia regla
        # aunque el merge global la haya perdido o contaminado.
        clusters: dict[str, list[Any]] = {}
        for rule in verified:
            provenance = list(getattr(rule, "provenance", ()) or ())
            unit = ""
            if provenance:
                unit = str(
                    getattr(provenance[0], "unit_id", "")
                    or getattr(provenance[0], "evidence_id", "")
                    or ""
                )
            clusters.setdefault(unit or str(getattr(rule, "rule_id", "")), []).append(rule)
        seen_ids = {str(getattr(rule, "rule_id", "") or id(rule)) for rule in merged}
        for cluster in clusters.values():
            for rule in merge_distributed_rules(cluster):
                rule_id = str(getattr(rule, "rule_id", "") or id(rule))
                if rule_id in seen_ids:
                    continue
                seen_ids.add(rule_id)
                merged.append(rule)
        rules: list[Any] = []
        for rule in merged:
            if rule.verification_state != VerificationState.SUPPORTED.value:
                continue
            relations = dict(getattr(rule, "relations", {}) or {})
            relations[QUERY_LOCAL_MARKER] = sorted(
                {
                    str(getattr(evidence, "evidence_id", "") or "")
                    for evidence in (getattr(rule, "provenance", ()) or ())
                    if getattr(evidence, "evidence_id", "")
                }
            )
            relations["QUERY_LOCAL_VERSION"] = [QUERY_LOCAL_RULES_VERSION]
            rule.relations = relations
            rules.append(rule)
        compilation.rules = rules
        compilation.supported = len(rules)
        compilation.executable = sum(1 for rule in rules if getattr(rule, "executable", False))
    except Exception as exc:  # noqa: BLE001 — compilación provisional jamás rompe
        compilation.errors.append(type(exc).__name__)
        logger.warning(
            "Query-local rule compilation failed", error=str(exc)[:200]
        )
    return compilation


def rules_are_query_local(rules: Sequence[Any]) -> bool:
    return any(
        QUERY_LOCAL_MARKER in (getattr(rule, "relations", {}) or {}) for rule in rules or ()
    )


__all__ = [
    "QUERY_LOCAL_MARKER",
    "QUERY_LOCAL_RULES_VERSION",
    "QueryLocalCompilation",
    "compile_query_local_rules",
    "evidence_items_to_context",
    "rules_are_query_local",
]
