# =============================================================================
# P18.2-11 — Matriz de aceptación por familia documental
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.core.domain.knowledge_v2 import DocumentSection, StructuredBlock, StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.candidates import assess_rule_candidate
from src.knowledge.understanding.explorer import build_explorer_insight
from src.knowledge.understanding.passages import build_passage_understanding
from src.knowledge.understanding.views import source_profile

ROOT = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> Path:
    for base in (ROOT / "p18_2", ROOT / "p18_1"):
        path = base / name
        if path.exists():
            return path
    raise FileNotFoundError(name)


def _document(name: str) -> tuple[StructuredDocument, list[dict]]:
    path = _fixture(name)
    text = path.read_text(encoding="utf-8")
    blocks = []
    domain_blocks = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        kind = StructuredBlockKind.HEADING if index == 0 else StructuredBlockKind.PARAGRAPH
        block = StructuredBlock(kind=kind, text=line.strip(), order=index, page=1 + index // 5)
        blocks.append(block)
        domain_blocks.append(
            {
                "id": str(block.id),
                "kind": "section" if kind is StructuredBlockKind.HEADING else "paragraph",
                "text": line.strip(),
                "heading": line.strip() if kind is StructuredBlockKind.HEADING else None,
                "page_number": block.page,
                "order_index": index,
                "section_path": [line.strip()] if kind is StructuredBlockKind.HEADING else [],
                "metadata": {},
            }
        )
    document = StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id=name,
        title=path.stem,
        content_hash=f"hash:{name}",
        blocks=tuple(blocks),
        sections=(
            DocumentSection(
                document_id=uuid4(),
                organization_id=uuid4(),
                section_path=(text.splitlines()[0].strip(),),
                heading=text.splitlines()[0].strip(),
                order=0,
            ),
        ),
    )
    return document, domain_blocks


def _profile(document: StructuredDocument, name: str, extracted: dict | None = None) -> dict:
    return source_profile(document, extracted or {}, {}, filename=name)


def test_narrative_family_has_no_false_concepts_and_grounded_proposals() -> None:
    document, blocks = _document("narrative_journey.txt")
    profile = _profile(document, "narrative_journey.txt")
    assert profile["document_genre"] == "narrative"
    assert profile["document_type"] != "technical_specification"

    view = build_passage_understanding(
        document=None, blocks=blocks, genre=profile["document_genre"]
    )
    names = {item["name"] for item in view["participants"]}
    assert {"lía", "tomás", "nara"} <= names
    assert "52" not in names
    assert "¿recuerdas?" not in names

    block_text = "\n".join(block["text"] for block in blocks)
    for participant in view["participants"]:
        assert participant["excerpt"] in block_text


def test_technical_family_keeps_fields_and_rules() -> None:
    document, blocks = _document("technical_manual.txt")
    extracted = {
        "technical_fields": [
            {"name": "Fare Basis", "description": "posición 12"},
            {"name": "Currency", "description": "posición 20"},
            {"name": "Byte 105", "description": "máscara 999"},
        ],
        "exact_literals": [
            {"value": "AAAAAAAA", "pattern_type": "mask"},
            {"value": "999", "pattern_type": "mask"},
        ],
    }
    profile = _profile(document, "technical_manual.txt", extracted)
    assert profile["document_genre"] == "technical"
    assert profile["document_type"] == "technical_specification"
    assert {"Fare Basis", "Currency", "Byte 105"} <= set(profile["field_vocabulary"])

    view = build_passage_understanding(
        document=None, blocks=blocks, genre=profile["document_genre"]
    )
    assert view["narrative_signal"] is False
    assert view["participants"] == []

    decision = assess_rule_candidate(
        "The carrier must not change the fare basis code on reissue.",
        subject="The carrier",
        document=document,
        section_path=("Manual",),
    )
    assert decision.accepted


def test_policy_and_contract_family_keep_normative_context() -> None:
    policy, _ = _document("policy_expenses.txt")
    contract, _ = _document("contract_services.txt")
    policy_profile = _profile(policy, "policy_expenses.txt")
    contract_profile = _profile(contract, "contract_services.txt")

    assert policy_profile["document_genre"] == "policy"
    assert contract_profile["document_genre"] == "legal"
    assert policy_profile["document_type"] == "policy"
    assert contract_profile["document_type"] == "contract"

    rule = assess_rule_candidate(
        "El empleado debe solicitar aprobación antes del gasto.",
        subject="El empleado",
        document=policy,
        section_path=("Política de gastos",),
    )
    assert rule.accepted
    assert rule.claim_kind == "policy_rule"
    assert policy_profile["business_domain"] is None


def test_tabular_family_is_tabular_and_produces_no_narrative_claims() -> None:
    document, blocks = _document("inventory.csv")
    profile = _profile(document, "inventory.csv")
    assert profile["document_genre"] == "tabular"
    assert profile["document_type"] == "tabular"
    view = build_passage_understanding(
        document=None, blocks=blocks, genre=profile["document_genre"]
    )
    assert view["narrative_signal"] is False
    assert view["participants"] == []
    assert view["relations"] == []


def test_every_displayed_claim_opens_an_existing_excerpt() -> None:
    document, blocks = _document("narrative_journey.txt")
    document_row = {
        "id": str(document.id),
        "content_hash": "hash",
        "page_count": 3,
        "section_count": 1,
        "table_count": 0,
        "metadata": {
            "understanding": {
                "profile": {
                    "document_genre": "narrative",
                    "profile_version": "1.1",
                },
                "report": {"pages": 3, "sections": 1, "tables": 0},
            }
        },
    }
    result = build_explorer_insight(
        source={"id": "src-1", "name": "narrative_journey.txt"},
        document=document_row,
        objects=[],
        evidence=[],
        blocks=blocks,
    )
    block_text = "\n".join(block["text"] for block in blocks)
    for topic in result["topics"]:
        for insight in topic["insights"]:
            if insight["grounded_excerpt"]:
                assert insight["grounded_excerpt"] in block_text
            assert insight["verification_state"] in {"proposed", "discovered"}
            assert insight["object_id"] is None
    assert result["counts"]["objects_visible"] == 0
    assert result["provenance"]["evaluation_state"] == "not_evaluated"
