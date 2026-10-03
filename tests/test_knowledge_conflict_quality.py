# =============================================================================
# Knowledge OS — Regresión de calidad semántica y conflictos
# =============================================================================
# Cubre los casos reales que producían conflictos sin sentido:
#
#   "RECORD 2 – CATEG"        vs "ORD 2 – CATEG"              -> NO CONFLICT
#   "FOR RECORD 2 – CATEGORY CONT" vs "Y CONT"                -> PARSER_FRAGMENT
#   "Category 31"             vs "CAT 31"                     -> ALIAS_VARIATION
#   "Fee = 100 USD"           vs "Fee = 200 USD"              -> POTENTIAL TRUE CONFLICT
#   "Fee = 100 USD through 2025" vs "Fee = 200 USD beginning 2026" -> TEMPORAL_CHANGE
# =============================================================================
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest

from src.core.domain.knowledge_v2 import (
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.compiler import (
    CompilationResult,
    ConflictType,
    KnowledgeCompiler,
    detect_conflicts,
)
from src.knowledge.compiler.conflicts import classify_conflict
from src.knowledge.compiler.model import (
    ConflictCandidate,
    EvidenceRef,
    EvidenceType,
    FactCandidate,
    QualityIssue,
    SourceLocator,
    TemporalScope,
)
from src.knowledge.quality import (
    TextQualityStatus,
    analyze_text_quality,
)

ORG = UUID("11111111-2222-3333-4444-555555555555")
SOURCE_A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
SOURCE_B = UUID("bbbbbbbb-0000-0000-0000-000000000002")
DOC = UUID("cccccccc-0000-0000-0000-000000000003")


def _evidence(source: UUID, excerpt: str) -> EvidenceRef:
    return EvidenceRef(
        locator=SourceLocator(
            source_id=source,
            document_id=DOC,
            document_title="manual.pdf",
            page=1,
        ),
        evidence_type=EvidenceType.STRUCTURAL.value,
        excerpt=excerpt,
        confidence=0.9,
    )


def _fact(
    *,
    subject: str,
    predicate: str,
    value: str,
    source: str,
    source_id: UUID = SOURCE_A,
    temporal: TemporalScope | None = None,
    evidence: bool = True,
) -> FactCandidate:
    return FactCandidate(
        subject=subject,
        predicate=predicate,
        object_value=value,
        confidence=0.9,
        temporal=temporal or TemporalScope(),
        attributes={"source_label": source},
        evidence=[_evidence(source_id, value)] if evidence else [],
    )


# ---------------------------------------------------------------------------
# 1. Fragment Quality Detector
# ---------------------------------------------------------------------------


def test_corte_de_palabra_es_fragmento_no_entidad() -> None:
    references = ("DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",)
    for candidate in (
        "CATEG",
        "CONT",
        "ORD 2 – CATEG",
        "Y CONT",
        "RECORD 2 – CATEG",
    ):
        verdict = analyze_text_quality(candidate, references=references)
        assert verdict.status in {
            TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value,
            TextQualityStatus.SENTENCE_FRAGMENT.value,
            TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
        }, (candidate, verdict)
        assert not verdict.ok


def test_alias_corto_con_limites_de_palabra_no_es_fragmento() -> None:
    references = ("ATPCO Record 4 (R4)", "Category 31 (Cat 31)")
    assert analyze_text_quality("R4", references=references).ok
    assert analyze_text_quality("Cat 31", references=references).ok
    assert analyze_text_quality("Record 4", references=references).ok


# ---------------------------------------------------------------------------
# 2. Alias no es conflicto
# ---------------------------------------------------------------------------


def test_alias_del_mismo_canonico_nunca_es_conflicto() -> None:
    alias_a = _fact(
        subject="Category 31",
        predicate="also_known_as",
        value="Cat 31",
        source="manual-a.pdf",
        source_id=SOURCE_A,
    )
    alias_b = _fact(
        subject="Category 31",
        predicate="also_known_as",
        value="Voluntary Changes",
        source="manual-b.pdf",
        source_id=SOURCE_B,
    )
    assert detect_conflicts([alias_a, alias_b]) == []

    conflict = classify_conflict(alias_a, alias_b)
    assert conflict.classification == ConflictType.ALIAS_VARIATION.value
    assert not conflict.displayable


def test_category_31_vs_cat_31_es_aliasing() -> None:
    left = _fact(
        subject="Category 31",
        predicate="display_name",
        value="Category 31",
        source="manual-a.pdf",
    )
    right = _fact(
        subject="Category 31",
        predicate="display_name",
        value="CAT 31",
        source="manual-b.pdf",
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.ALIAS_VARIATION.value
    assert not conflict.displayable


# ---------------------------------------------------------------------------
# 3. Fragmento de parser no es conflicto
# ---------------------------------------------------------------------------


def test_fragmento_de_parser_no_es_conflicto() -> None:
    full = _fact(
        subject="CONT",
        predicate="defined_as",
        value="FOR RECORD 2 – CATEGORY CONT",
        source="manual-a.pdf",
    )
    broken = _fact(
        subject="CONT",
        predicate="defined_as",
        value="Y CONT",
        source="manual-b.pdf",
    )
    conflict = classify_conflict(full, broken)
    assert conflict.classification == ConflictType.PARSER_FRAGMENT.value
    assert not conflict.displayable
    assert detect_conflicts([full, broken])[0].classification == (
        ConflictType.PARSER_FRAGMENT.value
    )


def test_recortes_superficiales_no_son_conflicto() -> None:
    left = _fact(
        subject="CATEG",
        predicate="defined_as",
        value="RECORD 2 – CATEG",
        source="manual-a.pdf",
    )
    right = _fact(
        subject="CATEG",
        predicate="defined_as",
        value="ORD 2 – CATEG",
        source="manual-b.pdf",
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.PARSER_FRAGMENT.value
    assert not conflict.displayable


# ---------------------------------------------------------------------------
# 4. Conflicto real y cambio temporal
# ---------------------------------------------------------------------------


def test_fee_distinto_misma_vigencia_y_fuentes_es_conflicto_potencial() -> None:
    left = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="100 USD",
        source="tariff-2025.pdf",
        source_id=SOURCE_A,
    )
    right = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="200 USD",
        source="carrier-manual.pdf",
        source_id=SOURCE_B,
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.TRUE_CONFLICT.value
    assert conflict.displayable
    assert conflict.source_independence == "independent_sources"
    assert conflict.materiality in {"MEDIUM", "HIGH", "CRITICAL"}


def test_regla_no_toma_el_banner_como_sujeto() -> None:
    from src.knowledge.compiler.rules import _subject_for

    subject = _subject_for(
        "The carrier must reissue the ticket within 24 hours.",
        ("DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",),
        document_title="Data Application For Record 2 – Category Control",
    )
    assert subject != "DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL"
    assert "carrier" in subject.lower()


def test_fee_con_vigencias_disjuntas_es_cambio_temporal() -> None:
    left = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="100 USD",
        source="tariff-2025.pdf",
        temporal=TemporalScope(
            effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31)
        ),
    )
    right = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="200 USD",
        source="tariff-2026.pdf",
        source_id=SOURCE_B,
        temporal=TemporalScope(effective_from=date(2026, 1, 1)),
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.TEMPORAL_CHANGE.value
    assert not conflict.displayable


