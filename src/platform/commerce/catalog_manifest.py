# =============================================================================
# P20-03 — manifiesto comercial revisable del catálogo retail.
# =============================================================================
# No copia datos ni crea tablas: describe la entidad, sus campos, la autoridad
# de precio/stock y las reglas de presentación que el agente y Studio deben
# respetar. Es un contrato legible, versionado y testeable.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

CATALOG_MANIFEST_VERSION = "p20.retail-catalog/v1"


def retail_catalog_manifest(
    *,
    source_id: UUID | str | None = None,
    connector_id: UUID | str | None = None,
    workspace_id: UUID | str | None = None,
) -> dict[str, Any]:
    return {
        "version": CATALOG_MANIFEST_VERSION,
        "domain": "retail",
        "source": {
            "kind": "postgres",
            "resource": "bodega.product_catalog_v",
            "source_id": str(source_id) if source_id else None,
            "connector_id": str(connector_id) if connector_id else None,
            "workspace_id": str(workspace_id) if workspace_id else None,
            "mode": "live_read_only",
        },
        "entity": {
            "name": "product",
            "primary_key": "sku",
            "display_name": "name",
            "search_fields": ["sku", "name", "category", "unit"],
            "attributes": {
                "sku": {"type": "string", "required": True},
                "name": {"type": "string", "required": True},
                "category": {"type": "string"},
                "unit": {"type": "string", "required": True},
                "price": {"type": "decimal", "required": True},
                "currency": {"type": "string", "required": True},
                "available": {"type": "integer", "required": True},
            },
        },
        "authority": {
            "product": "bodega.products",
            "price": "bodega.product_catalog_v.price",
            "stock": "bodega.product_catalog_v.available",
            "cart": "zent.commerce_cart_sessions",
            "order": "zent.commerce_orders",
            "stock_mutations": "inventory_adapter",
        },
        "presentation": {
            "currency_format": "server_side",
            "price_precision": 2,
            "quantity_precision": 3,
            "unit_terms": {
                "kg": ["kilo", "kilogramo", "1 kg"],
                "saco": ["saco", "5 kg", "costal"],
                "unidad": ["unidad", "unidades"],
                "botella": ["botella", "litro", "1 l"],
            },
            "variant_rule": (
                "Resolver presentación por SKU y unidad; nunca sumar kg de "
                "presentaciones distintas sin convertir."
            ),
            "forbidden": [
                "precio inventado por el LLM",
                "stock estimado",
                "total calculado en el prompt",
                "leer pedidos de otra conversación",
            ],
        },
        "capabilities": {
            "read": [
                "catalog.products.search",
                "catalog.product.get",
                "catalog.product.price",
                "inventory.stock.get",
            ],
            "cart": [
                "sales.cart.get",
                "sales.cart.add",
                "sales.cart.set_quantity",
                "sales.cart.remove",
                "sales.cart.clear",
                "sales.cart.quote",
            ],
            "checkout": [
                "sales.order.create",
                "sales.order.mark_paid",
                "bodega.order.create",
                "bodega.stock.reserve_batch",
                "bodega.stock.commit_batch",
            ],
        },
        "review": {
            "owner": "retail-ops",
            "change_policy": "manifest_version_required",
            "requires_approval": True,
        },
    }


__all__ = ["CATALOG_MANIFEST_VERSION", "retail_catalog_manifest"]
