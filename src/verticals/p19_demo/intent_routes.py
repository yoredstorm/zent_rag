# =============================================================================
# Pack de intención demo P19 — vocabulario y extractores de comercio.
#
# Este pack es un ejemplo de vertical: el motor genérico
# (src/platform/workflows/intent_route.py) no contiene rutas, palabras ni
# extractores de negocio. P19.1-06 sustituirá este default por rutas
# configurables por workflow; hasta entonces se usa como compatibilidad.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.platform.workflows.intent_route import MAX_ENTITY_CHARS, IntentRouteSpec

ROUTE_IDS = ("price_lookup", "loyalty_balance", "order_status", "other")

INJECTION_PATTERNS = (
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

OWNERSHIP_RISK_PATTERNS = (
    "pedido de otra persona",
    "otra persona",
    "de otro cliente",
    "ajeno",
    "someone else",
)

ROUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
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
        "stock",
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
    "en",
    "soles",
    "pen",
}


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
        r"(?:precio|cuanto cuesta|cuánto cuesta|price of|precio de|"
        r"costo de|cuanto vale|cuánto vale|vale)\s+"
        r"(?:un|una|el|la|los|las|kilo de|kg de)?\s*([a-z0-9 ]{2,60})",
        normalized,
    )
    if not match:
        match = re.search(r"^([a-z0-9 ]{2,40}?)\s+a\s+\d", normalized)
    if not match:
        return None
    words = [word for word in match.group(1).split() if word not in _PRODUCT_STOPWORDS]
    return _sanitize_entity(" ".join(words) or None)


def _extract_order(raw: str, normalized: str) -> str | None:
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
    if re.search(r"\b(pedido|orden|order)\b", normalized):
        numeric = re.search(r"\b\d{4,12}\b", raw)
        if numeric:
            return _sanitize_entity(numeric.group(0))
    return None


@dataclass(frozen=True)
class DemoIntentRoutes:
    route_ids: tuple[str, ...] = ROUTE_IDS
    keywords: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(ROUTE_KEYWORDS))
    injection_patterns: tuple[str, ...] = INJECTION_PATTERNS
    ownership_risk_patterns: tuple[str, ...] = OWNERSHIP_RISK_PATTERNS
    identity_routes: frozenset[str] = frozenset({"loyalty_balance", "order_status"})

    def default_routes(self) -> list[IntentRouteSpec]:
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
                examples=["dónde está mi pedido", "seguimiento de la orden"],
            ),
            IntentRouteSpec(
                id="other",
                description="Solicitud distinta o no identificada",
                entities=[],
            ),
        ]

    def extract_entities(self, route_id: str, raw: str, normalized: str) -> dict[str, str]:
        entities: dict[str, str] = {}
        if route_id == "price_lookup":
            sku = re.search(r"\b[A-Z]{2,6}-\d{2,6}\b", raw)
            if sku:
                entities["sku"] = sku.group(0)
            product = _extract_product(raw, normalized)
            if product:
                entities["product_name"] = product
        elif route_id == "order_status":
            order_number = _extract_order(raw, normalized)
            if order_number:
                entities["order_number"] = order_number
        return entities

    def extra_missing_slots(self, route_id: str, entities: dict[str, str]) -> list[str]:
        if route_id == "price_lookup" and not entities:
            return ["product_name"]
        return []


def build_pack() -> DemoIntentRoutes:
    return DemoIntentRoutes()


def default_routes() -> list[IntentRouteSpec]:
    return build_pack().default_routes()


__all__ = ["DemoIntentRoutes", "build_pack", "default_routes"]
