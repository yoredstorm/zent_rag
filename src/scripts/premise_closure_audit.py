#!/usr/bin/env python
# =============================================================================
# Premise Closure Audit — diagnóstico explícito ANTES de cambiar el runtime.
# =============================================================================
# Responde, sobre datos REALES persistidos:
#
#   A. ¿Se crearon CanonicalRules para las premisas que la pregunta exige?
#   B. ¿Están persistidas?
#   C. ¿Están SUPPORTED?
#   D. ¿Son executable?
#   E. ¿Tienen provenance?
#   F. ¿Rule Lane puede encontrarlas (camino productivo)?
#   G. ¿El fallo es de COMPILACIÓN o de RETRIEVAL?
#
# Clasificación explícita:
#   COMPILATION_MISSING     evidencia existe, ninguna regla representa la premisa
#   RULE_INDEX_MISSING      filas de regla existen, el índice/consulta no las expone
#   RULE_RETRIEVAL_MISS     índice OK pero la búsqueda por la pregunta no las trae
#   PREMISE_LINK_MISSING    la regla existe pero no declara la dimensión semántica
#   EVIDENCE_RETRIEVAL_MISS la evidencia necesaria no aparece en chunks (no auditado aquí)
#   PREMISE_UNSUPPORTED     la regla existe y se encuentra, pero no es ejecutable
#
# Uso:
#   python -m src.scripts.premise_closure_audit --org <uuid> [--document <uuid>]
#       [--question "..."] [--no-db]
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.knowledge.rule_compiler.model import CanonicalRule

# -----------------------------------------------------------------------------
# Mapa premisa -> propiedades de CanonicalRule que la representan
# (genérico, sin dominio; solo dimensiones semánticas del compilador)
# -----------------------------------------------------------------------------
PREMISE_PROPERTY_MAP: dict[str, tuple[str, ...]] = {
    "definition:symbol:X": ("matching.symbol.X",),
    "matching:positional": ("matching.operator", "matching.fixed_position"),
    "matching:literal": ("matching.literal", "matching.fixed_position"),
    "length_policy": ("length.policy", "length.value", "length.upper", "length.boundary"),
}


@dataclass(kw_only=True)
class RuleRow:
    id: str
    name: str
    description: str
    kind: str
    verification_state: str
    executable: bool
    rule_kind: str
    operator: str
    semantics: dict
    provenance_count: int
    has_index: bool
    properties: dict[str, str] = field(default_factory=dict)


def _known_properties(semantics: dict) -> dict[str, str]:
    props: dict[str, str] = {}
    for name, payload in (semantics.get("properties") or {}).items():
        if not isinstance(payload, dict):
            continue
        value = payload.get("value")
        if value in (None, "", [], {}, "UNKNOWN"):
            continue
        props[str(name)] = str(value)[:80]
    return props


def premise_state(rules: list[RuleRow], premise: str, symbol: str = "") -> str:
    """Estado de una premisa sobre el conjunto de reglas: SATISFIED | PROPOSED | MISSING."""
    patt = premise.replace("symbol:X", f"symbol:{symbol}") if symbol else premise
    names = PREMISE_PROPERTY_MAP.get(premise, ())
    if "{symbol}" not in patt and "symbol:X" in patt:
        names = tuple(name.replace("X", symbol) for name in names) if symbol else names
    hit_any = False
    hit_supported = False
    for rule in rules:
        for name in names:
            if name.endswith(".X") and symbol:
                name = name.replace(".X", f".{symbol}")
            if name in rule.properties or (
                name.startswith("matching.symbol.") and name in rule.properties
            ):
                hit_any = True
                if rule.verification_state == "SUPPORTED":
                    hit_supported = True
        # búsqueda laxa por prefijo para dimensiones con sufijos (.1, .2)
        for name in names:
            base = name.split(".")[0]
            if base in ("length", "matching") and any(
                key.startswith(name if not name.endswith(".X") else name[:-2])
                for key in rule.properties
            ):
                hit_any = True
                if rule.verification_state == "SUPPORTED":
                    hit_supported = True
    if hit_supported:
        return "SATISFIED"
    if hit_any:
        return "PROPOSED"
    return "MISSING"


async def load_rule_rows(organization_id: UUID, document_id: UUID | None) -> list[RuleRow]:
    session = await get_async_session()
    try:
        where = ["organization_id = :org", "kind IN ('business_rule', 'BUSINESS_RULE')"]
        params: dict = {"org": str(organization_id)}
        if document_id:
            where.append("metadata->>'document_id' = :doc")
            params["doc"] = str(document_id)
        where_clause = " AND ".join(where)
        sql = (
            "SELECT id, name, description, kind, confidence, metadata "  # noqa: S608 — fragmentos constantes
            "FROM knowledge_canonical_objects "
            f"WHERE {where_clause} ORDER BY name, id"
        )
        rows = (
            await session.execute(text(sql), params)
        ).all()
    finally:
        await session.close()

    result: list[RuleRow] = []
    for row in rows:
        metadata = dict(row.metadata or {})
        semantics = metadata.get("semantics") if isinstance(metadata.get("semantics"), dict) else {}
        provenance = metadata.get("rule_provenance")
        result.append(
            RuleRow(
                id=str(row.id),
                name=str(row.name or ""),
                description=str(row.description or ""),
                kind=str(row.kind or ""),
                verification_state=str(
                    metadata.get("verification_state")
                    or semantics.get("verification_state")
                    or ""
                ),
                executable=bool(semantics.get("executable", False)),
                rule_kind=str(semantics.get("kind") or metadata.get("rule_kind") or ""),
                operator=str(semantics.get("operator") or ""),
                semantics=semantics,
                provenance_count=len(provenance or []) if isinstance(provenance, list) else 0,
                has_index=bool(metadata.get("retrieval_index")),
                properties=_known_properties(semantics),
            )
        )
    return result


