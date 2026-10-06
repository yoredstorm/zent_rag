#!/usr/bin/env python
# =============================================================================
# Rules backfill — reglas canónicas para documentos indexados antes del
# Semantic Rule Compiler (sin re-embeddings, idempotente).
#
# Uso:
#   python -m src.scripts.rules_backfill --org <uuid> --dry-run
#   python -m src.scripts.rules_backfill --org <uuid> --limit 200
#   python -m src.scripts.rules_backfill --org <uuid> --document <uuid>
#   python -m src.scripts.rules_backfill --org <uuid> --source <uuid>
#   python -m src.scripts.rules_backfill --org <uuid> --kb <uuid>
#
# La autoridad sigue siendo knowledge_canonical_objects; este comando solo
# recompila y enlaza. Para reingesta completa usar src.scripts.knowledge_reprocess.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from src.knowledge.rule_compiler.backfill import backfill_documents


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def _main(args: argparse.Namespace) -> None:
    organization_id = UUID(args.org)
    document_id = UUID(args.document) if args.document else None
    source_id = UUID(args.source) if args.source else None
    knowledge_base_id = UUID(args.kb) if args.kb else None
    report = await backfill_documents(
        organization_id,
        document_id=document_id,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    _print(
        "Rules backfill "
        f"{'(dry-run)' if args.dry_run else ''}: "
        f"documentos={report.documents_scanned} "
        f"backfilled={report.documents_backfilled} "
        f"rules={report.rules_persisted} "
        f"created={report.rules_created} "
        f"reinforced={report.rules_reinforced} "
        f"canonical_rules={report.canonical_rules} "
        f"payloads={report.payloads_updated} "
        f"errores={len(report.errors)}"
    )
    for error in report.errors[:8]:
        _print(f"[ERROR] {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical rules backfill")
    parser.add_argument("--org", required=True, help="Organization UUID")
    parser.add_argument("--document", help="Document UUID (scope puntual)")
    parser.add_argument("--source", help="Source UUID")
    parser.add_argument("--kb", help="Knowledge base UUID")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
