"""Knowledge Operating System — modelo de conocimiento durable (FASE 34).

Extiende la identidad canónica (102) para que sea el registro real de objetos
de conocimiento (dominios, conceptos, entidades, atributos, relaciones, reglas,
métricas, KPIs, procesos, términos, sinónimos, eventos, restricciones) y agrega
las tablas de aristas, assertions, versiones y conflictos.

Reutiliza:
  - knowledge_canonical_objects  -> objeto de conocimiento (identidad + estado)
  - knowledge_canonical_links    -> mapping objeto físico -> canónico
  - evidence_ledger              -> evidencia (se enriquece, no se duplica)
  - context_gaps                 -> gaps accionables (se enriquece)

Nuevo:
  - knowledge_edges              -> relaciones tipadas entre objetos
  - knowledge_assertions         -> afirmaciones con provenance/confianza
  - knowledge_object_versions    -> historial de cambios de un objeto
  - knowledge_conflicts          -> conflictos entre assertions

Puro aditivo. Revision ID: 132. Revises: 131.
"""
from __future__ import annotations

from alembic import op

revision: str = "132"
down_revision: str = "131"
branch_labels = None
depends_on = None

_KINDS = (
    "'source','document','section','block','chunk','entity','fact','rule','metric',"
    "'glossary_term','relationship','question','claim','evidence','artifact',"
    "'domain','concept','attribute','kpi','process','term','synonym','event',"
    "'constraint','table','column','verified_query'"
)

# Vocabulario nuevo + legado (observed/approved/archived se normalizan en API).
_STATUSES = (
    "'draft','discovered','observed','inferred','verified','approved','rejected',"
    "'deprecated','archived'"
)

_GAP_TYPES = (
    "'CONTEXT_MISSING','DATA_MISSING','MISSING_SOURCE','MISSING_TABLE',"
    "'MISSING_FIELD','MISSING_RELATIONSHIP','MISSING_BUSINESS_TERM','MISSING_METRIC',"
    "'UNDEFINED_ENUM','AMBIGUOUS_TERM','STALE_SOURCE','LOW_DATA_QUALITY',"
    "'SOURCE_CONFLICT','PERMISSION_LIMITATION','UNSUPPORTED_OPERATION',"
    "'UNKNOWN_DEFINITION','LOW_CONFIDENCE','CONTRADICTION',"
    "'MISSING_METRIC_DEFINITION','MISSING_BUSINESS_RULE','STALE_KNOWLEDGE',"
    "'UNRESOLVED_QUERY','UNSUPPORTED_ASSERTION','INCOMPLETE_SOURCE',"
    "'RETRIEVAL_FAILURE'"
)


