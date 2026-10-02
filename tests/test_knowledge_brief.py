# =============================================================================
# Knowledge Brief — representación progresiva con refs (C3).
# =============================================================================
from __future__ import annotations

from src.runtime.evidence_assembly import (
    EvidencePackage,
    EvidenceUnit,
)
from src.runtime.knowledge_brief import build_knowledge_brief

_SECTION_ORDER = (
    "facts",
    "relations",
    "rules",
    "critical_excerpts",
    "supporting_excerpts",
)


def _package() -> EvidencePackage:
    return EvidencePackage(
        units=(
            EvidenceUnit(
                unit_id="U1",
                kind="fact",
                text="Rule X aplica Category 31",
                refs={"assertion_id": "a1"},
                canonical_ids=("c1",),
                validity="current",
                score=0.9,
            ),
            EvidenceUnit(
                unit_id="U2",
                kind="relation",
                text="Record 4 requires Record 2",
                refs={"edge_id": "e1"},
                canonical_ids=("c2",),
                score=0.7,
            ),
            EvidenceUnit(
                unit_id="U3",
                kind="excerpt",
                text="El campo FCLAS determina la clase",
                refs={"document_id": "d1"},
                evidence_ids=("E1",),
                critical=True,
                score=0.9,
            ),
            EvidenceUnit(
                unit_id="U4",
                kind="excerpt",
                text="Texto de apoyo semántico",
                refs={"document_id": "d2"},
                evidence_ids=("E2",),
                score=0.4,
            ),
        ),
        chars=200,
        budget_chars=12_000,
        counts={"fact": 1, "relation": 1, "excerpt": 2},
    )


def test_secciones_en_orden_con_items() -> None:
    brief = build_knowledge_brief(_package())
    assert [section.kind for section in brief.sections] == list(_SECTION_ORDER)
    by_kind = {section.kind: section for section in brief.sections}
    assert len(by_kind["facts"].items) == 1
    assert len(by_kind["relations"].items) == 1
    assert len(by_kind["critical_excerpts"].items) == 1
    assert len(by_kind["supporting_excerpts"].items) == 1


def test_refs_kn_y_ev_en_texto() -> None:
    brief = build_knowledge_brief(_package())
    by_kind = {section.kind: section for section in brief.sections}
    assert "kn:c1" in by_kind["facts"].items[0].text
    assert "ev:E1" in by_kind["critical_excerpts"].items[0].text
    assert by_kind["facts"].items[0].refs["unit_id"] == "U1"


def test_budget_acota_y_marca_truncados() -> None:
    brief = build_knowledge_brief(_package(), budget_chars=80)
    assert brief.chars <= 80
    assert sum(section.truncated for section in brief.sections) >= 1


def test_render_text_incluye_secciones_no_vacias() -> None:
    text = build_knowledge_brief(_package()).render_text()
    assert "[Facts]" in text
    assert "[Relations]" in text
    assert "[Critical excerpts]" in text


def test_payload_publico_determinista() -> None:
    import json

    first = build_knowledge_brief(_package()).to_public_dict()
    second = build_knowledge_brief(_package()).to_public_dict()
    assert first == second
    assert json.loads(json.dumps(first)) == first


def test_package_vacio_mantiene_shape() -> None:
    brief = build_knowledge_brief(EvidencePackage())
    assert [section.kind for section in brief.sections] == list(_SECTION_ORDER)
    assert brief.chars == 0
    assert all(not section.items for section in brief.sections)
