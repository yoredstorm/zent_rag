# =============================================================================
# P19-04 — Contrato de intención de negocio y extracción de entidades.
#
# Decisión de alcance: no hay un clasificador global ni un orquestador nuevo.
# Este módulo implementa el motor genérico de reglas deterministas y el
# contrato tipado reutilizable por el nodo intent_route. Las rutas concretas,
# su vocabulario y sus extractores viven en un pack de vertical
# (src/verticals/p19_demo/intent_routes.py); el motor no conoce negocios.
# Un LLM futuro solo podrá proponer; la ruta y los permisos se validan contra
# el grafo y el plan autorizado.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INTENT_SCHEMA = "zent.workflow.intent.route/v1"
MAX_INPUT_CHARS = 2000
MAX_ENTITY_CHARS = 80


class IntentRoutePack(Protocol):
    """Política de rutas inyectada por un vertical; el motor solo la consume."""

    route_ids: tuple[str, ...]
    keywords: dict[str, tuple[str, ...]]
    injection_patterns: tuple[str, ...]
    ownership_risk_patterns: tuple[str, ...]
    identity_routes: frozenset[str]

    def default_routes(self) -> list[IntentRouteSpec]: ...

    def extract_entities(self, route_id: str, raw: str, normalized: str) -> dict[str, str]: ...

    def extra_missing_slots(self, route_id: str, entities: dict[str, str]) -> list[str]: ...


@lru_cache(maxsize=1)
def _default_pack() -> IntentRoutePack:
    """Pack demo usado cuando el workflow no declara rutas (compatibilidad P19)."""
    from src.verticals.p19_demo.intent_routes import build_pack

    return build_pack()


class IntentConfigError(ValueError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class IntentRouteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=300)
    entities: list[str] = Field(default_factory=list, max_length=10)
    examples: list[str] = Field(default_factory=list, max_length=20)
    negative_examples: list[str] = Field(default_factory=list, max_length=20)
    required_entities: list[str] = Field(default_factory=list, max_length=10)
    requires_identity_verification: bool = False

    @field_validator("entities", "required_entities")
    @classmethod
    def _entity_names(cls, value: list[str]) -> list[str]:
        for item in value:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,40}$", item):
                raise ValueError(f"entidad inválida: {item!r}")
        return value


class IntentRouteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    intent_schema: Literal["zent.workflow.intent.route/v1"] = Field(default=INTENT_SCHEMA, alias="schema")
    routes: list[IntentRouteSpec] = Field(min_length=1, max_length=10)
    confidence_min: float = Field(default=0.75, ge=0.0, le=1.0)
    ambiguity_policy: Literal["ask_clarification", "other"] = "ask_clarification"
    decision_source: Literal["rules"] = "rules"

    @field_validator("routes")
    @classmethod
    def _routes_unique(cls, value: list[IntentRouteSpec]) -> list[IntentRouteSpec]:
        ids = [route.id for route in value]
        if len(ids) != len(set(ids)):
            raise ValueError("rutas duplicadas")
        if "other" not in ids:
            raise ValueError("falta la ruta other")
        return value


class IntentResult(BaseModel):
    intent: str
    confidence: float
    entities: dict[str, str] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    route: str
    decision_source: str = "rules"
    reason_codes: list[str] = Field(default_factory=list)
    requires_identity_verification: bool = False


def default_routes() -> list[IntentRouteSpec]:
    """Rutas del pack por defecto; compatibilidad con workflows P19 sin config."""
    return _default_pack().default_routes()


def parse_intent_config(
    config: dict[str, Any] | None,
    pack: IntentRoutePack | None = None,
) -> IntentRouteConfig:
    active = pack or _default_pack()
    raw = dict(config or {})
    if not raw.get("routes"):
        raw["routes"] = [item.model_dump(mode="json") for item in active.default_routes()]
    raw.setdefault("schema", INTENT_SCHEMA)
    try:
        parsed = IntentRouteConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()[:5]
        )
        raise IntentConfigError(f"configuración de intención inválida: {details}") from exc
    unknown = sorted({route.id for route in parsed.routes} - set(active.route_ids))
    if unknown:
        raise IntentConfigError(f"ruta no permitida por el pack de intención: {', '.join(unknown)}")
    return parsed


def _normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", lowered.lower()).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)


