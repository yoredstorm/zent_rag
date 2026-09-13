# =============================================================================
# Living Workflows (Fases A+B+C+E) — BusinessEvent, catálogo, watchers,
# transiciones, cooldown/debounce y E2E: fila cambia, watcher detecta, workflow
# dispara y notifica (in-app, sin efectos externos).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from src.platform.workflows import watchers as watchers_module
from src.platform.workflows.business_events import (
    build_business_event,
    changed_fields,
    compute_dedupe_key,
    normalize_legacy_event,
    split_event_type,
    transition_of,
)
from src.platform.workflows.event_registry import (
    catalog_payload,
    get_event_schema,
    list_catalog,
)
from src.platform.workflows.watchers import (
    WatcherCondition,
    WatcherDefinition,
    WatcherState,
    build_incremental_sql,
    debounce_ready,
    evaluate_row_condition,
    should_fire,
    should_suppress_by_cooldown,
)
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# BusinessEvent
# ---------------------------------------------------------------------------
def test_dedupe_key_is_deterministic_and_sensitive() -> None:
    base = dict(
        organization_id="org-1",
        event_type="inventory.stock.changed",
        event_version=1,
        entity_type="producto",
        entity_id="SKU-123",
        operation="transition",
        before={"stock": 12},
        after={"stock": 8},
        extra="false_to_true",
    )
    key_a = compute_dedupe_key(**base)
    key_b = compute_dedupe_key(**base)
    assert key_a == key_b
    assert "inventory.stock.changed@v1" in key_a

    changed = {**base, "after": {"stock": 7}}
    assert compute_dedupe_key(**changed) != key_a
    other_transition = {**base, "extra": "true_to_false"}
    assert compute_dedupe_key(**other_transition) != key_a


def test_event_type_version_split() -> None:
    assert split_event_type("inventory.stock.low@v2") == ("inventory.stock.low", 2)
    assert split_event_type("sales.closed") == ("sales.closed", 1)


def test_changed_fields_and_transitions() -> None:
    assert changed_fields({"stock": 12, "precio": 10}, {"stock": 8, "precio": 10}) == ["stock"]
    assert transition_of(None, True) == "false_to_true"
    assert transition_of(False, True) == "false_to_true"
    assert transition_of(True, True) == "true_to_true"
    assert transition_of(True, False) == "true_to_false"
    assert transition_of(False, False) == "false_to_false"


def test_build_event_and_dispatch_payload_exposes_business_fields() -> None:
    event = build_business_event(
        organization_id=uuid4(),
        event_type="inventory.stock.low",
        source="watcher",
        entity_type="producto",
        entity_id="SKU-123",
        operation="transition",
        before={"stock": 12},
        after={"stock": 8, "product": "MacBook"},
        transition="false_to_true",
    )
    assert event.dedupe_key
    payload = event.to_dispatch_payload()
    assert payload["event"] == "inventory.stock.low@v1"
    assert payload["stock"] == 8  # filtros existentes siguen funcionando
    assert payload["entity_id"] == "SKU-123"
    assert payload["before"] == {"stock": 12}


def test_normalize_legacy_event() -> None:
    event = normalize_legacy_event(
        "sales.closed",
        {
            "organization_id": str(uuid4()),
            "workspace_id": None,
            "total": 25000,
            "entity_id": "sale-1",
        },
    )
    assert event is not None
    assert event.event_type == "sales.closed"
    assert event.entity_id == "sale-1"
    assert normalize_legacy_event("sales.closed", {}) is None


# ---------------------------------------------------------------------------
# EventSchemaRegistry
# ---------------------------------------------------------------------------
def test_catalog_uses_business_names() -> None:
    schema = get_event_schema("sales.closed")
    assert schema.business_name == "Se cerró una venta"
    assert schema.category == "ventas"
    labels = {field.label for field in schema.fields}
    assert {"Total", "Cliente", "Vendedor"} <= labels

    payload = catalog_payload()
    categories = {c["key"] for c in payload["categories"]}
    assert {"ventas", "inventario", "documentos"} <= categories
    assert payload["count"] >= 19


def test_custom_event_falls_back_gracefully() -> None:
    schema = get_event_schema("custom.pokemon.updated@v3")
    assert schema.id == "custom.pokemon.updated"
    assert schema.version == 3
    assert schema.source_kind == "custom"
    assert list_catalog("inventario")


# ---------------------------------------------------------------------------
# WatcherDefinition / transiciones (puro)
# ---------------------------------------------------------------------------
def _watcher(**overrides) -> WatcherDefinition:
    data = {
        "name": "Stock bajo",
        "strategy": "watermark_polling",
        "entity": "producto",
        "table_name": "inventory",
        "primary_key": "id",
        "selected_fields": ["sku", "product", "stock"],
        "condition": {"field": "stock", "operator": "<", "value": 10},
        "event_type": "inventory.stock.low",
    }
    data.update(overrides)
    return WatcherDefinition.model_validate(data)


