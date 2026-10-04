# =============================================================================
# ContextCompiler — contexto estructurado, no chunks concatenados (§43-44)
# =============================================================================
# Pipeline: PLAN -> SEED -> INSPECT -> REQUIREMENTS -> EXPAND -> COVERAGE ->
#           GAIN -> COMPILE -> REASON.
#
# El compilador produce secciones reales:
#   QUESTION, USER INPUTS, DEFINITIONS, RULES, CONDITIONS, EXCEPTIONS,
#   RELATED EVIDENCE, CONFLICTS, UNRESOLVED REQUIREMENTS, CITATION MAP.
#
# Clasifica por el payload del Fabric (rule_ids/definition_ids/...) y NUNCA
# descarta evidencia en silencio: lo omitido se cuenta y se declara.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

CONTEXT_COMPILER_VERSION = "context-compiler-1"

#: Secciones en orden de render.
SECTION_ORDER: tuple[str, ...] = (
    "definitions",
    "rules",
    "conditions",
    "exceptions",
    "related_evidence",
    "conflicts",
)

#: Prioridad de recorte (menor = se conserva más tiempo). Excepciones y reglas
#: jamás se pierden antes que la evidencia genérica.
_TRIM_PRIORITY: dict[str, int] = {
    "rules": 0,
    "exceptions": 1,
    "definitions": 2,
    "conditions": 3,
    "conflicts": 4,
    "related_evidence": 5,
}

_TYPE_FIELDS: tuple[tuple[str, str], ...] = (
    ("rules", "rule_ids"),
    ("definitions", "definition_ids"),
    ("exceptions", "exception_ids"),
    ("conditions", "condition_ids"),
)


@dataclass(frozen=True, kw_only=True)
class CompiledContext:
    question: str = ""
    user_inputs: tuple[str, ...] = ()
    definitions: tuple[dict, ...] = ()
    rules: tuple[dict, ...] = ()
    conditions: tuple[dict, ...] = ()
    exceptions: tuple[dict, ...] = ()
    related_evidence: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    unresolved_requirements: tuple[str, ...] = ()
    citation_map: tuple[dict, ...] = ()
    omitted: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    version: str = CONTEXT_COMPILER_VERSION

    @property
    def fingerprint(self) -> str:
        import json

        material = {
            "version": self.version,
            "question": self.question,
            "citations": [item.get("key") for item in self.citation_map],
            "definitions": len(self.definitions),
            "rules": len(self.rules),
            "conditions": len(self.conditions),
            "exceptions": len(self.exceptions),
            "related_evidence": len(self.related_evidence),
            "conflicts": len(self.conflicts),
            "unresolved": list(self.unresolved_requirements),
        }
        raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    @property
    def total_items(self) -> int:
        return sum(
            len(section)
            for section in (
                self.definitions,
                self.rules,
                self.conditions,
                self.exceptions,
                self.related_evidence,
                self.conflicts,
            )
        )

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "question": self.question[:300],
            "user_inputs": list(self.user_inputs[:8]),
            "definitions": [dict(item) for item in self.definitions],
            "rules": [dict(item) for item in self.rules],
            "conditions": [dict(item) for item in self.conditions],
            "exceptions": [dict(item) for item in self.exceptions],
            "related_evidence": [dict(item) for item in self.related_evidence],
            "conflicts": [dict(item) for item in self.conflicts],
            "unresolved_requirements": list(self.unresolved_requirements[:12]),
            "citation_map": [dict(item) for item in self.citation_map],
            "omitted": dict(self.omitted),
            "stats": dict(self.stats),
        }


def _chunk_key(chunk) -> str:
    metadata = getattr(chunk, "metadata", None) or {}
    value = str(metadata.get("chunk_id") or metadata.get("unit_id") or "")
    if value:
        return value
    return str(getattr(chunk, "document_id", ""))[:36]


def _excerpt(chunk, limit: int = 240) -> str:
    text = " ".join((getattr(chunk, "content", "") or "").split())
    return text[:limit]