def test_mismo_valor_escrito_distinto_no_es_conflicto() -> None:
    left = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="100 USD",
        source="tariff-2025.pdf",
    )
    right = _fact(
        subject="Fee",
        predicate="fee_amount",
        value="100  usd",
        source="carrier-manual.pdf",
        source_id=SOURCE_B,
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.DUPLICATE.value
    assert not conflict.displayable


def test_diferencia_de_scope_no_es_conflicto() -> None:
    left = _fact(
        subject="Field Name",
        predicate="field_meaning",
        value="name of the field",
        source="schema-dev",
        temporal=TemporalScope(scope="schema dev"),
    )
    right = _fact(
        subject="Field Name",
        predicate="field_meaning",
        value="label shown to the user",
        source="schema-prod",
        source_id=SOURCE_B,
        temporal=TemporalScope(scope="schema prod"),
    )
    conflict = classify_conflict(left, right)
    assert conflict.classification == ConflictType.SCOPE_DIFFERENCE.value
    assert not conflict.displayable


def test_sin_fuentes_no_hay_conflicto_mostrable() -> None:
    left = _fact(
        subject="Rule 4",
        predicate="applies_to",
        value="Weekday flights",
        source="",
    )
    right = _fact(
        subject="Rule 4",
        predicate="applies_to",
        value="Weekend flights",
        source="",
        source_id=SOURCE_B,
    )
    conflict = classify_conflict(left, right)
    assert not conflict.displayable


# ---------------------------------------------------------------------------
# 5. Compilador completo: fragmentos no llegan a entidades ni conflictos
# ---------------------------------------------------------------------------


def _fragmented_document() -> StructuredDocument:
    table = DocumentTable(
        id=uuid4(),
        document_id=DOC,
        organization_id=ORG,
        source_id=SOURCE_A,
        caption="layout",
        headers=("CATEG", "CONT", "ORD 2 – CATEG"),
        rows=(
            ("RECORD 2 – CATEG", "FOR RECORD 2 – CATEGORY CONT", "Y CONT"),
        ),
        page=14,
    )
    return StructuredDocument(
        id=DOC,
        organization_id=ORG,
        workspace_id=uuid4(),
        source_id=SOURCE_A,
        external_id="Rec2_Rules_dapp_C.pdf",
        title="DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",
        content_hash="hash-fragmentos",
        blocks=(
            StructuredBlock(
                kind=StructuredBlockKind.PARAGRAPH,
                text="DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",
                order=0,
                page=14,
            ),
        ),
        tables=(table,),
    )


def test_compilador_rechaza_fragmentos_y_no_crea_conflictos_de_alias() -> None:
    result = KnowledgeCompiler.build(_fragmented_document())
    entity_names = {entity.name for entity in result.entities}

    for fragment in ("CATEG", "CONT", "ORD 2 – CATEG"):
        assert fragment not in entity_names, fragment

    quality_kinds = result.quality_counts()
    assert quality_kinds, "los fragmentos deben quedar en la cola de calidad"
    assert any(
        kind
        in {
            "FRAGMENT_OF_EXISTING_TEXT",
            "SENTENCE_FRAGMENT",
            "LOW_QUALITY_EXTRACTION",
            "TRUNCATED_WORD",
        }
        for kind in quality_kinds
    )

    for conflict in result.conflicts:
        assert conflict.predicate != "also_known_as"
        assert not conflict.values_equivalent or not conflict.displayable
    assert not result.displayable_conflicts


# ---------------------------------------------------------------------------
# 6. Gate estricto en persistencia: solo lo mostrable se abre
# ---------------------------------------------------------------------------


class _GateStore:
    """Store mínimo para verificar el gate de persistencia."""

    def __init__(self) -> None:
        self.conflicts: list = []
        self.quality: list = []

    async def existing_aliases(self, organization_id):
        return {}

    async def existing_rule_keys(self, organization_id):
        return {}

    async def upsert_entity(self, organization_id, entity, *, source_id, workspace_id):
        return uuid4()

    async def upsert_alias(self, organization_id, **kwargs):
        return None

    async def upsert_fact(self, organization_id, fact, **kwargs):
        return uuid4(), 1, "created"

    async def upsert_relationship(self, organization_id, relationship, **kwargs):
        return uuid4(), "created"

    async def upsert_rule(self, organization_id, rule, **kwargs):
        return uuid4(), "created"

    async def add_evidence(self, organization_id, evidence, **kwargs):
        return uuid4()

    async def upsert_conflict(self, organization_id, conflict, *, object_id, workspace_id):
        self.conflicts.append(conflict)
        return "created"

    async def record_quality_issue(self, organization_id, issue, *, workspace_id):
        self.quality.append(issue)

    async def record_compilation(self, organization_id, **kwargs):
        return None

    async def refresh_counters(self, organization_id):
        return None


class _PreparedCompiler(KnowledgeCompiler):
    def __init__(self, result: CompilationResult, store) -> None:
        super().__init__(store=store)
        self._result = result

    def build(self, document: StructuredDocument) -> CompilationResult:  # type: ignore[override]
        return self._result


def _rich_conflict(*, displayable: bool):
    sources = {
        "source_a": "tariff-2025.pdf",
        "source_b": "carrier-manual.pdf",
    }
    if not displayable:
        sources = {}
    return dict(
        subject="Fee",
        predicate="fee_amount",
        value_a="100 USD",
        value_b="200 USD",
        conflict_type=ConflictType.SOURCE_CONFLICT.value,
        classification=(
            ConflictType.TRUE_CONFLICT.value
            if displayable
            else ConflictType.PARSER_FRAGMENT.value
        ),
        confidence=0.8,
        reason="prueba de gate",
        source_a=sources.get("source_a"),
        source_b=sources.get("source_b"),
        evidence=(
            [
                _evidence(SOURCE_A, "100 USD"),
                _evidence(SOURCE_B, "200 USD"),
            ]
            if displayable
            else []
        ),
    )


@pytest.mark.asyncio
async def test_gate_persiste_solo_conflictos_mostrables() -> None:
    store = _GateStore()
    document = _fragmented_document()
    result = CompilationResult(
        organization_id=ORG,
        source_id=SOURCE_A,
        document_id=DOC,
        document_title="manual.pdf",
        conflicts=[
            ConflictCandidate(**{**_rich_conflict(displayable=True)}),
            ConflictCandidate(**{**_rich_conflict(displayable=False)}),
        ],
        quality_issues=[
            QualityIssue(
                kind="PARSER_FRAGMENT",
                subject="Y CONT",
                detail={"stage": "conflict_gate"},
                source_id=SOURCE_A,
                document_id=DOC,
            )
        ],
    )
    compiler = _PreparedCompiler(result, store)

    await compiler.compile_document(document)

    assert len(store.conflicts) == 1, "solo el conflicto con evidencia y fuentes se abre"
    assert store.conflicts[0].classification == ConflictType.TRUE_CONFLICT.value
    assert result.persisted["conflicts"] == 1
    assert result.persisted["conflicts_auto_resolved"] >= 1
    assert store.quality, "la cola de calidad de ingesta recibe los problemas"
    assert result.persisted["status"] == "completed"
