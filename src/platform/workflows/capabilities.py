# =============================================================================
# Phase 33B — Marketplace-native workflows: contexto del canvas, costos,
# recomendaciones, install inline y puertos tipados de acciones.
#
# Reutiliza el marketplace runtime existente (installs, execute_action,
# circuit, ledger). No crea un runtime nuevo.
# =============================================================================
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_ACTION_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bruc\b|ruc|sunat|taxpayer|contribuyente"), "peru.taxpayer.lookup", "sunat"),
    (re.compile(r"\bdni\b|reniec|identidad|identity|verificar persona"), "peru.identity.verify", "reniec-verification"),
    (re.compile(r"tipo de cambio|exchange|moneda|currency|dolar|dólar|soles"), "currency.current_rate", "rates-currency"),  # noqa: E501
    (re.compile(r"echo|demo"), "demo.echo", "demo-echo"),
]


def _cost_of(cost_model: dict | None) -> dict:
    cm = cost_model or {}
    model = str(cm.get("model") or "FREE")
    price = _num(cm.get("price"))
    if model == "PER_CALL" and not price:
        price = _num(cm.get("units") or 0)
    return {"model": model, "price": price, "currency": str(cm.get("currency") or "PEN")}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _org_manifests(organization_id: UUID) -> dict[str, dict]:
    """Slug -> manifest (con actions) para el org."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT m.id, m.slug, m.name, m.description, m.category, m.status, "
                    "m.data_policy, m.auth_modes "
                    "FROM integration_manifests m"
                )
            )
        ).fetchall()
        actions = (
            await session.execute(
                text(
                    "SELECT a.action_id, a.display_name, a.description, a.input_schema, "
                    "a.output_schema, a.renderer, a.cost_model, a.risk_level, a.read_only, "
                    "a.requires_approval, a.status, m.slug AS integration_slug "
                    "FROM integration_actions a JOIN integration_manifests m ON m.id = a.integration_id "
                    "ORDER BY a.action_id"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    by_slug: dict[str, dict] = {}
    for r in rows:
        modes = [str(x) for x in (r.auth_modes or [])]
        auth_modes = [m for m in modes if m.upper() != "NONE"]
        data_policy = r.data_policy or {}
        by_slug[str(r.slug)] = {
            "id": r.id,
            "slug": r.slug,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "status": r.status,
            "data_policy": data_policy,
            "requires_credentials": bool(auth_modes),
            "requires_purpose": bool(data_policy.get("purpose_required")),
            "auth_modes": modes,
            "actions": [],
        }
    for a in actions:
        if str(a.integration_slug) in by_slug:
            by_slug[str(a.integration_slug)]["actions"].append(
                {
                    "action_id": a.action_id,
                    "display_name": a.display_name,
                    "description": a.description,
                    "input_schema": a.input_schema or {},
                    "output_schema": a.output_schema or {},
                    "renderer": a.renderer,
                    "cost": _cost_of(a.cost_model),
                    "risk_level": a.risk_level,
                    "read_only": bool(a.read_only),
                    "requires_approval": bool(a.requires_approval),
                    "status": a.status,
                }
            )
    return by_slug


async def _installed_status(
    organization_id: UUID,
    workspace_id: UUID | None,
    manifests: dict[str, dict],
) -> dict[str, dict]:
    """install_id -> estado con acciones habilitadas y status del nodo."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT i.id, i.integration_id, i.status, i.credential_ref, i.purpose, "
                    "i.enabled_actions, i.version, m.slug, m.name, m.status AS manifest_status, "
                    "m.version AS manifest_version, m.data_policy "
                    "FROM installed_integrations i JOIN integration_manifests m ON m.id = i.integration_id "
                    "WHERE i.organization_id = :oid AND (i.workspace_id IS NOT DISTINCT FROM :ws)"
                ),
                {"oid": organization_id, "ws": workspace_id},
            )
        ).fetchall()
    finally:
        await session.close()

    states: dict[str, dict] = {}
    for r in rows:
        install_id = str(r.id)
        enabled = set(str(a) for a in (r.enabled_actions or []))
        actions = [
            dict(a)
            for a in manifests.get(str(r.slug), {}).get("actions", [])
            if not enabled or a["action_id"] in enabled
        ]
        status: list[str] = []
        if r.status not in ("active", "installed"):
            status.append("disabled")
        if not r.credential_ref and manifests.get(str(r.slug), {}).get("requires_credentials", True):
            status.append("credentials_missing")
        if (r.data_policy or {}).get("purpose_required") and not r.purpose:
            status.append("purpose_required")
        if str(r.manifest_status) == "DEPRECATED":
            status.append("deprecated")
        if int(r.manifest_version or 1) > int(r.version or 1):
            status.append("version_update")
        if not status:
            status.append("connected")
        states[install_id] = {
            "install_id": install_id,
            "integration": {
                "slug": r.slug,
                "name": r.name,
                "manifest_status": r.manifest_status,
            },
            "installed_version": int(r.version or 1),
            "manifest_version": int(r.manifest_version or 1),
            "status": status,
            "actions": actions,
        }
    return states


