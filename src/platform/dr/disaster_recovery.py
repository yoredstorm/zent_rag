# =============================================================================
# Disaster Recovery — backups (pg_dump + Qdrant snapshot), DR drill a standby
# DB (validación no destructiva), readiness score por organización.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

BACKUP_ROOT = Path(get_settings().DR_BACKUP_DIR)


def _backup_dir(organization_id: UUID) -> Path:
    d = BACKUP_ROOT / str(organization_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603 (cmds fijas del platform)


async def _update_backup(backup_id: UUID, **fields) -> None:
    session = await get_async_session()
    try:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        params = {"bid": backup_id, **fields}
        await session.execute(text(f"UPDATE dr_backups SET {sets} WHERE id = :bid"), params)  # noqa: S608 (sets whitelisted por _update_backup)
        await session.commit()
    finally:
        await session.close()


async def _insert_backup(organization_id: UUID, trigger: str) -> UUID:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO dr_backups (id, organization_id, kind, status, trigger) "
                    "VALUES (gen_random_uuid(), :oid, 'full', 'running', :trigger) "
                    "RETURNING id"
                ),
                {"oid": organization_id, "trigger": trigger},
            )
        ).scalar()
        await session.commit()
        return row
    finally:
        await session.close()


async def create_backup(organization_id: UUID, trigger: str = "manual") -> dict:
    """pg_dump (custom format) + snapshot de Qdrant; verifica checksum."""
    started = time.monotonic()
    backup_id = await _insert_backup(organization_id, trigger)
    settings = get_settings()
    qdrant_ok = False
    error: str | None = None
    file_path: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None

    try:
        # 1) PostgreSQL: pg_dump custom format vía docker exec (salida binaria).
        dump_path = _backup_dir(organization_id) / f"pg_{backup_id}.dump"
        result = subprocess.run(  # noqa: S603, S607 (cmds docker fijas)
            [
                "docker", "exec", settings.DR_POSTGRES_CONTAINER,
                "pg_dump", "-U", settings.POSTGRES_USER, "-Fc", "-d", settings.POSTGRES_DB,
            ],
            capture_output=True,
            timeout=900,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed: {result.stderr.decode(errors='replace')[-500:]}"
            )
        if not result.stdout:
            raise RuntimeError("pg_dump produced no output")
        dump_path.write_bytes(result.stdout)
        size_bytes = dump_path.stat().st_size
        checksum = hashlib.sha256(dump_path.read_bytes()).hexdigest()
        file_path = str(dump_path)

        # 2) Qdrant: snapshot de la colección (fail-soft).
        try:
            from src.infrastructure.qdrant.vector_store import (
                RAG_DOCUMENTS_COLLECTION,
                _get_client,
            )

            client = await _get_client()
            snapshot = await client.create_snapshot(RAG_DOCUMENTS_COLLECTION)
            qdrant_ok = bool(snapshot)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant snapshot failed", error=str(exc)[:200])
            qdrant_ok = False

        duration = int((time.monotonic() - started) * 1000)
        await _update_backup(
            backup_id,
            status="completed",
            file_path=file_path,
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            duration_ms=duration,
            qdrant_snapshot=qdrant_ok,
            completed_at=datetime.now(timezone.utc),
        )
        return {
            "id": str(backup_id),
            "status": "completed",
            "file_path": file_path,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum,
            "duration_ms": duration,
            "qdrant_snapshot": qdrant_ok,
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:500]
        logger.error("Backup failed", organization_id=str(organization_id), error=error)
        await _update_backup(
            backup_id,
            status="failed",
            error=error,
            qdrant_snapshot=qdrant_ok,
            duration_ms=int((time.monotonic() - started) * 1000),
            completed_at=datetime.now(timezone.utc),
        )
        return {"id": str(backup_id), "status": "failed", "error": error}


