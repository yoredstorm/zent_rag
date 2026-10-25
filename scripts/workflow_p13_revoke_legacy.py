"""Revoca una exención legacy. Solo operador de plataforma, explícito y auditado."""
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


async def run(workflow_id: str, reason: str, confirm: bool) -> int:
    if not confirm:
        print("Rechazado: requiere --confirm-revoke.")
        return 2
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, published_version_id, "
                    "release_policy FROM workflows WHERE id = :wid"
                ),
                {"wid": UUID(workflow_id)},
            )
        ).fetchone()
        if row is None:
            print(json.dumps({"revoked": False, "reason": "workflow inexistente"}))
            return 1
        await session.execute(
            text(
                "UPDATE workflows SET release_policy = 'standard', "
                "release_policy_reason = :reason, release_policy_at = NOW(), "
                "deployment_generation = deployment_generation + 1 "
                "WHERE id = :wid"
            ),
            {"wid": row.id, "reason": reason[:2000]},
        )
        await session.execute(
            text(
                "UPDATE workflow_versions SET legacy_baseline = false "
                "WHERE workflow_id = :wid"
            ),
            {"wid": row.id},
        )
        await session.execute(
            text(
                "INSERT INTO workflow_deployments "
                "(organization_id, workspace_id, workflow_id, version_id, "
                "graph_hash, deployment_generation, action, actor_type, reason) "
                "SELECT :oid, :ws, :wid, :vid, '', deployment_generation, "
                "'revoke_legacy', 'platform_admin', :reason FROM workflows WHERE id = :wid"
            ),
            {
                "oid": row.organization_id,
                "ws": row.workspace_id,
                "wid": row.id,
                "vid": row.published_version_id,
                "reason": reason[:2000],
            },
        )
        await session.commit()
    finally:
        await session.close()
    print(json.dumps({"revoked": True, "workflow_id": workflow_id}))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Revocar exención legacy P13")
    parser.add_argument("workflow_id")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm-revoke", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(run(args.workflow_id, args.reason, args.confirm_revoke))
    )


if __name__ == "__main__":
    main()
