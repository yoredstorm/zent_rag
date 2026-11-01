# =============================================================================
# P19-04 — Contrato de intención de negocio y extracción de entidades.
#
# Decisión de alcance: no hay un clasificador global ni un orquestador nuevo.
# Este módulo implementa reglas deterministas y un contrato tipado reutilizable
# por el nodo intent_route. Un LLM futuro solo podrá proponer; la ruta y los
# permisos se validan contra el grafo y el plan autorizado.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INTENT_SCHEMA = "zent.workflow.intent.route/v1"
ALLOWED_ROUTES = ("price_lookup", "loyalty_balance", "order_status", "other")
MAX_INPUT_CHARS = 2000
MAX_ENTITY_CHARS = 80
_INJECTION_PATTERNS = (
    "ignora las reglas",
    "ignore the rules",
    "ignora las instrucciones",
    "ignore previous",
    "system prompt",
    "consulta todos los pedidos",
    "select *",
    "drop table",
    "union select",
    "bypass",
    "sql",
)
_OWNERSHIP_RISK = (
    "pedido de otra persona",
    "otra persona",
    "de otro cliente",
    "ajeno",
    "someone else",
)
_ROUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "price_lookup": (
        "precio",
        "precios",
        "cuesta",
        "cuestan",
        "costo",
        "vale",
        "valor",
        "price",
        "pricing",
        "soles",
        "pen",
        "moneda",
        "sku",
        "producto",
        "productos",
        "product",
        "disponible",
        "disponibilidad",
    ),
    "loyalty_balance": (
        "puntos",
        "punto",
        "saldo",
        "fidelidad",
        "loyalty",
        "points",
        "balance",
        "rewards",
        "canje",
        "nivel",
    ),
    "order_status": (
        "pedido",
        "pedidos",
        "orden",
        "ordenes",
        "estado",
        "seguimiento",
        "tracking",
        "order",
        "envio",
        "entrega",
        "cancelado",
        "despacho",
    ),
}
_PRODUCT_STOPWORDS = {
    "un",
    "una",
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "kilo",
    "kg",
    "precio",
    "cuesta",
    "cuanto",
    "cuánto",
    "vale",
    "producto",
    "por",
}


class IntentConfigError(ValueError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class IntentRouteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["price_lookup", "loyalty_balance", "order_status", "other"]
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
    return [
        IntentRouteSpec(
            id="price_lookup",
            description="Precio o disponibilidad de un producto",
            entities=["product_name", "sku"],
            required_entities=[],
            examples=["cuánto cuesta el arroz", "precio del SKU ARR-001"],
        ),
        IntentRouteSpec(
            id="loyalty_balance",
            description="Saldo o movimientos de puntos de fidelidad",
            entities=["customer_verified_ref"],
            requires_identity_verification=True,
            examples=["cuántos puntos tengo", "mi saldo de fidelidad"],
        ),
        IntentRouteSpec(
            id="order_status",
            description="Estado o seguimiento de un pedido",
            entities=["order_number"],
            required_entities=["order_number"],
            requires_identity_verification=True,
            examples=["en qué estado está mi pedido", "seguimiento de la orden"],
        ),
        IntentRouteSpec(
            id="other",
            description="Solicitud distinta o no identificada",
            entities=[],
        ),
    ]


def parse_intent_config(config: dict[str, Any] | None) -> IntentRouteConfig:
    raw = dict(config or {})
    if not raw.get("routes"):
        raw["routes"] = [item.model_dump(mode="json") for item in default_routes()]
    raw.setdefault("schema", INTENT_SCHEMA)
    try:
        return IntentRouteConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()[:5]
        )
        raise IntentConfigError(f"configuración de intención inválida: {details}") from exc


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


def _score_route(route: IntentRouteSpec, normalized: str) -> int:
    keywords = _ROUTE_KEYWORDS.get(route.id, ())
    score = 0
    for token in _tokens(normalized):
        if any(_close(token, keyword) for keyword in keywords):
            score += 1
    for example in route.examples:
        for token in _tokens(_normalize(example)):
            if token in _tokens(normalized) and len(token) >= 4:
                score += 1
                break
    return score