def compile_context(
    *,
    question: str,
    chunks: list | tuple = (),
    requirements: object | None = None,
    requirement_graph: object | None = None,
    evidence_state: object | None = None,
    user_inputs: list | tuple = (),
    max_items_per_section: int = 12,
    max_tokens: int = 0,
) -> CompiledContext:
    """Compila el contexto estructurado desde chunks + requirements."""
    citations: list[dict] = []
    citation_index: dict[str, int] = {}
    sections: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}
    unresolved: list[str] = []

    def cite(chunk) -> int:
        key = _chunk_key(chunk)
        if key not in citation_index:
            metadata = getattr(chunk, "metadata", None) or {}
            citation_index[key] = len(citations) + 1
            citations.append(
                {
                    "key": key,
                    "document_id": str(getattr(chunk, "document_id", "")),
                    "label": str(metadata.get("title") or metadata.get("filename") or "")[:160],
                    "page": metadata.get("page_start"),
                    "section_path": list(metadata.get("section_path") or ())[:6],
                    "excerpt": _excerpt(chunk, 160),
                }
            )
        return citation_index[key]

    for chunk in chunks or ():
        metadata = getattr(chunk, "metadata", None) or {}
        citation = cite(chunk)
        item_base = {
            "citation": citation,
            "key": _chunk_key(chunk),
            "label": str(metadata.get("fabric_labels") or ())[:200]
            if isinstance(metadata.get("fabric_labels"), str)
            else ", ".join(
                str(value) for value in (metadata.get("fabric_labels") or ())[:4]
            ),
            "excerpt": _excerpt(chunk),
        }
        placed = False
        for section_name, field_name in _TYPE_FIELDS:
            values = metadata.get(field_name) or ()
            if isinstance(values, str):
                values = [values]
            values = [str(value) for value in values if value]
            if not values:
                continue
            if len(sections[section_name]) >= max_items_per_section:
                continue
            sections[section_name].append(
                {**item_base, "node_ids": values[:6]}
            )
            placed = True
            break
        neighborhood = metadata.get("semantic_neighborhood") or ()
        for entry in neighborhood:
            if not isinstance(entry, dict):
                continue
            relation = str(entry.get("relation") or "")
            if relation in ("CONTRADICTS", "SUPERSEDES") and len(
                sections["conflicts"]
            ) < max_items_per_section:
                sections["conflicts"].append(
                    {
                        **item_base,
                        "relation": relation,
                        "object_label": str(entry.get("label") or "")[:160],
                        "object_id": str(entry.get("node_id") or ""),
                    }
                )
                placed = True
        if not placed and len(sections["related_evidence"]) < max_items_per_section:
            sections["related_evidence"].append(item_base)

    # UNRESOLVED REQUIREMENTS: autoridad canónica si existe; si no, el grafo.
    if evidence_state is not None and hasattr(
        evidence_state, "missing_documentable_evidence"
    ):
        try:
            unresolved.extend(
                str(value)
                for value in evidence_state.missing_documentable_evidence()
                if str(value or "").strip()
            )
        except Exception:  # noqa: BLE001
            pass
    elif requirement_graph is not None:
        unresolved.extend(
            str(value) for value in getattr(requirement_graph, "missing", ()) or ()
        )
    elif requirements is not None and hasattr(requirements, "pending"):
        unresolved.extend(str(value) for value in requirements.pending)

    omitted = {name: 0 for name in SECTION_ORDER}
    if max_tokens and max_tokens > 0:
        sections, omitted = _trim_to_budget(sections, max_tokens)

    return CompiledContext(
        question=str(question or "")[:400],
        user_inputs=tuple(
            dict.fromkeys(str(value) for value in user_inputs if str(value or "").strip())
        )[:8],
        definitions=tuple(sections["definitions"]),
        rules=tuple(sections["rules"]),
        conditions=tuple(sections["conditions"]),
        exceptions=tuple(sections["exceptions"]),
        related_evidence=tuple(sections["related_evidence"]),
        conflicts=tuple(sections["conflicts"]),
        unresolved_requirements=tuple(dict.fromkeys(unresolved))[:24],
        citation_map=tuple(citations),
        omitted=omitted,
        stats={
            "chunks": len(list(chunks or ())),
            "citations": len(citations),
            "items": sum(len(value) for value in sections.values()),
            "trimmed": sum(omitted.values()),
        },
    )


def _trim_to_budget(
    sections: dict[str, list[dict]], max_tokens: int
) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Recorta por prioridad: la evidencia genérica cae antes que reglas y
    excepciones. Lo omitido se cuenta, nunca se oculta."""
    chars_per_token = 4
    budget_chars = max(0, int(max_tokens) * chars_per_token)
    used = 0
    omitted = {name: 0 for name in SECTION_ORDER}
    trimmed: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}
    # Orden de recorte por PRIORIDAD: reglas y excepciones se conservan antes
    # que la evidencia genérica.
    for name in sorted(
        SECTION_ORDER, key=lambda value: (_TRIM_PRIORITY.get(value, 9), value)
    ):
        for item in sections.get(name, []):
            size = len(str(item.get("excerpt") or "")) + 80
            if used + size > budget_chars:
                omitted[name] += 1
                continue
            used += size
            trimmed[name].append(item)
    return trimmed, omitted


def render_compiled_context_block(compiled: CompiledContext | dict | None) -> str:
    """Bloque de texto estructurado para el prompt (si el llamador lo usa)."""
    if compiled is None:
        return ""
    data = (
        compiled.to_public_dict()
        if isinstance(compiled, CompiledContext)
        else dict(compiled)
    )
    lines: list[str] = ["[CONTEXTO COMPILADO]"]
    if data.get("question"):
        lines.append(f"Pregunta: {data['question']}")
    if data.get("user_inputs"):
        lines.append("Datos del usuario: " + ", ".join(data["user_inputs"]))
    for key, title in (
        ("definitions", "Definiciones"),
        ("rules", "Reglas"),
        ("conditions", "Condiciones"),
        ("exceptions", "Excepciones"),
        ("related_evidence", "Evidencia relacionada"),
        ("conflicts", "Conflictos"),
    ):
        items = data.get(key) or ()
        if not items:
            continue
        lines.append(f"{title}:")
        for item in items:
            label = item.get("label") or item.get("key")
            lines.append(f"  [{item.get('citation')}] {label}: {item.get('excerpt')}")
    if data.get("unresolved_requirements"):
        lines.append(
            "Requisitos sin resolver: " + "; ".join(data["unresolved_requirements"])
        )
    if data.get("omitted") and any(data["omitted"].values()):
        lines.append(f"Omitido por presupuesto: {data['omitted']}")
    return "\n".join(lines)


__all__ = [
    "CONTEXT_COMPILER_VERSION",
    "SECTION_ORDER",
    "CompiledContext",
    "compile_context",
    "render_compiled_context_block",
]
