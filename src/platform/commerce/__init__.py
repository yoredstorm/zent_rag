# =============================================================================
# Commerce — datos de negocio del tenant (catálogo, inventario, ventas, pagos)
# =============================================================================
# Un workflow portable depende de CAPACIDADES (catalog.products.search,
# inventory.stock.get, sales.order.create, payments.checkout.create). Este
# paquete implementa esas capacidades como un `provider_kind` más del binder
# (`commerce` / `payment_provider`), igual que `managed_db`, `semantic_query`
# o `marketplace_action`. No hay workflow paralelo ni runtime paralelo: el
# scheduler sigue siendo `execute_graph` y el ejecutor sigue siendo
# `execute_binding`.
#
# Regla de autoridad:
#   LLM interpreta. CAPACIDAD decide datos reales.
#   precio, stock, monto, pago y estado de orden salen de aquí, nunca del LLM.
# =============================================================================
from __future__ import annotations

from src.platform.commerce.capabilities import (
    COMMERCE_PROVIDER_KIND,
    PAYMENT_PROVIDER_KIND,
    execute_commerce_capability,
    execute_payment_capability,
)

__all__ = [
    "COMMERCE_PROVIDER_KIND",
    "PAYMENT_PROVIDER_KIND",
    "execute_commerce_capability",
    "execute_payment_capability",
]