def _close(token: str, keyword: str) -> bool:
    if token == keyword:
        return True
    if len(token) < 4 or len(keyword) < 4:
        return False
    return SequenceMatcher(None, token, keyword).ratio() >= 0.84


def _score_route(route: IntentRouteSpec, normalized: str, keywords: dict[str, tuple[str, ...]]) -> int:
    route_keywords = keywords.get(route.id, ())
    score = 0
    for token in _tokens(normalized):
        if any(_close(token, keyword) for keyword in route_keywords):
            score += 1
    for example in route.examples:
        for token in _tokens(_normalize(example)):
            if token in _tokens(normalized) and len(token) >= 4:
                score += 1
                break
    return score


def classify_intent(
    config: dict[str, Any] | None,
    text: str,
    pack: IntentRoutePack | None = None,
) -> IntentResult:
    """Clasificación determinista con rutas cerradas y entidades sanitizadas."""
    active = pack or _default_pack()
    parsed = parse_intent_config(config, active)
    raw = str(text or "")
    if len(raw) > MAX_INPUT_CHARS:
        return IntentResult(
            intent="other",
            confidence=0.0,
            route="other",
            reason_codes=["INPUT_TOO_LONG"],
        )
    normalized = _normalize(raw)
    if not normalized:
        return IntentResult(
            intent="other",
            confidence=0.0,
            route="other",
            reason_codes=["EMPTY_INPUT"],
        )
    if any(pattern in normalized for pattern in active.injection_patterns):
        return IntentResult(
            intent="other",
            confidence=0.0,
            route="other",
            reason_codes=["PROMPT_INJECTION_REJECTED"],
        )

    scores = {
        route.id: _score_route(route, normalized, active.keywords)
        for route in parsed.routes
        if route.id != "other"
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_id, top_score = ranked[0] if ranked else ("other", 0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    matched = [(route_id, score) for route_id, score in ranked if score > 0]

    if len(matched) > 1 and second_score >= max(1, top_score - 1):
        return IntentResult(
            intent="other",
            confidence=0.4,
            route="other",
            decision_source="rules",
            reason_codes=["MULTI_INTENT"],
            missing_slots=["clarification"],
        )

    if top_score <= 0:
        return IntentResult(
            intent="other",
            confidence=0.0,
            route="other",
            reason_codes=["LOW_CONFIDENCE", "UNKNOWN_INTENT"],
            missing_slots=["clarification"],
        )

    confidence = min(0.99, 0.55 + 0.25 * min(top_score, 3) / 3 + 0.2 * ((top_score - second_score) / top_score))
    route_spec = next(route for route in parsed.routes if route.id == top_id)
    if confidence < parsed.confidence_min:
        return IntentResult(
            intent="other",
            confidence=round(confidence, 2),
            route="other",
            reason_codes=["LOW_CONFIDENCE"],
            missing_slots=["clarification"],
        )

    entities = active.extract_entities(top_id, raw, normalized)
    missing_slots = [entity for entity in route_spec.required_entities if entity not in entities]
    for slot in active.extra_missing_slots(top_id, entities):
        if slot not in missing_slots:
            missing_slots.append(slot)
    requires_identity = route_spec.requires_identity_verification or top_id in active.identity_routes
    if missing_slots:
        return IntentResult(
            intent=top_id,
            confidence=round(confidence, 2),
            route=top_id,
            entities=entities,
            missing_slots=missing_slots,
            reason_codes=["MISSING_SLOT"],
            requires_identity_verification=requires_identity,
        )

    reason_codes = ["RULES_MATCH"]
    if any(pattern in normalized for pattern in active.ownership_risk_patterns):
        reason_codes.append("OWNERSHIP_NOT_VERIFIED")
        requires_identity = True
    return IntentResult(
        intent=top_id,
        confidence=round(confidence, 2),
        entities=entities,
        missing_slots=[],
        route=top_id,
        decision_source="rules",
        reason_codes=reason_codes,
        requires_identity_verification=requires_identity,
    )


__all__ = [
    "INTENT_SCHEMA",
    "IntentConfigError",
    "IntentResult",
    "IntentRouteConfig",
    "IntentRoutePack",
    "IntentRouteSpec",
    "classify_intent",
    "default_routes",
    "parse_intent_config",
]
