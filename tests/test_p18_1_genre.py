# =============================================================================
# P18.1-05 — Género documental y dominio separados
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.entities import _domain_from
from src.knowledge.understanding.views import source_profile


def _doc(text: str, *, title: str = "documento", kind=StructuredBlockKind.PARAGRAPH):
    blocks = [
        StructuredBlock(kind=kind, text=line, order=index)
        for index, line in enumerate(text.splitlines())
        if line.strip()
    ]
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="fixture.txt",
        title=title,
        content_hash="pending",
        blocks=tuple(blocks),
    )


def test_narrative_with_dialogue_and_numbers_is_not_technical() -> None:
    text = "\n".join(
        [
            "—¿Recuerdas? —preguntó el principito.",
            "—Sí —respondí—. El planeta era pequeño, el asteroide 52.",
            "—Debes cuidar la flor —dijo él.",
            "Yo no soy una hierba, respondió la rosa.",
            "—¿Y los baobabs? —preguntó.",
        ]
    )
    extracted = {
        "technical_fields": [
            {"name": "planeta?", "description": "..."},
            {"name": "recuerdas?", "description": "..."},
        ]
    }
    profile = source_profile(
        _doc(text, title="El principito"),
        extracted,
        {},
        filename="el_principito.pdf",
    )
    assert profile["document_genre"] == "narrative"
    assert profile["document_type"] == "narrative"
    assert profile["document_type"] != "technical_specification"
    assert profile["genre_confidence"] > 0.3


def test_real_technical_manual_keeps_technical_specification() -> None:
    text = "\n".join(
        [
            "Especificación del registro de tarifas",
            "Campo Fare Basis | posición 12 | longitud 8 | formato alfanumérico",
            "Campo Currency Code | posición 20 | longitud 3 | ISO 4217",
            "Campo Byte 105 | posición 105 | longitud 3 | máscara numérica",
            "El registro debe validar la máscara y la columna antes de publicar.",
        ]
    )
    extracted = {
        "technical_fields": [
            {"name": "Fare Basis", "description": "posición 12"},
            {"name": "Currency Code", "description": "posición 20"},
            {"name": "Byte 105", "description": "máscara 999"},
        ],
        "exact_literals": [{"value": "999", "pattern_type": "mask"}],
    }
    profile = source_profile(
        _doc(text, title="ATPCO record layout"),
        extracted,
        {},
        filename="atpco.pdf",
    )
    assert profile["document_genre"] == "technical"
    assert profile["document_type"] == "technical_specification"


def test_policy_and_contract_are_not_narrative() -> None:
    policy = _doc(
        "\n".join(
            [
                "Política de aprobación de gastos",
                "El empleado debe solicitar aprobación antes del gasto.",
                "El responsable autorizará el monto y dejará evidencia.",
                "El procedimiento es obligatorio para todos los empleados.",
            ]
        ),
        title="Política de gastos",
    )
    policy_profile = source_profile(policy, {}, {}, filename="politica.pdf")
    assert policy_profile["document_genre"] in {"policy", "mixed"}
    assert policy_profile["document_type"] in {"policy", "manual"}

    contract = _doc(
        "\n".join(
            [
                "Contrato de servicios",
                "El proveedor deberá pagar la indemnización prevista.",
                "Las partes aceptan la jurisdicción y las obligaciones.",
                "El contratista entregará el servicio en la fecha acordada.",
            ]
        ),
        title="Contrato",
    )
    contract_profile = source_profile(contract, {}, {}, filename="contrato.pdf")
    assert contract_profile["document_genre"] in {"legal", "mixed"}
    assert contract_profile["document_type"] in {"contract", "manual"}


def test_csv_suffix_is_tabular() -> None:
    profile = source_profile(
        _doc("nombre,precio\nrosa,10\n"), {}, {}, filename="inventario.csv"
    )
    assert profile["document_genre"] == "tabular"
    assert profile["document_type"] == "tabular"


def test_document_type_never_becomes_business_domain() -> None:
    doc = _doc("texto", title="Relato")
    doc.metadata["understanding"] = {
        "profile": {"document_type": "technical_specification"}
    }
    assert _domain_from(doc) is None


def test_explicit_folder_domain_is_preserved() -> None:
    doc = _doc("texto", title="Manual")
    doc.metadata["folder_path"] = "Operaciones/Fichas"
    assert _domain_from(doc) == "Operaciones"
