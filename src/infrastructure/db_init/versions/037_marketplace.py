"""Marketplace & Sharing — listings, reviews, share links, prompt templates.

Revision ID: 037
Revises: 036
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_listings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(60) NOT NULL DEFAULT 'general',
            tags JSONB NOT NULL DEFAULT '[]',
            agent_snapshot JSONB NOT NULL,
            rating_avg DOUBLE PRECISION NOT NULL DEFAULT 0,
            rating_count INT NOT NULL DEFAULT 0,
            installs INT NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'published',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (agent_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_marketplace_status "
        "ON marketplace_listings(status, category, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            listing_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (listing_id, organization_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_share_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            token VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ,
            max_uses INT,
            uses INT NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(120) NOT NULL,
            category VARCHAR(60) NOT NULL DEFAULT 'general',
            description TEXT,
            content TEXT NOT NULL,
            is_builtin BOOLEAN NOT NULL DEFAULT false,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO prompt_templates (name, category, description, content, is_builtin) VALUES
        ('Agente de Soporte', 'support',
         'Prompt de soporte al cliente con tono empático y escalamiento.',
         'Eres el asistente de soporte de {company}. Responde en el idioma del usuario, sé conciso y empático. Si no sabes la respuesta, ofrece escalar a un humano.', true),
        ('Analista de Ventas', 'sales',
         'Prompt de análisis de ventas con foco en métricas y recomendaciones.',
         'Eres un analista de ventas senior. Responde con datos concretos (montos, tendencias, variaciones %) y cierra cada respuesta con una recomendación accionable.', true),
        ('Asistente Financiero', 'finance',
         'Prompt de finanzas con precisión y advertencias de riesgo.',
         'Eres un asistente financiero. Sé conservador con los números, indica supuestos y agrega una nota de riesgo cuando corresponda. Nunca inventes cifras.', true),
        ('Investigador de Mercado', 'research',
         'Prompt de investigación con citas a fuentes.',
         'Eres un investigador. Responde con argumentos fundamentados, cita las fuentes consultadas y separa hechos de opiniones.', true)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_templates")
    op.execute("DROP TABLE IF EXISTS agent_share_links")
    op.execute("DROP TABLE IF EXISTS marketplace_reviews")
    op.execute("DROP INDEX IF EXISTS idx_marketplace_status")
    op.execute("DROP TABLE IF EXISTS marketplace_listings")
