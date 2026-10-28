#!/usr/bin/env python
"""P18.1-00 — Snapshot read-only del baseline de conocimiento.

No modifica conocimiento. Guarda el estado real que se usará para comparar
antes/después de la corrección: fuentes, perfiles, objetos, evidencia, reglas
y conteos de calidad. Los fixtures son sintéticos y seguros de versionar.

Uso:
    python scripts/p18_1_baseline.py --output artifacts/certification/p18-1/baseline.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path("tests/fixtures/p18_1")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


async def _collect() -> dict:
    from sqlalchemy import text

    from src.core.config import get_settings
    from src.infrastructure.postgres.session import get_async_session

    settings = get_settings()
    session = await get_async_session()
    try:
        async def rows(sql: str, params: dict | None = None) -> list[dict]:
            result = await session.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result.fetchall()]

        sources = await rows(
            "SELECT s.id, s.name, s.type, s.status, s.workspace_id, s.corpus_id, "
            "d.id AS document_id, "
            "d.metadata->'understanding'->'profile'->>'document_type' AS document_type, "
            "d.metadata->'understanding'->'profile'->>'document_genre' AS document_genre, "
            "d.metadata->'understanding'->'profile'->>'genre_confidence' AS genre_confidence, "
            "d.metadata->'understanding'->'profile'->>'profile_confidence' AS profile_confidence "
            "FROM kb_sources s LEFT JOIN structured_documents d ON d.source_id = s.id "
            "ORDER BY s.created_at DESC LIMIT 500"
        )
        objects = await rows(
            "SELECT source_id, kind, domain, status, count(*) AS n, "
            "round(avg(confidence)::numeric, 4) AS avg_confidence "
            "FROM knowledge_canonical_objects GROUP BY source_id, kind, domain, status "
            "ORDER BY n DESC"
        )
        quality = await rows(
            "SELECT kind, severity, count(*) AS n FROM knowledge_ingestion_quality "
            "GROUP BY kind, severity ORDER BY n DESC"
        )
        evidence = await rows(
            "SELECT count(*) AS n, count(DISTINCT source_id) AS sources, "
            "count(*) FILTER (WHERE excerpt IS NULL OR excerpt = '') AS without_excerpt "
            "FROM evidence_ledger"
        )
        rules = await rows(
            "SELECT count(*) AS n, "
            "count(*) FILTER (WHERE metadata->>'claim_kind' IS NOT NULL) AS with_claim_kind "
            "FROM knowledge_canonical_objects WHERE kind = 'business_rule'"
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_head": _git_head(),
            "config": {
                "knowledge_model_enabled": settings.KNOWLEDGE_MODEL_ENABLED,
                "simple_ux_enabled": getattr(
                    settings, "KNOWLEDGE_SIMPLE_UX_ENABLED", None
                ),
                "embedding_model": getattr(settings, "EMBEDDING_MODEL", None),
                "retrieval_strategy": settings.RAG_RETRIEVAL_STRATEGY,
            },
            "fixtures": {
                path.name: _sha256(path)
                for path in sorted(FIXTURES.glob("*"))
                if path.is_file()
            },
            "sources": sources,
            "object_counts": objects,
            "quality_counts": quality,
            "evidence": evidence[0] if evidence else {},
            "rules": rules[0] if rules else {},
        }
    finally:
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/certification/p18-1/baseline.json",
    )
    args = parser.parse_args()
    payload = asyncio.run(_collect())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Baseline written to {output}")


if __name__ == "__main__":
    main()
