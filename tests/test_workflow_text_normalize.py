# =============================================================================
# Nodo "Normalizar texto" — herramienta determinista para preparar búsquedas.
# =============================================================================
from __future__ import annotations

from src.platform.workflows.nodes import registry
from src.platform.workflows.parameters import node_business_schema
from src.platform.workflows.text_normalize import normalize_text


def test_product_query_removes_question_and_sales_words() -> None:
    result = normalize_text("tienes bicicleta en venta?")
    assert result["text"] == "bicicleta"
    assert result["terms"] == ["bicicleta"]
    assert result["status"] == "OK"
    assert "venta" in result["removed"]


def test_product_query_removes_configured_phrases() -> None:
    result = normalize_text(
        "busco bicicleta de montaña",
        ignore_phrases="de montaña",
    )
    assert result["text"] == "bicicleta"


def test_product_query_empty_terms() -> None:
    result = normalize_text("tienes en venta?")
    assert result["text"] == ""
    assert result["status"] == "EMPTY"


def test_email_mode_extracts_address() -> None:
    result = normalize_text("mi correo es ANA@EXAMPLE.COM", mode="email")
    assert result["text"] == "ana@example.com"
    assert result["terms"] == ["ana@example.com"]


def test_name_mode_preserves_case_and_accents_when_configured() -> None:
    result = normalize_text(
        "  Juan   Pérez  ",
        mode="name",
        lowercase=False,
        strip_accents=False,
    )
    assert result["text"] == "Juan Pérez"


def test_free_mode_only_collapses_spaces() -> None:
    result = normalize_text("  Hola,   quiero arroz  ", mode="free")
    assert result["text"] == "hola, quiero arroz"
    assert result["terms"] == ["hola,", "quiero", "arroz"]


def test_max_terms_limits_terms_but_not_text() -> None:
    result = normalize_text("uno dos tres cuatro", mode="free", max_terms=2)
    assert result["text"] == "uno dos tres cuatro"
    assert result["terms"] == ["uno", "dos"]


def test_text_normalize_is_registered_and_has_business_schema() -> None:
    node = registry.get("text_normalize")
    assert node is not None
    assert node.business_name == "Normalizar texto"
    assert node.category == "data"
    assert node.simulation_supported is True

    schema = node_business_schema("text_normalize")
    assert schema is not None
    assert schema.label == "Normalizar texto"
    assert {"text", "mode", "ignore_phrases", "lowercase", "strip_accents", "max_terms"} <= {
        parameter.key for parameter in schema.parameters
    }
    assert {"text", "terms", "original", "removed", "status", "mode"} <= {
        output.key for output in schema.outputs
    }
