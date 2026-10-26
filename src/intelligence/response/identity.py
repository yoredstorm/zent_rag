# =============================================================================
# Agent identity — quién es el agente, su voz y su misión persistente.
# =============================================================================
# La identidad NO es una restricción de conocimiento. Un propósito como
# "responde como un narrador de cuentos infantil" define voz y audiencia; no
# convierte toda pregunta en un cuento ni impide valorar una obra.
#
# Se deriva del config existente (`purpose`, `system_prompt`, `identity`) y se
# resuelve contra el perfil de respuesta. El perfil puede ajustar longitud,
# estructura y detalle; no puede borrar la voz sin declarar el conflicto.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

from src.core.domain.response import ResponseProfile

_IDENTITY_VERSION = 1

_NARRATIVE_RE = re.compile(
    r"\b(narrador|narradora|cuentacuentos|cuento|infantil|ni[nñ]o|ni[nñ]a|"
    r"storyteller|fairy\s*tale|children'?s?\s+story)\b",
    re.IGNORECASE,
)
_TEACHER_RE = re.compile(r"\b(profesor|profesora|docente|maestr[oa]|pedagog|teacher)\b", re.I)
_ADVISOR_RE = re.compile(r"\b(asesor|asesora|consultor|consultora|advisor)\b", re.I)
_ANALYST_RE = re.compile(r"\b(analista|analyst)\b", re.I)
_COMMERCIAL_RE = re.compile(r"\b(comercial|ventas|sales|account\s+executive)\b", re.I)
_AUDITOR_RE = re.compile(r"\b(auditor|auditora)\b", re.I)
_SUPPORT_RE = re.compile(r"\b(soporte|support|help\s*desk)\b", re.I)
_CHILD_AUDIENCE_RE = re.compile(
    r"\b(ni[nñ]o[s]?|ni[nñ]a[s]?|infantil(?:es)?|children|kids)\b", re.I
)
_BUSINESS_AUDIENCE_RE = re.compile(r"\b(ejecutiv|gerente|director|business|management)\b", re.I)
_TECHNICAL_AUDIENCE_RE = re.compile(r"\b(t[eé]cnic|ingenier|developer|expert)\b", re.I)


@dataclass(frozen=True)
class AgentIdentity:
    """Identidad comunicativa persistente, separada del estilo."""

    identity_id: str = ""
    version: int = _IDENTITY_VERSION
    label: str = ""
    voice: str = ""
    mission: str = ""
    audience: str = ""
    domain: str = ""
    language: str = "es"
    must_preserve: tuple[str, ...] = ("voice", "mission")
    may_adapt: tuple[str, ...] = ("length", "structure", "detail", "format")
    constraints: tuple[str, ...] = ()
    source: str = "derived"

    @property
    def active(self) -> bool:
        return bool(self.voice or self.mission)

    @property
    def hash(self) -> str:
        payload = {
            "id": self.identity_id,
            "version": self.version,
            "label": self.label,
            "voice": self.voice,
            "mission": self.mission,
            "audience": self.audience,
            "domain": self.domain,
            "must_preserve": list(self.must_preserve),
            "may_adapt": list(self.may_adapt),
            "constraints": list(self.constraints),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "identity_id": self.identity_id,
            "version": self.version,
            "label": self.label,
            "voice": self.voice[:240],
            "mission": self.mission[:400],
            "audience": self.audience,
            "domain": self.domain,
            "language": self.language,
            "must_preserve": list(self.must_preserve),
            "may_adapt": list(self.may_adapt),
            "constraints": list(self.constraints)[:8],
            "source": self.source,
            "hash": self.hash,
        }


@dataclass(frozen=True)
class IdentityResolution:
    profile: ResponseProfile
    identity: AgentIdentity
    preserved: bool = True
    mode: str = "no_identity"
    conflicts: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "preserved": bool(self.preserved),
            "mode": self.mode,
            "conflicts": list(self.conflicts),
        }


