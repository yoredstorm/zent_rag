"""Corrige el backfill de superficies del contrato v2.

Revision ID: 160
Revises: 159

La migración 159 asignó `["INTEGRATIONS", "DATA"]` a TODO manifest público sin
superficies declaradas, sustituyendo el default por categoría
(`products.default_applies_to`) y sacando addons v1 como `demo-echo` de la vista
contextual de Workflows.

Regla correcta, ahora explícita en el código: solo un addon que DECLARA el
contrato v2 gobierna sus superficies (`integration_manifests.applies_to`); un
manifest v1 vuelve al default por categoría. Esta migración limpia el backfill
para que los datos digan lo mismo que el runtime.
"""
from __future__ import annotations

from alembic import op

revision: str = "160"
down_revision: str = "159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE integration_manifests
        SET applies_to = '[]'::jsonb
        WHERE organization_id IS NULL
          AND contract_version < 2
          AND applies_to = '["INTEGRATIONS", "DATA"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE integration_manifests
        SET applies_to = '["INTEGRATIONS", "DATA"]'::jsonb
        WHERE organization_id IS NULL
          AND contract_version < 2
          AND applies_to = '[]'::jsonb
        """
    )
