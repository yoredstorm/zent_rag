"""Phase 28C — Advanced source conflict."""
from __future__ import annotations

from src.core.domain.intelligence import EvidenceObject, EvidenceType
from src.intelligence.source_conflict import SourceConflictAnalyzer


def test_cross_type_document_vs_sql_conflict() -> None:
    analyzer = SourceConflictAnalyzer()
    evidences = [
        EvidenceObject(
            type=EvidenceType.SQL_RESULT,
            source_name="ERP",
            value=120,
            metadata={"metric": "list_price"},
        ),
        EvidenceObject(
            type=EvidenceType.DOCUMENT_CHUNK,
            source_name="PDF Policy",
            value=100,
            content="price is 100",
            metadata={"metric": "list_price"},
        ),
    ]
    report = analyzer.analyze(evidences)
    assert report.has_conflict is True
    assert report.resolved is False
    assert report.status == "SOURCE_CONFLICT"
    kinds = {c.get("conflict_kind") for c in report.conflicts}
    assert "numeric" in kinds or "cross_type" in kinds


def test_authority_and_effective_dates_resolve() -> None:
    analyzer = SourceConflictAnalyzer()
    evidences = [
        {
            "source_name": "ERP",
            "evidence_type": "sql",
            "value": 120,
            "metric": "price",
        },
        {
            "source_name": "PDF",
            "evidence_type": "document",
            "value": 100,
            "metric": "price",
        },
    ]
    report = analyzer.analyze(
        evidences,
        authority={
            "source_name": "ERP",
            "authority_level": "authoritative",
            "priority": 1,
            "effective_from": "2020-01-01",
        },
        as_of="2026-01-01",
    )
    assert report.has_conflict is True
    assert report.resolved is True
    assert report.resolved_by == "ERP"
    assert report.status is None


def test_definition_vs_metric_conflict() -> None:
    analyzer = SourceConflictAnalyzer()
    report = analyzer.analyze(
        [
            {
                "source_name": "glossary",
                "evidence_type": "definition",
                "value": "purchase within 180 days",
                "claim_key": "active_customer",
            },
            {
                "source_name": "metrics",
                "evidence_type": "metric",
                "value": "purchase within 90 days",
                "claim_key": "active_customer",
            },
        ]
    )
    assert report.has_conflict
    assert any(c.get("conflict_kind") == "cross_type" for c in report.conflicts)
