"""P20-11 - plantilla de checkout manual MVP.

Revision ID: 181
Revises: 180

Publica `retail_checkout_manual`: carrito temporal, orden ZENT, proyección
idempotente a Bodega, reserva/commit batch y validación manual de pago.
El snapshot JSON está congelado para que infrastructure no importe platform.
"""
from __future__ import annotations

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision: str = "181"
down_revision: str = "180"
branch_labels = None
depends_on = None

_SEED_PATH = (
    Path(__file__).resolve().parent.parent / "seeds" / "retail_checkout_manual.json"
)


def _load() -> dict:
    return json.loads(_SEED_PATH.read_text(encoding="utf-8"))


def upgrade() -> None:
    row = _load()["template"]
    op.get_bind().execute(
        text(
            "INSERT INTO workflow_templates "
            "(slug, name, description, category, trigger_type, steps, "
            "trigger_config, package, graph) "
            "VALUES (:slug, :name, :descr, :cat, :trigger, '[]'::jsonb, "
            "CAST(:tcfg AS jsonb), CAST(:pkg AS jsonb), CAST(:graph AS jsonb)) "
            "ON CONFLICT (slug) DO UPDATE SET "
            "name = EXCLUDED.name, description = EXCLUDED.description, "
            "category = EXCLUDED.category, trigger_type = EXCLUDED.trigger_type, "
            "trigger_config = EXCLUDED.trigger_config, "
            "package = EXCLUDED.package, graph = EXCLUDED.graph"
        ),
        {
            "slug": row["slug"],
            "name": row["name"],
            "descr": row["description"],
            "cat": row["category"],
            "trigger": row["trigger_type"],
            "tcfg": json.dumps(row["trigger_config"], ensure_ascii=False),
            "pkg": json.dumps(row["package"], ensure_ascii=False),
            "graph": json.dumps(row["graph"], ensure_ascii=False),
        },
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM workflow_templates WHERE slug = 'retail_checkout_manual'"
    )
