# Cognitive Runtime C3 — Evidence Assembly + Knowledge Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir evidencia heterogénea (retrieval + runners canónicos) en un paquete coherente de evidencia y una representación progresiva compacta (Facts/Relations/Rules/Critical excerpts/Supporting excerpts) con refs `kn:`/`ev:`, trazada en `flow["cognitive"]` en modo observación.

**Architecture:** Dos módulos puros en `src/runtime/` (`evidence_assembly.py`, `knowledge_brief.py`); refs aditivas en los runners graph/temporal para poder detectar conflictos y vigencias; wiring fail-soft en `RAGOrchestrator` al final del run (usa la evidencia ya recuperada + los runners observados); retiro del `EvidenceBlackboard` (reemplazado por este engine).

**Tech Stack:** Python del repo, pytest + pytest-asyncio, Postgres solo en tests ya existentes, ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` (S6, §7, fase C3 §15).

## Global Constraints

- `RAG_COGNITIVE_OS_ENABLED` default `off`; con `off` el runtime actual queda intacto (cero imports de assembly/brief, flow sin bloque `cognitive`).
- C3 sigue siendo **observación**: el paquete y el brief se trazan; NO alimentan prompt, retrieval, JEV ni LLM. La respuesta y las llamadas LLM no cambian.
- Deterministic first: sin LLM, sin I/O en los módulos nuevos; presupuesto y orden deterministas.
- Conflictos se **retienen** (ambos lados, marcados), nunca se resuelven.
- Sin dependencias nuevas. Sin migraciones. Sin cambios de contrato API.
- Código/comentarios en español, estilo del repo; tests en `tests/test_*.py`.
- Cada tarea termina con tests verdes, lint limpio y commit. Branch `feat/cognitive-runtime-c3` desde `master`.

---

### Task 1: Evidence Assembly engine

**Files:**
- Create: `src/runtime/evidence_assembly.py`
- Modify: `src/runtime/graph_runner.py` (ref `predicate` aditiva)
- Modify: `src/runtime/temporal_runner.py` (refs `subject_label`/`predicate`/`object_value` aditivas)
- Modify: `tests/test_graph_temporal_runners.py` (asserts aditivos)
- Test: `tests/test_evidence_assembly.py`

**Interfaces:**
- Consumes: `src.core.domain.adaptive.EvidenceItem`, `src.runtime.representation_runners.RunnerResult/RunnerItem`, `src.runtime.entity_resolution.EntityResolution`.
- Produces:
  - `EvidenceUnit(unit_id, kind, text, refs, score, match, evidence_ids, canonical_ids, validity, critical, conflict, connected)` + `to_public_dict()`.
  - `EvidenceConflict(key, unit_ids, values)`.
  - `EvidencePackage(units, conflicts, dropped, chars, budget_chars, counts)` + `to_public_dict(max_units=12)`.
  - `assemble_evidence(*, items=(), runner_results=(), entities=None, budget_chars=DEFAULT_ASSEMBLY_BUDGET_CHARS) -> EvidencePackage`.
  - `DEFAULT_ASSEMBLY_BUDGET_CHARS = 12_000`, `MAX_UNIT_CHARS = 1_200`, `MAX_UNITS = 40`.

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c3
pytest tests/test_graph_temporal_runners.py tests/test_cognitive_runtime_shadow.py -q
```

Expected: PASS.

- [ ] **Step 2: Escribir los tests que fallan**

2a. `tests/test_evidence_assembly.py`:

