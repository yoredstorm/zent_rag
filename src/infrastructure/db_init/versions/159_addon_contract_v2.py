"""Addon Contract v2 — contrato completo del addon persistido y proyectado.

Revision ID: 159
Revises: 158

Aditiva. `integration_manifests` gana el bloque `contract` (identidad,
superficies, capacidades con esquemas, eventos con webhook, credenciales por
NOMBRE, riesgo, permisos, aprobación, idempotencia, rate limits, coste, health
check, sandbox, compatibilidad y documentación) más `contract_version` y
`applies_to` para que la proyección al catálogo global no adivine superficies.

Nunca se guardan valores secretos: solo nombres de credenciales; los valores
viven en el SecretStore.
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision: str = "159"
down_revision: str = "158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE integration_manifests "
        "ADD COLUMN IF NOT EXISTS contract JSONB NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE integration_manifests "
        "ADD COLUMN IF NOT EXISTS contract_version INT NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE integration_manifests "
        "ADD COLUMN IF NOT EXISTS applies_to JSONB NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_integration_manifests_surfaces "
        "ON integration_manifests USING GIN (applies_to)"
    )
    # Addon incorporado de mensajería: contrato v2 explícito (superficies y
    # credenciales ninguna: Zent lo provee).
    op.execute(
        text(
            "UPDATE integration_manifests SET contract_version = 2, "
            "applies_to = CAST(:applies AS jsonb), contract = CAST(:contract AS jsonb) "
            "WHERE slug = 'zent-messaging'"
        ).bindparams(
            applies=json.dumps(["WORKFLOWS", "AGENTS", "CHANNELS"]),
            contract=json.dumps(
                {
                    "contract_version": 2,
                    "applies_to": ["WORKFLOWS", "AGENTS", "CHANNELS"],
                    "credentials": [],
                    "risk": "info",
                    "idempotency": {"support": True, "scope": "operation"},
                    "capabilities": [
                        {
                            "ref": "conversation.send",
                            "risk_level": "normal",
                            "requires_approval": False,
                            "idempotency_support": True,
                            "idempotency_scope": "operation",
                        }
                    ],
                    "events": [{"ref": "conversation.message", "delivery_mode": "internal"}],
                }
            ),
        )
    )
    # Los manifiestos publicados sin contrato declarado se quedan en v1 (1) y su
    # proyección sigue usando las superficies por defecto del producto.
    op.execute(
        "UPDATE integration_manifests SET applies_to = "
        "'[\"INTEGRATIONS\", \"DATA\"]'::jsonb "
        "WHERE applies_to = '[]'::jsonb AND organization_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_integration_manifests_surfaces")
    op.execute("ALTER TABLE integration_manifests DROP COLUMN IF EXISTS applies_to")
    op.execute("ALTER TABLE integration_manifests DROP COLUMN IF EXISTS contract_version")
    op.execute("ALTER TABLE integration_manifests DROP COLUMN IF EXISTS contract")
