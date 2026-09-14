# =============================================================================
# Node Contributions — escrituras inmutables de un nodo al WorkflowContext
# (Workflow Semantic Core, Fase 1).
#
# El nodo propone; el runtime valida y aplica (ContextMerger). Facilita audit,
# replay, debug, seguridad y testing (brief §3). Sin I/O.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from src.platform.workflows.context import (
    CONTEXT_SCHEMA_VERSION,
    WRITABLE_SECTIONS,
    WorkflowContext,
    normalize_section,
)
from src.platform.workflows.values import Provenance, WorkflowValue

# Topes defensivos para evitar contextos sin límite (brief §13/§12).
MAX_VALUES_PER_SECTION = 200
MAX_WRITE_CHARS = 50_000

_APPEND_SECTIONS = frozenset(
    {"evidence_refs", "claim_refs", "entity_refs", "findings", "decisions", "artifacts"}
)
_SLOT_SECTIONS = frozenset({"data", "knowledge"})
_ID_KEYS: dict[str, str] = {
    "evidence_refs": "evidence_id",
    "claim_refs": "claim_id",
    "entity_refs": "entity_id",
}


@dataclass(frozen=True, kw_only=True)
class ContextWrite:
    """Una escritura propuesta por un nodo.

    `value` acepta un `WorkflowValue` ya envuelto o un valor crudo (se envuelve
    en el merge con `value_type`/`label`/`provenance` declarados aquí).
    """

    section: str
    value: Any = None
    key: str | None = None
    value_type: str | None = None
    label: str | None = None
    unit: str | None = None
    provenance: Provenance | None = None
    redacted: bool = False


@dataclass(frozen=True, kw_only=True)
class NodeContribution:
    """Conjunto inmutable de escrituras que un nodo aporta al contexto."""

    writes: tuple[ContextWrite, ...] = ()
    schema_version: int = CONTEXT_SCHEMA_VERSION


@dataclass
class MergeReport:
    """Resultado auditable del merge: aplicadas y rechazadas."""

    node_id: str = ""
    node_type: str = ""
    applied: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "applied": list(self.applied),
            "rejected": list(self.rejected),
        }


class ContextMerger:
    """Aplica contribuciones validadas sobre un `WorkflowContext`.

    Políticas:
    - append + dedupe por id: evidence/claim/entity refs, findings, decisions,
      artifacts.
    - slot last-write: data, knowledge (clave = `write.key` o node_id).
    - merge por clave: variables.
    - nunca escribibles: identity, trigger, execution, security.
    """

    def __init__(
        self,
        *,
        max_values_per_section: int = MAX_VALUES_PER_SECTION,
        max_write_chars: int = MAX_WRITE_CHARS,
    ) -> None:
        self._max_values = max(int(max_values_per_section), 1)
        self._max_write_chars = max(int(max_write_chars), 1)

    def apply(
        self,
        context: WorkflowContext,
        *,
        node_id: str,
        node_type: str,
        contribution: NodeContribution | None,
        allowed_sections: tuple[str, ...] | list[str] | None = None,
    ) -> MergeReport:
        report = MergeReport(node_id=node_id, node_type=node_type)
        if contribution is None:
            return report
        allowed: frozenset[str] | None = None
        if allowed_sections is not None:
            allowed = frozenset(
                key for key in (normalize_section(section) for section in allowed_sections) if key
            )
        for index, write in enumerate(contribution.writes):
            section = normalize_section(write.section)
            if section is None or section not in WRITABLE_SECTIONS:
                report.rejected.append(
                    {"index": index, "section": write.section, "reason": "section_not_writable"}
                )
                continue
            if allowed is not None and section not in allowed:
                report.rejected.append(
                    {"index": index, "section": section, "reason": "section_not_declared"}
                )
                continue
            value = self._wrap(write, node_id=node_id, node_type=node_type)
            if len(json.dumps(value.to_dict(), ensure_ascii=False, default=str)) > self._max_write_chars:
                report.rejected.append(
                    {"index": index, "section": section, "reason": "value_too_large"}
                )
                continue
            error, detail = self._merge(context, section=section, key=write.key, value=value)
            if error is not None:
                report.rejected.append({"index": index, "section": section, "reason": error})
                continue
            applied: dict[str, Any] = {
                "index": index,
                "section": section,
                "key": write.key,
                "value_type": value.value_type,
                "label": value.label,
            }
            applied.update(detail)
            report.applied.append(applied)
        return report

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _wrap(self, write: ContextWrite, *, node_id: str, node_type: str) -> WorkflowValue:
        if isinstance(write.value, WorkflowValue):
            value = write.value
        else:
            value = WorkflowValue.from_raw(
                write.value,
                value_type=write.value_type,
                label=write.label,
                unit=write.unit,
                redacted=write.redacted,
            )
        if value.provenance is None:
            value = replace(
                value,
                provenance=Provenance(
                    origin_kind="node",
                    node_id=node_id,
                    node_type=node_type,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        return value

    def _merge(
        self,
        context: WorkflowContext,
        *,
        section: str,
        key: str | None,
        value: WorkflowValue,
    ) -> tuple[str | None, dict[str, Any]]:
        entry = value.to_dict()
        if section in _APPEND_SECTIONS:
            target = getattr(context, section)
            dedupe_key = self._entry_key(section, entry)
            for existing in target:
                if self._entry_key(section, existing) == dedupe_key:
                    return None, {"deduplicated": True}
            if len(target) >= self._max_values:
                return "section_full", {}
            target.append(entry)
            return None, {}
        if section in _SLOT_SECTIONS:
            target = getattr(context, section)
            slot = str(key or value.label or "value")
            if slot not in target and len(target) >= self._max_values:
                return "section_full", {}
            target[slot] = entry
            return None, {"key": slot}
        if section == "variables":
            if not key:
                return "missing_key", {}
            if key not in context.variables and len(context.variables) >= self._max_values:
                return "section_full", {}
            context.variables[str(key)] = value.json_value()
            return None, {}
        return "section_not_writable", {}

    def _entry_key(self, section: str, entry: dict[str, Any]) -> str:
        raw = entry.get("value")
        raw = raw if isinstance(raw, dict) else {}
        id_key = _ID_KEYS.get(section)
        if id_key and raw.get(id_key):
            return f"{id_key}:{raw[id_key]}"
        if raw.get("id"):
            return f"id:{raw['id']}"
        if raw.get("text"):
            digest_source = str(raw["text"])[:200]
        else:
            digest_source = json.dumps(entry.get("value"), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "ContextMerger",
    "ContextWrite",
    "MAX_VALUES_PER_SECTION",
    "MAX_WRITE_CHARS",
    "MergeReport",
    "NodeContribution",
]
