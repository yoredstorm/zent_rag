"""Commerce + Retail Sales Funnel — datos de negocio, pagos y plantilla oficial.

Revision ID: 158
Revises: 157

Aditiva. Crea las tablas de negocio del tenant (catálogo, stock, órdenes,
reservas, checkouts, proveedores de pago y eventos de proveedor), registra las
capacidades y eventos del contrato de pagos, y publica la plantilla
`retail_sales_funnel` en el catálogo global con su producto de marketplace.

Sin sistemas paralelos: los ejecutores siguen siendo `execute_binding` +
`execute_action`; esta migración solo añade datos y contratos.

La migración NO importa `src.platform` (infrastructure no conoce capas
superiores): lee el snapshot congelado
`db_init/seeds/retail_sales_funnel.json`, generado desde la definición viva con
`python -m src.infrastructure.db_init.seeds.sales_funnel_snapshot --write`.
Un test de certificación falla si el snapshot se desvía de la definición viva.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic import op
from sqlalchemy import text

revision: str = "158"
down_revision: str = "157"
branch_labels = None
depends_on = None

_SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "retail_sales_funnel.json"

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS commerce_products (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        sku VARCHAR(64) NOT NULL,
        name VARCHAR(240) NOT NULL,
        description TEXT,
        aliases JSONB NOT NULL DEFAULT '[]',
        category VARCHAR(80),
        unit VARCHAR(16) NOT NULL DEFAULT 'UNIT',
        price NUMERIC(14,4) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        tax_rate NUMERIC(6,4) NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_products_sku "
    "ON commerce_products(organization_id, sku)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_products_org "
    "ON commerce_products(organization_id, active)",
    """
    CREATE TABLE IF NOT EXISTS commerce_stock (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        product_id UUID NOT NULL REFERENCES commerce_products(id) ON DELETE CASCADE,
        warehouse VARCHAR(60) NOT NULL DEFAULT 'main',
        available NUMERIC(16,3) NOT NULL DEFAULT 0,
        reserved NUMERIC(16,3) NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_stock "
    "ON commerce_stock(organization_id, product_id, warehouse)",
    """
    CREATE TABLE IF NOT EXISTS commerce_orders (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        order_number VARCHAR(40) NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
        customer JSONB NOT NULL DEFAULT '{}',
        cart JSONB NOT NULL DEFAULT '{}',
        subtotal NUMERIC(16,2) NOT NULL DEFAULT 0,
        total NUMERIC(16,2) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        workflow_id UUID,
        workflow_instance_id UUID,
        conversation_id UUID,
        business_operation_id VARCHAR(160),
        payment_reference VARCHAR(160),
        payment_provider VARCHAR(40),
        payment_status VARCHAR(24),
        reservation_id UUID,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        paid_at TIMESTAMPTZ,
        fulfilled_at TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_orders_number "
    "ON commerce_orders(organization_id, order_number)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_orders_operation "
    "ON commerce_orders(organization_id, business_operation_id) "
    "WHERE business_operation_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_org "
    "ON commerce_orders(organization_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_instance ON commerce_orders(workflow_instance_id)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_reference ON commerce_orders(payment_reference)",
    """
    CREATE TABLE IF NOT EXISTS commerce_order_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID NOT NULL REFERENCES commerce_orders(id) ON DELETE CASCADE,
        product_id UUID,
        sku VARCHAR(64),
        name VARCHAR(240),
        quantity NUMERIC(16,3) NOT NULL,
        unit VARCHAR(16) NOT NULL DEFAULT 'UNIT',
        unit_price NUMERIC(14,4) NOT NULL DEFAULT 0,
        line_total NUMERIC(16,2) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commerce_order_items_order ON commerce_order_items(order_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_reservations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID,
        product_id UUID NOT NULL,
        warehouse VARCHAR(60) NOT NULL DEFAULT 'main',
        quantity NUMERIC(16,3) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'held',
        workflow_instance_id UUID,
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commerce_reservations_order ON commerce_reservations(order_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_checkout_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID NOT NULL,
        provider VARCHAR(40) NOT NULL,
        provider_reference VARCHAR(200),
        reference VARCHAR(160) NOT NULL,
        idempotency_key VARCHAR(120) NOT NULL,
        amount NUMERIC(16,2) NOT NULL,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        checkout_url TEXT,
        qr_payload TEXT,
        qr_image_url TEXT,
        expires_at TIMESTAMPTZ,
        workflow_instance_id UUID,
        node_id VARCHAR(80),
        raw JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_idem "
    "ON commerce_checkout_sessions(organization_id, idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_reference "
    "ON commerce_checkout_sessions(organization_id, reference)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_provider_ref "
    "ON commerce_checkout_sessions(provider, provider_reference) "
    "WHERE provider_reference IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS commerce_payment_providers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        provider VARCHAR(40) NOT NULL,
        display_name VARCHAR(120),
        status VARCHAR(20) NOT NULL DEFAULT 'connected',
        mode VARCHAR(16) NOT NULL DEFAULT 'test',
        sandbox BOOLEAN NOT NULL DEFAULT FALSE,
        credential_ref UUID,
        config JSONB NOT NULL DEFAULT '{}',
        capabilities JSONB NOT NULL DEFAULT '[]',
        events JSONB NOT NULL DEFAULT '[]',
        health JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_payment_providers "
    "ON commerce_payment_providers(organization_id, provider)",
    """
    CREATE TABLE IF NOT EXISTS commerce_provider_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        provider VARCHAR(40) NOT NULL,
        provider_event_id VARCHAR(200) NOT NULL,
        event_type VARCHAR(120) NOT NULL,
        organization_id UUID,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        verified BOOLEAN NOT NULL DEFAULT FALSE,
        normalized_event JSONB NOT NULL DEFAULT '{}',
        correlation JSONB NOT NULL DEFAULT '{}',
        processing_status VARCHAR(24) NOT NULL DEFAULT 'received',
        processing_error TEXT,
        signature_mode VARCHAR(40),
        replay_guard_at TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_provider_events "
    "ON commerce_provider_events(provider, provider_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_provider_events_org "
    "ON commerce_provider_events(organization_id, received_at DESC)",
)

_CONTRACTS_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workflow_capability_contracts (
        capability_ref VARCHAR(120) PRIMARY KEY,
        name VARCHAR(160) NOT NULL,
        description TEXT,
        provider_kinds JSONB NOT NULL DEFAULT '[]',
        input_schema JSONB NOT NULL DEFAULT '{}',
        output_schema JSONB NOT NULL DEFAULT '{}',
        read_only BOOLEAN NOT NULL DEFAULT TRUE,
        financial BOOLEAN NOT NULL DEFAULT FALSE,
        idempotency_required BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_event_contracts (
        event_type VARCHAR(120) PRIMARY KEY,
        description TEXT,
        source VARCHAR(40) NOT NULL DEFAULT 'platform',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
)


def load_seed(path: Path | None = None) -> dict[str, Any]:
    """Snapshot congelado del embudo (sin tocar la capa platform)."""
    return json.loads((path or _SEED_PATH).read_text(encoding="utf-8"))


def capability_contract_statements(seed: dict[str, Any] | None = None) -> list[Any]:
    data = seed or load_seed()
    statements: list[Any] = []
    for row in data.get("capability_contracts") or []:
        statements.append(
            text(
                """
                INSERT INTO workflow_capability_contracts
                    (capability_ref, name, description, provider_kinds, input_schema,
                     output_schema, read_only, financial, idempotency_required)
                VALUES (:ref, :name, :descr, CAST(:kinds AS jsonb), CAST(:inp AS jsonb),
                        CAST(:out AS jsonb), :ro, :fin, :idem)
                ON CONFLICT (capability_ref) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    provider_kinds = EXCLUDED.provider_kinds,
                    input_schema = EXCLUDED.input_schema,
                    output_schema = EXCLUDED.output_schema,
                    read_only = EXCLUDED.read_only,
                    financial = EXCLUDED.financial,
                    idempotency_required = EXCLUDED.idempotency_required
                """
            ).bindparams(
                ref=row["ref"],
                name=row["name"],
                descr=row.get("description"),
                kinds=json.dumps(row.get("provider_kinds") or []),
                inp=json.dumps(row.get("input_schema") or {}),
                out=json.dumps(row.get("output_schema") or {}),
                ro=bool(row.get("read_only", True)),
                fin=bool(row.get("financial", False)),
                idem=bool(row.get("idempotency_required", False)),
            )
        )
    return statements


def event_contract_statements(seed: dict[str, Any] | None = None) -> list[Any]:
    data = seed or load_seed()
    return [
        text(
            """
            INSERT INTO workflow_event_contracts (event_type, description, source)
            VALUES (:et, :descr, 'commerce')
            ON CONFLICT (event_type) DO UPDATE SET
                description = EXCLUDED.description,
                source = EXCLUDED.source
            """
        ).bindparams(et=row["event_type"], descr=row.get("description"))
        for row in data.get("events") or []
    ]


def messaging_statements() -> list[Any]:
    """Addon incorporado de mensajería (resuelve `conversation.send`)."""
    manifest = text(
        """
        INSERT INTO integration_manifests
            (slug, name, provider, version, description, category, auth_modes, countries,
             pricing, status, events, organization_id)
        VALUES (
            'zent-messaging', 'Mensajería Zent', 'Zent', 1,
            'Canal de conversación incorporado (in-app, email y webhook).',
            'communication', '["NONE"]', '[]'::jsonb, '{"model": "FREE"}'::jsonb,
            'PUBLISHED', '["conversation.message"]'::jsonb, NULL
        )
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            events = EXCLUDED.events
        """
    )
    capability = text(
        """
        INSERT INTO integration_capabilities (integration_id, slug, name, description)
        SELECT id, 'conversation.send', 'Enviar mensaje',
               'Envía un mensaje al cliente del proceso por el canal conectado.'
        FROM integration_manifests WHERE slug = 'zent-messaging'
        ON CONFLICT (integration_id, slug) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description
        """
    )
    return [manifest, capability]


def template_statements(seed: dict[str, Any] | None = None) -> list[Any]:
    """Sentencias de la plantilla (las ejecuta la migración o el re-seed)."""
    row = (seed or load_seed()).get("template") or {}
    return [
        text(
            """
            INSERT INTO workflow_templates
                (slug, name, description, category, trigger_type, steps, trigger_config, package, graph)
            VALUES (
                :slug, :name, :descr, :cat, :trigger,
                '[]'::jsonb, CAST(:tcfg AS jsonb), CAST(:pkg AS jsonb), CAST(:graph AS jsonb)
            )
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                trigger_type = EXCLUDED.trigger_type,
                trigger_config = EXCLUDED.trigger_config,
                package = EXCLUDED.package,
                graph = EXCLUDED.graph
            """
        ).bindparams(
            slug=row["slug"],
            name=row["name"],
            descr=row.get("description"),
            cat=row.get("category") or "ventas",
            trigger=row.get("trigger_type") or "event",
            tcfg=json.dumps(row.get("trigger_config") or {}, ensure_ascii=False),
            pkg=json.dumps(row.get("package") or {}, ensure_ascii=False),
            graph=json.dumps(row.get("graph") or {}, ensure_ascii=False),
        )
    ]


def product_statements(seed: dict[str, Any] | None = None) -> list[Any]:
    """Sentencias del producto de marketplace del embudo."""
    row = (seed or load_seed()).get("product") or {}
    return [
        text(
            """
            INSERT INTO marketplace_products
                (slug, name, short_description, long_description, product_type, version,
                 status, category, applies_to, capabilities, events, included_assets,
                 pricing, entitlements, configuration_schema, security, privacy,
                 certification, featured, tags)
            VALUES (
                :slug, :name, :short, :long, 'WORKFLOW_TEMPLATE', :version,
                :status, :category, CAST(:applies AS jsonb), CAST(:caps AS jsonb),
                CAST(:events AS jsonb), CAST(:assets AS jsonb), CAST(:pricing AS jsonb),
                CAST(:entitlements AS jsonb), CAST(:config AS jsonb), CAST(:security AS jsonb),
                CAST(:privacy AS jsonb), CAST(:certification AS jsonb), CAST(:featured AS jsonb),
                CAST(:tags AS jsonb)
            )
            ON CONFLICT (slug) DO UPDATE SET
                version = EXCLUDED.version,
                name = EXCLUDED.name,
                short_description = EXCLUDED.short_description,
                long_description = EXCLUDED.long_description,
                category = EXCLUDED.category,
                applies_to = EXCLUDED.applies_to,
                capabilities = EXCLUDED.capabilities,
                events = EXCLUDED.events,
                included_assets = EXCLUDED.included_assets,
                pricing = EXCLUDED.pricing,
                configuration_schema = EXCLUDED.configuration_schema,
                tags = EXCLUDED.tags,
                updated_at = NOW()
            """
        ).bindparams(
            slug=row["slug"],
            name=row["name"],
            short=row.get("short_description"),
            long=row.get("long_description"),
            version=int(row.get("version") or 1),
            status=row.get("status") or "PUBLISHED",
            category=row.get("category") or "sales",
            applies=json.dumps(row.get("applies_to") or [], ensure_ascii=False),
            caps=json.dumps(row.get("capabilities") or [], ensure_ascii=False),
            events=json.dumps(row.get("events") or [], ensure_ascii=False),
            assets=json.dumps(row.get("included_assets") or [], ensure_ascii=False),
            pricing=json.dumps(row.get("pricing") or {}, ensure_ascii=False),
            entitlements=json.dumps(row.get("entitlements") or {}, ensure_ascii=False),
            config=json.dumps(row.get("configuration_schema") or {}, ensure_ascii=False),
            security=json.dumps(row.get("security") or {}, ensure_ascii=False),
            privacy=json.dumps(row.get("privacy") or {}, ensure_ascii=False),
            certification=json.dumps(row.get("certification") or {}, ensure_ascii=False),
            featured=json.dumps(row.get("featured") or {}, ensure_ascii=False),
            tags=json.dumps(row.get("tags") or [], ensure_ascii=False),
        )
    ]


def seed_statements() -> list[Any]:
    """Todo lo que publica el embudo (contratos + addon + plantilla + producto)."""
    seed = load_seed()
    return [
        *capability_contract_statements(seed),
        *event_contract_statements(seed),
        *messaging_statements(),
        *template_statements(seed),
        *product_statements(seed),
    ]


def upgrade() -> None:
    for ddl in _DDL:
        op.execute(ddl)
    for ddl in _CONTRACTS_DDL:
        op.execute(ddl)
    for statement in seed_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DELETE FROM marketplace_products WHERE slug = 'retail-sales-funnel'")
    op.execute("DELETE FROM workflow_templates WHERE slug = 'retail_sales_funnel'")
    op.execute("DROP TABLE IF EXISTS workflow_event_contracts")
    op.execute("DROP TABLE IF EXISTS workflow_capability_contracts")
    for table in (
        "commerce_provider_events",
        "commerce_payment_providers",
        "commerce_checkout_sessions",
        "commerce_reservations",
        "commerce_order_items",
        "commerce_orders",
        "commerce_stock",
        "commerce_products",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