```python
# =============================================================================
# Evidence Assembly — dedupe, prioridad, conflictos y presupuesto (C3).
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.evidence_assembly import assemble_evidence
from src.runtime.representation_runners import RunnerItem, RunnerResult


def _item(
    *,
    document_id: str = "doc-1",
    chunk_id: str = "chunk-1",
    content: str = "Registro 1 OPEN",
    score: float = 0.9,
    retrieval_method: str = "semantic",
    evidence_id: str = "E1",
    entity_pin: bool = False,
) -> EvidenceItem:
    return EvidenceItem(
        source_type="qdrant",
        content=content,
        score=score,
        document_id=document_id,
        chunk_id=chunk_id,
        evidence_id=evidence_id,
        retrieval_method=retrieval_method,
        entity_pin=entity_pin,
    )


def _runner_result(representation: str, *items: RunnerItem) -> RunnerResult:
    return RunnerResult(representation=representation, status="ok", items=items)


def _temporal_item(
    *, assertion_id: str, canonical_id: str, value: str, validity: str, predicate: str = "aplica"
) -> RunnerItem:
    return RunnerItem(
        title=f"Rule X {predicate} {value}",
        summary=f"vigencia {validity}",
        refs={
            "assertion_id": assertion_id,
            "canonical_id": canonical_id,
            "subject_label": "Rule X",
            "predicate": predicate,
            "object_value": value,
            "validity": validity,
        },
        score=0.8,
    )


def test_dedupe_por_documento_y_chunk() -> None:
    package = assemble_evidence(
        items=[_item(evidence_id="E1"), _item(evidence_id="E2")]
    )
    assert len(package.units) == 1
    assert package.counts["excerpt"] == 1


def test_runner_units_con_refs_y_kind() -> None:
    relation = RunnerItem(
        title="Record 4 requires Record 2",
        summary="depends_on",
        refs={"edge_id": "e1", "canonical_id": "c1"},
        score=0.7,
    )
    package = assemble_evidence(
        runner_results=[
            _runner_result("graph", relation),
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1",
                    canonical_id="c1",
                    value="2024",
                    validity="historical",
                ),
            ),
        ]
    )
    kinds = {unit.kind for unit in package.units}
    assert kinds == {"relation", "fact"}
    fact = next(unit for unit in package.units if unit.kind == "fact")
    assert fact.refs["assertion_id"] == "a1"
    assert fact.validity == "historical"


def test_conflicto_retenido_no_resuelto() -> None:
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1", canonical_id="c1", value="2024", validity="historical"
                ),
                _temporal_item(
                    assertion_id="a2", canonical_id="c1", value="2026", validity="current"
                ),
            )
        ]
    )
    assert len(package.conflicts) == 1
    conflict = package.conflicts[0]
    assert conflict.values == ("2024", "2026")
    assert len(conflict.unit_ids) == 2
    facts = [unit for unit in package.units if unit.kind == "fact"]
    assert all(unit.conflict for unit in facts)


def test_vigente_antes_que_historico() -> None:
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1", canonical_id="c1", value="viejo", validity="historical"
                ),
                _temporal_item(
                    assertion_id="a2", canonical_id="c2", value="nuevo", validity="current"
                ),
            )
        ]
    )
    facts = [unit for unit in package.units if unit.kind == "fact"]
    assert facts[0].validity == "current"


def test_presupuesto_recorta_y_registra_dropped() -> None:
    items = [
        _item(
            document_id=f"doc-{i}",
            chunk_id=f"chunk-{i}",
            content="x" * 500,
            evidence_id=f"E{i}",
        )
        for i in range(10)
    ]
    package = assemble_evidence(items=items, budget_chars=1_200)
    assert package.chars <= 1_200
    assert package.dropped
    assert len(package.units) < 10


def test_connected_usa_entidades_resueltas() -> None:
    entities = EntityResolution(
        mentions=(
            MentionResolution(
                mention="Category 31",
                status="resolved",
                matches=(
                    EntityMatch(
                        mention="Category 31",
                        canonical_id="c1",
                        name="Category 31",
                        kind="entity",
                        match="exact_name",
                        confidence=0.9,
                    ),
                ),
            ),
        )
    )
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "graph",
                RunnerItem(
                    title="Category 31 requires Record 4",
                    summary="",
                    refs={"edge_id": "e1", "canonical_id": "c1"},
                ),
            )
        ],
        entities=entities,
    )
    assert package.units[0].connected is True


def test_payload_publico_serializable() -> None:
    import json

    package = assemble_evidence(items=[_item()])
    payload = package.to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["units"][0]["unit_id"] == "U1"
```

