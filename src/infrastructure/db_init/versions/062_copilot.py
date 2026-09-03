"""AI Copilot & Assistant Platform v2 — marketplace, sesiones y telemetría.

Revision ID: 062
Revises: 061
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_agents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(120) NOT NULL,
            slug VARCHAR(80) NOT NULL UNIQUE,
            description TEXT,
            category VARCHAR(40) NOT NULL DEFAULT 'general',
            tags JSONB NOT NULL DEFAULT '[]',
            prompt_template TEXT,
            config_template JSONB NOT NULL DEFAULT '{}',
            rating DOUBLE PRECISION NOT NULL DEFAULT 0,
            installs INT NOT NULL DEFAULT 0,
            featured BOOLEAN NOT NULL DEFAULT false,
            status VARCHAR(20) NOT NULL DEFAULT 'published',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_installs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            marketplace_agent_id UUID NOT NULL,
            agent_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'installed',
            installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            removed_at TIMESTAMPTZ,
            usage_count INT NOT NULL DEFAULT 0,
            UNIQUE (organization_id, marketplace_agent_id, status)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            user_id UUID,
            title VARCHAR(200) NOT NULL DEFAULT 'Nueva conversación',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_copilot_sessions_org "
        "ON copilot_sessions(organization_id, last_activity_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL,
            role VARCHAR(15) NOT NULL DEFAULT 'user',
            content TEXT NOT NULL,
            intent VARCHAR(30),
            resolved_agent_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_copilot_messages_session "
        "ON copilot_messages(session_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_usage (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            assistant_key VARCHAR(80) NOT NULL,
            events INT NOT NULL DEFAULT 0,
            last_event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, assistant_key)
        )
        """
    )

    # Seed del marketplace.
    op.execute(
        """
        INSERT INTO marketplace_agents (name, slug, description, category, tags,
            prompt_template, config_template, rating, installs, featured) VALUES
        ('Soporte al Cliente', 'customer-support', 'Responde consultas frecuentes
            de soporte y escala casos complejos a tu equipo.',
            'support', '["soporte","tickets","FAQ"]',
            'Eres el agente de soporte de {company}. Responde con claridad y
            empatía usando la base de conocimiento. Si no sabes, ofrece derivar
            a un humano.', '{"model": "gpt-4o-mini", "max_tokens": 1500}',
            4.8, 1240, true),
        ('Ventas & Lead Qualification', 'sales-qualifier', 'Califica leads,
            responde sobre precios y agenda reuniones.',
            'sales', '["ventas","leads","precios"]',
            'Eres el asistente de ventas de {company}. Identifica la intención
            de compra, responde sobre planes y captura datos de contacto.',
            '{"model": "gpt-4o", "max_tokens": 2000}',
            4.6, 980, true),
        ('Operaciones Internas', 'ops-assistant', 'Automatiza tareas internas:
            estados de proyectos, pedidos y métricas del equipo.',
            'operations', '["ops","proyectos","pedidos","métricas"]',
            'Eres el asistente de operaciones. Busca en la documentación interna
            y responde con estados concretos.',
            '{"model": "gpt-4o-mini", "max_tokens": 1500}',
            4.5, 760, true),
        ('Legal & Compliance', 'legal-assistant', 'Consulta de políticas,
            contratos y normativas de la organización.',
            'legal', '["legal","contratos","políticas"]',
            'Eres el asistente legal. Responde citando la cláusula o documento
            de referencia y sugiere revisión humana para casos límite.',
            '{"model": "gpt-4o", "max_tokens": 2000}',
            4.7, 540, false),
        ('HR & Onboarding', 'hr-onboarding', 'Preguntas de RRHH, beneficios y
            guías de onboarding para nuevos empleados.',
            'hr', '["rrhh","beneficios","onboarding"]',
            'Eres el asistente de RRHH. Responde sobre políticas internas y
            guía a nuevos empleados en su onboarding.',
            '{"model": "gpt-4o-mini", "max_tokens": 1500}',
            4.4, 410, false)
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in (
        "assistant_usage",
        "copilot_messages",
        "copilot_sessions",
        "marketplace_installs",
        "marketplace_agents",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
