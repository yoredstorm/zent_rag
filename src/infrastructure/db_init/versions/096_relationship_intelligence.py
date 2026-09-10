"""Phase 33C — Relationship Intelligence & Knowledge Graph.

Extiende catalog_relationships con provenance explícita
(OBSERVED/INFERRED/APPROVED/REJECTED), confianza numérica, cardinalidad,
evidencia detallada y trazabilidad del aprendizaje. Backfill de filas
existentes sin cambiar su semántica (FK física = OBSERVED, inferida =
INFERRED, confirmada por humano = APPROVED, rechazada = REJECTED).

Crea knowledge_business_rules (reglas de negocio gobernadas; materializadas
desde sugerencias aprobadas, nunca auto-aprobadas).

Revision ID: 096
Revises: 095
"""
from __future__ import annotations

from alembic import op

revision: str = "096"
down_revision: str = "095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------- relationship intelligence
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED'"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS semantic_similarity DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS cardinality VARCHAR(10)"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS evidence_detail JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS last_learned_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD COLUMN IF NOT EXISTS learned_run_id UUID"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "DROP CONSTRAINT IF EXISTS catalog_relationships_provenance_check"
    )
    op.execute(
        "ALTER TABLE catalog_relationships "
        "ADD CONSTRAINT catalog_relationships_provenance_check "
        "CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_relationships_org_provenance "
        "ON catalog_relationships(organization_id, provenance)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_relationships_org_status_prov "
        "ON catalog_relationships(organization_id, status, provenance)"
    )
    # Backfill: la clasificación previa se conserva; nunca se promueve a APPROVED
    # una relación solo por existir (solo confirmaciones humanas previas).
    op.execute(
        """
        UPDATE catalog_relationships SET
            provenance = CASE
                WHEN status = 'rejected' THEN 'REJECTED'
                WHEN relation_type = 'foreign_key' THEN 'OBSERVED'
                WHEN status = 'confirmed' THEN 'APPROVED'
                ELSE 'INFERRED'
            END,
            confidence_score = CASE confidence
                WHEN 'high' THEN 0.90
                WHEN 'medium' THEN 0.65
                ELSE 0.40
            END,
            last_learned_at = COALESCE(last_learned_at, created_at)
        WHERE confidence_score = 0 OR last_learned_at IS NULL
        """
    )

    # -------------------------------------------------- business rules
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_business_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            rule_key VARCHAR(200) NOT NULL,
            name VARCHAR(200) NOT NULL,
            definition TEXT NOT NULL,
            applies_to JSONB NOT NULL DEFAULT '[]'::jsonb,
            provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED')),
            confidence VARCHAR(10) NOT NULL DEFAULT 'medium'
                CHECK (confidence IN ('high','medium','low')),
            source VARCHAR(40) NOT NULL DEFAULT 'llm',
            suggestion_id UUID,
            created_by UUID,
            approved_by UUID,
            last_learned_at TIMESTAMPTZ,
            learned_run_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, rule_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_business_rules_org_status "
        "ON knowledge_business_rules(organization_id, provenance, confidence)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_business_rules")
    op.execute(
        "ALTER TABLE catalog_relationships "
        "DROP CONSTRAINT IF EXISTS catalog_relationships_provenance_check"
    )
    for column in (
        "provenance",
        "confidence_score",
        "semantic_similarity",
        "cardinality",
        "evidence_detail",
        "last_learned_at",
        "learned_run_id",
    ):
        op.execute(
            f"ALTER TABLE catalog_relationships DROP COLUMN IF EXISTS {column}"
        )
