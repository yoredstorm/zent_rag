"""Knowledge Nutrition — índices de consulta para tablas que crecen.

`knowledge_retrieval_probes` y `knowledge_nutrition_actions` crecen con la
operación normal (un probe por pregunta evaluada, una acción por fallo
clasificado). Los índices existentes cubren el filtro base; estos cubren los
patrones reales de lectura:

- actions por documento ordenadas por fecha (bandeja de nutrición),
- probes activos por documento agrupados por tipo (re-evaluación y reporte).

Aditiva y compatible: IF NOT EXISTS, sin cambios de columnas.

Revision ID: 141
Revises: 140
"""
from __future__ import annotations

from alembic import op

revision: str = "141"
down_revision: str = "140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_nutrition_actions_doc_created "
        "ON knowledge_nutrition_actions(organization_id, document_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_probes_doc_active_type "
        "ON knowledge_retrieval_probes(organization_id, document_id, active, query_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_nutrition_actions_doc_created")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_probes_doc_active_type")
