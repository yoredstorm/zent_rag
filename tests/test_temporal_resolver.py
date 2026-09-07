"""Phase 28A — Temporal resolver."""
from __future__ import annotations

from datetime import date

from src.intelligence.temporal import TemporalResolver


def test_hoy_is_current_not_past() -> None:
    r = TemporalResolver(today=date(2026, 9, 7))
    result = r.parse_time_phrase("hoy")
    assert result is not None
    assert result.scope == "current"
    assert result.start == date(2026, 9, 7)
    assert result.end == date(2026, 9, 7)

    ventas_hoy = r.parse_time_phrase("ventas de hoy")
    assert ventas_hoy is not None
    assert ventas_hoy.scope == "current"


def test_ayer_esta_semana_mes_pasado_q1_ytd_mtd() -> None:
    r = TemporalResolver(today=date(2026, 9, 7))
    assert r.parse_time_phrase("ayer").scope == "past"
    assert r.parse_time_phrase("ayer").start == date(2026, 9, 6)

    semana = r.parse_time_phrase("esta semana")
    assert semana.scope == "period"
    assert semana.start == date(2026, 9, 7)  # Monday

    mes = r.parse_time_phrase("mes pasado")
    assert mes.scope == "past"
    assert mes.start == date(2026, 8, 1)
    assert mes.end == date(2026, 8, 31)

    q1 = r.parse_time_phrase("Q1 2025")
    assert q1.scope == "quarter"
    assert q1.start == date(2025, 1, 1)
    assert q1.end == date(2025, 3, 31)

    ytd = r.parse_time_phrase("YTD")
    assert ytd.scope == "ytd"
    assert ytd.start == date(2026, 1, 1)

    mtd = r.parse_time_phrase("MTD")
    assert mtd.scope == "mtd"
    assert mtd.start == date(2026, 9, 1)


def test_resolve_version_as_of() -> None:
    r = TemporalResolver()
    versions = [
        {
            "version": 1,
            "name": "Active Customer v1",
            "effective_from": "2025-01-01",
            "effective_to": "2026-01-01",
            "rule": "180 days",
        },
        {
            "version": 2,
            "name": "Active Customer v2",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "rule": "90 days",
        },
    ]
    oct = r.resolve_version(versions, "2025-10-15")
    assert oct is not None
    assert oct["version"] == 1
    now = r.resolve_version(versions, date(2026, 9, 7))
    assert now["version"] == 2
    missing = r.resolve_version(versions, "2024-01-01")
    assert missing is None
