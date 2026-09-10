# =============================================================================
# Data Onboarding — unit tests for document fact extractors (reglas)
# =============================================================================
# Cubre extractores deterministas en isolation. El flujo E2E HTTP vive en
# tests/test_data_onboarding.py. El path LLM debe permanecer apagado bajo pytest.
# =============================================================================
from __future__ import annotations

import pytest

from src.platform.data_onboarding.document_facts import (
    _DATE_PATTERNS,
    _dedupe,
    _extract_amounts,
    _extract_clauses,
    _extract_dates,
    _extract_identifiers,
    _extract_parties,
    _fact,
    _llm_facts,
    _normalize_date,
    extract_document_facts,
)

_CONTRACT_TXT = """\
CONTRATO DE PRESTACIÓN DE SERVICIOS

Entre Acme SpA, RUT 76.123.456-7, en adelante "el Contratante", por una parte, \
y Consultora Beta Limitada, por la otra parte, se celebra el presente contrato.

Contacto: legal@acme.cl

PRIMERO: El presente contrato tiene vigencia desde el 15 de marzo de 2025 hasta el 14 de marzo de 2026.

SEGUNDO: El Contratante pagará un honorario mensual de CLP 1.500.000 a Consultora Beta Limitada.

# Renovación
El contrato se renovará automáticamente por períodos de 12 meses salvo aviso.

# Confidencialidad
Ambas partes mantendrán confidencial la información intercambiada durante la vigencia.
"""


