#!/usr/bin/env python
# =============================================================================
# P18.3-04 - Backfill autorizado de fuentes históricas sin corpus
# =============================================================================
# Fuente histórica con kb_sources.corpus_id IS NULL no es alcanzable por
# /workspaces/{corpus_id}/sources/{source_id}/insight. Este CLI produce un plan
# auditable, aplica solo relaciones inequívocas y permite revertir.
#
# Uso:
#   python -m src.scripts.legacy_source_corpus_backfill plan --org <uuid>
#   python -m src.scripts.legacy_source_corpus_backfill plan --org <uuid> \
#       --resolve <source_id>=<corpus_id> --out plan.jsonl
#   python -m src.scripts.legacy_source_corpus_backfill apply \
#       --plan-file plan.jsonl --plan-id <uuid> --plan-sha256 <sha> --approve
#   python -m src.scripts.legacy_source_corpus_backfill rollback \
#       --plan-id <uuid> --approve
#
# No borra fuentes, documentos, evidencias, embeddings ni sesiones. No elige
# "el primer corpus": si no hay vínculo explícito, la fila queda bloqueada para
# resolución humana.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

DEFAULT_OUT = Path("artifacts/certification/p18-3/legacy_source_plan.jsonl")
_PLAN_FIELDS = (
    "record_type",
    "plan_id",
    "organization_id",
    "workspace_id",
    "source_id",
    "source_status",
    "knowledge_base_id",
    "current_corpus_id",
    "candidate_corpus_id",
    "candidates",
    "classification",
    "decision",
    "reason",
    "name_sha256",
    "source_name",
    "source_updated_at",
)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))  # noqa: T201


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_row(row: dict[str, Any]) -> str:
    clean = {key: row.get(key) for key in _PLAN_FIELDS if key in row}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_checksum(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda item: str(item.get("source_id") or ""))
    return _sha256_text("\n".join(_canonical_row(row) for row in ordered))


def write_plan(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda item: str(item.get("source_id") or ""))
    path.write_text(
        "\n".join(_canonical_row(row) for row in ordered) + "\n",
        encoding="utf-8",
    )
    checksum = plan_checksum(ordered)
    path.with_suffix(path.suffix + ".sha256").write_text(checksum + "\n", encoding="utf-8")
    return checksum