def audit_rule_set(
    rules: list[RuleRow],
    *,
    symbol: str,
    premises: list[str],
) -> dict:
    coverage = {}
    for premise in premises:
        coverage[premise] = premise_state(rules, premise, symbol=symbol)
    return {
        "total": len(rules),
        "by_state": _count(rules, lambda r: r.verification_state or "(sin estado)"),
        "executable": sum(1 for r in rules if r.executable),
        "with_provenance": sum(1 for r in rules if r.provenance_count > 0),
        "with_index": sum(1 for r in rules if r.has_index),
        "by_rule_kind": _count(rules, lambda r: r.rule_kind or "(sin kind)"),
        "premise_coverage": coverage,
        "rules_matching_symbol": [
            {"id": r.id, "name": r.name[:50], "state": r.verification_state, "exec": r.executable}
            for r in rules
            if symbol in r.properties
            or symbol in json.dumps(r.semantics, ensure_ascii=False)
        ][:12],
    }


def _count(rules: list[RuleRow], key) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in rules:
        value = key(rule)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


async def production_retrieval(organization_id: UUID, question: str, rules: list[RuleRow]) -> dict:
    """Ejecuta el camino productivo del Rule Lane (PostgresRuleIndex + Lookup)."""
    from src.runtime.rule_retrieval import retrieve_canonical_rules

    result = await retrieve_canonical_rules(organization_id, question)
    return {
        "strategy": result.strategy,
        "candidates": len(result.candidate_rules),
        "supported": len(result.supported_rules),
        "executable": len(result.executable_rules),
        "reasons": result.reasons,
        "evidence_signal": result.evidence_signal,
        "errors": result.errors,
        "public": result.to_public_dict(),
    }


def evaluate_direct(
    question: str,
    rules: list[RuleRow],
) -> dict:
    """Evalúa como si el retrieval hubiese funcionado: carga directa de reglas."""
    from src.intelligence.reasoning.grounded_engine import reason_over_evidence

    canonical = [CanonicalRule.from_dict(rule.semantics) for rule in rules if rule.semantics]
    canonical = [rule for rule in canonical if rule.rule_id]
    grounded = reason_over_evidence(question=question, evidence_items=[], canonical_rules=canonical)
    return {
        "rules_supplied": len(canonical),
        "answerability": grounded.answerability,
        "missing_premises": list(grounded.missing_premises),
        "abstention_message": grounded.abstention_message,
        "claims": [
            {
                "status": getattr(claim, "verification_status", ""),
                "operation": getattr(claim, "operation", ""),
                "statement": str(getattr(claim, "statement", ""))[:120],
            }
            for claim in (getattr(getattr(grounded, "derivations", None), "claims", ()) or ())
        ][:6],
    }


def classify(audit: dict, retrieval: dict, direct: dict) -> list[str]:
    findings: list[str] = []
    coverage = audit["premise_coverage"]
    missing_in_rules = [p for p, state in coverage.items() if state == "MISSING"]
    proposed = [p for p, state in coverage.items() if state == "PROPOSED"]
    if audit["total"] and missing_in_rules:
        findings.append("COMPILATION_MISSING: " + ", ".join(missing_in_rules))
    if proposed:
        findings.append("PREMISE_UNSUPPORTED: " + ", ".join(proposed))
    if audit["total"] and not audit["with_index"]:
        findings.append("RULE_INDEX_MISSING: ninguna regla persistida tiene retrieval_index")
    if audit["total"] and retrieval["candidates"] == 0 and not retrieval["errors"]:
        findings.append(
            "RULE_RETRIEVAL_MISS: hay reglas persistidas pero el Rule Lane productivo devolvió 0"
        )
    if retrieval["candidates"] > 0 and not retrieval["supported"]:
        findings.append("PREMISE_UNSUPPORTED: candidatas encontradas, ninguna SUPPORTED")
    if direct.get("missing_premises"):
        findings.append(
            "COMPILATION_GAP: aun con carga directa faltan premisas: "
            + ", ".join(direct["missing_premises"][:8])
        )
    if not findings:
        findings.append("SIN HALLAZGOS: revisar pregunta/documento/org")
    return findings


def _print(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")  # noqa: T201
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))  # noqa: T201


async def _main(args: argparse.Namespace) -> None:
    organization_id = UUID(args.org)
    document_id = UUID(args.document) if args.document else None
    question = args.question
    symbol = args.symbol

    rules = await load_rule_rows(organization_id, document_id)
    premises = ["definition:symbol:X", "matching:positional", "matching:literal", "length_policy"]
    audit = audit_rule_set(rules, symbol=symbol, premises=premises)
    audit["organization_id"] = str(organization_id)
    audit["document_id"] = str(document_id) if document_id else None
    _print("A-E: CanonicalRules persistidas", audit)

    retrieval = await production_retrieval(organization_id, question, rules)
    _print("F: Rule Lane productivo", retrieval)

    direct = evaluate_direct(question, rules)
    _print("G: Evaluación con carga directa (si retrieval funcionara)", direct)

    findings = classify(audit, retrieval, direct)
    _print("DIAGNÓSTICO", {"findings": findings})


def main() -> None:
    parser = argparse.ArgumentParser(description="Premise closure audit")
    parser.add_argument("--org", required=True, help="Organization UUID")
    parser.add_argument("--document", help="Document UUID (scope)")
    parser.add_argument(
        "--question",
        default="yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE cumple o no cumple",
    )
    parser.add_argument("--symbol", default="&")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
