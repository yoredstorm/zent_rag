# =============================================================================
# Response Composer — decisión por código + redacción humana por LLM
# =============================================================================
# PRINCIPIO DE AUTORIDAD:
#
#   La decisión la calcula CÓDIGO (DecisionEnvelope inmutable).
#   El LLM puede cambiar: tono, estructura, explicación, ejemplos, nivel de
#   detalle, lenguaje y forma de dirigirse al usuario.
#   El LLM NO puede cambiar: operation, result, answerability, CanonicalRule,
#   checks, premise status, evidencia, numeric/matching/date/enum results.
#
# Pipeline:
#   DecisionEnvelope → DeterministicResponseFacts → PersonalityAwareComposer
#   → validate_composed_answer → citation handles → FINAL_AUTHORITY_LOCK
#   → serialization
#
# Este módulo NO reemplaza al FINAL_AUTHORITY_LOCK ni al DerivedGuard: el texto
# que sale de acá siempre vuelve a pasar por ellos. El composer recibe solo
# hechos compactos (no documentos completos): presupuesto típico 800-2500
# tokens de entrada y 100-400 de salida.
#
# Modos de redacción (DETERMINISTIC_RENDER_MODE):
#   strict    0 llamadas LLM (renderer determinista actual)
#   polish    1 llamada pequeña cuando existe personalidad del agente
#   adaptive  0 para respuestas triviales; 1 si la personalidad/el caso lo pide
# =============================================================================
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

RESPONSE_COMPOSER_VERSION = "response-composer-1"

# --- modos de redacción -----------------------------------------------------
RENDER_MODE_STRICT = "strict"
RENDER_MODE_POLISH = "polish"
RENDER_MODE_ADAPTIVE = "adaptive"
RENDER_MODES: tuple[str, ...] = (
    RENDER_MODE_STRICT,
    RENDER_MODE_POLISH,
    RENDER_MODE_ADAPTIVE,
)

# --- modos de ejecución del fast path ---------------------------------------
#: El fast path NO deja de ser determinista por una llamada de PRESENTACIÓN:
#: en ambos la decisión se calcula con 0 llamadas LLM.
EXECUTION_MODE_FAST_PATH_STRICT = "DETERMINISTIC_FAST_PATH_STRICT"
EXECUTION_MODE_FAST_PATH_POLISHED = "DETERMINISTIC_FAST_PATH_POLISHED"

# --- constraints del contrato de hechos -------------------------------------
CONSTRAINT_MUST_NOT_CHANGE_RESULT = "must_not_change_result"
CONSTRAINT_MUST_NOT_INVENT_PREMISES = "must_not_invent_premises"
CONSTRAINT_MUST_NOT_INVENT_EVIDENCE = "must_not_invent_evidence"

_POSITIVE_STATES = frozenset({"MATCH", "TRUE", "VALID", "ELIGIBLE", "YES"})
_NEGATIVE_STATES = frozenset({"NO_MATCH", "FALSE", "INVALID", "NOT_ELIGIBLE", "NO"})

_CITATION_HANDLE_RE = re.compile(r"\[?\(?\bC(\d+)\b\)?\]?")
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_QUESTION_RE = re.compile(r"[?¿]")
_CONVERSATIONAL_RE = re.compile(
    r"\b(?:hola|buenas|gracias|por\s+favor|me|mi|mis|yo|tengo|necesito|quiero|"
    r"pod[eé]s|puedes|podr[ií]as|me\s+confirmas|decime|dime)\b",
    re.IGNORECASE,
)
_EXPLANATION_RE = re.compile(
    r"\b(?:explica(?:me|r)?|expl[ií]came|detalla(?:me|r)?|por\s+qu[eé]|porque|"
    r"paso\s+a\s+paso|en\s+detalle|c[oó]mo\s+funciona|a\s+fondo)\b",
    re.IGNORECASE,
)
_MECHANICAL_RENDER_RE = re.compile(
    r"resultado determinista \(|la operación documentada se evaluó", re.IGNORECASE
)

