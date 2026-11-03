# =============================================================================
# P19.1-07 - Adaptador de inventario: core sin SQL bodega y validacion batch.
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.platform.workflows.bindings import BindingError
from src.platform.workflows.inventory_adapter import (
    execute_inventory_action,
    expire_inventory_reservations,
    reserve_stock_batch,
)


def test_core_has_no_inventory_sql() -> None:
    source = Path("src/platform/workflows/bindings.py").read_text(encoding="utf-8")
    assert "bodega." not in source
    assert "stock_reservations" not in source


@pytest.mark.asyncio
async def test_batch_rejects_duplicate_sku_before_db() -> None:
    binding = {"config": {"connector_id": str(uuid4()), "write": True}}
    with pytest.raises(BindingError) as exc:
        await reserve_stock_batch(
            uuid4(),
            binding,
            {
                "order_number": "BOD-1001",
                "items": [
                    {"sku": "BD-ARROZ-01", "quantity": 1},
                    {"sku": "BD-ARROZ-01", "quantity": 2},
                ],
            },
            workspace_id=None,
        )
    assert exc.value.code == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_batch_rejects_empty_items() -> None:
    binding = {"config": {"connector_id": str(uuid4()), "write": True}}
    with pytest.raises(BindingError) as exc:
        await reserve_stock_batch(
            uuid4(),
            binding,
            {"order_number": "BOD-1001", "items": []},
            workspace_id=None,
        )
    assert exc.value.code == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_expiration_requires_write_enablement() -> None:
    binding = {"config": {"connector_id": str(uuid4()), "write": False}}
    with pytest.raises(BindingError) as exc:
        await expire_inventory_reservations(uuid4(), binding, workspace_id=None)
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_unsupported_action_is_rejected() -> None:
    binding = {"config": {"action": "drop_all", "connector_id": str(uuid4()), "write": True}}
    with pytest.raises(BindingError) as exc:
        await execute_inventory_action(
            uuid4(), binding, {}, workspace_id=None
        )
    assert exc.value.code == "PROVIDER_NOT_SUPPORTED"
