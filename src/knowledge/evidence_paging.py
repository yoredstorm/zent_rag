# =============================================================================
# Evidence ledger paging - cursor tipado y orden total estable
# =============================================================================
# P18.3-06. El orden observable del Explorador es:
#   strength DESC NULLS LAST, created_at DESC, id ASC
#
# Un cursor no es "la última fila menos que el predicado": para un ORDER BY
# descendente con desempate ascendente la comparación lexicográfica mixta debe
# respetar la dirección de cada columna. Este módulo encapsula ese contrato y
# el codec versionado del cursor. No es un ledger nuevo: lee el existente.
# =============================================================================
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EVIDENCE_ORDER_SQL = "strength DESC NULLS LAST, created_at DESC, id ASC"
EVIDENCE_CURSOR_VERSION = 1
MAX_EVIDENCE_PAGE_SIZE = 5000

_CURSOR_PREDICATE_SQL = """
    AND (
        CAST(:has_cursor AS boolean) = false
        OR (
            CASE
                WHEN CAST(:c_strength AS double precision) IS NULL THEN (
                    strength IS NULL
                    AND (
                        created_at < CAST(:c_created AS timestamptz)
                        OR (
                            created_at = CAST(:c_created AS timestamptz)
                            AND id > CAST(:c_id AS uuid)
                        )
                    )
                )
                WHEN strength IS NULL THEN true
                WHEN strength < CAST(:c_strength AS double precision) THEN true
                WHEN strength = CAST(:c_strength AS double precision)
                     AND created_at < CAST(:c_created AS timestamptz) THEN true
                WHEN strength = CAST(:c_strength AS double precision)
                     AND created_at = CAST(:c_created AS timestamptz)
                     AND id > CAST(:c_id AS uuid) THEN true
                ELSE false
            END
        )
    )
"""

_EVIDENCE_SELECT_SQL = """
    SELECT id, canonical_id, page, section_path, excerpt, locator,
           evidence_type, strength, created_at
    FROM evidence_ledger
    WHERE organization_id = :oid AND source_id = :sid
"""


@dataclass(frozen=True)
class EvidenceCursor:
    """Posición exacta dentro del orden observable del ledger."""

    strength: float | None
    created_at: datetime
    evidence_id: UUID

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at del cursor debe incluir zona horaria")


@dataclass
class EvidencePage:
    rows: list[dict[str, Any]]
    total: int
    returned: int
    limit: int
    next_cursor: EvidenceCursor | None
    has_more: bool
    read_scope: dict[str, str | None]


def encode_evidence_cursor(cursor: EvidenceCursor) -> str:
    payload = {
        "v": EVIDENCE_CURSOR_VERSION,
        "s": cursor.strength,
        "t": cursor.created_at.isoformat(),
        "id": str(cursor.evidence_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_evidence_cursor(token: str) -> EvidenceCursor:
    if not token or len(token) > 512:
        raise ValueError("cursor inválido")
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception as exc:  # noqa: BLE001 - cualquier token corrupto es 400
        raise ValueError("cursor inválido") from exc
    if not isinstance(payload, dict) or payload.get("v") != EVIDENCE_CURSOR_VERSION:
        raise ValueError("versión de cursor no soportada")
    strength = payload.get("s")
    if strength is not None and not isinstance(strength, (int, float)):
        raise ValueError("strength del cursor inválida")
    try:
        created_at = datetime.fromisoformat(str(payload.get("t")))
        evidence_id = UUID(str(payload.get("id")))
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor inválido") from exc
    if created_at.tzinfo is None:
        raise ValueError("cursor sin zona horaria")
    return EvidenceCursor(
        strength=float(strength) if strength is not None else None,
        created_at=created_at,
        evidence_id=evidence_id,
    )


async def count_evidence(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_id: UUID,
) -> int:
    total = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM evidence_ledger "
                "WHERE organization_id = :oid AND source_id = :sid"
            ),
            {"oid": str(organization_id), "sid": str(source_id)},
        )
    ).scalar_one()
    return int(total or 0)


async def fetch_evidence_page(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_id: UUID,
    cursor: EvidenceCursor | None = None,
    limit: int = 1000,
) -> EvidencePage:
    """Lee una página sin duplicados ni omisiones por empate.

    No abre una transacción larga: si una fila se inserta o borra entre
    páginas, el total puede cambiar. El cursor garantiza que las filas que
    permanecen se recorran una sola vez; las escrituras concurrentes se
    describen en ``read_scope`` (``snapshot_consistency=false``).
    """

    if limit < 1 or limit > MAX_EVIDENCE_PAGE_SIZE:
        raise ValueError(f"limit debe estar entre 1 y {MAX_EVIDENCE_PAGE_SIZE}")
    params: dict[str, Any] = {
        "oid": str(organization_id),
        "sid": str(source_id),
        "has_cursor": cursor is not None,
        "c_strength": cursor.strength if cursor else None,
        "c_created": cursor.created_at if cursor else None,
        "c_id": str(cursor.evidence_id) if cursor else None,
        "limit_plus_one": limit + 1,
    }
    rows = (
        await session.execute(
            text(
                _EVIDENCE_SELECT_SQL
                + _CURSOR_PREDICATE_SQL
                + " ORDER BY "
                + EVIDENCE_ORDER_SQL
                + " LIMIT :limit_plus_one"
            ),
            params,
        )
    ).fetchall()
    has_more = len(rows) > limit
    page_rows = [dict(row._mapping) for row in rows[:limit]]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = EvidenceCursor(
            strength=float(last["strength"]) if last["strength"] is not None else None,
            created_at=last["created_at"],
            evidence_id=UUID(str(last["id"])),
        )
    total = await count_evidence(
        session, organization_id=organization_id, source_id=source_id
    )
    return EvidencePage(
        rows=page_rows,
        total=total,
        returned=len(page_rows),
        limit=limit,
        next_cursor=next_cursor,
        has_more=has_more,
        read_scope={
            "organization_id": str(organization_id),
            "source_id": str(source_id),
            "snapshot_consistency": "false",
            "order": EVIDENCE_ORDER_SQL,
        },
    )
