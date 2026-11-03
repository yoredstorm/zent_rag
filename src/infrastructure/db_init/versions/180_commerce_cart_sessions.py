"""P20-10 - carrito temporal por sesión con TTL configurable.

Revision ID: 180
Revises: 179

Aditiva. Persiste el carrito conversacional en tablas temporales del tenant:
sesión, líneas y ledger de idempotencia. No crea un motor paralelo: las
capacidades siguen siendo `sales.cart.*` y `execute_binding` sigue siendo el
único ejecutor.

La purga es perezosa (al acceder) y también corre en un loop periódico de la
API. El `expires_at` se refresca en cada mutación (TTL deslizante).
"""
from __future__ import annotations

from alembic import op

revision: str = "180"
down_revision: str = "179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_cart_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            cart_key VARCHAR(200) NOT NULL,
            conversation_id UUID,
            workflow_instance_id UUID,
            user_id UUID,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            currency CHAR(3) NOT NULL DEFAULT 'PEN',
            revision INTEGER NOT NULL DEFAULT 1,
            ttl_seconds INTEGER NOT NULL DEFAULT 3600,
            expires_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_sessions_key "
        "ON commerce_cart_sessions (organization_id, "
        "COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), "
        "cart_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_commerce_cart_sessions_expiry "
        "ON commerce_cart_sessions(expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_commerce_cart_sessions_conversation "
        "ON commerce_cart_sessions(organization_id, conversation_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_cart_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            cart_id UUID NOT NULL REFERENCES commerce_cart_sessions(id) ON DELETE CASCADE,
            product_id UUID,
            source_id UUID,
            sku VARCHAR(80) NOT NULL,
            name VARCHAR(240) NOT NULL,
            unit VARCHAR(24) NOT NULL DEFAULT 'UNIT',
            quantity NUMERIC(16,3) NOT NULL,
            unit_price NUMERIC(14,4) NOT NULL DEFAULT 0,
            currency CHAR(3) NOT NULL DEFAULT 'PEN',
            price_source VARCHAR(80) NOT NULL DEFAULT 'commerce',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_items_line "
        "ON commerce_cart_items (cart_id, "
        "COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid), sku)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_commerce_cart_items_cart "
        "ON commerce_cart_items(cart_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_cart_operations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cart_id UUID NOT NULL REFERENCES commerce_cart_sessions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL,
            operation VARCHAR(24) NOT NULL,
            result JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_operations "
        "ON commerce_cart_operations(cart_id, idempotency_key)"
    )
    for ref, name, description, read_only in (
        (
            "sales.cart.get",
            "Consultar carrito",
            "Carrito temporal de la sesión con TTL.",
            True,
        ),
        (
            "sales.cart.add",
            "Agregar al carrito",
            "Agrega una línea con precio resuelto por el backend.",
            False,
        ),
        (
            "sales.cart.set_quantity",
            "Cambiar cantidad",
            "Fija la cantidad de una línea existente.",
            False,
        ),
        (
            "sales.cart.remove",
            "Quitar del carrito",
            "Elimina una línea del carrito.",
            False,
        ),
        (
            "sales.cart.clear",
            "Vaciar carrito",
            "Borra todas las líneas sin cerrar la sesión.",
            False,
        ),
    ):
        op.execute(
            f"""
            INSERT INTO workflow_capability_contracts
                (capability_ref, name, description, provider_kinds,
                 input_schema, output_schema, read_only, financial,
                 idempotency_required)
            VALUES (
                '{ref}', '{name}', '{description}',
                '["commerce", "managed_db", "connected_db", "rest_api",
                  "marketplace_action"]'::jsonb,
                '{{}}'::jsonb, '{{}}'::jsonb, {str(read_only).lower()},
                false, false
            )
            ON CONFLICT (capability_ref) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                provider_kinds = EXCLUDED.provider_kinds,
                read_only = EXCLUDED.read_only,
                financial = EXCLUDED.financial,
                idempotency_required = EXCLUDED.idempotency_required
            """
        )


def downgrade() -> None:
    for table in (
        "commerce_cart_operations",
        "commerce_cart_items",
        "commerce_cart_sessions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for ref in (
        "sales.cart.clear",
        "sales.cart.remove",
        "sales.cart.set_quantity",
        "sales.cart.add",
        "sales.cart.get",
    ):
        op.execute(
            f"DELETE FROM workflow_capability_contracts "
            f"WHERE capability_ref = '{ref}'"
        )
