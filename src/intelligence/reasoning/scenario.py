# =============================================================================
# Scenario Parser (§14/§15/§16/§17)
# =============================================================================
# Convierte el escenario crudo del usuario en StructuredScenario.
#
# REGLA CRÍTICA (§16): si el usuario entrega registros de ancho fijo y no
# conocemos posiciones de byte ni layout, NO se infieren. Se emite
# MissingRequirement y el parser marca el ítem como no parseado.
#
# Orden de resolución de schema (§17):
#   1. Company Intelligence confirmed mappings (metadata/aliases de la entidad)
#   2. metadata de conocimiento estructurado
#   3. fuentes autoritativas
#   4. retrieval
#   5. relaciones DISCOVERED como hint (nunca como verdad)
#   6. sin resolver -> MissingRequirement
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.domain.reasoning import (
    MissingRequirement,
    RequirementKind,
    ScenarioEvent,
    StructuredScenario,
)

#: Línea con pinta de registro crudo: arranca con dígitos de secuencia, o usa
#: separadores explícitos (pipe/tab/coma). Sin separadores y sin layout
#: conocido, se trata como ancho fijo y NO se parsea a ciegas.
_RAW_LINE_RE = re.compile(
    r"^\s*(?:\d{3,}|[\w./-]{1,12}\s{2,}\S)",
)
_PIPE_RE = re.compile(r"[|;,\t]")
_SEQUENCE_RE = re.compile(r"(?:seq(?:uence)?|secuencia)\D{0,6}(\d{1,12})", re.I)
_RECORD_TYPE_RE = re.compile(r"\brecord\s*([A-Za-z])\b|\bregistro\s*([A-Za-z])\b", re.I)
_ACTION_RE = re.compile(
    r"\b(open|update|close|renumber|renumbering|create|delete|replace|"
    r"abre|cierra|actualiza|renumera|reemplaza)\b",
    re.I,
)
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4})"
)
_EFFECTIVE_RE = re.compile(
    r"(?:effective|vigente|vigen(?:cia)?\s+desde|desde)\D{0,10}(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4})",
    re.I,
)
_DISCONTINUE_RE = re.compile(
    r"(?:discontinue|hasta|vigente\s+hasta|hasta\s+el)\D{0,10}(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4})",
    re.I,
)
#: Campos técnicos citados por el usuario (columna, byte range, posición).
_FIELD_REF_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]{2,})\.([A-Z][A-Z0-9_]{2,})\b|\b[A-Z][A-Z0-9_]{3,}\b"
)
_BYTE_RANGE_RE = re.compile(r"\b(?:byte|pos(?:ition)?|col(?:umn)?)\s*[:=]?\s*\d{1,4}", re.I)


def parse_date(value: str | None) -> datetime | None:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass(frozen=True, kw_only=True)
class ResolvedSchema:
    """Schema disponible para parsear. `origin` explica de dónde salió."""

    ref: str
    record_types: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    sequence_positions: dict = field(default_factory=dict)
    origin: str = ""
    authoritative: bool = False
    confirmed: bool = False
    detail: dict = field(default_factory=dict)

    def knows_layout(self) -> bool:
        return bool(self.fields or self.sequence_positions)


class ScenarioSchemaResolver:
    """Resuelve schemas en el orden de §17. Nunca inventa posiciones."""

    def __init__(self, *, catalog: list[ResolvedSchema] | None = None) -> None:
        self._catalog = list(catalog or [])

    def register(self, schema: ResolvedSchema) -> None:
        self._catalog.append(schema)

    def resolve(self, text: str, *, company_context: dict | None = None) -> list[ResolvedSchema]:
        """Devuelve los schemas relevantes para el texto, por prioridad."""
        found: list[ResolvedSchema] = []
        for schema in self._catalog:
            token = schema.ref.lower()
            if token and token in (text or "").lower():
                found.append(schema)
        if company_context:
            found.extend(self._from_company_context(company_context))
        return found

    @staticmethod
    def _from_company_context(company_context: dict) -> list[ResolvedSchema]:
        """Mappings confirmados del Company Graph son la primera fuente (§17.1)."""
        resolved: list[ResolvedSchema] = []
        for bucket in ("systems", "concepts", "rules"):
            for item in company_context.get(bucket) or ():
                if not isinstance(item, dict):
                    continue
                identifiers = item.get("technical_identifiers") or ()
                if not identifiers:
                    continue
                resolved.append(
                    ResolvedSchema(
                        ref=str(item.get("name") or ""),
                        fields=tuple(str(entry) for entry in identifiers),
                        origin="company_graph",
                        confirmed=str(item.get("status") or "").lower()
                        in ("confirmed", "auto_confirmed"),
                        detail={"authority_level": item.get("authority_level")},
                    )
                )
        return resolved


