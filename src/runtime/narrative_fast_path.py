# =============================================================================
# Narrative Fast Path — explicación documental en una generación.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.domain.reasoning import QueryMode
from src.intelligence.reasoning.classifier import deterministic_shape
from src.runtime.deterministic_authority import requires_deterministic_decision

NARRATIVE_FAST_PATH = "NARRATIVE_FAST_PATH"
ROUTE_DETERMINISTIC = "DETERMINISTIC_FAST_PATH"
ROUTE_SCENARIO = "SCENARIO_ANALYSIS"
ROUTE_AGENT = "AGENT"

VERIFIED_GROUNDED = "VERIFIED_GROUNDED"
PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
UNSUPPORTED = "UNSUPPORTED"
TRUNCATED = "TRUNCATED"
CITATION_ERROR = "CITATION_ERROR"
PARTIALLY_COMPLETE_BUT_GROUNDED = "PARTIALLY_COMPLETE_BUT_GROUNDED"

_FOOTER_RE = re.compile(
    r"(?im)^(?:page\s+\d+|p[aá]gina\s+\d+|confidential|all rights reserved|©.*)$"
)
_META_RE = re.compile(
    r"(?im)^(?:parser_engine|parser_version|bbox|chunk_id|evidence_id)\s*[:=].*$"
)
# Cortesía al arranque («buenas, ¿qué significa X?»): el mensaje completo no es
# la consulta. El modelo reformula la pregunta material antes de buscar.
_CONVERSATIONAL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"hola|buenas(?:\s+(?:tardes|noches|d[ií]as))?|buenos\s+d[ií]as|"
    r"hey|hi|hello|saludos|qu[eé]\s+tal|gracias"
    r")\b",
    re.IGNORECASE,
)

_SOURCE_IDENTITY_KEYS = (
    "organization_id",
    "workspace_id",
    "source_id",
    "document_id",
    "external_id",
    "title",
    "filename",
    "original_filename",
    "page_start",
    "page_end",
    "section_path",
    "parser_engine",
    "parser_version",
    "representation_kind",
    "canonical_evidence_id",
)


@dataclass(frozen=True)
class NarrativeRoute:
    route: str
    eligible: bool
    query_mode: str
    shape: str
    blueprint: str
    reason: str
    jev: str = "skip"
    llm_calls: int = 1

    def to_public_dict(self) -> dict:
        return {
            "route": self.route,
            "mode": self.route,
            "eligible": self.eligible,
            "query_mode": self.query_mode,
            "reasoning_shape": self.shape,
            "blueprint": self.blueprint,
            "reason": self.reason,
            "jev": self.jev,
            "llm_calls": self.llm_calls if self.eligible else 0,
        }


def narrative_route(question: str) -> NarrativeRoute:
    """Código decide la ruta. Fechas en el tópico no activan JEV ni escenario."""
    classification = deterministic_shape(question)
    mode = classification.query_mode
    mode_value = mode.value if mode else ""
    shape = classification.shape.value
    if (
        mode is QueryMode.INFORMATIONAL
        and not classification.scenario_payload
        and not classification.is_complex
    ):
        if _CONVERSATIONAL_PREFIX_RE.search(question or ""):
            # La cortesía no es la consulta: sin ruta narrativa, el agente
            # decide la query material (la intención material manda).
            return NarrativeRoute(
                route=ROUTE_AGENT,
                eligible=False,
                query_mode="INFORMATIONAL",
                shape=shape,
                blueprint="conversational_knowledge",
                reason="conversational_prefix",
                jev="skip",
                llm_calls=0,
            )
        blueprint = (
            "definition_explanation"
            if re.search(r"\bqu[eé]\s+(?:es|significa)\b", question or "", re.I)
            else "technical_explanation"
        )
        return NarrativeRoute(
            route=NARRATIVE_FAST_PATH,
            eligible=True,
            query_mode="INFORMATIONAL",
            shape=shape,
            blueprint=blueprint,
            reason=classification.routing_reason,
            jev="skip",
            llm_calls=1,
        )
    why_case = bool(re.search(r"\bpor\s+qu[eé]\b|\bwhy\s+did\b", question or "", re.I))
    has_mask = bool(re.search(r"[&%#*]{2,}", question or ""))
    has_verdict = bool(re.search(r"\bcumpl\w*", question or "", re.I))
    if why_case and not has_mask and not has_verdict:
        return NarrativeRoute(
            route=ROUTE_SCENARIO,
            eligible=False,
            query_mode=mode_value or "SCENARIO",
            shape=shape,
            blueprint="scenario_analysis",
            reason="why_instance",
            jev="if_material",
            llm_calls=0,
        )
    executable = requires_deterministic_decision(question) or mode is QueryMode.EXECUTABLE
    if executable:
        return NarrativeRoute(
            route=ROUTE_DETERMINISTIC,
            eligible=False,
            query_mode=mode_value or "EXECUTABLE",
            shape=shape,
            blueprint="",
            reason="executable_decision",
            jev="skip",
            llm_calls=0,
        )
    if mode is QueryMode.SCENARIO or (
        classification.is_complex and mode is not QueryMode.INFORMATIONAL
    ):
        return NarrativeRoute(
            route=ROUTE_SCENARIO,
            eligible=False,
            query_mode=mode_value or "SCENARIO",
            shape=shape,
            blueprint="scenario_analysis",
            reason=classification.routing_reason or "scenario_or_complex",
            jev="if_material",
            llm_calls=0,
        )
    return NarrativeRoute(
        route=ROUTE_AGENT,
        eligible=False,
        query_mode=mode_value,
        shape=shape,
        blueprint="",
        reason=classification.routing_reason or "not_informational",
    )


