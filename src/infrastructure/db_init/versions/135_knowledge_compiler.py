"""Knowledge Compiler — identidad de entidades, compilaciones y conflictos clasificados.

Cierra el modelo canónico del Knowledge OS con lo que faltaba para que el
conocimiento compilado desde documentos y datos tabulares sea de primera clase:

1. ``knowledge_entity_aliases``: identidad canónica multi-alias. Una entidad
   ("ATPCO Record 4") acumula alias ("Record 4", "R4", "Cat 4") con tipo,
   confianza y razón. La fusión NUNCA es silenciosa: cada alias guarda la
   evidencia que lo respalda y el motivo por el que se vinculó.

2. ``knowledge_compilations``: traza de cada corrida del Knowledge Compiler
   (qué fuente, cuántas unidades/entidades/hechos/relaciones/reglas/conflictos
   produjo y en cuánto tiempo). Es la unidad de observabilidad del compilador.

3. ``knowledge_conflicts``: clasificación del conflicto. Antes existía
   "mismo sujeto + mismo predicado + valor distinto". Ahora el motor además
   clasifica la causa (VERSION_CHANGE, TEMPORAL_CHANGE, SCOPE_DIFFERENCE,
   EXCEPTION, SOURCE_CONFLICT, POSSIBLE_DUPLICATE, UNRESOLVED) con su detalle.

4. ``knowledge_assertions``: soporte temporal nativo (``observed_at``,
   ``superseded_by``) y de alcance (``scope``), más el índice que hace barato
   preguntar "¿qué regla aplicaba en marzo de 2025?".

Revision ID: 135
Revises: 134
"""
from __future__ import annotations

from alembic import op

revision: str = "135"
down_revision: str = "134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------- vocabulario canónico de kinds
    # La migración 102 congeló la lista de kinds en un CHECK. El compilador
    # escribe el vocabulario de Knowledge OS (business_rule, process, concept…):
    # se reemplaza el CHECK por la lista completa, sin perder filas.
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "DROP CONSTRAINT IF EXISTS knowledge_canonical_objects_kind_check"
    )
    op.execute(
        """
        ALTER TABLE knowledge_canonical_objects
            ADD CONSTRAINT knowledge_canonical_objects_kind_check
            CHECK (kind IN (
                'source','document','section','block','chunk','entity','fact',
                'rule','metric','glossary_term','relationship','question',
                'claim','evidence','artifact',
                'domain','concept','attribute','business_rule','kpi','process',
                'term','synonym','event','constraint','table','column',
                'verified_query'
            ))
        """
    )

    # ------------------------------------------------------------- aliases
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_entity_aliases (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            entity_id UUID NOT NULL
                REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            alias VARCHAR(512) NOT NULL,
            normalized VARCHAR(512) NOT NULL,
            alias_type VARCHAR(24) NOT NULL DEFAULT 'synonym'
                CHECK (alias_type IN
                       ('synonym','abbreviation','acronym','alternate_spelling',
                        'contextual_name','code','translation')),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
                CHECK (confidence >= 0 AND confidence <= 1),
            reason VARCHAR(200) NOT NULL DEFAULT '',
            source_id UUID,
            document_id UUID,
            evidence_ids UUID[] NOT NULL DEFAULT '{}',
            verified BOOLEAN NOT NULL DEFAULT false,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, entity_id, normalized)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_entity_aliases_org_norm "
        "ON knowledge_entity_aliases(organization_id, normalized)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_entity_aliases_entity "
        "ON knowledge_entity_aliases(organization_id, entity_id)"
    )

    # -------------------------------------------------------- compilations
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_compilations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            compilation_kind VARCHAR(24) NOT NULL DEFAULT 'document'
                CHECK (compilation_kind IN ('document','tabular','catalog','mixed')),
            status VARCHAR(16) NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','completed','failed','skipped')),
            units INT NOT NULL DEFAULT 0,
            entities INT NOT NULL DEFAULT 0,
            entities_merged INT NOT NULL DEFAULT 0,
            facts INT NOT NULL DEFAULT 0,
            relationships INT NOT NULL DEFAULT 0,
            rules INT NOT NULL DEFAULT 0,
            conflicts INT NOT NULL DEFAULT 0,
            evidence INT NOT NULL DEFAULT 0,
            duration_ms INT NOT NULL DEFAULT 0,
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_compilations_org_started "
        "ON knowledge_compilations(organization_id, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_compilations_org_source "
        "ON knowledge_compilations(organization_id, source_id)"
    )

    # ------------------------------------------------------------- conflicts
    op.execute(
        "ALTER TABLE knowledge_conflicts "
        "ADD COLUMN IF NOT EXISTS conflict_type VARCHAR(32) NOT NULL DEFAULT 'UNRESOLVED'"
    )
    op.execute(
        "ALTER TABLE knowledge_conflicts "
        "ADD COLUMN IF NOT EXISTS classification JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE knowledge_conflicts "
        "ADD COLUMN IF NOT EXISTS evidence_ids UUID[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_conflicts_org_type "
        "ON knowledge_conflicts(organization_id, conflict_type, status)"
    )

    # ------------------------------------------------------------ assertions
    op.execute(
        "ALTER TABLE knowledge_assertions ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE knowledge_assertions ADD COLUMN IF NOT EXISTS superseded_by UUID "
        "REFERENCES knowledge_assertions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE knowledge_assertions ADD COLUMN IF NOT EXISTS scope VARCHAR(200)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_temporal "
        "ON knowledge_assertions(organization_id, valid_from, valid_to)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_observed "
        "ON knowledge_assertions(organization_id, observed_at DESC)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_canonical_objects "
        "DROP CONSTRAINT IF EXISTS knowledge_canonical_objects_kind_check"
    )
    op.execute(
        """
        ALTER TABLE knowledge_canonical_objects
            ADD CONSTRAINT knowledge_canonical_objects_kind_check
            CHECK (kind IN (
                'source','document','section','block','chunk','entity','fact',
                'rule','metric','glossary_term','relationship','question',
                'claim','evidence','artifact'
            ))
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_knowledge_assertions_observed")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_assertions_temporal")
    op.execute("ALTER TABLE knowledge_assertions DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE knowledge_assertions DROP COLUMN IF EXISTS superseded_by")
    op.execute("ALTER TABLE knowledge_assertions DROP COLUMN IF EXISTS observed_at")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_conflicts_org_type")
    op.execute("ALTER TABLE knowledge_conflicts DROP COLUMN IF EXISTS evidence_ids")
    op.execute("ALTER TABLE knowledge_conflicts DROP COLUMN IF EXISTS classification")
    op.execute("ALTER TABLE knowledge_conflicts DROP COLUMN IF EXISTS conflict_type")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_compilations_org_source")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_compilations_org_started")
    op.execute("DROP TABLE IF EXISTS knowledge_compilations")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_entity_aliases_entity")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_entity_aliases_org_norm")
    op.execute("DROP TABLE IF EXISTS knowledge_entity_aliases")