def _voice_from_purpose(purpose: str) -> tuple[str, str]:
    """(label, voice) a partir del propósito en lenguaje natural."""
    text = " ".join(str(purpose or "").split())
    if not text:
        return "", ""
    if _NARRATIVE_RE.search(text):
        return "Narrador", "voz narrativa, cercana y adecuada a la audiencia infantil"
    if _TEACHER_RE.search(text):
        return "Docente", "voz pedagógica que explica paso a paso"
    if _ADVISOR_RE.search(text):
        return "Asesor", "voz consultiva que recomienda con criterios"
    if _ANALYST_RE.search(text):
        return "Analista", "voz analítica que separa hechos, hipótesis y conclusiones"
    if _COMMERCIAL_RE.search(text):
        return "Asistente comercial", "voz comercial clara y orientada a la acción"
    if _AUDITOR_RE.search(text):
        return "Auditor", "voz de auditoría, precisa y trazable"
    if _SUPPORT_RE.search(text):
        return "Soporte", "voz de soporte, clara y orientada a resolver"
    return "Identidad del agente", text[:240]


def _audience_from_purpose(purpose: str) -> str:
    text = str(purpose or "")
    if _CHILD_AUDIENCE_RE.search(text):
        return "infantil"
    if _BUSINESS_AUDIENCE_RE.search(text):
        return "negocio"
    if _TECHNICAL_AUDIENCE_RE.search(text):
        return "técnico"
    return ""


def identity_from_agent_config(
    config: Mapping[str, Any] | None,
    *,
    name: str = "",
    system_prompt: str = "",
) -> AgentIdentity:
    """Deriva la identidad del config existente. Nunca inventa hechos."""
    data = dict(config or {})
    explicit = data.get("identity")
    purpose = str(data.get("purpose") or "").strip()
    if isinstance(explicit, Mapping):
        label = str(explicit.get("label") or explicit.get("role") or "").strip()
        voice = str(explicit.get("voice") or explicit.get("persona") or "").strip()
        mission = str(explicit.get("mission") or purpose).strip()
        audience = str(explicit.get("audience") or "").strip()
        domain = str(explicit.get("domain") or data.get("domain") or "").strip()
        return AgentIdentity(
            identity_id=str(explicit.get("identity_id") or explicit.get("id") or "agent-identity")[:80],
            version=int(explicit.get("version") or _IDENTITY_VERSION),
            label=label or "Identidad del agente",
            voice=voice or voice_from_purpose(purpose),
            mission=mission,
            audience=audience or _audience_from_purpose(purpose),
            domain=domain,
            language=str(explicit.get("language") or "es")[:16],
            must_preserve=tuple(str(item) for item in (explicit.get("must_preserve") or ("voice", "mission"))),
            may_adapt=tuple(
                str(item)
                for item in (explicit.get("may_adapt") or ("length", "structure", "detail", "format"))
            ),
            constraints=tuple(str(item) for item in (explicit.get("constraints") or ()))[:8],
            source="config",
        )
    label, voice = _voice_from_purpose(purpose)
    if not voice and system_prompt:
        label, voice = _voice_from_purpose(system_prompt)
    mission = purpose or str(system_prompt or "").strip()[:400]
    return AgentIdentity(
        identity_id="agent-identity",
        version=_IDENTITY_VERSION,
        label=label or "Identidad del agente",
        voice=voice,
        mission=mission,
        audience=_audience_from_purpose(purpose or system_prompt),
        domain=str(data.get("domain") or "").strip(),
        source="derived" if voice else "none",
    )


def voice_from_purpose(purpose: str) -> str:
    return _voice_from_purpose(purpose)[1]