2b. En `tests/test_graph_temporal_runners.py`, agregar asserts aditivos:
- en `test_graph_runner_items_con_refs`: `assert result.items[0].refs["predicate"] == "requires"`.
- en `test_temporal_runner_estado_vigencia`: `assert result.items[0].refs["object_value"] == "Category 31"` y `assert result.items[0].refs["subject_label"] == "Rule X"`.

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_evidence_assembly.py tests/test_graph_temporal_runners.py -q`
Expected: FAIL (`ModuleNotFoundError: src.runtime.evidence_assembly`).

- [ ] **Step 4: Implementar**

4a. `src/runtime/evidence_assembly.py`:

```python
# =============================================================================
# Evidence Assembly — paquete coherente de evidencia (S6, C3).
# =============================================================================
# Compone retrieval + conocimiento canónico en unidades deduplicadas,
# rankeadas y conectadas, con provenance, prioridad de vigencia, conflictos
# retenidos y presupuesto. Sin I/O y sin LLM: determinista.
# =============================================================================
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from src.core.domain.adaptive import EvidenceItem
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.representation_runners import RunnerResult

DEFAULT_ASSEMBLY_BUDGET_CHARS = 12_000
MAX_UNIT_CHARS = 1_200
MAX_UNITS = 40

_KIND_ORDER = {"rule": 0, "fact": 1, "relation": 2, "table": 3, "excerpt": 4}
_RUNNER_KINDS = {"graph": "relation", "temporal": "fact", "structured": "table"}


@dataclass(frozen=True)
class EvidenceUnit:
    unit_id: str
    kind: str
    text: str
    refs: dict = field(default_factory=dict)
    score: float | None = None
    match: str = ""
    evidence_ids: tuple[str, ...] = ()
    canonical_ids: tuple[str, ...] = ()
    validity: str | None = None
    critical: bool = False
    conflict: bool = False
    connected: bool = False

    def to_public_dict(self) -> dict:
        payload = {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "text": self.text,
            "refs": dict(self.refs),
            "match": self.match,
            "critical": self.critical,
            "conflict": self.conflict,
            "connected": self.connected,
        }
        if self.score is not None:
            payload["score"] = round(float(self.score), 4)
        if self.evidence_ids:
            payload["evidence_ids"] = list(self.evidence_ids)
        if self.canonical_ids:
            payload["canonical_ids"] = list(self.canonical_ids)
        if self.validity:
            payload["validity"] = self.validity
        return payload


@dataclass(frozen=True)
class EvidenceConflict:
    key: str
    unit_ids: tuple[str, ...]
    values: tuple[str, ...]

    def to_public_dict(self) -> dict:
        return {
            "key": self.key,
            "unit_ids": list(self.unit_ids),
            "values": list(self.values),
        }