class ScenarioParser:
    """Parsea el escenario crudo. Determinista; no inventa nada."""

    def __init__(
        self,
        *,
        resolver: ScenarioSchemaResolver | None = None,
        max_events: int = 200,
    ) -> None:
        self._resolver = resolver or ScenarioSchemaResolver()
        self._max_events = max_events

    def register_schema(self, schema: ResolvedSchema) -> None:
        """Registra un schema resuelto (grafo, metadata o evidencia)."""
        self._resolver.register(schema)

    def parse(
        self,
        raw: str,
        *,
        company_context: dict | None = None,
        evidence_texts: tuple[str, ...] = (),
    ) -> StructuredScenario:
        text = raw or ""
        schemas = self._resolver.resolve(text, company_context=company_context)
        known_layout = any(schema.knows_layout() for schema in schemas)
        missing: list[MissingRequirement] = []

        lines = [line for line in text.splitlines() if line.strip()]
        events: list[ScenarioEvent] = []
        unparsed: list[str] = []
        unknown_fields: list[str] = []

        # Registros crudos sin layout conocido: no se inventan posiciones.
        if self._looks_like_fixed_width(lines) and not known_layout:
            missing.append(
                MissingRequirement(
                    kind=RequirementKind.RECORD_LAYOUT_REQUIRED,
                    detail=(
                        "Los registros parecen de ancho fijo y no hay layout "
                        "conocido (posiciones de byte) para parsearlos"
                    ),
                    subject="scenario",
                )
            )
            if _BYTE_RANGE_RE.search(text) is None:
                missing.append(
                    MissingRequirement(
                        kind=RequirementKind.SEQUENCE_FIELD_POSITION_REQUIRED,
                        detail="Falta la posición del campo de secuencia",
                        subject="sequence",
                    )
                )
            return StructuredScenario(
                items=tuple(lines),
                events=(),
                unparsed_items=tuple(lines[: self._max_events]),
                missing_requirements=tuple(missing),
                parse_confidence=0.0,
                source_refs=tuple(evidence_texts[:5]),
            )

        for index, line in enumerate(lines[: self._max_events]):
            event = self._parse_line(index, line, schemas)
            if event is None:
                # Línea que no es evento (prosa del usuario): no es fallo.
                continue
            events.append(event)
            unknown_fields.extend(
                field_name
                for field_name in event.parse_issues
                if field_name not in unknown_fields
            )

        if events:
            declared = self._declared_fields(text)
            if declared:
                known = {field for schema in schemas for field in schema.fields}
                unresolved = tuple(
                    field for field in declared if field not in known
                )
                if unresolved:
                    missing.append(
                        MissingRequirement(
                            kind=RequirementKind.SCHEMA_REQUIRED,
                            detail=(
                                "Hay campos citados sin definición conocida: "
                                + ", ".join(unresolved[:6])
                            ),
                            subject="fields",
                        )
                    )

        confidence = 0.0
        if events:
            confidence = round(
                sum(event.confidence for event in events) / len(events), 4
            )
        return StructuredScenario(
            items=tuple(lines),
            events=tuple(events),
            entities=tuple(self._entities(events)),
            unparsed_items=tuple(unparsed),
            schema_refs=tuple(schema.ref for schema in schemas),
            unknown_fields=tuple(unknown_fields),
            missing_requirements=tuple(missing),
            parse_confidence=confidence,
            source_refs=tuple(evidence_texts[:5]),
        )

    # ------------------------------------------------------------------
    def _parse_line(
        self, index: int, line: str, schemas: list[ResolvedSchema]
    ) -> ScenarioEvent | None:
        stripped = line.strip()
        if not stripped:
            return None
        seq_match = _SEQUENCE_RE.search(stripped)
        record_match = _RECORD_TYPE_RE.search(stripped)
        action_match = _ACTION_RE.search(stripped)
        explicit_values = _parse_value_list(stripped)
        # Un valor suelto de una columna de secuencia también cuenta como evento.
        if (
            seq_match is None
            and record_match is None
            and action_match is None
            and not explicit_values
        ):
            return None

        sequence = seq_match.group(1) if seq_match else ""
        if not sequence and explicit_values:
            sequence = explicit_values[0]
        record_type = ""
        if record_match:
            record_type = (record_match.group(1) or record_match.group(2) or "").upper()
        effective_match = _EFFECTIVE_RE.search(stripped)
        discontinue_match = _DISCONTINUE_RE.search(stripped)
        timestamp = parse_date(
            (effective_match.group(1) if effective_match else None)
            or (discontinue_match.group(1) if discontinue_match else None)
            or (_DATE_RE.search(stripped).group(1) if _DATE_RE.search(stripped) else None)
        )
        issues: list[str] = []
        if not sequence:
            issues.append("sequence_missing")
        if not record_type:
            issues.append("record_type_missing")
        confidence = 0.9 if (sequence and record_type) else 0.6 if sequence else 0.4
        return ScenarioEvent(
            index=index,
            raw_ref=f"line:{index + 1}",
            record_type=record_type,
            action=(action_match.group(1).lower() if action_match else ""),
            sequence=sequence,
            timestamp=timestamp,
            effective_date=parse_date(
                effective_match.group(1) if effective_match else None
            ),
            discontinue_date=parse_date(
                discontinue_match.group(1) if discontinue_match else None
            ),
            entity_identifiers=tuple(
                value
                for value in explicit_values[1:3]
                if value and not value.isdigit()
            ),
            parsed_fields=(
                {"values": list(explicit_values)} if explicit_values else {}
            ),
            schema_ref=schemas[0].ref if schemas else "",
            confidence=confidence,
            parse_issues=tuple(issues),
        )

    @staticmethod
    def _declared_fields(text: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(match.group(0) for match in _FIELD_REF_RE.finditer(text)))

    @staticmethod
    def _entities(events: list[ScenarioEvent]) -> list[str]:
        found: list[str] = []
        for event in events:
            for identifier in event.entity_identifiers:
                if identifier not in found:
                    found.append(identifier)
        return found

    @staticmethod
    def _looks_like_fixed_width(lines: list[str]) -> bool:
        """Varias líneas con dígitos alineados y sin separadores: ancho fijo."""
        candidates = [
            line
            for line in lines
            if _RAW_LINE_RE.match(line) and not _PIPE_RE.search(line)
        ]
        if len(candidates) < 3:
            return False
        positional = sum(1 for line in candidates if _looks_positional(line))
        return positional >= 3


