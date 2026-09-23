# =============================================================================
# AI configurator — propósito y perfil de respuesta (§30-§33).
# =============================================================================
# El generador propone CÓMO debe trabajar/comunicar un agente. Nunca agrega
# hechos, reglas de dominio ni capacidades que el agente no tenga configuradas.
#
# Reglas duras:
#   - sólo conoce: nombre, descripción, propósito actual, fuentes, herramientas,
#     dominio del tenant y perfil actual;
#   - la salida se valida: si menciona capacidades no configuradas, se rechaza
#     la parte problemática (no se guarda);
#   - es un borrador: el usuario lo revisa y guarda (§34 preview).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.core.domain.response import ResponseProfile
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.response.profile import (
    PRESET_LABELS,
    RESPONSE_PROFILE_PRESETS,
    profile_from_config,
)

logger = get_logger(__name__)

#: Capacidades y su vocabulario: si el agente no la tiene, no puede nombrarla.
_CAPABILITY_TERMS: dict[str, tuple[str, ...]] = {
    "sql": ("sql", "base de datos", "database", "consulta estructurada", "tabla de datos"),
    "api": ("api", "endpoint", "http", "llamada externa"),
    "email": ("email", "correo", "enviar mail"),
    "workflow": ("workflow", "flujo de trabajo automatizado"),
    "graph": ("grafo", "graph", "relaciones entre entidades"),
}
_TOOL_CAPABILITIES: dict[str, str] = {
    "query_database": "sql",
    "query_tabular_data": "sql",
    "call_api": "api",
    "send_email": "email",
}

PURPOSE_MAX_CHARS = 600
INSTRUCTIONS_MAX_CHARS = 800


@dataclass(frozen=True)
class AgentConfigContext:
    """Lo que el generador PUEDE saber. Nada más."""

    name: str = ""
    description: str = ""
    purpose: str = ""
    audience: str = ""
    domain: str = ""
    source_kinds: tuple[str, ...] = ()
    source_titles: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    profile: ResponseProfile | None = None

    @property
    def capabilities(self) -> frozenset[str]:
        caps = {"knowledge"}
        for tool in self.tools:
            capability = _TOOL_CAPABILITIES.get(tool)
            if capability:
                caps.add(capability)
        return frozenset(caps)

    def facts_block(self) -> str:
        lines = [f"- nombre: {self.name or '(sin nombre)'}"]
        if self.description:
            lines.append(f"- descripción: {self.description[:300]}")
        if self.purpose:
            lines.append(f"- propósito actual: {self.purpose[:300]}")
        if self.domain:
            lines.append(f"- dominio: {self.domain[:120]}")
        if self.audience:
            lines.append(f"- audiencia declarada: {self.audience[:80]}")
        if self.source_titles:
            lines.append(f"- fuentes: {', '.join(list(self.source_titles)[:6])}")
        elif self.source_kinds:
            lines.append(f"- tipos de fuente: {', '.join(list(self.source_kinds)[:6])}")
        if self.tools:
            lines.append(f"- herramientas configuradas: {', '.join(list(self.tools)[:10])}")
        else:
            lines.append("- herramientas configuradas: ninguna")
        lines.append(
            "- capacidades permitidas: " + ", ".join(sorted(self.capabilities))
        )
        return "\n".join(lines)


def context_from_agent(
    *,
    agent: Any,
    source_kinds: Iterable[str] = (),
    source_titles: Iterable[str] = (),
    domain: str = "",
) -> AgentConfigContext:
    config = agent.config_json if isinstance(getattr(agent, "config_json", None), dict) else {}
    return AgentConfigContext(
        name=str(getattr(agent, "name", "") or ""),
        description=str(getattr(agent, "description", "") or ""),
        purpose=str(config.get("purpose") or ""),
        audience=str((config.get("response_profile") or {}).get("audience") or "")
        if isinstance(config.get("response_profile"), Mapping)
        else "",
        domain=domain,
        source_kinds=tuple(str(item) for item in source_kinds if item),
        source_titles=tuple(str(item) for item in source_titles if item),
        tools=tuple(str(item) for item in (getattr(agent, "tools", None) or [])),
        profile=profile_from_config(config),
    )


def _forbidden_mentions(text: str, capabilities: frozenset[str]) -> list[str]:
    lowered = (text or "").lower()
    hits: list[str] = []
    for capability, terms in _CAPABILITY_TERMS.items():
        if capability in capabilities:
            continue
        if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms):
            hits.append(capability)
    return hits


def validate_purpose(text: str, context: AgentConfigContext) -> tuple[str, list[str]]:
    """Recorta el propósito a lo permitido. Devuelve (texto, avisos)."""
    clean = " ".join(str(text or "").split())[:PURPOSE_MAX_CHARS]
    forbidden = _forbidden_mentions(clean, context.capabilities)
    warnings: list[str] = []
    if forbidden:
        warnings.append("mentions_unconfigured_capability:" + ",".join(forbidden))
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        kept = [
            sentence
            for sentence in sentences
            if not _forbidden_mentions(sentence, context.capabilities)
        ]
        clean = " ".join(kept).strip()
    return clean, warnings


