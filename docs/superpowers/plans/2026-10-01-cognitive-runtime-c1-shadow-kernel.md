# Cognitive Runtime C1 — Shadow Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir el kernel cognitivo (plan de necesidades + strategy trazable + estado del turno) al runtime productivo en modo `shadow`, sin cambiar la ejecución.

**Architecture:** Módulos puros en `src/runtime/` (sin I/O) que el `RAGOrchestrator` construye al inicio de `execute()` y publica en `result.flow["cognitive"]`. `off` no paga nada. Ningún retrieval/JEV/LLM cambia de comportamiento en C1.

**Tech Stack:** Python (repo), pytest + pytest-asyncio, Postgres/Qdrant no se tocan, ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` (programa W1–W6, secciones 3–5 y fase C1).

## Global Constraints

- `RAG_COGNITIVE_OS_ENABLED` default `off`; con `off` el runtime actual queda intacto (cero imports de plan/strategy, flow sin bloque `cognitive`).
- Sin dependencias nuevas. Sin migraciones. Sin cambios de contrato API.
- Código y comentarios en español, estilo del repo; tests en `tests/test_*.py`.
- Cada tarea termina con tests verdes, `ruff check src tests` limpio y commit.
- Trabajar en branch `feat/cognitive-runtime` (desde `master`).
- Los tests de integración usan fakes; nunca store real.
- Ley del spec: deterministic first; JEV no se toca en C1; evidencia solo lectura.

---

### Task 1: Cognitive Plan (necesidades de conocimiento)

**Files:**
- Create: `src/runtime/cognitive_plan.py`
- Test: `tests/test_cognitive_plan.py`

**Interfaces:**
- Consumes: `src.core.domain.cognitive.classify_complexity`, `src.rag.retrieval.planner.build_retrieval_plan` / `RetrievalPlan`.
- Produces:
  - `KnowledgeNeed` (StrEnum, 14 valores del brief §2).
  - `PlanStep(need: KnowledgeNeed, reason: str)` con `to_public_dict()`.
  - `CognitivePlan(query, complexity, needs, steps)` con `requires_knowledge` y `to_public_dict()`.
  - `build_cognitive_plan(query: str, *, retrieval_plan: RetrievalPlan | None = None) -> CognitivePlan`.

- [ ] **Step 1: Crear branch y verificar baseline**

```bash
git checkout -b feat/cognitive-runtime
pytest tests/test_retrieval_planner.py -q
```

Expected: PASS (baseline verde antes de tocar nada).

- [ ] **Step 2: Escribir el test que falla**

`tests/test_cognitive_plan.py`:

```python
# =============================================================================
# Cognitive Plan — planificación determinista de necesidades de conocimiento.
# =============================================================================
from __future__ import annotations

import json

from src.runtime.cognitive_plan import KnowledgeNeed, build_cognitive_plan


def test_saludo_no_necesita_retrieval() -> None:
    plan = build_cognitive_plan("Hola, buenos días")
    assert plan.needs == (KnowledgeNeed.NO_RETRIEVAL,)
    assert plan.requires_knowledge is False
    assert plan.steps[0].reason


def test_literal_exacto_activa_exact_lookup() -> None:
    plan = build_cognitive_plan("¿Qué significa el Byte 105 de Category 31?")
    assert KnowledgeNeed.EXACT_LOOKUP in plan.needs
    assert KnowledgeNeed.SEMANTIC_SEARCH in plan.needs
    assert plan.requires_knowledge is True


def test_temporal_y_regla() -> None:
    plan = build_cognitive_plan(
        "¿Qué cambió en la regla X respecto a la versión anterior?"
    )
    assert KnowledgeNeed.TEMPORAL_LOOKUP in plan.needs
    assert KnowledgeNeed.RULE_LOOKUP in plan.needs


def test_comparacion_agregacion_y_cruce_de_documentos() -> None:
    plan = build_cognitive_plan(
        "Compara el total de la columna 7 entre la versión 2024 y 2025"
    )
    assert KnowledgeNeed.COMPARISON in plan.needs
    assert KnowledgeNeed.AGGREGATION in plan.needs
    assert KnowledgeNeed.CROSS_DOCUMENT_REASONING in plan.needs


