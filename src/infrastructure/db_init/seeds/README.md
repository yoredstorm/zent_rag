"""Snapshot congelado del seed del embudo de ventas (solo datos).

La migración 158 no puede importar `src.platform` (invariante de arquitectura:
infrastructure no conoce capas superiores), así que lee este JSON. La definición
VIVA está en `src/platform/commerce/sales_funnel.py::snapshot_payload` y el JSON
se regenera con:

    python scripts/seed_sales_funnel.py

Un test de certificación falla si el JSON se desvía de la definición viva.
"""
