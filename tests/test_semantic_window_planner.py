# =============================================================================
# SemanticWindowPlanner — tests puros (sin DB, sin LLM)
# =============================================================================
# Reglas que se prueban:
#   - el hard limit se deriva de la capacidad REAL del modelo (registry), no
#     de una constante universal;
#   - los perfiles cambian el tamaño objetivo (economy < balanced < quality <
#     maximum_quality), ajustado por densidad de la fuente;
#   - límites SOFT: una unidad semántica que cruza el objetivo entra completa
#     dentro del headroom;
#   - HARD limit: un bloque gigante se parte en piezas con char offsets y
#     ninguna ventana supera el hard limit;
#   - cobertura total: las ventanas son contiguas y cubren todos los bloques;
#   - determinismo: mismo documento + misma config => mismo fingerprint.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredDocument
from src.knowledge.semantic import SemanticWindowPlanner
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding
from src.knowledge.understanding.units import build_retrieval_units


def _document(text: str) -> StructuredDocument:
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id="doc.md",
        source_id=uuid4(),
        source_name="doc.md",
    )
    # En ingesta real el planner corre DESPUÉS del Document Understanding
    # (bloques con dueño de sección); el test reproduce ese estado.
    return apply_understanding(parsed, filename="doc.md")


def _paragraph_document(paragraphs: int = 40, words: int = 18) -> StructuredDocument:
    lines = ["# Manual"]
    for index in range(paragraphs):
        lines.append("")
        lines.append(" ".join(f"p{index}w{word}" for word in range(words)))
    return _document("\n".join(lines))


def _giant_document(words: int = 900) -> StructuredDocument:
    return _document(" ".join(f"w{index}" for index in range(words)))


def _indexable(document: StructuredDocument) -> list[StructuredBlock]:
    from src.knowledge.semantic.planner import _is_indexable

    return [block for block in document.blocks if _is_indexable(block)]


def _atomic_source_ranges(document: StructuredDocument) -> list[tuple[int, int]]:
    blocks = _indexable(document)
    position = {block.id: index for index, block in enumerate(blocks)}
    ranges: list[tuple[int, int]] = []
    for unit in build_retrieval_units(document, budget=1200):
        if unit.unit_type == "SECTION":
            continue
        indexes = []
        for raw in unit.block_ids:
            try:
                block_id = UUID(str(raw))
            except (TypeError, ValueError):
                continue
            if block_id in position:
                indexes.append(position[block_id])
        if indexes:
            ranges.append((min(indexes), max(indexes)))
    return ranges


def test_hard_limit_comes_from_model_capability_not_a_constant() -> None:
    planner = SemanticWindowPlanner()
    document = _document("# Manual\n\ntexto corto")
    plan = planner.plan(
        document, model="deepseek-chat", reserves=5000, min_tokens=1000
    )
    # deepseek-chat = 128K documentado en el registry; 128000 - 5000 reservas.
    assert plan.hard_limit_tokens == 123_000
    assert plan.model_source == "builtin"
    assert plan.notes["reserves_tokens"] == 5000


def test_configured_max_caps_the_capability() -> None:
    planner = SemanticWindowPlanner()
    document = _document("# Manual\n\ntexto corto")
    plan = planner.plan(
        document,
        model="deepseek-chat",
        max_tokens=40_000,
        reserves=5000,
        min_tokens=1000,
    )
    assert plan.hard_limit_tokens == 35_000


def test_profiles_change_window_target() -> None:
    planner = SemanticWindowPlanner()
    document = _document("# Manual\n\ntexto corto")
    targets = {}
    for profile in ("economy", "balanced", "quality", "maximum_quality"):
        plan = planner.plan(
            document,
            profile=profile,
            model="deepseek-chat",
            reserves=0,
            min_tokens=1000,
        )
        targets[profile] = plan.target_tokens
    assert targets == {
        "economy": 16_000,
        "balanced": 32_000,
        "quality": 64_000,
        "maximum_quality": 96_000,
    }


def test_soft_boundary_preserves_atomic_unit_and_covers_everything() -> None:
    planner = SemanticWindowPlanner()
    document = _paragraph_document()
    plan = planner.plan(
        document,
        profile="balanced",
        model="deepseek-chat",
        max_tokens=400,
        reserves=0,
        min_tokens=100,
        headroom_ratio=3.0,
    )
    assert plan.window_count >= 2
    assert plan.soft_extensions >= 1

    # Cobertura total y contigua de todas las unidades de plan.
    position = 0
    for window in plan.windows:
        assert window.unit_start == position
        position = window.unit_end + 1
    assert position == plan.total_units

    # Ningún corte cae DENTRO de una unidad semántica (límite SOFT real).
    for window in plan.windows[:-1]:
        boundary = window.unit_end + 1
        for start, end in _atomic_source_ranges(document):
            assert not (start < boundary <= end), (
                f"corte {boundary} dentro de unidad ({start},{end})"
            )


def test_giant_block_is_split_and_never_exceeds_hard_limit() -> None:
    planner = SemanticWindowPlanner()
    document = _giant_document(words=900)
    plan = planner.plan(
        document,
        model="deepseek-chat",
        max_tokens=200,
        reserves=0,
        min_tokens=50,
        headroom_ratio=0.0,
    )
    assert plan.split_units >= 1
    assert plan.window_count == 5  # 900 palabras / 200 por pieza
    assert all(window.estimated_tokens <= 200 for window in plan.windows)
    assert all(window.char_start is not None for window in plan.windows)


def test_plan_is_deterministic() -> None:
    planner = SemanticWindowPlanner()
    document = _paragraph_document(paragraphs=10, words=12)
    first = planner.plan(document, model="deepseek-chat", max_tokens=400)
    second = planner.plan(document, model="deepseek-chat", max_tokens=400)
    assert first.fingerprint == second.fingerprint
    assert first.to_dict(include_windows=False)["window_count"] == second.window_count


def test_empty_document_plans_zero_windows() -> None:
    planner = SemanticWindowPlanner()
    plan = planner.plan(_document(""), model="deepseek-chat")
    assert plan.window_count == 0
    assert plan.notes.get("empty") is True