def _looks_positional(line: str) -> bool:
    """Dígitos repetidos en posiciones parecidas: pinta de ancho fijo."""
    digits = [index for index, char in enumerate(line) if char.isdigit()]
    if len(digits) < 4:
        return False
    return digits[0] in (0, 1, 2, 3)


def _parse_value_list(line: str) -> list[str]:
    """Valores separados por comas o pipes dentro de una línea de escenario."""
    if not _PIPE_RE.search(line):
        return []
    parts = [part.strip() for part in _PIPE_RE.split(line) if part.strip()]
    return [part for part in parts if len(part) <= 40][:8]


def schema_from_facts(rules: list[Any]) -> list[ResolvedSchema]:
    """Construye schemas desde hechos ya resueltos (evidencia o grafo)."""
    resolved: list[ResolvedSchema] = []
    for fact in rules:
        statement = str(getattr(fact, "statement", "") or "")
        fields = tuple(
            dict.fromkeys(match.group(0) for match in _FIELD_REF_RE.finditer(statement))
        )
        if not fields:
            continue
        resolved.append(
            ResolvedSchema(
                ref=statement[:80],
                fields=fields,
                origin=str(getattr(fact, "origin", "") or "evidence"),
                confirmed=str(getattr(fact, "status", "")).endswith("CONFIRMED"),
            )
        )
    return resolved


__all__ = [
    "ResolvedSchema",
    "ScenarioParser",
    "ScenarioSchemaResolver",
    "parse_date",
    "schema_from_facts",
]