def test_watcher_definition_validates_safe_identifiers() -> None:
    with pytest.raises(ValidationError):
        _watcher(table_name="inventory; DROP TABLE users")
    with pytest.raises(ValidationError):
        _watcher(selected_fields=["stock) UNION SELECT password"])
    with pytest.raises(ValidationError):
        _watcher(primary_key=None, timestamp_field=None)
    with pytest.raises(ValidationError):
        _watcher(strategy="timestamp_polling", timestamp_field=None)  # sin cursor válido


def test_watcher_condition_accepts_friendly_operator() -> None:
    condition = WatcherCondition(field="stock", operator="es menor que", value=10)
    assert condition.operator == "<"
    assert condition.field == "stock"


def test_should_fire_matrix() -> None:
    assert should_fire("on_enter", False, True, changed=True, condition_present=True)[0] is True
    assert should_fire("on_enter", True, True, changed=False, condition_present=True)[0] is False
    assert should_fire("on_enter", True, False, changed=True, condition_present=True)[0] is False
    assert should_fire("on_exit", True, False, changed=True, condition_present=True)[0] is True
    assert should_fire("on_change", None, False, changed=True, condition_present=True)[0] is True
    assert should_fire("on_change", None, True, changed=False, condition_present=True)[0] is False
    assert should_fire("while_true", True, True, changed=False, condition_present=True)[0] is True
    assert should_fire("while_true", True, False, changed=True, condition_present=True)[0] is False


def test_cooldown_and_debounce_pure() -> None:
    now = datetime.now(timezone.utc)
    state = WatcherState(cooldown_until=now + timedelta(minutes=5))
    assert should_suppress_by_cooldown(state, now) is True
    assert should_suppress_by_cooldown(state, now + timedelta(minutes=6)) is False

    state = WatcherState()
    ready, state = debounce_ready(state, 300, now)
    assert ready is False and state.pending_since == now
    ready, state = debounce_ready(state, 300, now + timedelta(seconds=100))
    assert ready is False
    ready, state = debounce_ready(state, 300, now + timedelta(seconds=301))
    assert ready is True

    ready, state = debounce_ready(WatcherState(), 0, now)
    assert ready is True


def test_incremental_sql_is_bounded_and_cursor_based() -> None:
    watcher = _watcher().model_dump(mode="json")
    sql, params = build_incremental_sql(watcher, {"pk": 42})
    assert 'WHERE "id" > :cursor' in sql
    assert 'ORDER BY "id" ASC' in sql
    assert "LIMIT :limit" in sql
    assert params["cursor"] == 42
    assert params["limit"] <= 500

    ts_watcher = _watcher(strategy="timestamp_polling", timestamp_field="updated_at").model_dump(mode="json")
    sql_ts, _ = build_incremental_sql(ts_watcher, {"timestamp": "2026-09-01T00:00:00+00:00"})
    assert 'WHERE "updated_at" > :cursor' in sql_ts


def test_evaluate_row_condition_uses_engine_operators() -> None:
    condition = {"field": "stock", "operator": "<", "value": 10}
    assert evaluate_row_condition(condition, {"stock": 8}) is True
    assert evaluate_row_condition(condition, {"stock": 12}) is False
    assert evaluate_row_condition({"field": "sku", "operator": "is_empty"}, {"sku": None}) is True


# ---------------------------------------------------------------------------
# E2E: fila cambia -> watcher detecta -> workflow dispara -> notificación
# ---------------------------------------------------------------------------
async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _workflow_graph() -> dict:
    return _graph(
        nodes=[
            _node("t", "trigger_event", {"event_type": "inventory.stock.low", "filters": {}}),
            _node(
                "notify",
                "notify",
                {"channel": "in_app", "title": "Stock bajo", "message": "Producto con stock bajo"},
                label="Avisar a compras",
            ),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "notify"), _edge("e2", "notify", "end")],
        entrypoints=["t"],
    )


