"""Phase 27A — Catalog embeddings."""
from __future__ import annotations

from src.catalog.embeddings import CatalogEmbeddingService


def test_enriched_document_includes_business_not_only_physical() -> None:
    svc = CatalogEmbeddingService()
    text = svc.build_enriched_document(
        "table",
        {
            "physical_name": "A1672",
            "business_name": "Sales Transaction",
            "description": "Cabecera de ventas legacy",
            "columns": ["CCUST", "FPROC", "TRNCU"],
            "synonyms": ["venta", "sale"],
        },
    )
    assert "A1672" in text
    assert "Sales Transaction" in text
    assert "Cabecera de ventas legacy" in text
    assert "CCUST" in text
    assert "venta" in text
    assert text.strip() != "A1672"


def test_column_entity_metric_term_documents() -> None:
    svc = CatalogEmbeddingService()
    col = svc.build_enriched_document(
        "column",
        {
            "physical_name": "CCUST",
            "business_name": "Customer Id",
            "description": "Código de cliente",
            "synonyms": ["cliente_id"],
        },
    )
    assert "Customer Id" in col and "cliente_id" in col

    ent = svc.build_enriched_document(
        "entity",
        {
            "business_name": "Customer",
            "description": "Cliente empresarial",
            "synonyms": ["cliente", "account"],
        },
    )
    assert "Customer" in ent and "cliente" in ent

    metric = svc.build_enriched_document(
        "metric",
        {
            "metric_name": "Gross Margin",
            "definition": "Revenue - COGS",
            "formula": "rev - cogs",
            "synonyms": ["margen_bruto"],
        },
    )
    assert "Gross Margin" in metric and "margen_bruto" in metric

    term = svc.build_enriched_document(
        "term",
        {
            "term": "cliente activo",
            "definition": "Compra en 90 días",
            "synonyms": ["active_customer"],
        },
    )
    assert "cliente activo" in term and "active_customer" in term


def test_injectable_embedder_and_store() -> None:
    calls: list[str] = []

    def fake_embed(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0, 0.0]

    svc = CatalogEmbeddingService(embed_text=fake_embed)
    rec = svc.index_object(
        "table",
        "t1",
        {
            "physical_name": "A1672",
            "business_name": "Sales",
            "description": "desc",
            "columns": ["X"],
        },
    )
    assert rec.vector == [1.0, 0.0, 0.0]
    assert calls and "Sales" in calls[0]
    listed = svc.list_embeddings()
    assert len(listed) == 1
    assert listed[0]["object_type"] == "table"
    assert listed[0]["object_id"] == "t1"
    assert "text" in listed[0] and "vector" in listed[0]
    assert svc.embed_text("hola") == [1.0, 0.0, 0.0]