def jev_needed(
    *,
    sufficiency_ambiguous: bool = False,
    conflicts: int = 0,
    blueprint_ambiguous: bool = False,
    authority_uncertain: bool = False,
    query_ambiguous: bool = False,
) -> bool:
    """JEV solo si cambia la respuesta. Mencionar fechas no basta."""
    return bool(
        sufficiency_ambiguous
        or conflicts > 0
        or blueprint_ambiguous
        or authority_uncertain
        or query_ambiguous
    )


def compress_narrative_context(blocks: list[str], *, max_chars: int) -> str:
    """Contexto de secciones. Sin pies de página, metadata de parser ni headers repetidos."""
    seen_headers: set[str] = set()
    kept: list[str] = []
    used = 0
    for block in blocks:
        lines: list[str] = []
        for line in str(block or "").splitlines():
            stripped = line.strip()
            if not stripped or _FOOTER_RE.match(stripped) or _META_RE.match(stripped):
                continue
            if stripped.startswith("#"):
                key = stripped.lower()
                if key in seen_headers:
                    continue
                seen_headers.add(key)
            lines.append(stripped)
        piece = "\n".join(lines).strip()
        if not piece:
            continue
        if used + len(piece) > max_chars and kept:
            break
        kept.append(piece[: max(0, max_chars - used)])
        used += len(kept[-1])
    return "\n\n".join(kept)


def prompt_char_budget(question: str, *, evidence_items: int, detail: str = "") -> int:
    text = f"{question or ''} {detail or ''}".lower()
    if any(token in text for token in ("en profundidad", "tutorial", "desde cero", "deep")):
        return 16_000
    if evidence_items <= 2 or "en una línea" in text or "breve" in text:
        return 5_000
    return 8_000


def output_token_budget(blueprint: str, *, detail: str = "") -> int:
    kind = f"{blueprint or ''} {detail or ''}".lower()
    if "direct" in kind or "fact" in kind:
        return 280
    if "tutorial" in kind or "deep" in kind or "en profundidad" in kind:
        return 1600
    return 800


def completeness_for_finish(finish_reason: str, verification: str) -> tuple[str, str]:
    """Grounding y completeness no se mezclan. Truncado con soporte sigue grounded."""
    truncated = str(finish_reason or "").lower() in {"length", "max_tokens"}
    grounded = verification in {VERIFIED_GROUNDED, "COMPLETE"}
    if truncated and grounded:
        return TRUNCATED, PARTIALLY_COMPLETE_BUT_GROUNDED
    if truncated:
        return TRUNCATED, TRUNCATED
    if grounded:
        return "COMPLETE", VERIFIED_GROUNDED
    return "COMPLETE", verification or PARTIALLY_GROUNDED


def source_identity(metadata: dict | None) -> dict:
    meta = metadata if isinstance(metadata, dict) else {}
    found = {
        key: meta[key]
        for key in _SOURCE_IDENTITY_KEYS
        if meta.get(key) not in (None, "", [], {})
    }
    found["identity_status"] = (
        "OK" if found.get("document_id") or found.get("source_id") else "WEAK"
    )
    return found


def personality_instruction(tone: str = "", instructions: str = "") -> str:
    parts = [
        "Aplica el tono del agente. No cambies hechos, evidencia ni citas."
    ]
    if tone:
        parts.append(f"Tono: {tone}.")
    if instructions:
        parts.append(instructions.strip()[:400])
    return " ".join(parts)