@pytest.mark.asyncio
async def test_watcher_e2e_fires_workflow_on_enter(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _org(async_client, "Living E2E")
    h = _headers(org)

    created_wf = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={
            "name": "Alerta stock",
            "trigger_type": "event",
            "graph": _workflow_graph(),
            "workflow_version": 2,
        },
    )
    assert created_wf.status_code == 200, created_wf.text
    workflow_id = created_wf.json()["workflow_id"]

    # Suscripción del workflow al evento del watcher (tabla existente).
    sub = await async_client.post(
        "/api/v1/workflows/triggers",
        headers=h,
        json={"workflow_id": workflow_id, "event_type": "inventory.stock.low", "filters": {}},
    )
    assert sub.status_code == 200, sub.text

    created_w = await async_client.post(
        "/api/v1/workflows/watchers",
        headers=h,
        json={
            "name": "Vigilar stock",
            "strategy": "watermark_polling",
            "entity": "producto",
            "table_name": "inventory",
            "primary_key": "id",
            "selected_fields": ["sku", "product", "stock"],
            "condition": {"field": "stock", "operator": "<", "value": 10},
            "transition_mode": "on_enter",
            "interval_seconds": 60,
            "cooldown_seconds": 3600,
            "event_type": "inventory.stock.low",
            "workflow_id": workflow_id,
        },
    )
    assert created_w.status_code == 200, created_w.text
    watcher_id = created_w.json()["id"]

    # Fuente simulada: la tabla cambia entre checks (runner inyectado).
    rows: list[dict] = [{"id": 1, "sku": "SKU-123", "product": "MacBook Pro", "stock": 12}]

    async def fake_runner(sql: str, params: dict) -> list[dict]:  # noqa: ARG001
        return [dict(row) for row in rows]

    monkeypatch.setattr(watchers_module, "_default_query_runner", fake_runner)

    # Check 1: stock 12, la condición no se cumple -> no dispara.
    first = await async_client.post(
        f"/api/v1/workflows/watchers/{watcher_id}/check",
        headers={**h, "Idempotency-Key": f"chk1-{uuid4().hex}"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["triggered"] is False
    assert body["condition_result"] is False
    assert "no" in body["reason"].lower() or "No" in body["reason"]

    # Check 2: stock 8 -> transición false_to_true -> workflow dispara.
    rows[:] = [{"id": 2, "sku": "SKU-123", "product": "MacBook Pro", "stock": 8}]
    second = await async_client.post(
        f"/api/v1/workflows/watchers/{watcher_id}/check",
        headers={**h, "Idempotency-Key": f"chk2-{uuid4().hex}"},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    compact = {k: body.get(k) for k in ("status", "reason", "condition_result", "transition", "after")}
    assert body["triggered"] is True, compact
    assert body["transition"] == "false_to_true"
    assert body["after"]["stock"] == 8

    runs = await async_client.get(f"/api/v1/workflows/{workflow_id}/runs", headers=h)
    assert runs.status_code == 200, runs.text
    run_list = runs.json()["runs"]
    assert len(run_list) == 1, run_list
    assert run_list[0]["status"] == "succeeded"

    # Estado persistido para la UX ("por qué corrió").
    state = (await async_client.get(f"/api/v1/workflows/watchers/{watcher_id}/state", headers=h)).json()
    assert state["last_condition_result"] is True
    assert state["last_value"]["stock"] == 8
    assert state["trigger_count"] == 1

    # Cooldown: en el siguiente cambio no vuelve a avisar (llamada directa sin force).
    from src.platform.workflows.watchers import check_watcher

    rows[:] = [{"id": 3, "sku": "SKU-123", "product": "MacBook Pro", "stock": 7}]
    cooldown = await check_watcher(UUID(org["organization_id"]), UUID(watcher_id))
    assert cooldown is not None
    assert cooldown.status == "cooldown"
    runs_after = await async_client.get(f"/api/v1/workflows/{workflow_id}/runs", headers=h)
    assert len(runs_after.json()["runs"]) == 1


@pytest.mark.asyncio
async def test_watchers_are_tenant_isolated(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_a = await _org(async_client, "Living Tenant A")
    org_b = await _org(async_client, "Living Tenant B")

    created = await async_client.post(
        "/api/v1/workflows/watchers",
        headers=_headers(org_a),
        json={
            "name": "A",
            "table_name": "inventory",
            "primary_key": "id",
            "selected_fields": ["stock"],
            "condition": {"field": "stock", "operator": "<", "value": 5},
        },
    )
    assert created.status_code == 200, created.text
    watcher_id = created.json()["id"]

    cross = await async_client.get(
        f"/api/v1/workflows/watchers/{watcher_id}", headers=_headers(org_b)
    )
    assert cross.status_code == 404

    cross_check = await async_client.post(
        f"/api/v1/workflows/watchers/{watcher_id}/check", headers=_headers(org_b)
    )
    assert cross_check.status_code == 404

    listing = await async_client.get("/api/v1/workflows/watchers", headers=_headers(org_b))
    assert listing.json()["watchers"] == []


@pytest.mark.asyncio
async def test_watcher_api_rejects_unsafe_table(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Living Unsafe")
    resp = await async_client.post(
        "/api/v1/workflows/watchers",
        headers=_headers(org),
        json={
            "name": "Malo",
            "table_name": "inventory; DROP TABLE users",
            "primary_key": "id",
            "condition": {"field": "stock", "operator": "<", "value": 1},
        },
    )
    assert resp.status_code in (400, 422)
