"""Unified Marketplace — applies_to, capabilities, events en productos;
readiness/health/last_used_at en instalaciones de producto.

Revision ID: 152
Revises: 151

Aditiva: solo columnas, índices y backfill. No renombra ni elimina nada.
- marketplace_products.applies_to: superficies de Zent donde el producto
  aporta funcionalidad (AGENTS, WORKFLOWS, KNOWLEDGE, ...). No es ownership.
- marketplace_products.capabilities/events: agregados de los assets técnicos
  (integration_capabilities / integration_manifests.events).
- marketplace_product_installations.readiness: vocabulario de instalación
  (READY, NEEDS_CONFIGURATION, NEEDS_CREDENTIALS, MISSING_DEPENDENCY,
  INCOMPATIBLE, DISABLED, ERROR). status se conserva para compatibilidad.
- health/last_used_at: estado vivo de la instalación para la biblioteca.
"""
from __future__ import annotations

from alembic import op

revision: str = "152"
down_revision: str = "151"
branch_labels = None
depends_on = None

_APPLIES_TO_BY_TYPE = """
    CASE product_type
        WHEN 'INTEGRATION' THEN CASE category
            WHEN 'government' THEN '["WORKFLOWS","DATA","KNOWLEDGE"]'::jsonb
            WHEN 'sales' THEN '["WORKFLOWS","AGENTS","ANALYTICS"]'::jsonb
            WHEN 'finance' THEN '["WORKFLOWS","AGENTS","PAYMENTS","ANALYTICS"]'::jsonb
            WHEN 'communication' THEN '["WORKFLOWS","AGENTS","CHANNELS"]'::jsonb
            WHEN 'commerce' THEN '["WORKFLOWS","AGENTS","PAYMENTS","ANALYTICS"]'::jsonb
            WHEN 'operations' THEN '["WORKFLOWS","AGENTS","AUTOMATIONS"]'::jsonb
            WHEN 'data' THEN '["WORKFLOWS","DATA","KNOWLEDGE","ANALYTICS"]'::jsonb
            WHEN 'productivity' THEN '["WORKFLOWS","AGENTS"]'::jsonb
            WHEN 'demo' THEN '["WORKFLOWS","AGENTS","DATA","KNOWLEDGE"]'::jsonb
            ELSE '["WORKFLOWS","AGENTS"]'::jsonb
        END
        WHEN 'WORKFLOW_TEMPLATE' THEN '["WORKFLOWS"]'::jsonb
        WHEN 'AGENT_TEMPLATE' THEN '["AGENTS"]'::jsonb
        WHEN 'INTELLIGENCE_PACK' THEN '["KNOWLEDGE","DATA"]'::jsonb
        WHEN 'SEMANTIC_PACK' THEN '["KNOWLEDGE","DATA"]'::jsonb
        WHEN 'BUSINESS_PACK' THEN '["WORKFLOWS","AGENTS"]'::jsonb
        WHEN 'COMPOSITE_PACK' THEN '["WORKFLOWS","AGENTS"]'::jsonb
        ELSE '[]'::jsonb
    END
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE marketplace_products ADD COLUMN IF NOT EXISTS applies_to "
        "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE marketplace_products ADD COLUMN IF NOT EXISTS capabilities "
        "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE marketplace_products ADD COLUMN IF NOT EXISTS events "
        "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_products_applies_to "
        "ON marketplace_products USING gin (applies_to)"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations ADD COLUMN IF NOT EXISTS health "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations ADD COLUMN IF NOT EXISTS readiness "
        "VARCHAR(30) NOT NULL DEFAULT 'installed'"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations ADD COLUMN IF NOT EXISTS last_used_at "
        "TIMESTAMPTZ"
    )
    # Dedupe de instalaciones sin workspace antes del índice único parcial
    # (UNIQUE org+ws+product no aplica cuando ws es NULL).
    op.execute(
        """
        DELETE FROM marketplace_product_installations a
        USING marketplace_product_installations b
        WHERE a.workspace_id IS NULL AND b.workspace_id IS NULL
          AND a.organization_id = b.organization_id
          AND a.product_id = b.product_id
          AND (a.created_at, a.id) < (b.created_at, b.id)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_market_installations_org_product_null_ws "
        "ON marketplace_product_installations (organization_id, product_id) "
        "WHERE workspace_id IS NULL"
    )
    # Backfill applies_to (solo vacíos; no pisa ediciones manuales).
    op.execute(
        "UPDATE marketplace_products SET applies_to = " + _APPLIES_TO_BY_TYPE  # noqa: S608
        + " WHERE applies_to = '[]'::jsonb"
    )
    # Backfill capabilities desde integration_capabilities (productos de integración).
    op.execute(
        """
        UPDATE marketplace_products p
        SET capabilities = sub.caps
        FROM (
            SELECT m.slug, jsonb_agg(DISTINCT c.slug) AS caps
            FROM integration_capabilities c
            JOIN integration_manifests m ON m.id = c.integration_id
            GROUP BY m.slug
        ) sub
        WHERE p.legacy_source = 'integration_manifest'
          AND p.legacy_ref = sub.slug
          AND p.capabilities = '[]'::jsonb
        """
    )
    # Backfill events desde integration_manifests.events.
    op.execute(
        """
        UPDATE marketplace_products p
        SET events = m.events
        FROM integration_manifests m
        WHERE p.legacy_source = 'integration_manifest'
          AND p.legacy_ref = m.slug
          AND p.events = '[]'::jsonb
          AND jsonb_typeof(m.events) = 'array'
          AND m.events <> '[]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_market_installations_org_product_null_ws"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations DROP COLUMN IF EXISTS last_used_at"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations DROP COLUMN IF EXISTS readiness"
    )
    op.execute(
        "ALTER TABLE marketplace_product_installations DROP COLUMN IF EXISTS health"
    )
    op.execute("DROP INDEX IF EXISTS idx_market_products_applies_to")
    op.execute("ALTER TABLE marketplace_products DROP COLUMN IF EXISTS events")
    op.execute("ALTER TABLE marketplace_products DROP COLUMN IF EXISTS capabilities")
    op.execute("ALTER TABLE marketplace_products DROP COLUMN IF EXISTS applies_to")
