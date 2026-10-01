"""Knowledge Learning Sessions — la ingesta como aprendizaje observable.

Una sesión agrupa las fuentes que se están enseñando a ZENT y guarda:

1. ``knowledge_learning_sessions``: estado, etapa humana, métricas reales del
   Knowledge Pulse, delta de conocimiento (nuevo/reforzado/actualizado/
   conflictivo/ignorado) y totales antes/después del Knowledge OS.
2. ``knowledge_learning_session_sources``: evolución por fuente (leída,
   comprendida, indexada, disponible, enriquecida) con estadísticas crudas.
3. ``knowledge_learning_session_events``: stream semántico durable con replay
   (SSE). Los eventos de alta frecuencia llegan agregados por ventana, con
   ``payload.count`` y muestras acotadas: la UI nunca recibe 5.000 updates/s.

Revision ID: 136
Revises: 135
"""
from __future__ import annotations

from alembic import op

revision: str = "136"
down_revision: str = "135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_learning_sessions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            title VARCHAR(255) NOT NULL DEFAULT '',
            origin VARCHAR(32) NOT NULL DEFAULT 'upload',
            status VARCHAR(24) NOT NULL DEFAULT 'preparing'
                CHECK (status IN ('preparing','learning','available','optimizing',
                                  'completed','partial','failed','canceled')),
            stage VARCHAR(24) NOT NULL DEFAULT 'reading'
                CHECK (stage IN ('reading','understanding','organizing',
                                 'connecting','verifying','learned')),
            source_count INTEGER NOT NULL DEFAULT 0,
            available_sources INTEGER NOT NULL DEFAULT 0,
            completed_sources INTEGER NOT NULL DEFAULT 0,
            failed_sources INTEGER NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            knowledge_delta JSONB NOT NULL DEFAULT '{}'::jsonb,
            totals_before JSONB NOT NULL DEFAULT '{}'::jsonb,
            totals_after JSONB NOT NULL DEFAULT '{}'::jsonb,
            warnings INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            available_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            sealed_at TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_sessions_org_created "
        "ON knowledge_learning_sessions(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_sessions_org_status "
        "ON knowledge_learning_sessions(organization_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_learning_session_sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            session_id UUID NOT NULL
                REFERENCES knowledge_learning_sessions(id) ON DELETE CASCADE,
            source_id UUID,
            job_id UUID,
            name VARCHAR(512) NOT NULL DEFAULT '',
            source_type VARCHAR(32) NOT NULL DEFAULT 'file',
            status VARCHAR(24) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','learning','available','completed','failed')),
            stage VARCHAR(24) NOT NULL DEFAULT 'reading'
                CHECK (stage IN ('reading','understanding','organizing',
                                 'connecting','verifying','learned')),
            stats JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT,
            available_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, session_id, source_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_sources_session "
        "ON knowledge_learning_session_sources(session_id, created_at ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_sources_job "
        "ON knowledge_learning_session_sources(job_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_learning_session_events (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            seq BIGSERIAL NOT NULL,
            organization_id UUID NOT NULL,
            session_id UUID NOT NULL
                REFERENCES knowledge_learning_sessions(id) ON DELETE CASCADE,
            source_id UUID,
            event_type VARCHAR(60) NOT NULL,
            stage VARCHAR(24),
            severity VARCHAR(10) NOT NULL DEFAULT 'info',
            message TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            aggregate BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_learning_session_events_seq "
        "ON knowledge_learning_session_events(seq)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_events_session_seq "
        "ON knowledge_learning_session_events(session_id, seq ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_events_org_created "
        "ON knowledge_learning_session_events(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_events_source "
        "ON knowledge_learning_session_events(session_id, source_id, seq ASC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_learning_session_events")
    op.execute("DROP TABLE IF EXISTS knowledge_learning_session_sources")
    op.execute("DROP TABLE IF EXISTS knowledge_learning_sessions")
