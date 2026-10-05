# =============================================================================
# Rule Retrieval — reglas canónicas como conocimiento de primera clase
# =============================================================================
# Query-time NO reparsea regex sobre texto bruto para reinterpretar semántica:
# recupera la CanonicalRule compilada (con scope, operator, conditions,
# exceptions, parámetros, evidence refs, verification state, confidence y
# vigencia) y RECIÉN DESPUÉS la evidencia de soporte para citas/auditoría.
#
# El contrato de ids viene del indexado: `metadata.canonical_rule_ids`
# (rule_key/rule_id -> id de knowledge_canonical_objects). Sin ids no se
# inventa nada: el grounded engine conserva el camino histórico.
# =============================================================================
from __future__ import annotations

from typing import Any, Iterable, Protocol, Sequence
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.rule_compiler.model import CanonicalRule

logger = get_logger(__name__)

RULE_RETRIEVAL_VERSION = "rule-retrieval-1"
MAX_RULES_PER_QUERY = 24


class RuleLookupPort(Protocol):
    """Puerto de carga de reglas canónicas por id (tenant-scoped)."""

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]: ...


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def collect_rule_ids(items: Sequence[Any]) -> list[UUID]:
    """Ids de reglas canónicas declarados por los chunks recuperados."""
    ids: list[UUID] = []
    seen: set[str] = set()
    for item in items or ():
        metadata = getattr(item, "metadata", None) or {}
        if not isinstance(metadata, dict):
            continue
        for field in ("canonical_rule_ids", "canonical_rule_objects"):
            values = metadata.get(field)
            if isinstance(values, dict):
                values = list(values.values())
            elif isinstance(values, str):
                values = [values]
            elif values is None:
                continue
            for value in values or ():
                parsed = _as_uuid(value)
                if parsed is None:
                    continue
                key = str(parsed)
                if key in seen:
                    continue
                seen.add(key)
                ids.append(parsed)
    return ids[:MAX_RULES_PER_QUERY]


class PostgresRuleLookup:
    """Carga reglas desde knowledge_canonical_objects (semántica en metadata)."""

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]:
        ids = [str(value) for value in rule_ids if value]
        if not ids:
            return []
        from sqlalchemy import bindparam
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            stmt = sql_text(
                "SELECT id, name, description, confidence, metadata "
                "FROM knowledge_canonical_objects "
                "WHERE organization_id = :org AND kind = :kind "
                "AND id::text IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            rows = (
                await session.execute(
                    stmt,
                    {
                        "org": organization_id,
                        "kind": "BUSINESS_RULE",
                        "ids": ids,
                    },
                )
            ).all()
        finally:
            await session.close()

        rules: list[CanonicalRule] = []
        for row in rows:
            metadata = dict(row.metadata or {}) if isinstance(row.metadata, dict) else {}
            payload = metadata.get("semantics")
            if not isinstance(payload, dict):
                payload = {}
            payload = dict(payload)
            payload.setdefault("rule_id", str(metadata.get("canonical_rule_id") or row.id))
            payload.setdefault("subject", str(row.name or ""))
            payload.setdefault("statement", str(row.description or ""))
            payload.setdefault("confidence", float(row.confidence or 0.7))
            if metadata.get("verification_state"):
                payload.setdefault("verification_state", metadata["verification_state"])
            provenance = metadata.get("rule_provenance")
            if isinstance(provenance, list):
                payload["provenance"] = provenance
            try:
                rule = CanonicalRule.from_dict(payload)
            except Exception as exc:  # noqa: BLE001 — payload ajeno no rompe la query
                logger.warning(
                    "Canonical rule payload invalid",
                    rule_id=str(row.id),
                    error=str(exc)[:160],
                )
                continue
            if rule.rule_id:
                rules.append(rule)
        return rules


class InMemoryRuleLookup:
    """Lookup para tests y runtimes embebidos (sin DB)."""

    def __init__(self, rules: Iterable[CanonicalRule] = ()) -> None:
        self._rules: dict[str, CanonicalRule] = {
            str(rule.rule_id): rule for rule in rules
        }

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]:
        del organization_id
        found: list[CanonicalRule] = []
        for value in rule_ids:
            rule = self._rules.get(str(value))
            if rule is None:
                continue
            if rule.rule_id not in {item.rule_id for item in found}:
                found.append(rule)
        return found


async def load_rules_for_evidence(
    organization_id: UUID,
    items: Sequence[Any],
    *,
    lookup: RuleLookupPort | None = None,
    max_rules: int = MAX_RULES_PER_QUERY,
) -> list[CanonicalRule]:
    """Fail-soft: sin ids o sin lookup devuelve [] (camino histórico intacto)."""
    rule_ids = collect_rule_ids(items)
    if not rule_ids:
        return []
    resolved = lookup or PostgresRuleLookup()
    try:
        rules = await resolved.load_rules(organization_id, rule_ids[:max_rules])
    except Exception as exc:  # noqa: BLE001 — retrieval de reglas nunca frena el run
        logger.warning(
            "Canonical rule retrieval failed",
            organization_id=str(organization_id),
            error=str(exc)[:200],
        )
        return []
    return [rule for rule in rules if rule.rule_id][:max_rules]


def rules_metadata(rules: Sequence[CanonicalRule]) -> dict:
    return {
        "canonical_rules": [rule.to_dict() for rule in rules],
        "rule_retrieval_version": RULE_RETRIEVAL_VERSION,
    }


def attach_rules_to_items(items: Sequence[Any], rules: Sequence[CanonicalRule]) -> int:
    """Anota metadata de los items con las reglas cargadas (best-effort).

    El grounded engine puede consumir `canonical_rules=` directo; esto existe
    para caminos que solo transportan items (context compiler, auditoría).
    """
    if not rules:
        return 0
    payload = rules_metadata(rules)
    attached = 0
    for item in items or ():
        metadata = getattr(item, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        try:
            item.metadata = {**metadata, **payload}
            attached += 1
        except Exception:  # noqa: BLE001, S112 — item inmutable: no se toca
            continue
    return attached


__all__ = [
    "InMemoryRuleLookup",
    "MAX_RULES_PER_QUERY",
    "PostgresRuleLookup",
    "RULE_RETRIEVAL_VERSION",
    "RuleLookupPort",
    "attach_rules_to_items",
    "collect_rule_ids",
    "load_rules_for_evidence",
    "rules_metadata",
]