@dataclass(frozen=True)
class EvidencePackage:
    units: tuple[EvidenceUnit, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    dropped: tuple[str, ...] = ()
    chars: int = 0
    budget_chars: int = DEFAULT_ASSEMBLY_BUDGET_CHARS
    counts: dict = field(default_factory=dict)

    def to_public_dict(self, *, max_units: int = 12) -> dict:
        return {
            "count": len(self.units),
            "chars": self.chars,
            "budget_chars": self.budget_chars,
            "counts": dict(self.counts),
            "conflicts": [
                conflict.to_public_dict() for conflict in self.conflicts
            ],
            "dropped_count": len(self.dropped),
            "units": [
                unit.to_public_dict() for unit in self.units[: max(0, max_units)]
            ],
        }


def _clip(text: str, limit: int = MAX_UNIT_CHARS) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _excerpt_key(item: "EvidenceItem") -> str:
    doc = str(item.document_id or item.source_id or "")
    chunk = str(item.chunk_id or "")
    if doc or chunk:
        return f"{doc}|{chunk}"
    digest = hashlib.sha256(
        (item.content or "").encode("utf-8", "ignore")
    ).hexdigest()[:16]
    return f"excerpt|{digest}"


def _is_critical_excerpt(item: "EvidenceItem") -> bool:
    method = str(item.retrieval_method or "")
    return bool(item.entity_pin) or method.startswith(("exact", "entity"))


def _units_from_items(items: Sequence["EvidenceItem"]) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    seen: set[str] = set()
    for item in items or ():
        key = _excerpt_key(item)
        if key in seen:
            continue
        seen.add(key)
        content = _clip(item.content)
        if not content:
            continue
        units.append(
            EvidenceUnit(
                unit_id="",
                kind="excerpt",
                text=content,
                refs={
                    "evidence_id": item.evidence_id,
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "title": item.title,
                    "page": item.page,
                    "section_path": list(item.section_path),
                },
                score=float(item.score or 0.0),
                match=str(item.retrieval_method or "semantic"),
                evidence_ids=(item.evidence_id,) if item.evidence_id else (),
                critical=_is_critical_excerpt(item),
            )
        )
    return units


def _units_from_runners(
    results: Sequence["RunnerResult"],
) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    for result in results or ():
        representation = str(getattr(result, "representation", "") or "")
        kind = _RUNNER_KINDS.get(representation)
        if kind is None:
            continue
        for item in getattr(result, "items", ()) or ():
            refs = dict(getattr(item, "refs", None) or {})
            text = _clip(
                str(getattr(item, "title", "") or getattr(item, "summary", ""))
            )
            if not text:
                continue
            canonical = str(refs.get("canonical_id") or "")
            units.append(
                EvidenceUnit(
                    unit_id="",
                    kind=kind,
                    text=text,
                    refs=refs,
                    score=getattr(item, "score", None),
                    match=representation,
                    canonical_ids=(canonical,) if canonical else (),
                    validity=str(refs.get("validity") or "") or None,
                )
            )
    return units


def _fact_conflict_key(unit: EvidenceUnit) -> str | None:
    if unit.kind != "fact":
        return None
    canonical = unit.canonical_ids[0] if unit.canonical_ids else ""
    subject = str(unit.refs.get("subject_label") or "").lower()
    predicate = str(unit.refs.get("predicate") or "").lower()
    if not (canonical and predicate):
        return None
    return f"{canonical}|{subject}|{predicate}"


def _conflict_values(units: Sequence[EvidenceUnit]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for unit in units:
        key = _fact_conflict_key(unit)
        if key is None:
            continue
        value = str(unit.refs.get("object_value") or "").strip()
        if value:
            groups.setdefault(key, set()).add(value)
    return {key: values for key, values in groups.items() if len(values) > 1}


def _validity_rank(unit: EvidenceUnit) -> int:
    if unit.validity == "current":
        return 0
    if not unit.validity:
        return 1
    return 2


def _ordered(units: Sequence[EvidenceUnit]) -> list[EvidenceUnit]:
    return sorted(
        units,
        key=lambda unit: (
            _KIND_ORDER.get(unit.kind, 9),
            _validity_rank(unit),
            -float(unit.score or 0.0),
            unit.text.lower(),
        ),
    )


def _apply_budget(
    units: Sequence[EvidenceUnit], budget: int
) -> tuple[list[EvidenceUnit], list[str], int]:
    selected: list[EvidenceUnit] = []
    dropped: list[str] = []
    used = 0
    for unit in units:
        if len(selected) >= MAX_UNITS:
            dropped.append(unit.text[:80])
            continue
        cost = len(unit.text)
        if used + cost > budget:
            dropped.append(unit.text[:80])
            continue
        selected.append(unit)
        used += cost
    return selected, dropped, used


def assemble_evidence(
    *,
    items: Sequence["EvidenceItem"] = (),
    runner_results: Sequence["RunnerResult"] = (),
    entities: "EntityResolution | None" = None,
    budget_chars: int = DEFAULT_ASSEMBLY_BUDGET_CHARS,
) -> EvidencePackage:
    """Paquete coherente: dedupe, prioridad, conflictos retenidos y budget."""
    base = _units_from_items(items) + _units_from_runners(runner_results)
    conflict_values = _conflict_values(base)
    resolved = {
        mention.matches[0].canonical_id
        for mention in (entities.mentions if entities is not None else ())
        if mention.status == "resolved" and mention.matches
    }
    selected, dropped, used = _apply_budget(
        _ordered(base), max(0, int(budget_chars))
    )
    units: list[EvidenceUnit] = []
    for index, unit in enumerate(selected, start=1):
        key = _fact_conflict_key(unit)
        units.append(
            replace(
                unit,
                unit_id=f"U{index}",
                conflict=bool(key and key in conflict_values),
                connected=bool(set(unit.canonical_ids) & resolved),
            )
        )
    conflicts: list[EvidenceConflict] = []
    for key, values in sorted(conflict_values.items()):
        unit_ids = tuple(
            unit.unit_id for unit in units if _fact_conflict_key(unit) == key
        )
        if len(unit_ids) >= 2:
            conflicts.append(
                EvidenceConflict(
                    key=key, unit_ids=unit_ids, values=tuple(sorted(values))
                )
            )
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.kind] = counts.get(unit.kind, 0) + 1
    counts["critical_excerpts"] = sum(
        1 for unit in units if unit.kind == "excerpt" and unit.critical
    )
    return EvidencePackage(
        units=tuple(units),
        conflicts=tuple(conflicts),
        dropped=tuple(dropped),
        chars=used,
        budget_chars=max(0, int(budget_chars)),
        counts=counts,
    )
```

4b. `src/runtime/graph_runner.py`: dentro del `items.append(RunnerItem(...))`, agregar al dict `refs` la clave `"predicate": predicate,`.

4c. `src/runtime/temporal_runner.py`: dentro del `items.append(RunnerItem(...))`, agregar a `refs`:

```python
                            "subject_label": str(
                                row.get("subject_label") or mention.mention
                            ),
                            "predicate": str(row.get("predicate") or ""),
                            "object_value": str(row.get("object_value") or ""),
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_evidence_assembly.py tests/test_graph_temporal_runners.py -q`
Expected: `14 passed` (8 nuevos + 6 existentes, ajustar solo el conteo si difiere; ningún fallo).

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/runtime/evidence_assembly.py src/runtime/graph_runner.py src/runtime/temporal_runner.py tests/test_evidence_assembly.py tests/test_graph_temporal_runners.py
git add src/runtime/evidence_assembly.py src/runtime/graph_runner.py src/runtime/temporal_runner.py tests/test_evidence_assembly.py tests/test_graph_temporal_runners.py
git commit -m "feat(cognitive): evidence assembly engine (C3)"
```

---

### Task 2: Knowledge Brief (representación progresiva)

**Files:**
- Create: `src/runtime/knowledge_brief.py`
- Test: `tests/test_knowledge_brief.py`

**Interfaces:**
- Consumes: `src.runtime.evidence_assembly.EvidencePackage/EvidenceUnit`.
- Produces:
  - `BriefItem(text, refs)` + `to_public_dict()`.
  - `BriefSection(kind, items, chars, truncated)` + `to_public_dict(max_items=8)`.
  - `KnowledgeBrief(sections, chars, budget_chars)` + `render_text()` + `to_public_dict()`.
  - `build_knowledge_brief(package, *, budget_chars=8_000) -> KnowledgeBrief`.
  - Secciones fijas en orden: `facts`, `relations`, `rules`, `critical_excerpts`, `supporting_excerpts`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_knowledge_brief.py`:

```python
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
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_knowledge_brief.py -q`
Expected: FAIL (`ModuleNotFoundError: src.runtime.knowledge_brief`).

- [ ] **Step 3: Implementar**

`src/runtime/knowledge_brief.py`:

```python
# =============================================================================
# Knowledge Brief — representación progresiva para el prompt (S7, C3).
# =============================================================================
# Facts -> Relations -> Rules -> Critical excerpts -> Supporting excerpts.
# Cada línea conserva refs (kn: canónico, ev: evidencia). Presupuesto
# determinista por sección con arrastre; lo que no entra se declara truncado.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.runtime.evidence_assembly import EvidencePackage, EvidenceUnit

_SECTION_ORDER = (
    "facts",
    "relations",
    "rules",
    "critical_excerpts",
    "supporting_excerpts",
)
_SECTION_LABELS = {
    "facts": "Facts",
    "relations": "Relations",
    "rules": "Rules",
    "critical_excerpts": "Critical excerpts",
    "supporting_excerpts": "Supporting excerpts",
}
_BUDGET_SHARE = {
    "facts": 0.25,
    "relations": 0.15,
    "rules": 0.10,
    "critical_excerpts": 0.30,
    "supporting_excerpts": 0.20,
}
_ITEM_LIMITS = {
    "facts": 240,
    "relations": 200,
    "rules": 240,
    "critical_excerpts": 600,
    "supporting_excerpts": 600,
}


def _unit_section(unit: EvidenceUnit) -> str:
    if unit.kind == "fact":
        return "facts"
    if unit.kind == "relation":
        return "relations"
    if unit.kind == "rule":
        return "rules"
    if unit.kind == "excerpt":
        return "critical_excerpts" if unit.critical else "supporting_excerpts"
    return "supporting_excerpts"


def _refs_suffix(unit: EvidenceUnit) -> str:
    parts: list[str] = []
    for canonical_id in unit.canonical_ids[:1]:
        parts.append(f"kn:{canonical_id[:8]}")
    for evidence_id in unit.evidence_ids[:2]:
        parts.append(f"ev:{evidence_id}")
    if unit.validity:
        parts.append(f"vigencia:{unit.validity}")
    return " · ".join(parts)


@dataclass(frozen=True)
class BriefItem:
    text: str
    refs: dict = field(default_factory=dict)

    def to_public_dict(self) -> dict:
        return {"text": self.text, "refs": dict(self.refs)}


@dataclass(frozen=True)
class BriefSection:
    kind: str
    items: tuple[BriefItem, ...] = ()
    chars: int = 0
    truncated: int = 0

    def to_public_dict(self, *, max_items: int = 8) -> dict:
        return {
            "kind": self.kind,
            "count": len(self.items),
            "chars": self.chars,
            "truncated": self.truncated,
            "items": [
                item.to_public_dict() for item in self.items[: max(0, max_items)]
            ],
        }


@dataclass(frozen=True)
class KnowledgeBrief:
    sections: tuple[BriefSection, ...] = ()
    chars: int = 0
    budget_chars: int = 0

    def render_text(self) -> str:
        blocks: list[str] = []
        for section in self.sections:
            if not section.items:
                continue
            lines = "\n".join(f"- {item.text}" for item in section.items)
            blocks.append(f"[{_SECTION_LABELS[section.kind]}]\n{lines}")
        return "\n\n".join(blocks)

    def to_public_dict(self) -> dict:
        return {
            "chars": self.chars,
            "budget_chars": self.budget_chars,
            "sections": [section.to_public_dict() for section in self.sections],
        }


def build_knowledge_brief(
    package: EvidencePackage, *, budget_chars: int = 8_000
) -> KnowledgeBrief:
    """Brief determinista: estructurado primero, excerpts después."""
    budget = max(0, int(budget_chars))
    buckets: dict[str, list[EvidenceUnit]] = {kind: [] for kind in _SECTION_ORDER}
    for unit in package.units:
        buckets[_unit_section(unit)].append(unit)

    sections: list[BriefSection] = []
    leftover = 0
    used_total = 0
    for kind in _SECTION_ORDER:
        capacity = int(budget * _BUDGET_SHARE[kind]) + leftover
        used = 0
        truncated = 0
        items: list[BriefItem] = []
        limit = _ITEM_LIMITS[kind]
        for unit in buckets[kind]:
            raw = unit.text
            cut = len(raw) > limit
            text = raw[: limit - 1].rstrip() + "…" if cut else raw
            suffix = _refs_suffix(unit)
            line = f"{text} ({suffix})" if suffix else text
            if used + len(line) > capacity:
                truncated += 1
                continue
            if cut:
                truncated += 1
            items.append(
                BriefItem(
                    text=line,
                    refs={
                        **unit.refs,
                        "unit_id": unit.unit_id,
                        "evidence_ids": list(unit.evidence_ids),
                        "canonical_ids": list(unit.canonical_ids),
                    },
                )
            )
            used += len(line)
        leftover = max(0, capacity - used)
        used_total += used
        sections.append(
            BriefSection(
                kind=kind, items=tuple(items), chars=used, truncated=truncated
            )
        )
    return KnowledgeBrief(
        sections=tuple(sections), chars=used_total, budget_chars=budget
    )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_knowledge_brief.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/knowledge_brief.py tests/test_knowledge_brief.py
git add src/runtime/knowledge_brief.py tests/test_knowledge_brief.py
git commit -m "feat(cognitive): knowledge brief progresivo (C3)"
```

---

### Task 3: Wiring de observación (paquete + brief en la traza)

**Files:**
- Modify: `src/runtime/cognitive_state.py` (campos `evidence`, `brief`; `to_public_dict`)
- Modify: `src/agents/runtime/orchestrator.py` (`_assemble_cognitive_evidence`; llamada en el `finally`)
- Modify: `tests/test_cognitive_state.py`
- Modify: `tests/test_cognitive_runtime_shadow.py`

**Interfaces:**
- Consumes: `assemble_evidence`, `build_knowledge_brief`, `EvidenceRegistry` (existente), `adaptive["selection"]` si existe, `retrieval_context.chunks` si no.
- Produces:
  - `CognitiveTurn.evidence: EvidencePackage | None`, `CognitiveTurn.brief: KnowledgeBrief | None`; `to_public_dict()` con `"evidence"` y `"brief"`.
  - `RAGOrchestrator._assemble_cognitive_evidence(turn, *, retrieval_context, adaptive)` fail-soft.

- [ ] **Step 1: Escribir los tests que fallan**

1a. `tests/test_cognitive_state.py`, agregar:

```python
def test_turn_publica_evidence_y_brief(monkeypatch) -> None:
    from src.runtime.evidence_assembly import assemble_evidence
    from src.runtime.knowledge_brief import build_knowledge_brief

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    turn = CognitiveTurn(query="q")
    assert turn.to_public_dict()["evidence"] is None
    assert turn.to_public_dict()["brief"] is None
    package = assemble_evidence()
    turn.evidence = package
    turn.brief = build_knowledge_brief(package)
    payload = turn.to_public_dict()
    assert payload["evidence"]["count"] == 0
    assert [section["kind"] for section in payload["brief"]["sections"]][0] == "facts"
```

1b. `tests/test_cognitive_runtime_shadow.py`, agregar:

```python
@pytest.mark.asyncio
async def test_shadow_ensambla_evidencia_y_brief(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        edges={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_name": "Category 31",
                    "predicate": "requires",
                    "object_name": "Record 4",
                    "relationship_type": "depends_on",
                    "confidence": 0.8,
                }
            ]
        },
    )
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["evidence"]["counts"].get("relation", 0) >= 1
    assert cognitive["evidence"]["counts"].get("excerpt", 0) >= 1
    sections = {item["kind"] for item in cognitive["brief"]["sections"]}
    assert {"facts", "relations", "critical_excerpts"} <= sections
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_conflicto_temporal_retenido(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        assertions={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_label": "Rule X",
                    "predicate": "aplica",
                    "object_value": "2024",
                    "confidence": 0.9,
                    "valid_from": "2024-01-01T00:00:00+00:00",
                    "valid_to": "2025-01-01T00:00:00+00:00",
                },
                {
                    "id": str(uuid4()),
                    "subject_label": "Rule X",
                    "predicate": "aplica",
                    "object_value": "2026",
                    "confidence": 0.8,
                    "valid_from": "2026-01-01T00:00:00+00:00",
                    "valid_to": None,
                },
            ]
        },
    )
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿La Category 31 sigue vigente?"
    )
    conflicts = result.flow["cognitive"]["evidence"]["conflicts"]
    assert conflicts and conflicts[0]["values"] == ["2024", "2026"]