def load_plan(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    if not rows:
        raise ValueError("plan vacío")
    return rows


def _corpus_index(rows: list[Any]) -> dict[str, dict[str, str]]:
    return {
        str(row.id): {
            "corpus_id": str(row.id),
            "organization_id": str(row.organization_id),
            "workspace_id": str(row.workspace_id),
        }
        for row in rows
    }


async def build_plan(
    *,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    source_id: UUID | None = None,
    limit: int = 500,
    include_names: bool = False,
    resolutions: dict[UUID, UUID] | None = None,
    plan_id: UUID | None = None,
) -> dict[str, Any]:
    """Construye el plan sin escribir ni modificar kb_sources."""

    resolutions = resolutions or {}
    session = await get_async_session()
    try:
        corpora = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id FROM knowledge_corpora "
                    "WHERE organization_id = :oid"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchall()
        corpora_by_workspace: dict[str, list[dict[str, str]]] = {}
        for row in corpora:
            corpora_by_workspace.setdefault(str(row.workspace_id), []).append(
                _corpus_index([row])[str(row.id)]
            )
        index = _corpus_index(corpora)

        clauses = ["s.organization_id = :oid", "s.corpus_id IS NULL"]
        params: dict[str, Any] = {"oid": str(organization_id), "limit": limit}
        if workspace_id is not None:
            clauses.append("s.workspace_id = :wid")
            params["wid"] = str(workspace_id)
        if source_id is not None:
            clauses.append("s.id = :sid")
            params["sid"] = str(source_id)
        sources = (
            await session.execute(
                text(
                    "SELECT s.id, s.organization_id, s.workspace_id, s.name, s.status, "
                    "       s.knowledge_base_id, s.corpus_id, s.created_at, s.updated_at, "
                    "       w.id AS workspace_exists, "
                    "       kb.corpus_id AS kb_corpus_id, "
                    "       s.config_json->>'corpus_id' AS explicit_corpus_id "
                    "FROM kb_sources s "
                    "LEFT JOIN workspaces w ON w.id = s.workspace_id "
                    "                      AND w.organization_id = s.organization_id "
                    "LEFT JOIN knowledge_bases kb ON kb.id = s.knowledge_base_id "
                    "                      AND kb.organization_id = s.organization_id "
                    "WHERE " + " AND ".join(clauses) + " "
                    "ORDER BY s.created_at ASC, s.id ASC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    effective_plan_id = str(plan_id or uuid4())
    rows: list[dict[str, Any]] = []
    for source in sources:
        sid = str(source.id)
        swid = str(source.workspace_id) if source.workspace_id else None
        candidates: list[dict[str, str]] = []
        reason = ""
        classification = "needs_resolution"
        cross_conflict = False

        # Vínculo explícito: colección (knowledge_base) con corpus.
        if source.kb_corpus_id is not None:
            candidate = index.get(str(source.kb_corpus_id))
            if candidate is None:
                classification = "cross_scope_conflict"
                reason = "kb_corpus_missing"
                cross_conflict = True
            elif candidate["organization_id"] != str(organization_id):
                classification = "cross_scope_conflict"
                reason = "kb_corpus_other_organization"
                cross_conflict = True
            elif swid is None or candidate["workspace_id"] != swid:
                classification = "cross_scope_conflict"
                reason = "kb_corpus_other_workspace"
                cross_conflict = True
            else:
                candidates.append(
                    {"corpus_id": str(source.kb_corpus_id), "via": "knowledge_base"}
                )

        # Vínculo explícito declarado por el importador en config_json.
        if source.explicit_corpus_id:
            candidate = index.get(str(source.explicit_corpus_id))
            if candidate is None:
                classification = "cross_scope_conflict"
                reason = "source_config_corpus_missing"
                cross_conflict = True
            elif candidate["organization_id"] != str(organization_id):
                classification = "cross_scope_conflict"
                reason = "source_config_corpus_other_organization"
                cross_conflict = True
            elif swid is None or candidate["workspace_id"] != swid:
                classification = "cross_scope_conflict"
                reason = "source_config_corpus_other_workspace"
                cross_conflict = True
            else:
                candidates.append(
                    {
                        "corpus_id": str(source.explicit_corpus_id),
                        "via": "source_config",
                    }
                )

        if source.workspace_id is None or source.workspace_exists is None:
            classification = "orphan"
            reason = "workspace_missing"
        elif not cross_conflict:
            resolved = resolutions.get(UUID(sid))
            if resolved is not None:
                candidate = index.get(str(resolved))
                if (
                    candidate is None
                    or candidate["organization_id"] != str(organization_id)
                    or candidate["workspace_id"] != swid
                ):
                    classification = "cross_scope_conflict"
                    reason = "operator_corpus_out_of_scope"
                else:
                    candidates = [
                        {"corpus_id": str(resolved), "via": "operator_selected"}
                    ]
            if not reason:
                unique: dict[str, dict[str, str]] = {}
                for item in candidates:
                    unique[item["corpus_id"]] = item
                candidates = list(unique.values())
                if len(candidates) > 1:
                    classification = "ambiguous"
                    reason = "multiple_explicit_corpus_candidates"
                elif len(candidates) == 1:
                    classification = "determinate"
                    reason = candidates[0]["via"]
                elif not corpora_by_workspace.get(swid or ""):
                    classification = "orphan"
                    reason = "no_corpus_in_workspace"
                else:
                    classification = "needs_resolution"
                    reason = "no_explicit_link"
                    candidates = [
                        {"corpus_id": item["corpus_id"], "via": "workspace_candidate"}
                        for item in corpora_by_workspace[swid or ""]
                    ]

        row = {
            "record_type": "legacy_source",
            "plan_id": effective_plan_id,
            "organization_id": str(organization_id),
            "workspace_id": swid,
            "source_id": sid,
            "source_status": str(source.status),
            "knowledge_base_id": str(source.knowledge_base_id)
            if source.knowledge_base_id
            else None,
            "current_corpus_id": None,
            "candidate_corpus_id": (
                candidates[0]["corpus_id"]
                if classification == "determinate" and len(candidates) == 1
                else None
            ),
            "candidates": candidates,
            "classification": classification,
            "decision": "proposed" if classification == "determinate" else "blocked",
            "reason": reason,
            "name_sha256": _sha256_text(str(source.name)),
            "source_updated_at": source.updated_at.isoformat(),
        }
        if include_names:
            row["source_name"] = str(source.name)
        rows.append(row)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "plan_id": effective_plan_id,
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "generated_at": generated_at,
        "limit": limit,
        "rows": rows,
        "counts": counts,
        "checksum": plan_checksum(rows),
    }


async def apply_plan(
    *,
    rows: list[dict[str, Any]],
    plan_id: str,
    actor: str,
) -> dict[str, Any]:
    """Aplica solo filas proposed con CAS y journal. Idempotente."""

    if not actor.strip():
        raise ValueError("actor es obligatorio")
    applied = 0
    skipped = 0
    conflicts = 0
    session = await get_async_session()
    try:
        for row in rows:
            if row.get("plan_id") != plan_id:
                raise ValueError("el plan contiene otra plan_id")
            if row.get("decision") != "proposed" or not row.get("candidate_corpus_id"):
                skipped += 1
                continue
            sid = str(row["source_id"])
            oid = str(row["organization_id"])
            cid = str(row["candidate_corpus_id"])
            existing = (
                await session.execute(
                    text(
                        "SELECT status FROM legacy_source_corpus_journal "
                        "WHERE plan_id = :pid AND source_id = :sid"
                    ),
                    {"pid": plan_id, "sid": sid},
                )
            ).fetchone()
            if existing is not None:
                skipped += 1
                continue
            updated = (
                await session.execute(
                    text(
                        "UPDATE kb_sources SET corpus_id = :cid, updated_at = now() "
                        "WHERE id = :sid AND organization_id = :oid "
                        "  AND corpus_id IS NULL "
                        "  AND workspace_id IS NOT DISTINCT FROM :wid "
                        "  AND knowledge_base_id IS NOT DISTINCT FROM :kid "
                        "RETURNING updated_at"
                    ),
                    {
                        "cid": cid,
                        "sid": sid,
                        "oid": oid,
                        "wid": row.get("workspace_id"),
                        "kid": row.get("knowledge_base_id"),
                    },
                )
            ).fetchone()
            if updated is None:
                current = (
                    await session.execute(
                        text(
                            "SELECT corpus_id FROM kb_sources "
                            "WHERE id = :sid AND organization_id = :oid"
                        ),
                        {"sid": sid, "oid": oid},
                    )
                ).fetchone()
                if current is not None and str(current.corpus_id) == cid:
                    skipped += 1
                else:
                    conflicts += 1
                await session.commit()
                continue
            before_updated = row.get("source_updated_at")
            if isinstance(before_updated, str) and before_updated:
                before_updated = datetime.fromisoformat(before_updated)
            await session.execute(
                text(
                    "INSERT INTO legacy_source_corpus_journal "
                    "(plan_id, plan_sha256, organization_id, workspace_id, source_id, "
                    " knowledge_base_id, before_corpus_id, after_corpus_id, "
                    " before_updated_at, after_updated_at, actor, status) "
                    "VALUES (:pid, :sha, :oid, :wid, :sid, :kid, NULL, :cid, "
                    "        :before_updated, :after_updated, :actor, 'applied') "
                    "ON CONFLICT (plan_id, source_id) DO NOTHING"
                ),
                {
                    "pid": plan_id,
                    "sha": str(row.get("_plan_sha256") or ""),
                    "oid": oid,
                    "wid": row.get("workspace_id"),
                    "sid": sid,
                    "kid": row.get("knowledge_base_id"),
                    "cid": cid,
                    "before_updated": before_updated,
                    "after_updated": updated.updated_at,
                    "actor": actor[:120],
                },
            )
            await session.commit()
            applied += 1
    finally:
        await session.close()
    return {
        "plan_id": plan_id,
        "applied": applied,
        "skipped": skipped,
        "conflicts": conflicts,
    }


async def rollback_plan(*, plan_id: str, actor: str) -> dict[str, Any]:
    """Revierte solo si nadie modificó la fuente desde el apply."""

    if not actor.strip():
        raise ValueError("actor es obligatorio")
    reverted = 0
    conflicts = 0
    session = await get_async_session()
    try:
        entries = (
            await session.execute(
                text(
                    "SELECT id, organization_id, source_id, before_corpus_id, "
                    "       after_corpus_id, after_updated_at "
                    "FROM legacy_source_corpus_journal "
                    "WHERE plan_id = :pid AND status = 'applied' "
                    "ORDER BY created_at ASC"
                ),
                {"pid": plan_id},
            )
        ).fetchall()
        for entry in entries:
            updated = (
                await session.execute(
                    text(
                        "UPDATE kb_sources SET corpus_id = :before, updated_at = now() "
                        "WHERE id = :sid AND organization_id = :oid "
                        "  AND corpus_id = :after AND updated_at = :after_updated "
                        "RETURNING updated_at"
                    ),
                    {
                        "before": entry.before_corpus_id,
                        "sid": str(entry.source_id),
                        "oid": str(entry.organization_id),
                        "after": entry.after_corpus_id,
                        "after_updated": entry.after_updated_at,
                    },
                )
            ).fetchone()
            if updated is None:
                conflicts += 1
                await session.execute(
                    text(
                        "UPDATE legacy_source_corpus_journal "
                        "SET status = 'conflict', conflict_reason = 'source_changed_since_apply' "
                        "WHERE id = :id"
                    ),
                    {"id": entry.id},
                )
            else:
                reverted += 1
                await session.execute(
                    text(
                        "UPDATE legacy_source_corpus_journal "
                        "SET status = 'rolled_back', rolled_back_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": entry.id},
                )
            await session.commit()
    finally:
        await session.close()
    return {
        "plan_id": plan_id,
        "rolled_back": reverted,
        "conflicts": conflicts,
        "actor": actor,
    }


def _parse_resolutions(values: list[str]) -> dict[UUID, UUID]:
    out: dict[UUID, UUID] = {}
    for value in values:
        try:
            source, corpus = value.split("=", 1)
            out[UUID(source)] = UUID(corpus)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "--resolve debe ser <source_id>=<corpus_id>"
            ) from exc
    return out


async def _cmd_plan(args: argparse.Namespace) -> int:
    plan = await build_plan(
        organization_id=args.org,
        workspace_id=args.workspace,
        source_id=args.source,
        limit=args.limit,
        include_names=args.include_names,
        resolutions=_parse_resolutions(args.resolve or []),
    )
    if args.out:
        checksum = write_plan(args.out, plan["rows"])
        plan["checksum"] = checksum
        plan["path"] = str(args.out)
    _print_json(plan)
    return 0


async def _cmd_apply(args: argparse.Namespace) -> int:
    if not args.approve:
        _print_json({"status": "blocked", "reason": "apply requiere --approve"})
        return 2
    rows = load_plan(args.plan_file)
    actual = plan_checksum(rows)
    if args.plan_sha256 and actual != args.plan_sha256:
        _print_json(
            {
                "status": "blocked",
                "reason": "checksum no coincide",
                "expected": args.plan_sha256,
                "actual": actual,
            }
        )
        return 2
    sha = args.plan_sha256 or actual
    for row in rows:
        row["_plan_sha256"] = sha
    result = await apply_plan(rows=rows, plan_id=args.plan_id, actor=args.actor)
    _print_json({**result, "plan_sha256": sha})
    return 0


async def _cmd_rollback(args: argparse.Namespace) -> int:
    if not args.approve:
        _print_json({"status": "blocked", "reason": "rollback requiere --approve"})
        return 2
    result = await rollback_plan(plan_id=args.plan_id, actor=args.actor)
    _print_json(result)
    return 1 if result["conflicts"] else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="P18.3 backfill de fuentes históricas sin corpus"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Dry-run: construir plan sin escribir kb_sources")
    plan.add_argument("--org", type=UUID, required=True)
    plan.add_argument("--workspace", type=UUID, default=None)
    plan.add_argument("--source", type=UUID, default=None)
    plan.add_argument("--limit", type=int, default=500)
    plan.add_argument("--out", type=Path, default=DEFAULT_OUT)
    plan.add_argument("--include-names", action="store_true")
    plan.add_argument(
        "--resolve",
        action="append",
        default=[],
        help="Selección humana explícita <source_id>=<corpus_id>",
    )

    apply = sub.add_parser("apply", help="Aplicar plan aprobado con CAS + journal")
    apply.add_argument("--plan-file", type=Path, required=True)
    apply.add_argument("--plan-id", required=True)
    apply.add_argument("--plan-sha256", default=None)
    apply.add_argument("--actor", default="operator")
    apply.add_argument("--approve", action="store_true")

    rollback = sub.add_parser("rollback", help="Revertir un plan aplicado")
    rollback.add_argument("--plan-id", required=True)
    rollback.add_argument("--actor", default="operator")
    rollback.add_argument("--approve", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "plan":
        return asyncio.run(_cmd_plan(args))
    if args.command == "apply":
        return asyncio.run(_cmd_apply(args))
    if args.command == "rollback":
        return asyncio.run(_cmd_rollback(args))
    return 2


if __name__ == "__main__":
    sys.exit(main())