#: Palabras de OTRAS operaciones: si el texto describe una operación distinta
#: a la decidida, el validador lo rechaza.
_OPERATION_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "COMPARISON",
        re.compile(
            r"\b(?:comparaci[oó]n\s+num[eé]rica|mayor\s+o\s+igual|menor\s+o\s+igual|"
            r"comparaci[oó]n\s+de\s+valores)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "RANGE",
        re.compile(
            r"\b(?:rango\s+documentado|dentro\s+del\s+rango|fuera\s+del\s+rango|"
            r"entre\s+los\s+l[ií]mites)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATE",
        re.compile(
            r"\b(?:fecha\s+de\s+vigencia|condici[oó]n\s+temporal|est[aá]\s+vigente|"
            r"dentro\s+de\s+la\s+vigencia)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "FORMULA",
        re.compile(
            r"\b(?:f[oó]rmula\s+documentada|resultado\s+del\s+c[aá]lculo|"
            r"c[aá]lculo\s+documentado)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ENUM",
        re.compile(
            r"\b(?:valores\s+permitidos|lista\s+de\s+valores|valores\s+documentados)\b",
            re.IGNORECASE,
        ),
    ),
)

#: Operación determinista -> familia (comparación del validador).
_OPERATION_FAMILIES: dict[str, str] = {
    "POSITIONAL_MATCH": "MATCHING",
    "MATCH": "MATCHING",
    "STRING_EQUALITY": "MATCHING",
    "COMPARISON": "COMPARISON",
    "NUMERIC_COMPARE": "COMPARISON",
    "RANGE_CHECK": "RANGE",
    "DATE_COMPARE": "DATE",
    "DATE_COMPARISON": "DATE",
    "DATE_RANGE": "DATE",
    "FORMULA": "FORMULA",
    "FORMULA_EVALUATION": "FORMULA",
    "ARITHMETIC": "ARITHMETIC",
    "ENUM_CHECK": "ENUM",
    "SET_MEMBERSHIP": "ENUM",
    "BOOLEAN": "BOOLEAN",
    "ELIGIBILITY": "BOOLEAN",
}


def _public(value: Any) -> dict[str, Any]:
    """Vista dict de un envelope/grounded (objeto o mapping)."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        try:
            payload = to_public()
            return dict(payload) if isinstance(payload, Mapping) else {}
        except Exception:  # noqa: BLE001 — la observabilidad nunca rompe
            return {}
    return {}


def _text(value: Any, *, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def _headline_semantics(result: Any) -> str:
    text = str(result or "").strip().upper()
    if text in _POSITIVE_STATES:
        return "positive"
    if text in _NEGATIVE_STATES:
        return "negative"
    return "neutral"


def _numbers(text: Any) -> list[float]:
    found: list[float] = []
    for raw in _NUMBER_RE.findall(str(text or "")):
        try:
            found.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return found


# -----------------------------------------------------------------------------
# DeterministicResponseFacts (inmutable)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ResponseSourceFact:
    """Fuente citada con handle determinista (C1, C2, ...)."""

    handle: str
    document: str = ""
    page: int | None = None
    section: str = ""
    evidence_id: str = ""
    claim: str = ""

    def label(self) -> str:
        parts: list[str] = []
        if self.document:
            parts.append(self.document)
        if isinstance(self.page, int):
            parts.append(f"pág. {self.page}")
        if self.section:
            parts.append(self.section)
        return " · ".join(parts)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "document": _text(self.document, limit=120),
            "page": self.page,
            "section": _text(self.section, limit=120),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "document": _text(self.document, limit=160),
            "page": self.page,
            "section": _text(self.section, limit=160),
            "evidence_id": _text(self.evidence_id, limit=80),
            "claim": _text(self.claim, limit=200),
        }


@dataclass(frozen=True, kw_only=True)
class DeterministicResponseFacts:
    """Hechos de la decisión determinista: contrato INMUTABLE para el redactor.

    El composer puede explicar; no puede agregar, quitar ni cambiar ninguno de
    estos hechos. `constraints` lo declara de forma explícita.
    """

    operation: str = ""
    result: str = ""
    headline_semantics: str = "neutral"  # positive | negative | neutral
    answer_state: str = "DERIVED_RESULT"
    inputs: tuple[tuple[str, str], ...] = ()
    checks: tuple[dict, ...] = ()
    sources: tuple[ResponseSourceFact, ...] = ()
    rule_ids: tuple[str, ...] = ()
    statement: str = ""
    language: str = "es"
    constraints: tuple[str, ...] = (
        CONSTRAINT_MUST_NOT_CHANGE_RESULT,
        CONSTRAINT_MUST_NOT_INVENT_PREMISES,
        CONSTRAINT_MUST_NOT_INVENT_EVIDENCE,
    )
    version: str = RESPONSE_COMPOSER_VERSION

    @property
    def authoritative(self) -> bool:
        return self.answer_state == "DERIVED_RESULT"

    @property
    def citation_handles(self) -> tuple[str, ...]:
        return tuple(source.handle for source in self.sources)

    def to_prompt_dict(self) -> dict[str, Any]:
        """Vista COMPACTA para el LLM (sin documentos completos ni historial)."""
        return {
            "decision": {
                "operation": self.operation,
                "result": self.result,
                "polarity": self.headline_semantics,
                "state": self.answer_state,
            },
            "inputs": [
                {"name": _text(name, limit=60), "value": _text(value, limit=120)}
                for name, value in self.inputs[:6]
            ],
            "checks": [
                {
                    "name": _text(check.get("name") or check.get("operation"), limit=60),
                    "operation": _text(check.get("operation"), limit=60),
                    "status": _text(check.get("status"), limit=40),
                    "result": check.get("result"),
                    "detail": _text(check.get("detail"), limit=180),
                }
                for check in self.checks[:6]
            ],
            "sources": [source.to_prompt_dict() for source in self.sources[:4]],
            "rule": {"statement": _text(self.statement, limit=240)},
            "constraints": list(self.constraints),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "operation": self.operation,
            "result": self.result,
            "headline_semantics": self.headline_semantics,
            "answer_state": self.answer_state,
            "inputs": [
                {"name": name, "value": value} for name, value in self.inputs[:8]
            ],
            "checks": [dict(check) for check in self.checks[:8]],
            "sources": [source.to_public_dict() for source in self.sources[:6]],
            "rule_ids": list(self.rule_ids[:6]),
            "statement": _text(self.statement, limit=300),
            "language": self.language,
            "constraints": list(self.constraints),
        }


def _inputs_from_runtime(runtime_inputs: Sequence[Any]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in runtime_inputs or ():
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" in text:
            name, value = text.split("=", 1)
            pair = (_text(name, limit=60), _text(value, limit=120))
        else:
            pair = ("input", _text(text, limit=120))
        key = f"{pair[0]}={pair[1]}"
        if key in seen:
            continue
        seen.add(key)
        pairs.append(pair)
    return tuple(pairs[:8])


def _checks_from(values: Sequence[Any], *, limit: int = 8) -> tuple[dict, ...]:
    checks: list[dict] = []
    for value in values or ():
        payload = _public(value)
        if not payload:
            continue
        checks.append(
            {
                "name": _text(payload.get("name") or payload.get("operation"), limit=80),
                "operation": _text(payload.get("operation"), limit=80),
                "status": _text(payload.get("status"), limit=40),
                "result": payload.get("result"),
                "detail": _text(payload.get("detail"), limit=200),
            }
        )
    return tuple(checks[:limit])


def _sources_from_citations(citations: Sequence[Any]) -> tuple[ResponseSourceFact, ...]:
    sources: list[ResponseSourceFact] = []
    used_docs: set[str] = set()
    for value in citations or ():
        payload = _public(value)
        if not payload:
            continue
        document = _text(
            payload.get("document_name")
            or payload.get("title")
            or payload.get("display_name"),
            limit=160,
        )
        page = payload.get("page")
        section_path = payload.get("section_path")
        section = ""
        if isinstance(section_path, (list, tuple)):
            section = " · ".join(str(part) for part in section_path[:2] if str(part))
        elif section_path:
            section = _text(section_path, limit=120)
        claim = _text(payload.get("locator") or payload.get("excerpt"), limit=200)
        if not (document or isinstance(page, int)):
            continue
        dedup_key = f"{document}|{page}|{section}"
        if dedup_key in used_docs:
            continue
        used_docs.add(dedup_key)
        sources.append(
            ResponseSourceFact(
                handle=f"C{len(sources) + 1}",
                document=document,
                page=page if isinstance(page, int) else None,
                section=section,
                evidence_id=_text(payload.get("evidence_id"), limit=80),
                claim=claim,
            )
        )
        if len(sources) >= 4:
            break
    return tuple(sources)


def build_response_facts(
    envelope: Any,
    *,
    grounded: Any = None,
    checks: Sequence[Any] = (),
    runtime_inputs: Sequence[Any] = (),
    citations: Sequence[Any] = (),
    statement: str = "",
    rule_ids: Sequence[Any] = (),
    language: str = "es",
    answer_state: str = "DERIVED_RESULT",
) -> DeterministicResponseFacts:
    """Construye los hechos inmutables desde el DecisionEnvelope + evidencia."""
    env = _public(envelope)
    grounded_public = _public(grounded)
    result = str(env.get("result") or "")
    operation = str(env.get("operation") or "")
    resolved_checks = _checks_from(checks or env.get("checks") or ())
    if not resolved_checks:
        flow = grounded_public.get("canonical_rule_flow")
        if isinstance(flow, Sequence) and not isinstance(flow, (str, bytes)):
            merged: list[Any] = []
            for evaluation in flow:
                payload = _public(evaluation)
                merged.extend(payload.get("checks") or ())
            resolved_checks = _checks_from(merged)
    resolved_inputs = _inputs_from_runtime(
        runtime_inputs or env.get("runtime_inputs") or ()
    )
    resolved_rules = tuple(
        str(value)
        for value in (rule_ids or env.get("canonical_rule_ids") or ())
        if str(value or "").strip()
    )
    return DeterministicResponseFacts(
        operation=operation,
        result=result,
        headline_semantics=_headline_semantics(result),
        answer_state=str(answer_state or "DERIVED_RESULT"),
        inputs=resolved_inputs,
        checks=resolved_checks,
        sources=_sources_from_citations(citations),
        rule_ids=resolved_rules[:6],
        statement=str(statement or env.get("statement") or ""),
        language=str(language or "es")[:16],
    )


# -----------------------------------------------------------------------------
# Personalidad real del agente (la del ResponseProfile existente)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ComposerPersonality:
    """Personalidad efectiva del turno. Estructura, nunca hechos."""

    block: str = ""
    custom_instructions: str = ""
    tone: str = ""
    technical_level: str = ""
    detail: str = ""
    language: str = "es"
    use_examples: bool = False
    cite_sources: bool = True
    has_personality: bool = False
    source: str = "defaults"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.has_personality),
            "tone": self.tone,
            "technical_level": self.technical_level,
            "detail": self.detail,
            "language": self.language,
            "source": self.source,
            "custom_instructions": _text(self.custom_instructions, limit=200),
        }


def personality_for_agent(
    agent_config: Mapping[str, Any] | None,
    *,
    message: str = "",
    org_config: Mapping[str, Any] | None = None,
) -> ComposerPersonality:
    """Personalidad REAL del agente: usa ResponseProfile + instrucciones.

    No crea una personality paralela: lee `response_profile` (tone, level,
    detail, custom_instructions) y las instrucciones del agente/organización con
    la MISMA precedencia del pipeline normal.
    """
    config = dict(agent_config or {})
    org = dict(org_config or {})
    try:
        from src.intelligence.response.profile import (
            apply_turn_overrides,
            profile_from_config,
            profile_prompt_block,
        )

        profile = apply_turn_overrides(profile_from_config(config), message)
        block = profile_prompt_block(profile)
        custom = (
            str(config.get("custom_instructions") or "").strip()
            or str(config.get("additional_instructions") or "").strip()
            or str(org.get("custom_instructions") or "").strip()
            or str(profile.custom_instructions or "").strip()
        )
        explicit_profile = bool(config.get("response_profile"))
        has_personality = bool(
            explicit_profile
            or custom
            or str(config.get("purpose") or "").strip()
            or str(config.get("persona") or "").strip()
            or str(config.get("tone") or "").strip()
        )
        return ComposerPersonality(
            block=block,
            custom_instructions=custom,
            tone=str(profile.tone or ""),
            technical_level=str(profile.technical_level or ""),
            detail=str(profile.default_detail or ""),
            language=str(profile.language or "es")[:16],
            use_examples=bool(profile.use_examples),
            cite_sources=bool(profile.cite_sources),
            has_personality=has_personality,
            source="agent_config" if has_personality else "defaults",
        )
    except Exception:  # noqa: BLE001 — sin perfil el composer no se activa
        custom = (
            str(config.get("custom_instructions") or "").strip()
            or str(config.get("additional_instructions") or "").strip()
            or str(org.get("custom_instructions") or "").strip()
        )
        has_personality = bool(
            custom
            or config.get("response_profile")
            or str(config.get("purpose") or "").strip()
            or str(config.get("persona") or "").strip()
        )
        return ComposerPersonality(
            custom_instructions=custom,
            has_personality=has_personality,
            source="agent_config" if has_personality else "defaults",
        )


# -----------------------------------------------------------------------------
# Decisión de redacción (strict / polish / adaptive)
# -----------------------------------------------------------------------------


def render_mode_from_settings(settings: Any | None = None) -> str:
    """Modo de redacción resuelto (con compatibilidad del flag legacy)."""
    if settings is None:
        from src.core.config import get_settings

        settings = get_settings()
    mode = str(
        getattr(settings, "RUNTIME_DETERMINISTIC_RENDER_MODE", RENDER_MODE_ADAPTIVE)
        or RENDER_MODE_ADAPTIVE
    ).lower()
    if mode not in RENDER_MODES:
        mode = RENDER_MODE_ADAPTIVE
    if mode == RENDER_MODE_ADAPTIVE and bool(
        getattr(settings, "RUNTIME_FAST_PATH_POLISH", False)
    ):
        # Flag legacy: pedía polish explícito.
        return RENDER_MODE_POLISH
    return mode


def resolve_composer_model(settings: Any, agent_model: str = "") -> str:
    """Modelo barato para presentación: explícito > fast > cheap > agente."""
    for value in (
        getattr(settings, "RUNTIME_COMPOSER_MODEL", ""),
        getattr(settings, "GATEWAY_FAST_MODEL", ""),
        getattr(settings, "GATEWAY_CHEAP_MODEL", ""),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(agent_model or "")


def _looks_conversational(message: str) -> bool:
    text = str(message or "")
    if not text.strip():
        return False
    return bool(_QUESTION_RE.search(text) or _CONVERSATIONAL_RE.search(text))


def _requests_explanation(message: str) -> bool:
    return bool(_EXPLANATION_RE.search(str(message or "")))


def _renderer_sounds_mechanical(answer: str) -> bool:
    return bool(_MECHANICAL_RENDER_RE.search(str(answer or "")))


def should_polish(
    *,
    mode: str,
    personality: ComposerPersonality,
    facts: DeterministicResponseFacts,
    message: str = "",
    deterministic_answer: str = "",
) -> tuple[bool, str]:
    """¿Corresponde UNA llamada pequeña de redacción? (determinista)"""
    active_mode = str(mode or RENDER_MODE_ADAPTIVE).lower()
    if active_mode not in RENDER_MODES:
        active_mode = RENDER_MODE_ADAPTIVE
    if not facts.authoritative:
        return False, "not_authoritative"
    if active_mode == RENDER_MODE_STRICT:
        return False, "strict"
    if not personality.has_personality:
        return False, "no_personality"
    if active_mode == RENDER_MODE_POLISH:
        return True, "polish"
    triggers: list[str] = []
    if len(facts.checks) >= 2:
        triggers.append("multiple_checks")
    if _looks_conversational(message):
        triggers.append("conversational")
    if _requests_explanation(message):
        triggers.append("requested_detail")
    if personality.custom_instructions or personality.tone not in ("", "professional"):
        triggers.append("personality_tone")
    if _renderer_sounds_mechanical(deterministic_answer):
        triggers.append("mechanical_renderer")
    if triggers:
        return True, "adaptive:" + ",".join(triggers[:3])
    return False, "trivial"


# -----------------------------------------------------------------------------
# Validador semántico (determinista, sin LLM)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ComposedAnswerValidation:
    valid: bool = True
    problems: tuple[str, ...] = ()
    detail: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "problems": list(self.problems[:6]),
            "detail": _text(self.detail, limit=240),
        }


def _facts_numbers(facts: DeterministicResponseFacts) -> set[float]:
    numbers: set[float] = set()
    for _name, value in facts.inputs:
        numbers.update(_numbers(value))
    for check in facts.checks:
        numbers.update(_numbers(check.get("detail")))
        numbers.update(_numbers(check.get("result")))
    for source in facts.sources:
        if isinstance(source.page, int):
            numbers.add(float(source.page))
    numbers.update(_numbers(facts.statement))
    return numbers


def _detected_operation_family(answer: str, expected_family: str) -> str:
    lowered = str(answer or "").lower()
    for family, pattern in _OPERATION_KEYWORDS:
        if not pattern.search(lowered):
            continue
        # Una negación explícita ("no es una comparación numérica") no describe
        # la operación del texto.
        if re.search(r"\bno\s+(?:es|se\s+trata\s+de|fue)\b", lowered):
            continue
        if family != expected_family:
            return family
    return ""


def validate_composed_answer(
    answer: str,
    envelope: Any,
    facts: DeterministicResponseFacts,
    *,
    deterministic_answer: str = "",
) -> ComposedAnswerValidation:
    """Valida que el texto redactado NO cambie la decisión ni invente hechos.

    Detecta: contradicción/inversión, abstención epistémica, números inventados,
    descripción de otra operación y citas inexistentes.
    """
    text = str(answer or "").strip()
    if not text:
        return ComposedAnswerValidation(valid=False, problems=("empty_answer",))
    problems: list[str] = []

    env = _public(envelope)
    result = env.get("result") or facts.result
    operation = str(env.get("operation") or facts.operation or "")

    # 1. Inversión / abstención epistémica (mismo guard que la autoridad final).
    from src.runtime.derived_guard import contradicts_authoritative_result

    contradiction = contradicts_authoritative_result(text, result)
    if contradiction:
        problems.append(f"result_contradiction:{_text(contradiction, limit=80)}")

    # 2. Números inventados (se permiten los de los hechos y del renderer).
    allowed = _facts_numbers(facts) | set(_numbers(deterministic_answer))
    answer_without_handles = _CITATION_HANDLE_RE.sub("C", text)
    for value in _numbers(answer_without_handles):
        if value not in allowed:
            problems.append(f"invented_number:{value:g}")
            break

    # 3. Descripción de otra operación.
    expected_family = _OPERATION_FAMILIES.get(operation.upper(), "")
    detected = _detected_operation_family(text, expected_family)
    if detected:
        problems.append(f"operation_description_mismatch:{detected}")

    # 4. Citas inexistentes: solo los handles provistos existen.
    known_handles = set(facts.citation_handles)
    for number in _CITATION_HANDLE_RE.findall(text):
        handle = f"C{number}"
        if handle not in known_handles:
            problems.append(f"unknown_citation:{handle}")
            break

    return ComposedAnswerValidation(
        valid=not problems,
        problems=tuple(problems),
        detail="; ".join(problems[:4]),
    )


# -----------------------------------------------------------------------------
# Citas: handles C1..Cn -> documento/página determinista
# -----------------------------------------------------------------------------


def render_citation_handles(
    answer: str, sources: Sequence[ResponseSourceFact]
) -> str:
    """Convierte `[C1]` → `Documento · pág. N` (y elimina handles inventados)."""
    by_handle = {source.handle: source for source in sources or ()}

    def _replace(match: re.Match[str]) -> str:
        handle = f"C{match.group(1)}"
        source = by_handle.get(handle)
        if source is None:
            return ""
        label = source.label()
        return label or handle

    rendered = _CITATION_HANDLE_RE.sub(_replace, str(answer or ""))
    rendered = re.sub(r"\s+([.,;:])", r"\1", rendered)
    rendered = re.sub(r"[ \t]{2,}", " ", rendered)
    rendered = re.sub(r"[ \t]+\n", "\n", rendered)
    return rendered.strip()


# -----------------------------------------------------------------------------
# Prompt + composer
# -----------------------------------------------------------------------------

COMPOSER_SYSTEM_SAFETY = (
    "Tu trabajo NO es resolver el problema. La decisión ya fue calculada por "
    "código y es inmutable. Tu única tarea es explicarla con naturalidad, "
    "respetando la personalidad del agente y el pedido del usuario.\n"
    "Precedencia: seguridad de la plataforma > autoridad del DecisionEnvelope > "
    "política de la organización > personalidad/instrucciones del agente > "
    "estilo pedido por el usuario.\n"
    "No cambies la operación, el resultado, su polaridad, los números, las "
    "condiciones ni el estado de las premisas. No inventes hechos, reglas, "
    "fuentes ni citas. Si citás, usá únicamente los handles provistos "
    "(C1, C2, ...). Si no hay handles, no cites. No muestres IDs internos, "
    "tokens de control ni detalles de implementación."
)


def build_composer_prompt(
    facts: DeterministicResponseFacts,
    personality: ComposerPersonality,
    *,
    deterministic_answer: str = "",
    message: str = "",
    markdown_context: str = "",
) -> tuple[str, str]:
    """(system_prompt, user_prompt) COMPACTOS: hechos, estilo y nada más.

    `markdown_context` es la proyección LLM-ready del documento (secciones
    legibles): mejora la comprensión lingüística, nunca la autoridad. Si está
    vacío o no promovió el quality gate, no se incluye.
    """
    system_parts = [COMPOSER_SYSTEM_SAFETY]
    if personality.block:
        system_parts.append(personality.block)
    if personality.custom_instructions:
        system_parts.append(
            "## INSTRUCCIONES DEL AGENTE\n" + personality.custom_instructions
        )
    system_parts.append(
        "Estilo: respondé en "
        + (personality.language or "es")
        + "; el tono y el detalle salen del perfil del agente. "
        "No asumas que humanidad = respuesta larga: si el perfil es conciso, "
        "sé breve; si es didáctico, explicá el porqué. "
        "No uses encabezados salvo que el perfil los pida. "
        "No repitas literalmente 'Resultado determinista'; explicá como una "
        "persona. No muestres IDs internos, tokens de control ni rutas técnicas."
    )
    facts_payload = facts.to_prompt_dict()
    user_parts = [
        "HECHOS DE LA DECISIÓN (inmutables, no agregues ni cambies nada):",
        json.dumps(facts_payload, ensure_ascii=False, indent=2, sort_keys=True),
    ]
    if message.strip():
        user_parts.extend(["PEDIDO DEL USUARIO:", _text(message, limit=400)])
    if deterministic_answer.strip():
        user_parts.extend(
            [
                "REDACCIÓN DETERMINISTA DE REFERENCIA (podés reformularla; sus "
                "hechos no cambian):",
                _text(deterministic_answer, limit=1200),
            ]
        )
    context = str(markdown_context or "").strip()
    if context:
        user_parts.extend(
            [
                "CONTEXTO DOCUMENTAL (proyección Markdown legible de la MISMA "
                "fuente; ayuda a explicar, no cambia la decisión):",
                context[:1200],
            ]
        )
    user_parts.append(
        "Redactá la respuesta final para el usuario (solo texto, sin JSON). "
        "Primera línea: la conclusión con la MISMA polaridad del resultado."
    )
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


@dataclass(kw_only=True)
class ComposedAnswerResult:
    """Salida del composer: texto + telemetría de presentación."""

    answer: str
    mode: str = RENDER_MODE_ADAPTIVE
    personality_applied: bool = False
    llm_polish: bool = False
    fallback_used: bool = False
    skip_reason: str = ""
    composer_model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    #: Llamadas de PRESENTACIÓN (0 o 1). La decisión siempre usó 0.
    llm_presentation_calls: int = 0
    validation: dict = field(default_factory=dict)
    facts: DeterministicResponseFacts | None = None
    version: str = RESPONSE_COMPOSER_VERSION

    @property
    def execution_mode(self) -> str:
        return (
            EXECUTION_MODE_FAST_PATH_POLISHED
            if self.llm_presentation_calls > 0
            else EXECUTION_MODE_FAST_PATH_STRICT
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "mode": self.mode,
            "personality_applied": bool(self.personality_applied),
            "llm_polish": bool(self.llm_polish),
            "fallback_used": bool(self.fallback_used),
            "skip_reason": self.skip_reason[:120],
            "composer_model": self.composer_model,
            "input_tokens": int(self.prompt_tokens),
            "output_tokens": int(self.completion_tokens),
            "composer_latency": round(float(self.latency_ms), 2),
            "composer_latency_ms": round(float(self.latency_ms), 2),
            "llm_presentation_calls": int(self.llm_presentation_calls),
            "llm_decision_calls": 0,
            "semantic_validation": dict(self.validation),
            "execution_mode": self.execution_mode,
        }


def clean_composed_text(content: Any, *, limit: int = 6000) -> str:
    """Texto del composer: sin fences, sin etiquetas, sin JSON envoltorio."""
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            for key in ("answer", "respuesta", "text"):
                if isinstance(payload.get(key), str):
                    text = payload[key]
                    break
    text = re.sub(
        r"^(?:respuesta|answer|texto|rewritten answer)\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()[:limit]


class PersonalityAwareComposer:
    """Una llamada pequeña de redacción DESPUÉS del DecisionEnvelope.

    `generate` es el puerto LLM (mismo contrato que LLMProvider.generate).
    El composer NUNCA decide: solo redacta, y su texto vuelve a validarse.
    """

    def __init__(
        self,
        *,
        generate: Callable[..., Awaitable[Any]] | None = None,
        model: str = "",
        max_tokens: int = 400,
        temperature: float = 0.35,
    ) -> None:
        self._generate = generate
        self._model = str(model or "")
        self._max_tokens = max(64, min(int(max_tokens or 400), 1200))
        self._temperature = max(0.0, min(float(temperature or 0.35), 1.0))

    async def compose(
        self,
        *,
        facts: DeterministicResponseFacts,
        personality: ComposerPersonality,
        deterministic_answer: str,
        mode: str = RENDER_MODE_ADAPTIVE,
        message: str = "",
        envelope: Any = None,
        markdown_context: str = "",
    ) -> ComposedAnswerResult:
        started = time.perf_counter()
        should, reason = should_polish(
            mode=mode,
            personality=personality,
            facts=facts,
            message=message,
            deterministic_answer=deterministic_answer,
        )
        base = ComposedAnswerResult(
            answer=deterministic_answer,
            mode=str(mode or RENDER_MODE_ADAPTIVE),
            personality_applied=bool(personality.has_personality),
            facts=facts,
        )
        if not should:
            base.skip_reason = reason
            base.latency_ms = (time.perf_counter() - started) * 1000
            return base
        if self._generate is None:
            base.skip_reason = "no_llm"
            base.latency_ms = (time.perf_counter() - started) * 1000
            return base

        system_prompt, prompt = build_composer_prompt(
            facts,
            personality,
            deterministic_answer=deterministic_answer,
            message=message,
            markdown_context=markdown_context,
        )
        try:
            response = await self._generate(
                prompt=prompt,
                model=self._model or None,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system_prompt=system_prompt,
            )
        except Exception as exc:  # noqa: BLE001 — el polish jamás rompe el run
            base.fallback_used = True
            base.skip_reason = f"composer_error:{type(exc).__name__}"
            base.latency_ms = (time.perf_counter() - started) * 1000
            return base

        base.composer_model = str(
            getattr(response, "model", "") or self._model or ""
        )
        base.llm_presentation_calls = 1
        base.prompt_tokens = int(getattr(response, "prompt_tokens", 0) or 0)
        base.completion_tokens = int(getattr(response, "completion_tokens", 0) or 0)
        candidate = clean_composed_text(getattr(response, "content", ""))
        validation = validate_composed_answer(
            candidate, envelope, facts, deterministic_answer=deterministic_answer
        )
        base.validation = validation.to_public_dict()
        if not validation.valid:
            # Se descarta el texto del LLM: fallback determinista.
            base.answer = deterministic_answer
            base.fallback_used = True
            base.skip_reason = "semantic_validation_failed"
            base.latency_ms = (time.perf_counter() - started) * 1000
            return base
        base.answer = render_citation_handles(candidate, facts.sources)
        base.llm_polish = True
        base.latency_ms = (time.perf_counter() - started) * 1000
        return base


async def compose_fast_path_answer(
    *,
    envelope: Any,
    deterministic_answer: str,
    grounded: Any = None,
    checks: Sequence[Any] = (),
    runtime_inputs: Sequence[Any] = (),
    citations: Sequence[Any] = (),
    agent_config: Mapping[str, Any] | None = None,
    org_config: Mapping[str, Any] | None = None,
    message: str = "",
    mode: str = RENDER_MODE_ADAPTIVE,
    generate: Callable[..., Awaitable[Any]] | None = None,
    model: str = "",
    max_tokens: int = 400,
    temperature: float = 0.35,
    markdown_context: str = "",
) -> ComposedAnswerResult:
    """Pipeline de presentación sobre una decisión ya autoritativa.

    Nunca decide: si el LLM falla o inventa, devuelve la explicación
    determinista (`build_user_deterministic_explanation`). `markdown_context`
    es la proyección LLM-ready (secciones legibles) de la MISMA fuente: ayuda
    a explicar, jamás a decidir.
    """
    personality = personality_for_agent(
        agent_config, message=message, org_config=org_config
    )
    facts = build_response_facts(
        envelope,
        grounded=grounded,
        checks=checks,
        runtime_inputs=runtime_inputs,
        citations=citations,
        language=personality.language or "es",
    )
    composer = PersonalityAwareComposer(
        generate=generate,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    composed = await composer.compose(
        facts=facts,
        personality=personality,
        deterministic_answer=deterministic_answer,
        mode=mode,
        message=message,
        envelope=envelope,
        markdown_context=markdown_context,
    )
    if composed.fallback_used and not composed.answer.strip():
        # Fallback absoluto: explicación determinista natural.
        from src.runtime.fast_path import build_user_deterministic_explanation

        composed.answer = build_user_deterministic_explanation(
            envelope, grounded=grounded, checks=checks, runtime_inputs=runtime_inputs
        )
    return composed


__all__ = [
    "COMPOSER_SYSTEM_SAFETY",
    "CONSTRAINT_MUST_NOT_CHANGE_RESULT",
    "CONSTRAINT_MUST_NOT_INVENT_EVIDENCE",
    "CONSTRAINT_MUST_NOT_INVENT_PREMISES",
    "ComposedAnswerResult",
    "ComposedAnswerValidation",
    "ComposerPersonality",
    "DeterministicResponseFacts",
    "EXECUTION_MODE_FAST_PATH_POLISHED",
    "EXECUTION_MODE_FAST_PATH_STRICT",
    "PersonalityAwareComposer",
    "RENDER_MODE_ADAPTIVE",
    "RENDER_MODE_POLISH",
    "RENDER_MODE_STRICT",
    "RENDER_MODES",
    "RESPONSE_COMPOSER_VERSION",
    "ResponseSourceFact",
    "build_composer_prompt",
    "build_response_facts",
    "clean_composed_text",
    "compose_fast_path_answer",
    "personality_for_agent",
    "render_citation_handles",
    "render_mode_from_settings",
    "resolve_composer_model",
    "should_polish",
    "validate_composed_answer",
]
