from src.platform.data_onboarding.document_facts import extract_document_facts_rules
from src.platform.data_onboarding.glimpses import analyze_percent, build_glimpses


def test_analyze_percent_phases_and_cap() -> None:
    phases = [
        {"id": "a", "state": "done"},
        {"id": "b", "state": "done"},
        {"id": "c", "state": "active"},
        {"id": "d", "state": "pending"},
    ]
    assert analyze_percent(phases, "ANALYZING") == 50
    assert analyze_percent(phases, "ANALYZING", job_progress=80) == 65
    assert analyze_percent(
        [{"id": "a", "state": "done"}, {"id": "b", "state": "done"}],
        "ANALYZING",
    ) == 90
    assert analyze_percent(phases, "REVIEW_REQUIRED") == 100


def test_build_glimpses_document_and_tabular() -> None:
    docs = build_glimpses(
        {
            "facts": [
                {"fact_type": "party", "key": "Empresa", "value": "AIR FRANCE"},
                {"fact_type": "amount", "key": "Monto", "value": "29733"},
            ]
        }
    )
    assert [g["text"] for g in docs] == [
        "Ah, Empresa es AIR FRANCE",
        "Vi un monto: 29733",
    ]
    table = build_glimpses(
        {
            "likely_entity": "Producto",
            "columns": [{"physical_name": "precio"}],
        }
    )
    assert [g["text"] for g in table] == ["Esto parece Producto", "Columna precio…"]


def test_extract_document_facts_rules_finds_parties() -> None:
    text = (
        b"Entre Acme SpA, RUT 76.123.456-7, por una parte, "
        b"y Consultora Beta Limitada, por la otra parte. "
        b"Honorario mensual de CLP 1.500.000. "
        b"Vigencia desde el 15 de marzo de 2025."
    )
    extracted = extract_document_facts_rules(text, "contrato.txt")
    types = {f.get("fact_type") for f in extracted["facts"]}
    assert "party" in types
    assert extracted["text_ok"] is True