_PRESET_HINTS: tuple[tuple[str, str], ...] = (
    ("pdf", "technical_detailed"),
    ("manual", "technical_detailed"),
    ("contrato", "evidence_first"),
    ("policy", "evidence_first"),
    ("support", "clear_didactic"),
    ("ticket", "clear_didactic"),
    ("finance", "analytical"),
    ("csv", "analytical"),
)

_PROFILE_ALLOWED_KEYS = {
    "language",
    "tone",
    "technical_level",
    "default_detail",
    "audience",
    "conclusion_first",
    "use_headings",
    "use_bold",
    "use_tables",
    "use_examples",
    "cite_sources",
    "show_uncertainty",
    "show_practical_implications",
    "preserve_domain_terms",
    "custom_instructions",
    "preset",
}


def suggest_profile(
    *,
    context: AgentConfigContext,
    preset: str | None = None,
    instructions: str = "",
) -> dict[str, Any]:
    """Perfil propuesto por reglas (sin LLM) y sus instrucciones sugeridas."""
    chosen = preset if preset in RESPONSE_PROFILE_PRESETS else None
    if chosen is None:
        haystack = " ".join(
            [context.name, context.description, *context.source_kinds]
        ).lower()
        for marker, candidate in _PRESET_HINTS:
            if marker in haystack:
                chosen = candidate
                break
    chosen = chosen or "clear_didactic"
    profile = RESPONSE_PROFILE_PRESETS[chosen]
    suggested = [
        "responde primero la conclusión; el contexto va después",
        "conserva la terminología del dominio y glósala una vez si hace falta",
        "usa un ejemplo breve cuando aclare la regla",
        "separa hecho documentado de conclusión derivada",
        "declara qué información falta antes de especular",
    ]
    if context.tools:
        suggested.append("cita la fuente junto a la afirmación que sostiene")
    if "sql" in context.capabilities:
        suggested.append("usa tabla cuando haya dos o más atributos comparables")
    clean = " ".join(str(instructions or "").split())[:INSTRUCTIONS_MAX_CHARS]
    payload = profile.to_public_dict()
    payload["preset"] = chosen
    payload["custom_instructions"] = clean or "; ".join(suggested)
    return payload


def build_purpose_prompt(context: AgentConfigContext) -> str:
    return (
        "Escribí un propósito profesional para este agente.\n\n"
        "DATOS REALES DEL AGENTE (única fuente permitida):\n"
        f"{context.facts_block()}\n\n"
        "REGLAS:\n"
        "- 1 a 3 frases, en español, sin markdown ni listas.\n"
        "- Describe QUÉ debe lograr el agente y con qué trabaja.\n"
        "- PROHIBIDO inventar capacidades, fuentes o herramientas no listadas.\n"
        "- PROHIBIDO incluir hechos, reglas de negocio, códigos, valores o "
        "conocimiento de dominio: eso vive en el conocimiento, no en el prompt.\n"
        "Responde sólo el propósito."
    )


def build_profile_prompt(context: AgentConfigContext) -> str:
    presets = ", ".join(f"{key} ({label})" for key, label in PRESET_LABELS.items())
    return (
        "Proponé CÓMO debe explicar sus respuestas este agente.\n\n"
        "DATOS REALES DEL AGENTE (única fuente permitida):\n"
        f"{context.facts_block()}\n\n"
        f"PRESETS DISPONIBLES: {presets}\n\n"
        "DEVOLVÉ SOLO JSON con esta forma:\n"
        '{{"preset": "<id>", "custom_instructions": "<una o dos frases de estilo>"}}\n\n'
        "REGLAS:\n"
        "- Las instrucciones son de ESTILO: conclusión primero, nivel de detalle, "
        "uso de ejemplos o tablas, citas, cómo declarar incertidumbre.\n"
        "- PROHIBIDO incluir hechos, reglas de negocio, códigos o valores concretos.\n"
        "- PROHIBIDO mencionar capacidades no configuradas."
    )


def parse_profile_response(text: str, context: AgentConfigContext) -> dict[str, Any]:
    """Lee la propuesta del modelo y la valida. Fail-soft al preset sugerido."""
    import json

    suggestion = suggest_profile(context=context)
    raw = str(text or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            for key, value in parsed.items():
                if key not in _PROFILE_ALLOWED_KEYS:
                    continue
                if key == "preset":
                    if str(value) in RESPONSE_PROFILE_PRESETS:
                        suggestion["preset"] = str(value)
                        base = RESPONSE_PROFILE_PRESETS[str(value)].to_public_dict()
                        base["preset"] = str(value)
                        base["custom_instructions"] = suggestion.get(
                            "custom_instructions", ""
                        )
                        suggestion = base
                    continue
                if key == "custom_instructions":
                    value = " ".join(str(value).split())[:INSTRUCTIONS_MAX_CHARS]
                suggestion[key] = value
    instructions = str(suggestion.get("custom_instructions") or "")
    forbidden = _forbidden_mentions(instructions, context.capabilities)
    if forbidden:
        suggestion["custom_instructions"] = ""
        suggestion["warnings"] = ["mentions_unconfigured_capability:" + ",".join(forbidden)]
    return suggestion


__all__ = [
    "AgentConfigContext",
    "INSTRUCTIONS_MAX_CHARS",
    "PURPOSE_MAX_CHARS",
    "build_profile_prompt",
    "build_purpose_prompt",
    "context_from_agent",
    "parse_profile_response",
    "suggest_profile",
    "validate_purpose",
]