def test_calculo_y_herramienta_y_memoria() -> None:
    plan = build_cognitive_plan(
        "Calcula el porcentaje y envía un correo; recuerda la conversación anterior"
    )
    assert KnowledgeNeed.CALCULATION in plan.needs
    assert KnowledgeNeed.EXTERNAL_TOOL in plan.needs
    assert KnowledgeNeed.MEMORY in plan.needs


def test_payload_publico_serializable() -> None:
    payload = build_cognitive_plan("¿Aplica la regla 12?").to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["complexity"] in {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert payload["requires_knowledge"] is True
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_plan.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.cognitive_plan'`.

- [ ] **Step 4: Implementar**

`src/runtime/cognitive_plan.py`:

```python
# =============================================================================
# Cognitive Plan — qué tipo de conocimiento necesita la consulta (brief §2).
# =============================================================================
# Determinista y sin I/O. No ejecuta nada: declara capacidades con su razón.
# El runtime lo traza (shadow) y las fases siguientes lo usan para rutear
# retrieval, JEV y profundidad de razonamiento.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from src.core.domain.cognitive import ComplexityLevel, classify_complexity
from src.rag.retrieval.planner import RetrievalPlan, build_retrieval_plan


class KnowledgeNeed(StrEnum):
    """Capacidades de conocimiento del brief §2 (las que aplican al runtime)."""

    SEMANTIC_SEARCH = "semantic_search"
    EXACT_LOOKUP = "exact_lookup"
    STRUCTURED_QUERY = "structured_query"
    GRAPH_TRAVERSAL = "graph_traversal"
    TEMPORAL_LOOKUP = "temporal_lookup"
    CROSS_DOCUMENT_REASONING = "cross_document_reasoning"
    RULE_LOOKUP = "rule_lookup"
    CONFLICT_RESOLUTION = "conflict_resolution"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    CALCULATION = "calculation"
    EXTERNAL_TOOL = "external_tool"
    MEMORY = "memory"
    NO_RETRIEVAL = "no_retrieval"


@dataclass(frozen=True)
class PlanStep:
    need: KnowledgeNeed
    reason: str

    def to_public_dict(self) -> dict:
        return {"need": self.need.value, "reason": self.reason}


@dataclass(frozen=True)
class CognitivePlan:
    query: str
    complexity: ComplexityLevel
    needs: tuple[KnowledgeNeed, ...]
    steps: tuple[PlanStep, ...]

    @property
    def requires_knowledge(self) -> bool:
        return KnowledgeNeed.NO_RETRIEVAL not in self.needs

    def to_public_dict(self) -> dict:
        return {
            "complexity": self.complexity.value,
            "needs": [need.value for need in self.needs],
            "steps": [step.to_public_dict() for step in self.steps],
            "requires_knowledge": self.requires_knowledge,
        }


_GREETING = re.compile(
    r"^(hola|buenas|buenos d[ií]as|buenas tardes|buenas noches|hello|hi|hey|gracias)\b",
    flags=re.IGNORECASE,
)
_AGGREGATION = (
    "total",
    "suma",
    "sum",
    "average",
    "promedio",
    "cuántos",
    "cuantos",
    "count",
    "máximo",
    "maximo",
    "maximum",
    "mínimo",
    "minimo",
    "minimum",
)
_CALCULATION = ("calcula", "calculate", "porcentaje", "percent", "%")
_RULE = ("regla", "rule", "norma", "política", "politica", "policy", "aplica", "applies")
_CONFLICT = (
    "conflicto",
    "conflictos",
    "contradic",
    "contradice",
    "inconsistencia",
    "inconsistency",
)
_COMPARISON = (
    "compara",
    "comparar",
    "comparación",
    "comparacion",
    "versus",
    " vs ",
    "diferencia",
    "compare",
)
_CROSS_DOCUMENT = (
    "entre documentos",
    "cross-document",
    "todas las fuentes",
    "múltiples fuentes",
    "multiples fuentes",
)
_MEMORY = (
    "recuerda",
    "remember",
    "la vez pasada",
    "conversación anterior",
    "conversacion anterior",
    "mensajes anteriores",
)
_EXTERNAL_TOOL = (
    "envía",
    "envia",
    "send",
    "crea ",
    "create ",
    "actualiza ",
    "update ",
    "ejecuta",
    "ticket",
    "correo",
    "email",
)


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in text:
            return marker
    return None


def build_cognitive_plan(
    query: str,
    *,
    retrieval_plan: RetrievalPlan | None = None,
) -> CognitivePlan:
    """Plan determinista de necesidades. Reglas explícitas, sin LLM."""
    text = " ".join((query or "").strip().split())
    lowered = text.lower()
    plan = retrieval_plan if retrieval_plan is not None else build_retrieval_plan(text)
    steps: list[PlanStep] = []

    def add(need: KnowledgeNeed, reason: str) -> None:
        if all(step.need is not need for step in steps):
            steps.append(PlanStep(need=need, reason=reason))

    if text and _GREETING.match(lowered) and "?" not in text and len(lowered.split()) <= 6:
        add(KnowledgeNeed.NO_RETRIEVAL, "saludo o cortesía sin consulta de conocimiento")
        return CognitivePlan(
            query=text,
            complexity=classify_complexity(text),
            needs=tuple(step.need for step in steps),
            steps=tuple(steps),
        )

    add(KnowledgeNeed.SEMANTIC_SEARCH, "búsqueda semántica base sobre el índice")
    if plan.includes("structured"):
        add(
            KnowledgeNeed.STRUCTURED_QUERY,
            f"la consulta pide datos estructurados ('{plan.structured_intent}')",
        )
    if plan.includes("exact"):
        literales = ", ".join(plan.exact_needles[:3])
        add(KnowledgeNeed.EXACT_LOOKUP, f"la consulta contiene literales exactos: {literales}")
    if plan.includes("temporal"):
        add(
            KnowledgeNeed.TEMPORAL_LOOKUP,
            f"la consulta es temporal ('{plan.temporal_intent}')",
        )
    if plan.includes("graph"):
        entidades = ", ".join(plan.entity_mentions[:3])
        add(KnowledgeNeed.GRAPH_TRAVERSAL, f"menciona entidades del grafo: {entidades}")

    comparison = _first_marker(lowered, _COMPARISON)
    if comparison:
        add(KnowledgeNeed.COMPARISON, f"la consulta pide comparar ('{comparison}')")
        add(
            KnowledgeNeed.CROSS_DOCUMENT_REASONING,
            "comparar exige relacionar más de una fuente",
        )
    cross = _first_marker(lowered, _CROSS_DOCUMENT)
    if cross:
        add(
            KnowledgeNeed.CROSS_DOCUMENT_REASONING,
            f"la consulta cruza documentos ('{cross}')",
        )
    rule = _first_marker(lowered, _RULE)
    if rule:
        add(KnowledgeNeed.RULE_LOOKUP, f"la consulta refiere a una regla ('{rule}')")
    conflict = _first_marker(lowered, _CONFLICT)
    if conflict:
        add(
            KnowledgeNeed.CONFLICT_RESOLUTION,
            f"la consulta menciona conflicto ('{conflict}')",
        )
    aggregation = _first_marker(lowered, _AGGREGATION)
    if aggregation:
        add(KnowledgeNeed.AGGREGATION, f"la consulta pide agregar valores ('{aggregation}')")
    calculation = _first_marker(lowered, _CALCULATION)
    if calculation:
        add(KnowledgeNeed.CALCULATION, f"la consulta pide un cálculo ('{calculation}')")
    tool = _first_marker(lowered, _EXTERNAL_TOOL)
    if tool:
        add(KnowledgeNeed.EXTERNAL_TOOL, f"la consulta pide una acción externa ('{tool}')")
    memory = _first_marker(lowered, _MEMORY)
    if memory:
        add(
            KnowledgeNeed.MEMORY,
            f"la consulta apela a memoria de conversación ('{memory}')",
        )

    return CognitivePlan(
        query=text,
        complexity=classify_complexity(text),
        needs=tuple(step.need for step in steps),
        steps=tuple(steps),
    )
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_plan.py -q`
Expected: `6 passed`.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/runtime/cognitive_plan.py tests/test_cognitive_plan.py
git add src/runtime/cognitive_plan.py tests/test_cognitive_plan.py
git commit -m "feat(cognitive): plan determinista de necesidades de conocimiento (C1)"
```

---

### Task 2: Knowledge Strategy (representaciones + scope)

**Files:**
- Create: `src/runtime/knowledge_strategy.py`
- Test: `tests/test_knowledge_strategy.py`

**Interfaces:**
- Consumes: `src.rag.retrieval.planner.RetrievalPlan` / `build_retrieval_plan`.
- Produces:
  - `StrategyRepresentation(representation: str, reason: str)` con `to_public_dict()`.
  - `KnowledgeStrategy` con `primary`, `representations`, `exact_needles`, `entity_mentions`, `temporal_intent`, `structured_intent`, scope (`organization_id`, `workspace_id`, `role`), `includes(rep)` y `to_public_dict()`.
  - `build_knowledge_strategy(retrieval_plan=None, *, query="", organization_id=None, workspace_id=None, role="") -> KnowledgeStrategy`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_knowledge_strategy.py`:

```python
# =============================================================================
# Knowledge Strategy — representaciones declaradas + scope, trazables.
# =============================================================================
from __future__ import annotations

import json

from src.rag.retrieval.planner import build_retrieval_plan
from src.runtime.knowledge_strategy import build_knowledge_strategy


def test_estrategia_declara_representaciones_con_razones() -> None:
    strategy = build_knowledge_strategy(
        build_retrieval_plan("¿Qué significa el Byte 105 de Category 31?"),
        organization_id="org-1",
        workspace_id="ws-1",
        role="admin",
    )
    assert strategy.primary == "exact"
    assert strategy.includes("vector")
    assert strategy.includes("exact")
    assert strategy.includes("graph")
    payload = strategy.to_public_dict()
    assert payload["scope"] == {
        "organization_id": "org-1",
        "workspace_id": "ws-1",
        "role": "admin",
    }
    assert all(item["reason"] for item in payload["representations"])
    assert json.loads(json.dumps(payload)) == payload


def test_sin_plan_construye_desde_query() -> None:
    strategy = build_knowledge_strategy(query="")
    assert strategy.representations[0].representation == "vector"
    assert strategy.primary == "vector"


def test_scope_por_defecto_vacio() -> None:
    strategy = build_knowledge_strategy(query="estado de la regla 4")
    assert strategy.to_public_dict()["scope"] == {
        "organization_id": None,
        "workspace_id": None,
        "role": "",
    }
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_knowledge_strategy.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.knowledge_strategy'`.

- [ ] **Step 3: Implementar**

`src/runtime/knowledge_strategy.py`:

```python
# =============================================================================
# Knowledge Strategy — representaciones + razones + scope (brief §5).
# =============================================================================
# Determinista y sin I/O. En C1 se deriva del retrieval planner existente y se
# traza; las fases siguientes agregan entity resolution canónica y enforcement
# de scope pre-retrieval.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.rag.retrieval.planner import RetrievalPlan, build_retrieval_plan

#: Orden de presentación de las representaciones (el planner decide cuáles).
_REPRESENTATION_ORDER = ("structured", "exact", "temporal", "graph", "vector")


@dataclass(frozen=True)
class StrategyRepresentation:
    representation: str
    reason: str

    def to_public_dict(self) -> dict:
        return {"representation": self.representation, "reason": self.reason}


@dataclass(frozen=True)
class KnowledgeStrategy:
    query: str
    primary: str
    representations: tuple[StrategyRepresentation, ...]
    exact_needles: tuple[str, ...] = ()
    entity_mentions: tuple[str, ...] = ()
    temporal_intent: str | None = None
    structured_intent: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    role: str = ""

    def includes(self, representation: str) -> bool:
        return any(item.representation == representation for item in self.representations)

    def to_public_dict(self) -> dict:
        return {
            "primary": self.primary,
            "representations": [item.to_public_dict() for item in self.representations],
            "exact_needles": list(self.exact_needles),
            "entity_mentions": list(self.entity_mentions),
            "temporal_intent": self.temporal_intent,
            "structured_intent": self.structured_intent,
            "scope": {
                "organization_id": self.organization_id,
                "workspace_id": self.workspace_id,
                "role": self.role,
            },
        }


def build_knowledge_strategy(
    retrieval_plan: RetrievalPlan | None = None,
    *,
    query: str = "",
    organization_id: str | None = None,
    workspace_id: str | None = None,
    role: str = "",
) -> KnowledgeStrategy:
    """Estrategia declarada: qué representaciones consultar y con qué scope."""
    plan = retrieval_plan if retrieval_plan is not None else build_retrieval_plan(query)
    representations = tuple(
        StrategyRepresentation(
            representation=representation,
            reason=plan.reasons.get(representation, "representación base"),
        )
        for representation in _REPRESENTATION_ORDER
        if plan.includes(representation)
    )
    return KnowledgeStrategy(
        query=plan.query,
        primary=plan.primary,
        representations=representations,
        exact_needles=tuple(plan.exact_needles),
        entity_mentions=tuple(plan.entity_mentions),
        temporal_intent=plan.temporal_intent,
        structured_intent=plan.structured_intent,
        organization_id=organization_id,
        workspace_id=workspace_id,
        role=role,
    )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_knowledge_strategy.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/knowledge_strategy.py tests/test_knowledge_strategy.py
git add src/runtime/knowledge_strategy.py tests/test_knowledge_strategy.py
git commit -m "feat(cognitive): knowledge strategy trazable (C1)"
```

---

### Task 3: Cognitive Turn State (estado del turno)

**Files:**
- Create: `src/runtime/cognitive_state.py`
- Test: `tests/test_cognitive_state.py`

**Interfaces:**
- Consumes: `src.core.config.get_settings`, `src.runtime.cognitive_plan.CognitivePlan`, `src.runtime.knowledge_strategy.KnowledgeStrategy`.
- Produces:
  - `COGNITIVE_MODES = ("off", "shadow", "limited", "active")`.
  - `cognitive_runtime_mode() -> str` (modo válido o `"off"`).
  - `CognitiveTurn(query, plan=None, strategy=None, notes=[])` con `add_note(stage, detail)` y `to_public_dict()` (incluye `mode`).

- [ ] **Step 1: Escribir el test que falla**

`tests/test_cognitive_state.py`:

```python
# =============================================================================
# Cognitive Turn State — modo del runtime + estado compartido del turno.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.rag.retrieval.planner import build_retrieval_plan
from src.runtime.cognitive_plan import build_cognitive_plan
from src.runtime.cognitive_state import CognitiveTurn, cognitive_runtime_mode
from src.runtime.knowledge_strategy import build_knowledge_strategy


def test_modo_invalido_cae_a_off(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "banana")
    assert cognitive_runtime_mode() == "off"


def test_modo_shadow_se_lee(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    assert cognitive_runtime_mode() == "shadow"


def test_turn_publica_plan_y_strategy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Qué dice la regla 12?"
    plan = build_cognitive_plan(query)
    turn = CognitiveTurn(
        query=query,
        plan=plan,
        strategy=build_knowledge_strategy(build_retrieval_plan(query)),
    )
    turn.add_note("plan", "necesidades calculadas")
    payload = turn.to_public_dict()
    assert payload["mode"] == "shadow"
    assert payload["plan"]["needs"]
    assert payload["strategy"]["representations"]
    assert payload["notes"] == [{"stage": "plan", "detail": "necesidades calculadas"}]


def test_turn_sin_plan_es_serializable() -> None:
    payload = CognitiveTurn(query="hola").to_public_dict()
    assert "plan" not in payload
    assert "strategy" not in payload
    assert payload["notes"] == []
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_state.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.cognitive_state'`.

- [ ] **Step 3: Implementar**

`src/runtime/cognitive_state.py`:

```python
# =============================================================================
# Cognitive Turn State — estado compartido de las etapas cognitivas (W1).
# =============================================================================
# C1: plan + strategy + notas. Las fases siguientes agregan evidence, brief,
# claims, verification, budget y loop. Sin I/O.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.config import get_settings
from src.runtime.cognitive_plan import CognitivePlan
from src.runtime.knowledge_strategy import KnowledgeStrategy

COGNITIVE_MODES = ("off", "shadow", "limited", "active")


def cognitive_runtime_mode() -> str:
    """Modo del runtime cognitivo; cualquier valor desconocido cae a 'off'."""
    mode = str(getattr(get_settings(), "COGNITIVE_OS_ENABLED", "off") or "off")
    mode = mode.strip().lower()
    return mode if mode in COGNITIVE_MODES else "off"


@dataclass
class CognitiveTurn:
    query: str
    plan: CognitivePlan | None = None
    strategy: KnowledgeStrategy | None = None
    notes: list[dict] = field(default_factory=list)

    def add_note(self, stage: str, detail: str) -> None:
        self.notes.append({"stage": stage, "detail": detail[:240]})

    def to_public_dict(self) -> dict:
        payload: dict = {"mode": cognitive_runtime_mode(), "notes": list(self.notes)}
        if self.plan is not None:
            payload["plan"] = self.plan.to_public_dict()
        if self.strategy is not None:
            payload["strategy"] = self.strategy.to_public_dict()
        return payload
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_state.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/cognitive_state.py tests/test_cognitive_state.py
git add src/runtime/cognitive_state.py tests/test_cognitive_state.py
git commit -m "feat(cognitive): estado del turno cognitivo (C1)"
```

---

### Task 4: Wiring shadow en `RAGOrchestrator` + escenarios

**Files:**
- Modify: `src/agents/runtime/orchestrator.py` (import top; `execute` ~1572; `_run_knowledge_retrieve` ~1462; call site ~2223; finally ~4115).
- Test: `tests/test_cognitive_runtime_shadow.py`

**Interfaces:**
- Consumes: `CognitiveTurn`, `cognitive_runtime_mode`, `build_cognitive_plan`, `build_knowledge_strategy`, `build_retrieval_plan`.
- Produces:
  - `result.flow["cognitive"]` = `CognitiveTurn.to_public_dict()` cuando el modo ≠ `off`.
  - `_run_knowledge_retrieve(..., cognitive_turn: CognitiveTurn | None = None)` reemplaza la strategy declarada por la del retrieval real (mismo plan que usa el retriever).

- [ ] **Step 1: Escribir el test de integración que falla**

`tests/test_cognitive_runtime_shadow.py`:

```python
# =============================================================================
# Cognitive runtime (W1/C1) — shadow: plan + strategy en el flow, sin cambiar
# la ejecución. Escenarios base del harness de evaluación.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.config import get_settings
from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None:
        return None

    async def get_list(self, key: str) -> list[str]:
        return []

    async def trim_list(self, key: str, max_items: int) -> None:
        return None

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        return 1


class FakeOrganizationRepo:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self.organization if organization_id == self.organization.id else None

    async def check_rate_limit(self, organization_id: UUID) -> bool:
        return True

    async def log_usage(self, **kwargs: Any) -> None:
        return None


class FakeLLM:
    def __init__(self, content: str = "Respuesta generada") -> None:
        self.calls: list[dict] = []
        self.content = content

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content=self.content, model="fake-llm", total_tokens=12, latency_ms=1.0
        )


class FakeEmbed:
    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class FakeVectorStore:
    def __init__(self, context: RetrievalContext) -> None:
        self.context = context

    async def search(self, **kwargs: Any) -> RetrievalContext:
        return self.context

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def upsert_batch(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def delete_by_organization(self, organization_id: UUID) -> None:
        return None


def _organization() -> Organization:
    return Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)


def _retrieval(*, score: float = 0.9) -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Registro 1 OPEN | Registro 2 UPDATE | Registro 3 CLOSE",
                score=score,
                metadata={"filename": "secuencia.txt"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _build(
    *, organization: Organization, llm: FakeLLM, vector_store: FakeVectorStore
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=vector_store,
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
    )


async def _execute(orchestrator, organization_id: UUID, query: str):
    return await orchestrator.execute(
        organization_id=organization_id,
        user_id=uuid4(),
        query=query,
        role="admin",
        model="fake-llm",
        use_cache=False,
    )


@pytest.mark.asyncio
async def test_off_no_agrega_bloque_cognitivo(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "off")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105 de Category 31?"
    )
    assert result.flow is not None
    assert "cognitive" not in result.flow
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_traza_plan_y_strategy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105 de Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["mode"] == "shadow"
    assert "exact_lookup" in cognitive["plan"]["needs"]
    assert "vector" in [
        item["representation"] for item in cognitive["strategy"]["representations"]
    ]
    assert cognitive["strategy"]["scope"]["organization_id"] == str(organization.id)
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_saludo_no_requiere_conocimiento(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, "Hola, buenos días")
    cognitive = result.flow["cognitive"]
    assert cognitive["plan"]["needs"] == ["no_retrieval"]
    assert cognitive["plan"]["requires_knowledge"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_need"),
    [
        ("¿Qué cambió en la regla X respecto a la versión anterior?", "temporal_lookup"),
        ("Compara el total de la columna 7 entre 2024 y 2025", "comparison"),
        ("¿Aplica la regla 12 para este caso?", "rule_lookup"),
    ],
)
async def test_shadow_escenarios(monkeypatch, query: str, expected_need: str) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, query)
    assert expected_need in result.flow["cognitive"]["plan"]["needs"]
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_runtime_shadow.py -q`
Expected: FAIL (`KeyError: 'cognitive'`) en los tests de shadow.

- [ ] **Step 3: Wiring en el orchestrator**

3a. Import (después de `from src.rag.retrieval.models import RetrievalQuery`):

```python
from src.runtime.cognitive_state import CognitiveTurn, cognitive_runtime_mode
```

3b. En `execute`, después de `total_start = time.perf_counter()`:

```python
        # W1 (C1): plan + strategy del turno. Shadow: se trazan y no cambian la
        # ejecución. off: costo cero y comportamiento intacto.
        cognitive_turn: CognitiveTurn | None = None
        if cognitive_runtime_mode() != "off":
            from src.rag.retrieval.planner import build_retrieval_plan
            from src.runtime.cognitive_plan import build_cognitive_plan
            from src.runtime.knowledge_strategy import build_knowledge_strategy

            retrieval_plan = build_retrieval_plan(query)
            cognitive_turn = CognitiveTurn(
                query=query,
                plan=build_cognitive_plan(query, retrieval_plan=retrieval_plan),
                strategy=build_knowledge_strategy(
                    retrieval_plan,
                    organization_id=str(organization_id),
                    workspace_id=str(workspace_id) if workspace_id else None,
                    role=role,
                ),
            )
            logger.info(
                "Cognitive turn planned",
                mode=cognitive_runtime_mode(),
                complexity=(
                    cognitive_turn.plan.complexity.value if cognitive_turn.plan else None
                ),
                needs=(
                    [need.value for need in cognitive_turn.plan.needs]
                    if cognitive_turn.plan
                    else []
                ),
            )
```

3c. Firma de `_run_knowledge_retrieve`: agregar el parámetro al final de la lista keyword-only:

```python
        workspace_id: UUID | None = None,
        cognitive_turn: CognitiveTurn | None = None,
    ) -> RetrievalContext:
```

3d. Dentro de `_run_knowledge_retrieve`, después de `plan = KnowledgeRetrievalPlanner().plan(query)`:

```python
        if cognitive_turn is not None:
            from src.runtime.knowledge_strategy import build_knowledge_strategy

            cognitive_turn.strategy = build_knowledge_strategy(
                plan,
                organization_id=str(organization_id),
                workspace_id=str(workspace_id) if workspace_id else None,
                role=role,
            )
```

3e. Call site (dentro de `_vector_search_full_inner`): agregar el argumento:

```python
                        workspace_id=workspace_id,
                        cognitive_turn=cognitive_turn,
                    )
```

3f. En el `finally` de `execute`, entre el attach del preflight y `record_flow`:

```python
                    if cognitive_turn is not None and isinstance(result.flow, dict):
                        result.flow["cognitive"] = cognitive_turn.to_public_dict()
```

Contexto exacto:

```python
                        result.flow = self._preflight_hook.attach(  # type: ignore[union-attr]
                            result.flow, preflight_trace
                        )
                        result.flow = _flow_with_story(result.flow)
                    if cognitive_turn is not None and isinstance(result.flow, dict):
                        result.flow["cognitive"] = cognitive_turn.to_public_dict()
                    from src.rag.flow_store import record_flow
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_runtime_shadow.py -q`
Expected: `6 passed` (los 3 escenarios parametrizados cuentan como 3).

- [ ] **Step 5: Regresión del runtime**

Run:

```bash
pytest tests/test_cognitive_runtime_shadow.py tests/test_jev_preflight_flow.py tests/test_retrieval_planner.py tests/test_architecture.py -q
```

Expected: todos PASS.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src tests
git add src/agents/runtime/orchestrator.py tests/test_cognitive_runtime_shadow.py
git commit -m "feat(cognitive): plan+strategy shadow en el runtime RAG (C1)"
```

---

### Task 5: Documentación del modo y estado de fase

**Files:**
- Modify: `.env.example:432-434`
- Modify: `README.md:630`
- Modify: `docs/architecture/cognitive-runtime.md` (línea de estado)

- [ ] **Step 1: Actualizar `.env.example`**

Reemplazar:

```
# Cognitive OS (Phase 3): off | shadow | limited | active.
# off bloquea /api/v1/cognitive/* (503). Planificación/delegación únicamente.
RAG_COGNITIVE_OS_ENABLED=off
```

por:

```
# Cognitive runtime (W1): off | shadow | limited | active.
# off: runtime actual intacto (también bloquea /api/v1/cognitive/* con 503).
# shadow: plan+strategy se trazan en el flow; la ejecución no cambia.
# limited: pipeline cognitivo L0-L2. active: incluye DAG L3+.
RAG_COGNITIVE_OS_ENABLED=off
```

- [ ] **Step 2: Actualizar README**

Reemplazar:

```
| **En consolidación** | **Cognitive OS** | Activación de los motores cognitivos hoy flag-gated sobre el conocimiento canónico del Knowledge OS |
```

por:

```
| **En consolidación** | **Cognitive runtime (W1)** | Plan+strategy shadow en `/rag/query`; fases C1–C9 en [`docs/architecture/cognitive-runtime.md`](docs/architecture/cognitive-runtime.md) |
```

- [ ] **Step 3: Marcar C1 en el spec**

En `docs/architecture/cognitive-runtime.md`, tabla §15, fila C1: cambiar `shadow para probar; default off` por `shadow (default off) — **shipped**` y el Plan por el link del plan C1 ya existente.

- [ ] **Step 4: Verificación final**

```bash
pytest tests/test_cognitive_plan.py tests/test_knowledge_strategy.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_architecture.py tests/test_jev_preflight_flow.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md docs/architecture/cognitive-runtime.md
git commit -m "docs(cognitive): contrato runtime C1 y flags"
```

---

## Criterios de salida C1

- [ ] `off`: comportamiento y flow sin bloque `cognitive`; 1 llamada LLM como hoy.
- [ ] `shadow`: `flow["cognitive"]` con `mode`, plan (complejidad + needs + razones) y strategy (representaciones + razones + scope).
- [ ] Cero cambios de retrieval/JEV/LLM en C1 (los tests de regresión lo prueban).
- [ ] Sin migraciones, sin dependencias, sin cambios de contrato API.
- [ ] `ruff check src tests` limpio.