async def canvas_context(
    organization_id: UUID,
    workspace_id: UUID | None = None,
) -> dict:
    """Todo lo que el canvas necesita: instaladas, disponibles, costos y estados."""
    manifests = await _org_manifests(organization_id)
    installed = await _installed_status(organization_id, workspace_id, manifests)

    installed_slugs = {s["integration"]["slug"] for s in installed.values()}
    available: list[dict] = []
    for slug, m in manifests.items():
        if slug in installed_slugs:
            continue
        available.append(
            {
                "slug": slug,
                "name": m["name"],
                "description": m["description"],
                "category": m["category"],
                "requires_credentials": m["requires_credentials"],
                "requires_purpose": m["requires_purpose"],
                "actions": m["actions"],
            }
        )

    return {
        "installed": sorted(installed.values(), key=lambda s: s["integration"]["name"]),
        "available": sorted(available, key=lambda a: a["name"]),
        "recommendations": [],
        "costs": [
            {"action_id": a["action_id"], "cost": a["cost"]}
            for m in manifests.values()
            for a in m["actions"]
        ],
        "counts": {
            "installed": len(installed),
            "available": len(available),
            "actions": sum(len(m["actions"]) for m in manifests.values()),
        },
    }


async def recommend_for_graph(
    organization_id: UUID,
    graph: dict,
    workspace_id: UUID | None = None,
) -> dict:
    """Recomendaciones a partir del grafo (heurísticas sobre campos de negocio)."""
    installed = await _installed_status(organization_id, workspace_id, await _org_manifests(organization_id))
    installed_actions = {a["action_id"] for s in installed.values() for a in s["actions"]}

    haystack = json.dumps(graph, default=str).lower()
    recommendations: list[dict] = []
    for pattern, action_id, slug in _ACTION_HINTS:
        if action_id in installed_actions:
            continue
        if pattern.search(haystack) and action_id not in {r["action_id"] for r in recommendations}:
            recommendations.append(
                {
                    "action_id": action_id,
                    "integration_slug": slug,
                    "reason": "El grafo menciona un campo o dato que esta capacidad puede validar/enriquecer.",
                    "require_install": True,
                }
            )
    return {"recommendations": recommendations}


async def cost_estimate(organization_id: UUID, graph: dict, trigger_config: dict | None = None) -> dict:
    """Costo estimado por run y mensual (volumen según schedule)."""
    manifests = await _org_manifests(organization_id)
    price_by_action: dict[str, float] = {}
    for m in manifests.values():
        for a in m["actions"]:
            price_by_action[a["action_id"]] = a["cost"]["price"]

    def walk(node_id: str, multiplier: float = 1.0, visited: set[str] | None = None) -> tuple[int, float]:
        visited = visited or set()
        if node_id in visited:
            return 0, 0.0
        visited = visited | {node_id}
        node = by_id.get(node_id)
        if node is None:
            return 0, 0.0
        calls = 0
        cost = 0.0
        ntype = node.get("type")
        cfg = node.get("config") or {}
        if ntype == "for_each":
            base = _num(cfg.get("bulk_size") or cfg.get("expected_items") or 1000)
            multiplier = multiplier * base
        if ntype in ("marketplace_action", "business_node", "composite"):
            action_ids: list[str] = []
            if ntype == "marketplace_action" and cfg.get("action_id"):
                action_ids = [str(cfg["action_id"])]
            for act in cfg.get("actions") or []:
                if isinstance(act, dict) and act.get("action_id"):
                    action_ids.append(str(act["action_id"]))
            for aid in action_ids:
                price = price_by_action.get(aid, 0.0)
                calls += multiplier
                cost += price * multiplier
        for child_id in out_edges.get(node_id, []):
            c, co = walk(child_id, multiplier, visited)
            calls += c
            cost += co
        return calls, cost

    by_id: dict[str, dict] = {}
    out_edges: dict[str, list[str]] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        by_id[str(node["id"])] = node
        out_edges[str(node["id"])] = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        frm = str(edge.get("from_node") or edge.get("from") or "")
        to = str(edge.get("to_node") or edge.get("to") or "")
        if frm and to and frm in out_edges:
            out_edges[frm].append(to)

    entrypoints = [str(e) for e in (graph.get("entrypoints") or [])]
    calls, cost = 0, 0.0
    bulk_size = 1
    for node_id in entrypoints or list(by_id.keys()):
        c, co = walk(node_id)
        calls += c
        cost += co
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "for_each":
            bulk_size = max(bulk_size, int(_num((node.get("config") or {}).get("bulk_size") or 1000)))

    monthly = 30
    tc = trigger_config or {}
    if tc.get("frequency") == "hourly":
        monthly = 720
    elif tc.get("frequency") == "every_5_minutes":
        monthly = 8640
    elif tc.get("cron") and re.search(r"\b0 \d{1,2} \* \* \*\b", str(tc.get("cron"))):
        monthly = 30

    return {
        "per_run": round(cost, 4),
        "calls_per_run": calls,
        "monthly": round(cost * monthly, 4),
        "runs_per_month": monthly,
        "bulk_size": bulk_size,
        "bulk_warning": calls > 0 and cost > 0 and bulk_size > 100,
        "currency": "PEN",
    }


