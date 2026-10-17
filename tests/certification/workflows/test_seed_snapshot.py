# =============================================================================
# Certification — snapshot congelado del seed del embudo
# =============================================================================
# La migración 158 no puede importar `src.platform` (invariante de arquitectura:
# infrastructure no conoce capas superiores), así que siembra desde un JSON
# congelado. Este test garantiza que el JSON NO se desvía de la definición viva
# y que la migración no reintroduce el import prohibido.
# =============================================================================
from __future__ import annotations

import ast
import json
from pathlib import Path

from src.platform.commerce import sales_funnel

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "src" / "infrastructure" / "db_init" / "seeds" / "retail_sales_funnel.json"
MIGRATION = ROOT / "src" / "infrastructure" / "db_init" / "versions" / "158_commerce_sales_funnel.py"


def test_frozen_snapshot_matches_live_definition() -> None:
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    live = sales_funnel.snapshot_payload()
    assert frozen == live, (
        "El snapshot del seed se desvió de la definición viva: corre "
        "`python scripts/seed_sales_funnel.py` y commitea el JSON"
    )
    assert frozen["template"]["slug"] == sales_funnel.TEMPLATE_SLUG
    assert frozen["product"]["slug"] == sales_funnel.PRODUCT_SLUG
    assert frozen["template"]["graph"]["metadata"]["template"] == sales_funnel.TEMPLATE_SLUG
    assert len(frozen["template"]["graph"]["nodes"]) >= 30
    refs = {row["ref"] for row in frozen["capability_contracts"]}
    assert "payments.checkout.create" in refs and "catalog.products.search" in refs


def test_migration_reads_snapshot_without_importing_platform() -> None:
    """infrastructure no importa la capa de plataforma (ni de forma diferida)."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    forbidden = [mod for mod in imported if mod.startswith("src.platform")]
    assert not forbidden, f"la migración importa capas superiores: {forbidden}"
    # Y el snapshot que consume existe y declara los contratos financieros.
    assert SNAPSHOT.exists()


def test_snapshot_declares_idempotent_financial_contracts() -> None:
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    by_ref = {row["ref"]: row for row in frozen["capability_contracts"]}
    checkout = by_ref["payments.checkout.create"]
    assert checkout["financial"] is True
    assert checkout["idempotency_required"] is True
    assert checkout["provider_kinds"] == ["payment_provider"]
    assert by_ref["conversation.send"]["provider_kinds"] == ["conversation"]
    assert by_ref["catalog.products.search"]["provider_kinds"][0] == "commerce"
