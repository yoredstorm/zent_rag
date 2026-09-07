# =============================================================================
# Catalog Embeddings — representaciones semánticas enriquecidas (Phase 27A)
# =============================================================================
# Embedding de objetos de catálogo: business name + description + columns /
# synonyms, nunca solo el nombre físico. El embedder se inyecta (callable).
# =============================================================================
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EmbedFn = Callable[[str], list[float]]


@dataclass
class CatalogEmbeddingRecord:
    """Registro en memoria de un embedding de catálogo."""

    object_type: str
    object_id: str
    text: str
    vector: list[float]


def _join_parts(*parts: str) -> str:
    return "\n".join(p for p in parts if p and str(p).strip())


def _list_field(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        raw = payload.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            return [raw] if raw.strip() else []
        if isinstance(raw, (list, tuple)):
            out: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    name = (
                        item.get("name")
                        or item.get("column_name")
                        or item.get("business_name")
                        or item.get("synonym")
                    )
                    if name:
                        out.append(str(name))
                else:
                    out.append(str(item))
            return out
    return []


class CatalogEmbeddingService:
    """Construye documentos enriquecidos y mantiene embeddings en memoria."""

    def __init__(self, embed_text: EmbedFn | None = None) -> None:
        self._embed_text: EmbedFn = embed_text or self._default_embed
        self._store: list[CatalogEmbeddingRecord] = []

    @staticmethod
    def _default_embed(text: str) -> list[float]:
        """Embedder determinista sin dependencias (hash bag-of-chars)."""
        if not text:
            return [0.0] * 8
        vec = [0.0] * 8
        for i, ch in enumerate(text.lower()):
            vec[i % 8] += (ord(ch) % 31) / 31.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [round(v / norm, 6) for v in vec]

    @property
    def store(self) -> list[CatalogEmbeddingRecord]:
        return self._store

    def embed_text(self, text: str) -> list[float]:
        return self._embed_text(text)

    def build_enriched_document(self, object_type: str, payload: dict[str, Any]) -> str:
        """Documento semántico: negocio + descripción + columnas/synonyms."""
        kind = (object_type or "").strip().lower()
        physical = str(
            payload.get("physical_name")
            or payload.get("name")
            or payload.get("qualified_name")
            or payload.get("column_name")
            or ""
        ).strip()
        business = str(
            payload.get("business_name")
            or payload.get("entity_name")
            or payload.get("display_name")
            or payload.get("metric_name")
            or payload.get("term")
            or ""
        ).strip()
        description = str(
            payload.get("description")
            or payload.get("table_comment")
            or payload.get("definition")
            or ""
        ).strip()
        columns = _list_field(payload, "columns", "column_names", "fields")
        synonyms = _list_field(payload, "synonyms", "aliases")
        mappings = _list_field(payload, "approved_mappings", "mappings")
        common_queries = _list_field(payload, "common_queries", "queries")

        sections: list[str] = [f"Object Type: {kind or 'unknown'}"]
        if physical:
            sections.append(f"Physical Name: {physical}")
        if business:
            sections.append(f"Business Name: {business}")
        if description:
            sections.append(f"Description: {description}")
        if columns:
            sections.append("Columns: " + ", ".join(columns))
        if synonyms:
            sections.append("Synonyms: " + ", ".join(synonyms))
        if mappings:
            sections.append("Approved mappings: " + ", ".join(mappings))
        if common_queries:
            sections.append("Common queries: " + ", ".join(common_queries))

        # Extra fields useful for metric / term / entity
        for key in ("formula", "expression", "grain", "currency_semantics"):
            val = payload.get(key)
            if val:
                sections.append(f"{key.replace('_', ' ').title()}: {val}")

        text = _join_parts(*sections)
        # Must never be only the physical name
        if business and business.lower() not in text.lower():
            text = _join_parts(text, f"Business Name: {business}")
        return text

    def index_object(
        self,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
    ) -> CatalogEmbeddingRecord:
        text = self.build_enriched_document(object_type, payload)
        vector = self.embed_text(text)
        record = CatalogEmbeddingRecord(
            object_type=object_type,
            object_id=str(object_id),
            text=text,
            vector=vector,
        )
        self._store.append(record)
        return record

    def list_embeddings(
        self, *, object_type: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._store
        if object_type:
            rows = [r for r in rows if r.object_type == object_type]
        return [
            {
                "object_type": r.object_type,
                "object_id": r.object_id,
                "text": r.text,
                "vector": list(r.vector),
            }
            for r in rows
        ]