def _sanitize_entity(value: str | None) -> str | None:
    if not value:
        return None
    clean = re.sub(r"[\x00-\x1f<>{}]", " ", str(value))
    clean = re.sub(r"\s+", " ", clean).strip(" .,;:!?")
    if not clean:
        return None
    return clean[:MAX_ENTITY_CHARS]


def _extract_product(raw: str, normalized: str) -> str | None:
    sku = re.search(r"\b[A-Z]{2,6}-\d{2,6}\b", raw)
    if sku:
        return None  # el SKU va en su propio campo
    match = re.search(
        r"(?:precio|cuanto cuesta|cuánto cuesta|price of|precio de)\s+"
        r"(?:un|una|el|la|los|las|kilo de|kg de)?\s*([a-z0-9 ]{2,60})",
        normalized,
    )
    if not match:
        match = re.search(r"^([a-z0-9 ]{2,40}?)\s+a\s+\d", normalized)
    if not match:
        return None
    words = [word for word in match.group(1).split() if word not in _PRODUCT_STOPWORDS]
    return _sanitize_entity(" ".join(words) or None)


def _extract_order(raw: str) -> str | None:
    match = re.search(
        r"(?:pedido|orden|order)\s*(?:nro|numero|número|#|:)?\s*([A-Za-z0-9-]{4,24})",
        raw,
        re.IGNORECASE,
    )
    if match:
        return _sanitize_entity(match.group(1).upper())
    match = re.search(r"#([A-Za-z0-9-]{4,24})", raw)
    if match:
        return _sanitize_entity(match.group(1).upper())
    if re.search(r"\b(pedido|orden|order)\b", _normalize(raw)):
        numeric = re.search(r"\b\d{4,12}\b", raw)
        if numeric:
            return _sanitize_entity(numeric.group(0))
    return None


def classify_intent(
    config: dict[str, Any] | None,
    text: str,
) -> IntentResult:
    """Clasificación determinista con rutas cerradas y entidades sanitizadas."""
    parsed = parse_intent_config(config)
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
    if any(pattern in normalized for pattern in _INJECTION_PATTERNS):
        return IntentResult(
            intent="other",
            confidence=0.0,
            route="other",
            reason_codes=["PROMPT_INJECTION_REJECTED"],
        )

    scores = {route.id: _score_route(route, normalized) for route in parsed.routes if route.id != "other"}
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

    entities: dict[str, str] = {}
    if top_id == "price_lookup":
        sku = re.search(r"\b[A-Z]{2,6}-\d{2,6}\b", raw)
        if sku:
            entities["sku"] = sku.group(0)
        product = _extract_product(raw, normalized)
        if product:
            entities["product_name"] = product
        if not entities:
            return IntentResult(
                intent=top_id,
                confidence=round(confidence, 2),
                route=top_id,
                entities={},
                missing_slots=["product_name"],
                reason_codes=["MISSING_SLOT"],
                requires_identity_verification=route_spec.requires_identity_verification,
            )
    if top_id == "order_status":
        order_number = _extract_order(raw)
        if order_number:
            entities["order_number"] = order_number
        else:
            return IntentResult(
                intent=top_id,
                confidence=round(confidence, 2),
                route=top_id,
                entities={},
                missing_slots=["order_number"],
                reason_codes=["MISSING_SLOT"],
                requires_identity_verification=True,
            )

    reason_codes = ["RULES_MATCH"]
    requires_identity = route_spec.requires_identity_verification or top_id in (
        "loyalty_balance",
        "order_status",
    )
    if any(pattern in normalized for pattern in _OWNERSHIP_RISK):
        reason_codes.append("OWNERSHIP_NOT_VERIFIED")
        requires_identity = True
    return IntentResult(
        intent=top_id,
        confidence=round(confidence, 2),
        entities=entities,
        missing_slots=[entity for entity in route_spec.required_entities if entity not in entities],
        route=top_id,
        decision_source="rules",
        reason_codes=reason_codes,
        requires_identity_verification=requires_identity,
    )


__all__ = [
    "ALLOWED_ROUTES",
    "INTENT_SCHEMA",
    "IntentConfigError",
    "IntentResult",
    "IntentRouteConfig",
    "IntentRouteSpec",
    "classify_intent",
    "default_routes",
    "parse_intent_config",
]
