# =============================================================================
# Migración Qdrant — dense anónimo -> vectores nombrados (dense + sparse)
# =============================================================================
# Recrea la colección rag_documents con vectores nombrados y re-indexa los
# puntos existentes: el vector dense se copia tal cual y el sparse se
# computa del payload content (BM25). NO requiere llamadas a LLM.
#
# Flujo:
#   1. Verifica que la colección existe y aún no usa vectores nombrados.
#   2. Copia todos los puntos a rag_documents_hybrid (dense + sparse).
#   3. Verifica conteos; borra la colección vieja.
#   4. Recrea rag_documents con vectores nombrados y copia desde la temporal.
#      (Qdrant no soporta rename vía HTTP, por eso el segundo pase.)
#   5. Borra la temporal salvo --keep-backup.
#
# Uso (stack docker arriba):
#   python src/scripts/migrate_qdrant_hybrid.py [--batch-size 200] [--keep-backup]
# =============================================================================
from __future__ import annotations

import argparse
import asyncio

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qdrant_models

from src.core.config import get_settings
from src.infrastructure.qdrant.bm25 import encode_sparse, to_sparse_payload
from src.infrastructure.qdrant.vector_store import RAG_DOCUMENTS_COLLECTION

_TEMP_COLLECTION = f"{RAG_DOCUMENTS_COLLECTION}_hybrid"


def _sparse_index_params() -> qdrant_models.SparseVectorParams:
    index_params = None
    if hasattr(qdrant_models, "SparseIndexParams") and hasattr(
        qdrant_models, "Datatype"
    ):
        index_params = qdrant_models.SparseIndexParams(
            on_disk=False,
            datatype=qdrant_models.Datatype.FLOAT32,
        )
    kwargs: dict[str, object] = {"index": index_params}
    if hasattr(qdrant_models, "Modifier"):
        kwargs["modifier"] = qdrant_models.Modifier.IDF
    return qdrant_models.SparseVectorParams(**kwargs)  # type: ignore[arg-type]


def _named_vectors_config(dimension: int) -> dict[str, object]:
    return {
        "dense": qdrant_models.VectorParams(
            size=dimension,
            distance=qdrant_models.Distance.COSINE,
        ),
        "sparse": _sparse_index_params(),
    }


async def _collection_uses_named_vectors(client: AsyncQdrantClient) -> bool:
    info = await client.get_collection(RAG_DOCUMENTS_COLLECTION)
    return getattr(info.config.params.vectors, "size", None) is None


def _record_to_struct(record: qdrant_models.Record) -> qdrant_models.PointStruct | None:
    """Convierte un Record (dense anónimo o nombrado) en PointStruct nombrado."""
    payload = dict(record.payload or {})
    vector = record.vector
    if isinstance(vector, dict):
        dense = vector.get("dense")
    else:
        dense = vector
    if dense is None or not isinstance(dense, list):
        return None
    tf = encode_sparse(payload.get("content", ""))
    indices, values = to_sparse_payload(tf)
    return qdrant_models.PointStruct(
        id=record.id,
        vector={
            "dense": dense,
            "sparse": qdrant_models.SparseVector(indices=indices, values=values),
        },
        payload=payload,
    )


async def _copy_points(
    client: AsyncQdrantClient,
    src: str,
    dst: str,
    batch_size: int,
) -> tuple[int, int]:
    """Copia todos los puntos de src a dst computando sparse en el camino."""
    scanned = 0
    migrated = 0
    next_offset: object | None = None
    while True:
        page, next_offset = await client.scroll(
            collection_name=src,
            scroll_filter=None,
            limit=batch_size,
            offset=next_offset,  # type: ignore[arg-type]
            with_payload=True,
            with_vectors=True,
        )
        if not page:
            break
        structs = []
        for record in page:
            scanned += 1
            struct = _record_to_struct(record)
            if struct is None:
                print(f"WARN: point {record.id} has no dense vector, skipping")
                continue
            structs.append(struct)
            migrated += 1
        if structs:
            await client.upsert(collection_name=dst, points=structs, wait=True)
        if next_offset is None:
            break
        print(f"progress: scanned={scanned} migrated={migrated}")
    return scanned, migrated


async def migrate_collection(batch_size: int, keep_backup: bool) -> dict:
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
        timeout=int(settings.QDRANT_TIMEOUT_SECONDS),
        check_compatibility=False,
    )
    try:
        if not await client.collection_exists(RAG_DOCUMENTS_COLLECTION):
            print(f"Collection {RAG_DOCUMENTS_COLLECTION} does not exist. Nothing to migrate.")
            return {"collection": RAG_DOCUMENTS_COLLECTION, "migrated": 0, "scanned": 0}

        if await _collection_uses_named_vectors(client):
            print("Collection already uses named vectors. Nothing to do.")
            return {"collection": RAG_DOCUMENTS_COLLECTION, "migrated": 0, "scanned": 0}

        if await client.collection_exists(_TEMP_COLLECTION):
            await client.delete_collection(_TEMP_COLLECTION)

        await client.create_collection(
            collection_name=_TEMP_COLLECTION,
            vectors_config=_named_vectors_config(settings.VECTOR_DIMENSION),  # type: ignore[arg-type]
        )

        scanned, migrated = await _copy_points(
            client, RAG_DOCUMENTS_COLLECTION, _TEMP_COLLECTION, batch_size
        )

        old_count = await client.count(RAG_DOCUMENTS_COLLECTION, exact=True)
        new_count = await client.count(_TEMP_COLLECTION, exact=True)
        if old_count.count != new_count.count:
            await client.delete_collection(_TEMP_COLLECTION)
            raise RuntimeError(
                f"Count mismatch after reindex: old={old_count.count} new={new_count.count}"
            )

        await client.delete_collection(RAG_DOCUMENTS_COLLECTION)
        await client.create_collection(
            collection_name=RAG_DOCUMENTS_COLLECTION,
            vectors_config=_named_vectors_config(settings.VECTOR_DIMENSION),  # type: ignore[arg-type]
        )
        _, _ = await _copy_points(
            client, _TEMP_COLLECTION, RAG_DOCUMENTS_COLLECTION, batch_size
        )

        final_count = await client.count(RAG_DOCUMENTS_COLLECTION, exact=True)
        if final_count.count != old_count.count:
            raise RuntimeError(
                f"Final count mismatch: expected={old_count.count} got={final_count.count}"
            )

        if not keep_backup:
            await client.delete_collection(_TEMP_COLLECTION)

        return {
            "collection": RAG_DOCUMENTS_COLLECTION,
            "scanned": scanned,
            "migrated": migrated,
            "old_count": old_count.count,
            "new_count": final_count.count,
        }
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Qdrant collection to named vectors (dense + sparse)"
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--keep-backup",
        action="store_true",
        help="Keep the temporary collection after swap (debug).",
    )
    args = parser.parse_args()
    result = asyncio.run(migrate_collection(args.batch_size, args.keep_backup))
    print(result)


if __name__ == "__main__":
    main()
