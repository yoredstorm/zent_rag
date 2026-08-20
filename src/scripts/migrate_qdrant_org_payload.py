# =============================================================================
# Migración de payload Qdrant — tenant_id -> organization_id
# =============================================================================
# Reescribe el payload de la colección compartida rag_documents:
#   - "tenant_id": "<uuid>"  ->  "organization_id": "<uuid>"
#   - Los metadatos internos que referencien tenant_id se copian a
#     organization_id dentro de metadata.* (opcional, --include-metadata).
#
# Uso (con el stack docker arriba):
#   python src/scripts/migrate_qdrant_org_payload.py [--batch-size 200]
#
# Alternativa para volúmenes grandes: re-sync de ingestion (borra y
# re-indexa por organización), que evita el scan completo de la colección.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qdrant_models

from src.core.config import get_settings
from src.infrastructure.qdrant.vector_store import RAG_DOCUMENTS_COLLECTION

_ORG_KEY_OLD = "tenant_id"
_ORG_KEY_NEW = "organization_id"


async def migrate_collection(batch_size: int, limit: int | None) -> dict:
    settings = get_settings()
    api_key = (
        settings.QDRANT_API_KEY.get_secret_value()
        if settings.QDRANT_API_KEY
        else None
    )
    client = AsyncQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=api_key,
        https=settings.QDRANT_HTTPS,
        prefer_grpc=False,
        timeout=float(settings.QDRANT_TIMEOUT_SECONDS),
        check_compatibility=False,
    )
    try:
        if not await client.collection_exists(RAG_DOCUMENTS_COLLECTION):
            print(f"Collection {RAG_DOCUMENTS_COLLECTION} does not exist. Nothing to migrate.")
            return {"collection": RAG_DOCUMENTS_COLLECTION, "migrated": 0, "scanned": 0}

        scanned = 0
        migrated = 0
        next_offset: str | int | None = None

        while True:
            page: list[qdrant_models.Record] = []
            point_id = None
            page, next_offset = await client.scroll(
                collection_name=RAG_DOCUMENTS_COLLECTION,
                scroll_filter=None,
                limit=batch_size,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            if not page:
                break
            for record in page:
                scanned += 1
                if point_id is None and isinstance(next_offset, (str, int)):
                    pass
                payload = dict(record.payload or {})
                if _ORG_KEY_OLD not in payload:
                    continue
                old_value = payload.pop(_ORG_KEY_OLD)
                payload[_ORG_KEY_NEW] = old_value
                # Renombrar también dentro de metadata.* si existe
                metadata = payload.get("metadata")
                if isinstance(metadata, dict) and _ORG_KEY_OLD in metadata:
                    metadata[_ORG_KEY_NEW] = metadata.pop(_ORG_KEY_OLD)
                await client.set_payload(
                    collection_name=RAG_DOCUMENTS_COLLECTION,
                    payload=payload,
                    points=[record.id],
                )
                migrated += 1
            if next_offset is None:
                break
            if limit is not None and scanned >= limit:
                break
            print(
                f"progress: scanned={scanned} migrated={migrated} "
                f"next_offset={str(next_offset)[:40]}"
            )
        return {
            "collection": RAG_DOCUMENTS_COLLECTION,
            "scanned": scanned,
            "migrated": migrated,
        }
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Qdrant payload tenant_id -> organization_id"
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None, help="Max points to scan (dry-run parcial)")
    args = parser.parse_args()
    result = asyncio.run(migrate_collection(args.batch_size, args.limit))
    print(result)


if __name__ == "__main__":
    main()