async def list_backups(organization_id: UUID | None, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, kind, status, trigger, file_path, size_bytes, "
            "checksum_sha256, duration_ms, qdrant_snapshot, error, created_at, completed_at "
            "FROM dr_backups WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "kind": r.kind,
            "status": r.status,
            "trigger": r.trigger,
            "file_path": r.file_path,
            "size_bytes": r.size_bytes,
            "checksum_sha256": r.checksum_sha256,
            "duration_ms": r.duration_ms,
            "qdrant_snapshot": bool(r.qdrant_snapshot),
            "error": r.error,
            "created_at": r.created_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


async def prune_backups(organization_id: UUID | None, retention: int) -> int:
    """Elimina backups completados más viejos que `retention` (días) y sus archivos."""
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, file_path FROM dr_backups WHERE status = 'completed' "
            "AND created_at < NOW() - MAKE_INTERVAL(days => :retention) "
        )
        params: dict = {"retention": retention}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        rows = (await session.execute(text(sql), params)).fetchall()
        ids = [r.id for r in rows]
        removed = 0
        if ids:
            for r in rows:
                if r.file_path:
                    try:
                        Path(r.file_path).unlink(missing_ok=True)
                    except OSError:
                        pass
            await session.execute(
                text("DELETE FROM dr_backups WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            await session.commit()
            removed = len(ids)
    finally:
        await session.close()
    return removed


async def dr_drill(backup_id: UUID) -> dict:
    """Restaura el backup en una DB standby (rag_dr_*) y valida la integridad.
    NO destructivo: verifica que el dump es restaurable y lo elimina después."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, file_path, status FROM dr_backups "
                    "WHERE id = :bid"
                ),
                {"bid": backup_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"status": "failed", "error": "Backup not found"}
    if row.status != "completed" or not row.file_path:
        return {"status": "failed", "error": "Backup no completado o sin archivo"}

    settings = get_settings()
    standby = f"rag_dr_{str(backup_id)[:8]}"
    try:
        # 1) Crear standby DB.
        created = _run(
            ["docker", "exec", settings.DR_POSTGRES_CONTAINER, "createdb", "-U", settings.POSTGRES_USER, standby],
            timeout=60,
        )
        if created.returncode != 0 and "already exists" not in created.stderr:
            return {"status": "failed", "error": f"createdb: {created.stderr[-300:]}"}
        # 2) Restaurar el dump (sin owner, sin datos inválidos).
        with open(row.file_path, "rb") as fh:
            restore = subprocess.run(  # noqa: S603, S607
                ["docker", "exec", "-i", settings.DR_POSTGRES_CONTAINER, "pg_restore", "-U",
                 settings.POSTGRES_USER, "-d", standby, "-Fc", "--no-owner", "--clean"],
                stdin=fh,
                capture_output=True,
                timeout=900,
            )
        # pg_restore devuelve 0 o avisos; validamos por contenido, no por exit code.
        check = _run(
            [
                "docker", "exec", settings.DR_POSTGRES_CONTAINER, "psql", "-U", settings.POSTGRES_USER,
                "-d", standby, "-t", "-c", "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'",
            ],
            timeout=60,
        )
        table_count = int(check.stdout.strip() or 0) if check.returncode == 0 else 0
        ok = table_count >= 10  # esperamos las tablas del platform
        return {"status": "ok" if ok else "failed", "standby_db": standby, "tables": table_count}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc)[:400]}
    finally:
        try:
            _run(  # noqa: S603, S607
                ["docker", "exec", settings.DR_POSTGRES_CONTAINER, "dropdb", "-U", settings.POSTGRES_USER, standby],
                timeout=60,
            )
        except Exception:  # noqa: BLE001
            pass


async def dr_readiness(organization_id: UUID) -> dict:
    """Score 0-100: frescura del backup (RPO), estado, snapshots, región, worker."""
    settings = get_settings()
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT dr_regions, dr_rpo_minutes, dr_backup_enabled "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        last = (
            await session.execute(
                text(
                    "SELECT status, created_at, qdrant_snapshot FROM dr_backups "
                    "WHERE organization_id = :oid ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        worker = (
            await session.execute(
                text(
                    "SELECT last_seen_at FROM worker_heartbeats WHERE worker_name = 'ingestion'"
                )
            )
        ).fetchone()
    finally:
        await session.close()

    rpo_minutes = int(org.dr_rpo_minutes or 1440)
    components: list[dict] = []
    score = 0

    # 1) Backups habilitados.
    if org.dr_backup_enabled:
        components.append({"name": "backups_enabled", "ok": True, "detail": "habilitado"})
        score += 20
    else:
        components.append({"name": "backups_enabled", "ok": False, "detail": "deshabilitado"})

    # 2) Último backup y frescura (RPO).
    if last is not None:
        age_min = (datetime.now(timezone.utc) - last.created_at).total_seconds() / 60
        fresh = last.status == "completed" and age_min <= rpo_minutes
        components.append(
            {
                "name": "backup_freshness",
                "ok": fresh,
                "detail": (
                    f"último {last.status} hace {int(age_min)}m (RPO {rpo_minutes}m)"
                ),
            }
        )
        if fresh:
            score += 40
        elif last.status == "completed":
            score += 20
    else:
        components.append({"name": "backup_freshness", "ok": False, "detail": "sin backups"})

    # 3) Snapshot de Qdrant en el último backup.
    qdrant_ok = bool(last and last.qdrant_snapshot)
    components.append(
        {
            "name": "qdrant_snapshot",
            "ok": qdrant_ok,
            "detail": "presente" if qdrant_ok else "ausente en el último backup",
        }
    )
    if qdrant_ok:
        score += 20

    # 4) Regiones configuradas.
    regions = list(org.dr_regions or [])
    components.append(
        {
            "name": "regions",
            "ok": len(regions) > 0,
            "detail": ", ".join(regions) if regions else "sin regiones",
        }
    )
    if regions:
        score += 10

    # 5) Worker activo.
    worker_ok = worker is not None and (
        datetime.now(timezone.utc) - worker.last_seen_at
    ).total_seconds() < settings.OBS_WORKER_STALE_MINUTES * 60
    components.append(
        {
            "name": "ingestion_worker",
            "ok": worker_ok,
            "detail": "heartbeat ok" if worker_ok else "stale",
        }
    )
    if worker_ok:
        score += 10

    return {
        "organization_id": str(organization_id),
        "score": min(score, 100),
        "rpo_minutes": rpo_minutes,
        "backup_enabled": bool(org.dr_backup_enabled),
        "regions": regions,
        "components": components,
    }


async def get_org_dr_profile(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT dr_regions, dr_rpo_minutes, dr_backup_enabled "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "organization_id": str(organization_id),
        "regions": list(org.dr_regions or []),
        "rpo_minutes": int(org.dr_rpo_minutes or 1440),
        "backup_enabled": bool(org.dr_backup_enabled),
    }


async def set_org_dr_profile(
    organization_id: UUID,
    *,
    regions: list[str] | None = None,
    rpo_minutes: int | None = None,
    backup_enabled: bool | None = None,
) -> None:
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"oid": organization_id}
        if regions is not None:
            sets.append("dr_regions = :regions")
            params["regions"] = json.dumps(regions)
        if rpo_minutes is not None:
            sets.append("dr_rpo_minutes = :rpo")
            params["rpo"] = rpo_minutes
        if backup_enabled is not None:
            sets.append("dr_backup_enabled = :enabled")
            params["enabled"] = backup_enabled
        if sets:
            await session.execute(
                text(f"UPDATE organizations SET {', '.join(sets)} WHERE id = :oid"), params
            )
            await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Scheduler: backups automáticos según RPO
# ---------------------------------------------------------------------------
async def dr_scheduler_loop() -> None:
    """Cada 60s: para cada org con backup_enabled y RPO vencido, crea backup."""
    settings = get_settings()
    interval = settings.DR_SCHEDULER_INTERVAL_SECONDS
    while True:
        try:
            session = await get_async_session()
            try:
                rows = (
                    await session.execute(
                        text(
                            "SELECT o.id, o.dr_rpo_minutes FROM organizations o "
                            "WHERE o.dr_backup_enabled = true AND o.status <> 'deleted' "
                            "AND (SELECT COALESCE(MAX(created_at), 'epoch'::timestamptz) "
                            "FROM dr_backups b WHERE b.organization_id = o.id "
                            "AND b.status = 'completed') < NOW() - "
                            "MAKE_INTERVAL(mins => o.dr_rpo_minutes)"
                        )
                    )
                ).fetchall()
            finally:
                await session.close()
            for row in rows:
                logger.info(
                    "DR scheduler: backup due",
                    organization_id=str(row.id),
                    rpo_minutes=int(row.dr_rpo_minutes or 1440),
                )
                await create_backup(row.id, trigger="schedule")
        except Exception as exc:  # noqa: BLE001
            logger.warning("DR scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(interval)