def identity_prompt_block(identity: AgentIdentity | None) -> str:
    """Instrucción de identidad, siempre ANTES del perfil de estilo."""
    if identity is None or not identity.active:
        return ""
    lines = [
        "## AGENT IDENTITY (persistente; precede al estilo)",
        f"- identidad: {identity.label or 'agente'}",
    ]
    if identity.voice:
        lines.append(f"- voz: {identity.voice}")
    if identity.mission:
        lines.append(f"- misión: {identity.mission[:400]}")
    if identity.audience:
        lines.append(f"- audiencia de la identidad: {identity.audience}")
    if identity.domain:
        lines.append(f"- dominio: {identity.domain}")
    lines.append(
        "- conserva la voz y la misión en todas las respuestas. El perfil de respuesta "
        "puede ajustar longitud, estructura, detalle y formato, pero no sustituir la identidad."
    )
    lines.append(
        "- la identidad es comunicativa, no una restricción de conocimiento: no rechaces "
        "una pregunta por 'no tener experiencia personal'. Formula la parte justificable."
    )
    lines.append(
        "- adapta el vocabulario y los ejemplos al dominio de la identidad y de la evidencia; "
        "no impongas jerga de otro dominio."
    )
    if _NARRATIVE_RE.search(" ".join([identity.label, identity.voice, identity.mission])):
        lines.append(
            "- voz narrativa concreta: frases cálidas, imágenes simples y ritmo oral. "
            "No cambies a registro académico, a jerga de consultoría ni a una tesis "
            "universitaria; si el perfil pide brevedad, conserva la voz en una sola "
            "frase o en una imagen cotidiana."
        )
        lines.append(
            "- no muestres 'Criterios', 'evaluación', 'perfil' ni metadatos internos: "
            "responde como el agente, no como un evaluador."
        )
    if identity.constraints:
        lines.append("- límites de identidad: " + "; ".join(identity.constraints[:6]))
    return "\n".join(lines)


def identity_block_from_contract(contract: Any) -> str:
    """Reconstruye un bloque compacto desde un contrato ya publicado."""
    identity_id = str(getattr(contract, "identity_id", "") or "")
    voice = str(getattr(contract, "identity_voice", "") or "")
    if not identity_id and not voice:
        return ""
    label = identity_id or "agente"
    lines = ["## AGENT IDENTITY (persistente; precede al estilo)", f"- identidad: {label}"]
    if voice:
        lines.append(f"- voz: {voice}")
    lines.append(
        "- conserva la voz y la misión; el perfil ajusta longitud, estructura y formato, "
        "nunca la identidad."
    )
    return "\n".join(lines)


def resolve_identity_profile(
    identity: AgentIdentity | None,
    profile: ResponseProfile,
) -> IdentityResolution:
    """Resuelve el choque identidad/perfil sin borrar la identidad.

    El perfil conserva su extensión y estructura; la voz se preserva con el
    bloque de identidad. Los conflictos materiales se publican y, cuando el
    perfil apaga los ejemplos de una identidad narrativa, se restituye un
    ejemplo mínimo sustentado.
    """
    if identity is None or not identity.active:
        return IdentityResolution(
            profile=profile,
            identity=identity or AgentIdentity(),
            mode="preserve",
        )
    conflicts: list[str] = []
    resolved = profile
    narrative = bool(_NARRATIVE_RE.search(" ".join([identity.label, identity.voice, identity.mission])))
    if narrative and resolved.example_policy == "never":
        conflicts.append("profile_disables_examples")
        resolved = replace(
            resolved,
            example_policy="minimal_supported",
            use_examples=True,
        )
    if narrative and identity.audience and resolved.audience in {"business", "expert"}:
        conflicts.append("profile_audience_differs")
    if identity.domain and resolved.terminology_policy == "exact" and narrative:
        conflicts.append("profile_terms_may_overconstrain")
    if resolved.audience_assumptions:
        assumptions = resolved.audience_assumptions
    else:
        assumptions = ""
    if identity.audience:
        assumptions = (
            f"{assumptions}; " if assumptions else ""
        ) + f"identidad dirigida a {identity.audience}"
    resolved = replace(resolved, audience_assumptions=assumptions[:240])
    mode = "voice_over_style" if conflicts else "preserve"
    return IdentityResolution(
        profile=resolved,
        identity=identity,
        preserved=True,
        mode=mode,
        conflicts=tuple(dict.fromkeys(conflicts)),
    )


__all__ = [
    "AgentIdentity",
    "IdentityResolution",
    "identity_block_from_contract",
    "identity_from_agent_config",
    "identity_prompt_block",
    "resolve_identity_profile",
]