async def install_inline(
    organization_id: UUID,
    integration_slug: str,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
    purpose: str | None = None,
) -> dict:
    """Instala una integración desde el canvas (reusa instalación existente)."""
    from src.platform.marketplace.runtime import install_integration

    install = await install_integration(
        organization_id,
        integration_slug,
        workspace_id=workspace_id,
        created_by=created_by,
        purpose=purpose,
    )
    manifests = await _org_manifests(organization_id)
    manifest = manifests.get(integration_slug, {})
    return {
        "install_id": str(install["install_id"]),
        "reused": bool(install.get("reused", False)),
        "status": install.get("status", "installed"),
        "integration": {
            "slug": integration_slug,
            "name": manifest.get("name", integration_slug),
            "actions": manifest.get("actions", []),
        },
    }


async def ports_for_action(action_id: str) -> dict | None:
    """Puertos tipados de una acción (schemas + renderer) — sin JSONPath manual."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT a.display_name, a.description, a.input_schema, a.output_schema, "
                    "a.renderer, a.cost_model, m.slug AS integration_slug, m.name AS integration_name "
                    "FROM integration_actions a JOIN integration_manifests m ON m.id = a.integration_id "
                    "WHERE a.action_id = :aid"
                ),
                {"aid": action_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "action_id": action_id,
        "display_name": row.display_name,
        "description": row.description,
        "integration_slug": row.integration_slug,
        "integration_name": row.integration_name,
        "renderer": row.renderer,
        "cost": _cost_of(row.cost_model),
        "inputs": (row.input_schema or {}).get("properties", {}),
        "outputs": (row.output_schema or {}).get("properties", {}),
    }


async def draft_marketplace_flags(
    organization_id: UUID,
    steps: list[dict],
    workspace_id: UUID | None = None,
) -> dict:
    """Para el draft del copilot: resuelve placeholders de installs y marca missing."""
    installed = await _installed_status(organization_id, workspace_id, await _org_manifests(organization_id))
    install_by_slug = {s["integration"]["slug"]: s["install_id"] for s in installed.values()}
    installed_actions: set[str] = {
        a["action_id"] for s in installed.values() for a in s["actions"]
    }
    missing: list[dict] = []
    wired: list[dict] = []

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "marketplace_action":
            cfg = node.get("config") or {}
            action_id = str(cfg.get("action_id") or "")
            install_ph = str(cfg.get("install_id") or "")
            slug = None
            if install_ph.startswith("{{_pack."):
                slug = install_ph[8 : install_ph.rfind("_install}}")].replace("_", "-")
            if slug and slug in install_by_slug:
                node["config"]["install_id"] = install_by_slug[slug]
                wired.append({"action_id": action_id, "install_id": install_by_slug[slug]})
            elif action_id and action_id not in installed_actions:
                missing.append(
                    {"action_id": action_id, "install_slug": slug or action_id.split(".")[0]}
                )
        cfg = node.get("config")
        if isinstance(cfg, dict):
            for v in cfg.values():
                if isinstance(v, list):
                    for c in v:
                        walk(c)
                elif isinstance(v, dict):
                    walk(v)
        for branch in ("then", "else"):
            for c in node.get(branch) or []:
                walk(c)

    for step in steps:
        walk(step)
    return {"missing": missing, "wired": wired}
