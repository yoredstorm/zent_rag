# =============================================================================
# Data References — capa tipada sobre las referencias string del IR
# (Workflow Semantic Core, Fase 6).
#
# El runtime sigue resolviendo `{{nodes.X.output.Y}}` en ir.py
# (`resolve_stable_references`); este módulo solo describe la referencia con
# etiqueta de negocio y tipo, para el Data Catalog y la UI. Sin I/O.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NODE_REF_RE = re.compile(r"^\{\{nodes\.([A-Za-z0-9_-]+)(?:\.output)?(?:\.([A-Za-z0-9_.\[\]-]+))?\}\}$")
_TRIGGER_REF_RE = re.compile(r"^\{\{trigger\.([A-Za-z0-9_.\[\]-]+)\}\}$")
_VARIABLE_REF_RE = re.compile(r"^\{\{variables\.([A-Za-z0-9_-]+)\}\}$")

SOURCE_KINDS = ("trigger", "node", "variable")


def humanize_path(path: str) -> str:
    """`total_ventas` → `Total ventas`; `rows.0.producto` → `Rows 0 producto`."""
    text = re.sub(r"[_.\[\]-]+", " ", str(path or "")).strip()
    return text[:1].upper() + text[1:] if text else str(path)


@dataclass(frozen=True, kw_only=True)
class DataReference:
    """Referencia tipada a un dato disponible durante la ejecución."""

    source_kind: str = "node"  # trigger | node | variable
    source_id: str = ""
    path: tuple[str, ...] = ()
    value_type: str = "json"
    business_label: str = ""

    def render(self) -> str:
        if self.source_kind == "trigger":
            suffix = ".".join(self.path) if self.path else "message"
            return f"{{{{trigger.{suffix}}}}}"
        if self.source_kind == "variable":
            return f"{{{{variables.{self.source_id}}}}}"
        if self.path:
            return f"{{{{nodes.{self.source_id}.output.{'.'.join(self.path)}}}}}"
        return f"{{{{nodes.{self.source_id}.output}}}}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "path": list(self.path),
            "value_type": self.value_type,
            "business_label": self.business_label,
            "ref": self.render(),
        }


def parse_reference(ref: str) -> DataReference | None:
    """Parsea `{{nodes.X.output.Y}}`, `{{trigger.Y}}`, `{{variables.Z}}`."""
    text = str(ref or "").strip()
    match = _NODE_REF_RE.match(text)
    if match:
        raw_path = tuple(part for part in str(match.group(2) or "").split(".") if part)
        return DataReference(
            source_kind="node",
            source_id=match.group(1),
            path=raw_path,
            business_label=humanize_path(".".join(raw_path)),
        )
    match = _TRIGGER_REF_RE.match(text)
    if match:
        raw_path = tuple(part for part in str(match.group(1)).split(".") if part)
        return DataReference(
            source_kind="trigger",
            source_id="trigger",
            path=raw_path,
            business_label=humanize_path(".".join(raw_path)),
        )
    match = _VARIABLE_REF_RE.match(text)
    if match:
        return DataReference(
            source_kind="variable",
            source_id=match.group(1),
            business_label=humanize_path(match.group(1)),
        )
    return None


__all__ = [
    "DataReference",
    "SOURCE_KINDS",
    "humanize_path",
    "parse_reference",
]