@pytest.mark.asyncio
async def test_shadow_assembly_falla_no_rompe_el_run(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("assembly roto")

    monkeypatch.setattr("src.runtime.evidence_assembly.assemble_evidence", _boom)
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, "¿Qué dice el Byte 105?")
    assert result.flow["cognitive"]["evidence"] is None
    assert result.flow["cognitive"]["brief"] is None
    assert len(llm.calls) == 1
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: FAIL (`KeyError: 'evidence'` / `AttributeError`).

- [ ] **Step 3: Implementar**

3a. `src/runtime/cognitive_state.py`:
- Agregar bajo `if TYPE_CHECKING:`:

```python
    from src.runtime.evidence_assembly import EvidencePackage
    from src.runtime.knowledge_brief import KnowledgeBrief
```

- Campos en `CognitiveTurn` (después de `runners`):

```python
    evidence: "EvidencePackage | None" = None
    brief: "KnowledgeBrief | None" = None
```

- En `to_public_dict()`, antes de `return payload`:

```python
        payload["evidence"] = (
            self.evidence.to_public_dict() if self.evidence is not None else None
        )
        payload["brief"] = (
            self.brief.to_public_dict() if self.brief is not None else None
        )
```

3b. `src/agents/runtime/orchestrator.py`:
- Método nuevo junto a `_observe_cognitive`:

```python
    async def _assemble_cognitive_evidence(
        self,
        turn: CognitiveTurn,
        *,
        retrieval_context: object | None,
        adaptive: dict,
    ) -> None:
        """Ensambla paquete + brief desde la evidencia observada. Nunca lanza."""
        try:
            from src.runtime.evidence import EvidenceRegistry
            from src.runtime.evidence_assembly import assemble_evidence
            from src.runtime.knowledge_brief import build_knowledge_brief

            items: list = []
            selection = adaptive.get("selection") if isinstance(adaptive, dict) else None
            if selection is not None:
                items = list(getattr(selection, "items", ()) or ())
            elif retrieval_context is not None:
                registry = EvidenceRegistry()
                registry.add_chunks(
                    list(getattr(retrieval_context, "chunks", None) or ())
                )
                items = list(registry.all_items())
            package = assemble_evidence(
                items=items,
                runner_results=list(turn.runners),
                entities=turn.entities,
            )
            turn.evidence = package
            turn.brief = build_knowledge_brief(package)
        except Exception as exc:  # noqa: BLE001 — observación fail-soft
            logger.warning(
                "Cognitive evidence assembly failed", error=str(exc)[:200]
            )
```

- En el `finally` de `execute`, justo antes de `result.flow["cognitive"] = cognitive_turn.to_public_dict()`:

```python
                    if cognitive_turn is not None:
                        await self._assemble_cognitive_evidence(
                            cognitive_turn,
                            retrieval_context=locals().get("retrieval_context"),
                            adaptive=adaptive,
                        )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: todos PASS (state 7, shadow 17; ajustar conteo sin fallos).

- [ ] **Step 5: Regresión + lint**

```bash
pytest tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_graph_temporal_runners.py tests/test_tabular_runner.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py -q
ruff check src tests
```

Expected: PASS + `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/cognitive_state.py src/agents/runtime/orchestrator.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py
git commit -m "feat(cognitive): paquete de evidencia y brief en la traza shadow (C3)"
```

---

### Task 4: Retiro del EvidenceBlackboard + docs + verificación final

**Files:**
- Modify: `src/core/domain/cognitive.py` (remover clase `EvidenceBlackboard`)
- Modify: `tests/test_cognitive_domain.py` (remover import/uso; conservar validación de `AgentMessage`)
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C3; S6 blackboard retirado)
- Test: suite C1–C3

- [ ] **Step 1: Retirar el blackboard**

1a. En `src/core/domain/cognitive.py`, eliminar la clase `EvidenceBlackboard` completa.
1b. En `tests/test_cognitive_domain.py`:
- Quitar `EvidenceBlackboard` del import.
- Renombrar `test_message_and_blackboard` a `test_message_validation` y dejar solo la construcción/validación de `AgentMessage` (incluido el `pytest.raises` final); borrar las líneas del blackboard y sus asserts `snapshot`.
1c. Verificar que nadie más lo usa:

```bash
grep -rn "EvidenceBlackboard" src tests
```

Expected: sin resultados en `src/` y `tests/` (docs históricos pueden mencionarlo).

- [ ] **Step 2: Actualizar docs**

En `docs/architecture/cognitive-runtime.md`:
- §15 fila C3 → modo `shadow (default off) — **shipped**` y Plan: `docs/superpowers/plans/2026-10-01-cognitive-runtime-c3-evidence-brief.md`.
- Fila S6 de §4: cambiar "blackboard cognitivo se retira" por "blackboard cognitivo retirado (C3)".

- [ ] **Step 3: Verificación final**

```bash
pytest tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_cognitive_domain.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_graph_temporal_runners.py tests/test_tabular_runner.py tests/test_cognitive_plan.py tests/test_knowledge_strategy.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py tests/test_retrieval_planner.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 4: Commit**

```bash
git add src/core/domain/cognitive.py tests/test_cognitive_domain.py docs/architecture/cognitive-runtime.md
git commit -m "refactor(cognitive): retira EvidenceBlackboard y documenta C3"
```

---

## Criterios de salida C3

- [ ] `off`: runtime intacto; cero imports de assembly/brief.
- [ ] `shadow`: `flow["cognitive"]` gana `evidence` (unidades con kind/refs/critical/conflict/connected, conflictos retenidos, dropped) y `brief` (5 secciones con refs `kn:`/`ev:` y presupuesto).
- [ ] Respuesta y llamadas LLM sin cambio; assembly fail-soft (error → `evidence`/`brief` en `None`, run completo).
- [ ] `EvidenceBlackboard` retirado; sin usos en `src/`/`tests/`.
- [ ] Sin dependencias, migraciones ni cambios de contrato API; `ruff check src tests` limpio.