def _normalized_dates(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            iso = _normalize_date(match)
            if iso:
                found.append(iso)
    return found


def _values(facts: list[dict], fact_type: str | None = None) -> list[str]:
    if fact_type is None:
        return [f["value"] for f in facts]
    return [f["value"] for f in facts if f["fact_type"] == fact_type]


class TestDateExtraction:
    def test_spanish_day_month_year_normalizes_to_iso(self) -> None:
        assert _normalized_dates("firmado el 15 de marzo de 2025") == ["2025-03-15"]
        facts = _extract_dates("La fecha de firma es el 15 de marzo de 2025 en Santiago.")
        assert facts
        assert facts[0]["value"] == "2025-03-15"
        assert facts[0]["normalized_value"] == "2025-03-15"
        assert facts[0]["fact_type"] == "date"
        assert facts[0]["source"] == "rules"

    def test_numeric_dmy_and_iso_normalizes_to_iso(self) -> None:
        assert _normalized_dates("inicio 15/03/2025") == ["2025-03-15"]
        assert _normalized_dates("inicio 15-03-2025") == ["2025-03-15"]
        assert _normalized_dates("inicio 2025-03-15") == ["2025-03-15"]

        slash = _extract_dates("Vigencia desde el 15/03/2025.")
        iso = _extract_dates("Vigencia desde el 2025-03-15.")
        assert _values(slash) == ["2025-03-15"]
        assert _values(iso) == ["2025-03-15"]

    def test_forbidden_clause_and_folio_context_is_not_a_date(self) -> None:
        folio = _extract_dates("El folio 15/03/2025 identifica el anexo, no una fecha.")
        clause = _extract_dates("Según la cláusula 12/04/2024 del anexo no hay vigencia.")
        art = _extract_dates("Ver art. 01/02/2023 del código civil adjunto.")
        assert folio == []
        assert clause == []
        assert art == []

        real = _extract_dates("Firmado el 15/03/2025 en Santiago de Chile.")
        assert _values(real) == ["2025-03-15"]


class TestAmountExtraction:
    def test_clp_usd_uf_and_period_keywords(self) -> None:
        clp = _extract_amounts(
            "El Contratante pagará un honorario mensual de CLP 1.500.000 a la consultora"
        )
        assert clp
        assert clp[0]["fact_type"] == "amount"
        assert clp[0]["value"] == "CLP 1.500.000"
        assert clp[0]["normalized_value"] == "1500000"
        assert "CLP" in clp[0]["key"]
        assert "mensual" in clp[0]["key"].lower()

        usd = _extract_amounts("El precio acordado es USD 2.500 por mes.")
        assert usd
        assert usd[0]["value"] == "USD 2.500"
        assert "USD" in usd[0]["key"]
        assert "por mes" in usd[0]["key"].lower()

        uf = _extract_amounts("El canon de arriendo es UF 32 anual.")
        assert uf
        assert uf[0]["value"] == "UF 32"
        assert "UF" in uf[0]["key"]
        assert "anual" in uf[0]["key"].lower()


class TestPartyExtraction:
    def test_parte_a_and_parte_b_from_entre_por_la_otra_parte(self) -> None:
        text = (
            "Entre Acme SpA, RUT 76.123.456-7, en adelante el Contratante, "
            "por una parte, y Consultora Beta Limitada, por la otra parte, "
            "se celebra el presente contrato."
        )
        facts = _extract_parties(text)
        by_key = {f["key"]: f["value"] for f in facts}
        assert by_key["Parte A"] == "Acme SpA"
        assert by_key["Parte B"] == "Consultora Beta Limitada"
        assert all(f["fact_type"] == "party" for f in facts)


class TestIdentifierExtraction:
    def test_chilean_rut_and_email(self) -> None:
        text = (
            "Proveedor RUT 76.123.456-7 (también 12.345.678-K). "
            "Escribir a legal@acme.cl o ops+docs@beta.cl para soporte"
        )
        facts = _extract_identifiers(text)
        ruts = [f["value"] for f in facts if f["key"] == "RUT"]
        emails = [f["value"] for f in facts if f["key"] == "Correo"]
        assert "76.123.456-7" in ruts
        assert "12.345.678-K" in ruts
        assert "legal@acme.cl" in emails
        assert "ops+docs@beta.cl" in emails
        assert all(f["fact_type"] == "identifier" for f in facts)
        assert all(f["confidence"] == "high" for f in facts)


class TestClauseExtraction:
    def test_headings_renovacion_and_confidencialidad(self) -> None:
        text = (
            "Cláusulas del contrato\n"
            "Renovación automática\n"
            "El contrato se renovará cada 12 meses.\n"
            "Más texto.\n"
            "Confidencialidad\n"
            "Las partes no divulgarán información."
        )
        facts = _extract_clauses(
            text, ["Renovación automática", "Confidencialidad", "Objeto"]
        )
        values = _values(facts, "clause")
        assert "Renovación automática" in values
        assert "Confidencialidad" in values
        assert "Objeto" not in values
        assert all("Cláusula de" in f["key"] for f in facts)


class TestDedupe:
    def test_identical_facts_are_dropped(self) -> None:
        first = _fact("date", "Fecha", "2025-03-15", evidence="uno")
        duplicate = _fact("date", "Fecha", "2025-03-15", evidence="dos")
        other_key = _fact("date", "Fecha de inicio", "2025-03-15")
        out = _dedupe([first, duplicate, other_key, first])
        assert len(out) == 2
        assert (out[0]["key"], out[0]["value"]) == ("Fecha", "2025-03-15")
        assert (out[1]["key"], out[1]["value"]) == ("Fecha de inicio", "2025-03-15")


class TestExtractDocumentFacts:
    @pytest.mark.asyncio
    async def test_happy_path_spanish_contract_rules_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_calls: list[int] = []

        def _llm_must_stay_off(*_args, **_kwargs):
            llm_calls.append(1)
            raise AssertionError("LLM provider must not be used under pytest")

        monkeypatch.setattr("src.api.deps.get_llm_provider", _llm_must_stay_off)

        result = await extract_document_facts(
            _CONTRACT_TXT.encode("utf-8"), "contrato.txt"
        )
        facts = result["facts"]
        types = {f["fact_type"] for f in facts}
        assert result["text_ok"] is True
        assert result["text_len"] > 0
        assert "party" in types
        assert "date" in types
        assert "amount" in types
        assert "identifier" in types
        assert {f["source"] for f in facts} == {"rules"}
        assert llm_calls == []

        parties = {f["value"] for f in facts if f["fact_type"] == "party"}
        assert "Acme SpA" in parties
        assert "Consultora Beta Limitada" in parties
        dates = set(_values(facts, "date"))
        assert "2025-03-15" in dates
        assert "2026-03-14" in dates
        amounts = _values(facts, "amount")
        assert any("CLP" in v and "1.500.000" in v for v in amounts)
        identifiers = _values(facts, "identifier")
        assert "76.123.456-7" in identifiers
        assert "legal@acme.cl" in identifiers

    @pytest.mark.asyncio
    async def test_llm_facts_off_under_pytest_and_environment_test(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_calls: list[int] = []

        def _llm_must_stay_off(*_args, **_kwargs):
            llm_calls.append(1)
            raise AssertionError("LLM provider must not be used under pytest")

        monkeypatch.setattr("src.api.deps.get_llm_provider", _llm_must_stay_off)

        assert await _llm_facts("Entre Acme y Beta, honorario CLP 10.") == []
        assert llm_calls == []

        class _TestSettings:
            ENVIRONMENT = "test"
            LITELLM_API_KEY = "sk-not-used"
            LITELLM_API_BASE = "http://llm.example"

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr("src.core.config.get_settings", lambda: _TestSettings())
        assert await _llm_facts("texto con LITELLM configurado") == []
        assert llm_calls == []
