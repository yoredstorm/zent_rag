"""Restaura la fila viva desde el snapshot publicado antes de revertir P13.

Dry-run por defecto. `--apply --confirm-restore` ejecuta la copia atómica.
No cambia el puntero ni borra versiones; solo alinea `workflows` con la versión
publicada para que un SHA anterior siga ejecutando el mismo grafo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from src.infrastructure.postgres.session import get_async_session  # noqa: E402


async def run(workflow_id: str | None, apply: bool, confirm: bool) -> int:
    if apply and not confirm:
        print("Rechazado: --apply requiere --confirm-restore.")
        return 2
    session = await get_async_session()
    try:
        params: dict = {}
        sql = (
            "SELECT w.id, w.organization_id, w.workspace_id, w.trigger_config, "
            "w.name, w.description, w.trigger_type, w.steps, w.graph, w.workflow_version, "
            "w.graph_source, w.editor_state, v.version_number, v.config_snapshot, "
            "v.graph_hash FROM workflows w JOIN workflow_versions v "
            "ON v.id = w.published_version_id WHERE w.published_version_id IS NOT NULL"
        )
        if workflow_id:
            sql += " AND w.id = :wid"
            params["wid"] = UUID(workflow_id)
        rows = (await session.execute(text(sql), params)).fetchall()
        if not rows:
            print(json.dumps({"restored": 0, "reason": "sin versiones publicadas"}))
            return 0
        planned = []
        for row in rows:
            snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else {}
            trigger_config = dict(snapshot.get("trigger_config") or {})
            live_trigger = dict(row.trigger_config or {})
            if live_trigger.get("hook_secret_hash"):
                trigger_config["hook_secret_hash"] = live_trigger["hook_secret_hash"]
            planned.append(
                {
                    "workflow_id": str(row.id),
                    "version_number": int(row.version_number),
                    "graph_hash": row.graph_hash,
                }
            )
            if not apply:
                continue
            await session.execute(
                text(
                    "UPDATE workflows SET name = :name, description = :description, "
                    "trigger_type = :ttype, trigger_config = CAST(:tcfg AS jsonb), "
                    "steps = CAST(:steps AS jsonb), graph = CAST(:graph AS jsonb), "
                    "graph_source = :gsource, workflow_version = :wver, "
                    "editor_state = CAST(:estate AS jsonb), "
                    "draft_revision = draft_revision + 1, "
                    "deployment_generation = deployment_generation + 1, updated_at = NOW() "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {
                    "name": snapshot.get("name") or row.name,
                    "description": snapshot.get("description")
                    if snapshot.get("description") is not None
                    else row.description,
                    "ttype": snapshot.get("trigger_type") or row.trigger_type,
                    "tcfg": json.dumps(trigger_config),
                    "steps": json.dumps(snapshot.get("steps") or []),
                    "graph": json.dumps(snapshot.get("graph") or {}),
                    "gsource": snapshot.get("graph_source") or row.graph_source or "graph",
                    "wver": int(snapshot.get("workflow_version") or row.workflow_version or 1),
                    "estate": json.dumps(snapshot.get("editor_state") or {}),
                    "wid": row.id,
                    "oid": row.organization_id,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO workflow_deployments "
                    "(organization_id, workspace_id, workflow_id, version_id, "
                    "graph_hash, deployment_generation, action, actor_type, reason) "
                    "SELECT :oid, :ws, :wid, w.published_version_id, :ghash, "
                    "w.deployment_generation, 'rollback_live_restore', 'operator', "
                    "'workflow_p13_rollback.py' FROM workflows w WHERE w.id = :wid"
                ),
                {
                    "oid": row.organization_id,
                    "ws": row.workspace_id,
                    "wid": row.id,
                    "ghash": row.graph_hash or "",
                },
            )
        if apply:
            await session.commit()
        else:
            await session.rollback()
    finally:
        await session.close()
    print(json.dumps({"apply": apply, "workflows": planned}, indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback P13: live desde publicado")
    parser.add_argument("--workflow-id", default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(run(args.workflow_id, args.apply, args.confirm_restore))
    )


if __name__ == "__main__":
    main()