def upgrade() -> None:
    # ---------------------------------------------------------------- objetos
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS name VARCHAR(512) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS display_name VARCHAR(512) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS description TEXT"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS domain VARCHAR(128)"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS source_of_truth VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS source_id UUID"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS authority_level VARCHAR(32)"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS verified_by UUID"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS freshness_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS evidence_count INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "ADD COLUMN IF NOT EXISTS assertion_count INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS metadata JSONB "
        "NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS "
        "knowledge_canonical_objects_kind_check"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD CONSTRAINT "
        f"knowledge_canonical_objects_kind_check CHECK (kind IN ({_KINDS}))"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS "
        "knowledge_canonical_objects_status_check"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD CONSTRAINT "
        f"knowledge_canonical_objects_status_check CHECK (status IN ({_STATUSES}))"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS "
        "ck_canonical_approval_law"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects ADD CONSTRAINT "
        "ck_canonical_approval_law CHECK ("
        "status NOT IN ('approved','verified') OR provenance = 'APPROVED')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_kind_status "
        "ON knowledge_canonical_objects(organization_id, kind, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_domain "
        "ON knowledge_canonical_objects(organization_id, domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_name_lower "
        "ON knowledge_canonical_objects(organization_id, lower(name))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_source "
        "ON knowledge_canonical_objects(organization_id, source_id)"
    )

    # ----------------------------------------------------------------- aristas
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_edges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            subject_id UUID NOT NULL
                REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            predicate VARCHAR(120) NOT NULL,
            object_id UUID NOT NULL
                REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            relationship_type VARCHAR(20) NOT NULL DEFAULT 'logical'
                CHECK (relationship_type IN
                       ('physical','logical','semantic','business')),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence >= 0 AND confidence <= 1),
            status VARCHAR(16) NOT NULL DEFAULT 'inferred'
                CHECK (status IN ('discovered','inferred','verified','rejected','deprecated')),
            provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            source_id UUID,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, subject_id, predicate, object_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_org_subject "
        "ON knowledge_edges(organization_id, subject_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_org_object "
        "ON knowledge_edges(organization_id, object_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_org_status "
        "ON knowledge_edges(organization_id, status, confidence)"
    )

    # -------------------------------------------------------------- assertions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_assertions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            subject_id UUID REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            subject_label VARCHAR(512) NOT NULL DEFAULT '',
            predicate VARCHAR(200) NOT NULL,
            object_id UUID REFERENCES knowledge_canonical_objects(id) ON DELETE SET NULL,
            object_value TEXT,
            assertion_type VARCHAR(40) NOT NULL DEFAULT 'fact',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence >= 0 AND confidence <= 1),
            confidence_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'candidate'
                CHECK (status IN ('candidate','accepted','verified','rejected','conflicted','stale')),
            provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            method VARCHAR(40) NOT NULL DEFAULT 'deterministic',
            source_id UUID,
            evidence_count INT NOT NULL DEFAULT 0,
            version INT NOT NULL DEFAULT 1,
            verified_by UUID,
            verified_at TIMESTAMPTZ,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            stale_at TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, subject_label, predicate, object_value)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_org_subject "
        "ON knowledge_assertions(organization_id, subject_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_org_status "
        "ON knowledge_assertions(organization_id, status, confidence)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_org_stale "
        "ON knowledge_assertions(organization_id, stale_at)"
    )

    # -------------------------------------------------------------- versiones
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_object_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            object_id UUID NOT NULL
                REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            version INT NOT NULL DEFAULT 1,
            change_kind VARCHAR(24) NOT NULL DEFAULT 'updated'
                CHECK (change_kind IN ('created','updated','verified','deprecated','conflict')),
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            changed_by UUID,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (object_id, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_object_versions_org "
        "ON knowledge_object_versions(organization_id, object_id, version DESC)"
    )

    # ------------------------------------------------------------- conflictos
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_conflicts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            object_id UUID REFERENCES knowledge_canonical_objects(id) ON DELETE SET NULL,
            subject_label VARCHAR(512) NOT NULL DEFAULT '',
            predicate VARCHAR(200) NOT NULL,
            assertion_a UUID REFERENCES knowledge_assertions(id) ON DELETE CASCADE,
            assertion_b UUID REFERENCES knowledge_assertions(id) ON DELETE CASCADE,
            value_a TEXT,
            value_b TEXT,
            source_a VARCHAR(200),
            source_b VARCHAR(200),
            status VARCHAR(16) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','investigating','resolved','ignored')),
            resolution VARCHAR(24)
                CHECK (resolution IS NULL OR resolution IN
                       ('chose_a','chose_b','merged','exception','delegated')),
            resolved_value TEXT,
            resolved_by UUID,
            resolved_at TIMESTAMPTZ,
            reason TEXT,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_conflicts_org_status "
        "ON knowledge_conflicts(organization_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_conflicts_org_object "
        "ON knowledge_conflicts(organization_id, object_id)"
    )

    # ------------------------------------------- evidencia: enriquecer ledger
    op.execute(
        "ALTER TABLE evidence_ledger "
        "ADD COLUMN IF NOT EXISTS evidence_type VARCHAR(24) NOT NULL DEFAULT 'document'"
    )
    op.execute(
        "ALTER TABLE evidence_ledger "
        "ADD COLUMN IF NOT EXISTS strength DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS locator TEXT"
    )
    op.execute(
        "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS assertion_id UUID "
        "REFERENCES knowledge_assertions(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ledger_org_assertion "
        "ON evidence_ledger(organization_id, assertion_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ledger_org_canonical "
        "ON evidence_ledger(organization_id, canonical_id)"
    )

    # --------------------------------------------------- gaps: enriquecer
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_gap_type_check "
        f"CHECK (gap_type IN ({_GAP_TYPES}))"
    )
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_status_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_status_check "
        "CHECK (status IN ('open','investigating','resolved','ignored','acknowledged'))"
    )
    op.execute("ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS title VARCHAR(400)")
    op.execute("ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS priority VARCHAR(10) "
        "NOT NULL DEFAULT 'medium'"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS priority_score "
        "DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS object_id UUID "
        "REFERENCES knowledge_canonical_objects(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS source_id UUID")
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS impact_objects INT "
        "NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_priority_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_priority_check "
        "CHECK (priority IN ('critical','high','medium','low'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_gaps_org_priority "
        "ON context_gaps(organization_id, status, priority_score DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_gaps_org_object "
        "ON context_gaps(organization_id, object_id)"
    )

    # ------------------------------------------------------------- permisos
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000055', 'knowledge:validate',
             'Aprobar assertions y objetos de conocimiento'),
            ('40000000-0000-0000-0000-000000000056', 'knowledge:admin',
             'Reconstruir el modelo de conocimiento y resolver conflictos'),
            ('40000000-0000-0000-0000-000000000057', 'knowledge:run_learning',
             'Ejecutar aprendizaje sobre fuentes')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name IN ('owner','admin') "
        "AND p.code IN ('knowledge:validate','knowledge:admin','knowledge:run_learning') "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'member' "
        "AND p.code = 'knowledge:run_learning' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_conflicts")
    op.execute("DROP TABLE IF EXISTS knowledge_object_versions")
    op.execute("DROP TABLE IF EXISTS knowledge_assertions")
    op.execute("DROP TABLE IF EXISTS knowledge_edges")
    op.execute(
        "ALTER TABLE evidence_ledger DROP COLUMN IF EXISTS assertion_id, "
        "DROP COLUMN IF EXISTS locator, DROP COLUMN IF EXISTS strength, "
        "DROP COLUMN IF EXISTS evidence_type"
    )
    op.execute(
        "ALTER TABLE context_gaps DROP COLUMN IF EXISTS title, "
        "DROP COLUMN IF EXISTS description, DROP COLUMN IF EXISTS priority, "
        "DROP COLUMN IF EXISTS priority_score, DROP COLUMN IF EXISTS object_id, "
        "DROP COLUMN IF EXISTS source_id, DROP COLUMN IF EXISTS impact_objects"
    )
    op.execute(
        "ALTER TABLE knowledge_canonical_objects DROP COLUMN IF EXISTS name, "
        "DROP COLUMN IF EXISTS display_name, DROP COLUMN IF EXISTS description, "
        "DROP COLUMN IF EXISTS domain, DROP COLUMN IF EXISTS source_of_truth, "
        "DROP COLUMN IF EXISTS source_id, DROP COLUMN IF EXISTS authority_level, "
        "DROP COLUMN IF EXISTS verified_by, DROP COLUMN IF EXISTS verified_at, "
        "DROP COLUMN IF EXISTS last_seen_at, DROP COLUMN IF EXISTS freshness_at, "
        "DROP COLUMN IF EXISTS evidence_count, DROP COLUMN IF EXISTS assertion_count"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('knowledge:validate','knowledge:admin','knowledge:run_learning')"
    )
