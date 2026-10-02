# Cognitive Runtime C6 — Traza Cognitiva (3 niveles) + Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proyectar las etapas cognitivas a la traza existente (eventos + trace v2 + narrative) en 3 niveles (normal/expandido/raw) sin duplicar eventos técnicos, y renderizarlas en el portal reusando las vistas actuales.

**Architecture:** Un módulo puro nuevo `src/rag/cognitive_story.py` deriva los 3 niveles de `flow["cognitive"]`; `flow_story.with_story` agrega `cognitive_story` y genera los eventos cognitivos desde `normal` (único origen); `traceability` gana una sección `cognitive`; el orquestador adjunta `flow["cognitive"]` **antes** de construir la historia (hoy se adjunta después, por eso la traza no lo ve); el portal agrega dos componentes aislados (historia + tarjeta técnica) en `ExecutionStoryView`.

**Tech Stack:** Python del repo, pytest; portal React/TS con vitest + tsc (node 22/npm 11 disponibles); ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` §8 (W3), §12/§13, fase C6 §15.

## Global Constraints

- Aditivo y fail-soft: nada existente se reemplaza; sin `cognitive` no hay eventos/secciones nuevas y todo queda igual.
- Un solo origen: los eventos cognitivos se derivan de `cognitive_story.normal`; las vistas renderizan, no recalculan.
- Sin texto de UI en backend (solo claves/números/refs); el portal traduce.
- Sin CoT; sin dependencias nuevas; sin migraciones; sin cambios de contrato API.
- `off` intacto; `flow["cognitive"]` no cambia de forma.
- Código/comentarios español; tests `tests/test_*.py` y vitest `portal/src/**/*.test.{ts,tsx}`.
- Cada tarea: tests verdes, lint/typecheck, commit. Branch `feat/cognitive-runtime-c6` desde `master`.

---

### Task 1: `cognitive_story` (3 niveles, puro)

**Files:**
- Create: `src/rag/cognitive_story.py`
- Test: `tests/test_cognitive_story.py`

**Interfaces:**
- Consumes: `flow["cognitive"]` (forma C5).
- Produces:
  - `COGNITIVE_STORY_SCHEMA_VERSION = 1`.
  - `build_cognitive_story(flow: Mapping | None) -> dict` con `{schema_version, normal, expanded, raw}`.
  - `normal`: pasos `{kind, phase, status, metrics}` (sin texto UI); `expanded`/`raw`: subconjuntos acotados.

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c6
pytest tests/test_flow_story.py tests/test_traceability_v2.py -q
```

Expected: PASS.

- [ ] **Step 2: Escribir el test que falla**

`tests/test_cognitive_story.py`:

```python
# =============================================================================
# Cognitive story — proyección de flow["cognitive"] a 3 niveles (C6).
# =============================================================================
from __future__ import annotations

from src.rag.cognitive_story import build_cognitive_story

_COGNITIVE = {
    "mode": "active",
    "signals": {"exact_lookup_declared": True, "entity_resolved": True},
    "plan": {"complexity": "L3", "needs": ["comparison", "temporal_lookup"]},
    "strategy": {
        "primary": "exact",
        "representations": [{"representation": "exact", "reason": "literales"}],
    },
    "entities": {
        "resolved": True,
        "mentions": [{"mention": "Category 31", "status": "resolved", "matches": []}],
    },
    "runners": [
        {"representation": "graph", "status": "ok", "count": 2, "items": [], "latency_ms": 12.0}
    ],
    "evidence": {
        "count": 3,
        "chars": 900,
        "budget_chars": 12000,
        "counts": {"fact": 1, "excerpt": 2},
        "conflicts": [{"key": "c1|rule x|aplica", "unit_ids": ["U1", "U2"], "values": ["2024", "2026"]}],
        "dropped_count": 1,
        "units": [],
    },
    "brief": {
        "chars": 400,
        "budget_chars": 8000,
        "sections": [{"kind": "facts", "count": 1, "chars": 120, "truncated": 0, "items": []}],
    },
    "verification": {"action": "answer_with_limits", "count": 2, "supported": 1, "unsupported": 1},
    "budget": {"complexity": "L3", "llm_calls": 2, "tokens": 1200, "within_budget": True},
    "loop": {"rounds": [], "count": 1, "extra_round": False, "max_rounds": 3, "exhausted": False},
    "learning": [{"kind": "conflict", "concept": "c1", "detail": "x", "priority": 0.65}],
    "run_id": "run-1",
    "deep": {"status": "completed", "failure_mode": "", "metrics": {"tokens": 1200}},
}


def test_sin_cognitive_devuelve_shape_vacio() -> None:
    story = build_cognitive_story({})
    assert story["schema_version"] == 1
    assert story["normal"] == []
    assert story["expanded"] == {}
    assert story["raw"] == {}


def test_normal_deriva_pasos_con_metricas() -> None:
    story = build_cognitive_story({"cognitive": _COGNITIVE})
    kinds = [step["kind"] for step in story["normal"]]
    assert kinds == [
        "cognitive_plan",
        "cognitive_strategy",
        "cognitive_entities",
        "cognitive_runner",
        "cognitive_evidence",
        "cognitive_brief",
        "cognitive_verification",
        "cognitive_budget",
        "cognitive_loop",
        "cognitive_learning",
        "cognitive_deep_run",
    ]
    plan = story["normal"][0]
    assert plan["phase"] == "planning"
    assert plan["metrics"]["complexity"] == "L3"
    assert plan["metrics"]["needs"] == 2


def test_expanded_y_raw_acotados() -> None:
    story = build_cognitive_story({"cognitive": _COGNITIVE})
    assert story["expanded"]["strategy"]["primary"] == "exact"
    assert story["expanded"]["evidence"]["conflicts"] == 1
    assert story["expanded"]["budget"]["within_budget"] is True
    assert story["raw"]["run_id"] == "run-1"
    assert story["raw"]["deep_metrics"]["tokens"] == 1200


def test_nunca_lanza_con_cognitive_roto() -> None:
    story = build_cognitive_story({"cognitive": {"plan": "roto", "runners": 7}})
    assert isinstance(story["normal"], list)
    assert isinstance(story["expanded"], dict)
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_story.py -q`
Expected: FAIL (`ModuleNotFoundError: src.rag.cognitive_story`).

- [ ] **Step 4: Implementar**

`src/rag/cognitive_story.py`:

```python
# =============================================================================
# Cognitive story — proyección de flow["cognitive"] a 3 niveles (C6, W3).
# =============================================================================
# normal   = pasos humanos (claves + números; el portal traduce a texto)
# expanded = detalle estructurado acotado (strategy, evidencia, budget, loop)
# raw      = refs y métricas crudas del run profundo
# Aditivo y fail-soft: sin cognitive devuelve shape vacío; nunca lanza.
# =============================================================================
from __future__ import annotations

from typing import Any, Mapping

COGNITIVE_STORY_SCHEMA_VERSION = 1
_MAX_EXPANDED_ITEMS = 8


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _counts_by_status(mentions: list) -> dict:
    counts: dict[str, int] = {}
    for mention in mentions:
        status = str(_mapping(mention).get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_cognitive_story(flow: Mapping | None) -> dict:
    """Deriva los 3 niveles del bloque cognitivo del flow."""
    cognitive = _mapping(_mapping(flow).get("cognitive"))
    if not cognitive:
        return {
            "schema_version": COGNITIVE_STORY_SCHEMA_VERSION,
            "normal": [],
            "expanded": {},
            "raw": {},
        }

    normal: list[dict] = []

    plan = _mapping(cognitive.get("plan"))
    if plan:
        normal.append(
            {
                "kind": "cognitive_plan",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "complexity": plan.get("complexity"),
                    "needs": len(_sequence(plan.get("needs"))),
                },
            }
        )

    strategy = _mapping(cognitive.get("strategy"))
    if strategy:
        representations = _sequence(strategy.get("representations"))
        normal.append(
            {
                "kind": "cognitive_strategy",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "primary": strategy.get("primary"),
                    "representations": len(representations),
                },
            }
        )

    entities = _mapping(cognitive.get("entities"))
    if entities:
        mentions = _sequence(entities.get("mentions"))
        normal.append(
            {
                "kind": "cognitive_entities",
                "phase": "understanding",
                "status": "ok" if entities.get("resolved") else "warn",
                "metrics": {
                    "resolved": bool(entities.get("resolved")),
                    "mentions": len(mentions),
                    "by_status": _counts_by_status(mentions),
                },
            }
        )

    for runner in _sequence(cognitive.get("runners")):
        item = _mapping(runner)
        normal.append(
            {
                "kind": "cognitive_runner",
                "phase": "evidence",
                "status": str(item.get("status") or "ok"),
                "metrics": {
                    "representation": item.get("representation"),
                    "count": item.get("count"),
                    "latency_ms": item.get("latency_ms"),
                },
            }
        )

    evidence = _mapping(cognitive.get("evidence"))
    if evidence:
        normal.append(
            {
                "kind": "cognitive_evidence",
                "phase": "evidence",
                "status": "ok" if not _sequence(evidence.get("conflicts")) else "warn",
                "metrics": {
                    "count": evidence.get("count"),
                    "chars": evidence.get("chars"),
                    "budget_chars": evidence.get("budget_chars"),
                    "conflicts": len(_sequence(evidence.get("conflicts"))),
                    "dropped": evidence.get("dropped_count"),
                },
            }
        )

    brief = _mapping(cognitive.get("brief"))
    if brief:
        normal.append(
            {
                "kind": "cognitive_brief",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "chars": brief.get("chars"),
                    "budget_chars": brief.get("budget_chars"),
                    "sections": len(_sequence(brief.get("sections"))),
                },
            }
        )

    verification = _mapping(cognitive.get("verification"))
    if verification:
        normal.append(
            {
                "kind": "cognitive_verification",
                "phase": "verification",
                "status": (
                    "ok" if verification.get("action") == "approve" else "warn"
                ),
                "metrics": {
                    "action": verification.get("action"),
                    "count": verification.get("count"),
                    "unsupported": verification.get("unsupported"),
                    "conflicted": verification.get("conflicted"),
                },
            }
        )

    budget = _mapping(cognitive.get("budget"))
    if budget:
        normal.append(
            {
                "kind": "cognitive_budget",
                "phase": "decision",
                "status": "ok" if budget.get("within_budget") else "warn",
                "metrics": {
                    "complexity": budget.get("complexity"),
                    "tokens": budget.get("tokens"),
                    "max_tokens": budget.get("max_tokens"),
                    "llm_calls": budget.get("llm_calls"),
                },
            }
        )

    loop = _mapping(cognitive.get("loop"))
    if loop:
        normal.append(
            {
                "kind": "cognitive_loop",
                "phase": "evidence",
                "status": "warn" if loop.get("exhausted") else "ok",
                "metrics": {
                    "count": loop.get("count"),
                    "extra_round": bool(loop.get("extra_round")),
                    "exhausted": bool(loop.get("exhausted")),
                },
            }
        )

    learning = _sequence(cognitive.get("learning"))
    if learning:
        normal.append(
            {
                "kind": "cognitive_learning",
                "phase": "learning",
                "status": "ok",
                "metrics": {
                    "count": len(learning),
                    "kinds": sorted(
                        {str(_mapping(item).get("kind") or "") for item in learning}
                    ),
                },
            }
        )

    run_id = str(cognitive.get("run_id") or "")
    deep = _mapping(cognitive.get("deep"))
    if run_id or deep:
        normal.append(
            {
                "kind": "cognitive_deep_run",
                "phase": "generation",
                "status": (
                    "ok"
                    if str(deep.get("status") or "") == "completed"
                    else ("warn" if deep else "ok")
                ),
                "metrics": {
                    "run_id": run_id or None,
                    "status": deep.get("status"),
                    "failure_mode": deep.get("failure_mode") or None,
                    "tokens": _mapping(deep.get("metrics")).get("tokens"),
                },
            }
        )

    expanded = {
        "signals": dict(_mapping(cognitive.get("signals"))),
        "strategy": dict(strategy),
        "entities": dict(entities),
        "runners": _sequence(cognitive.get("runners"))[:_MAX_EXPANDED_ITEMS],
        "evidence": {
            "counts": dict(_mapping(evidence.get("counts"))),
            "chars": evidence.get("chars"),
            "budget_chars": evidence.get("budget_chars"),
            "conflicts": len(_sequence(evidence.get("conflicts"))),
            "dropped_count": evidence.get("dropped_count"),
        },
        "brief": {
            "chars": brief.get("chars"),
            "budget_chars": brief.get("budget_chars"),
            "sections": [
                {
                    "kind": _mapping(section).get("kind"),
                    "count": _mapping(section).get("count"),
                    "chars": _mapping(section).get("chars"),
                    "truncated": _mapping(section).get("truncated"),
                }
                for section in _sequence(brief.get("sections"))[:_MAX_EXPANDED_ITEMS]
            ],
        },
        "verification": dict(verification),
        "budget": dict(budget),
        "loop": dict(loop),
        "learning": learning[:_MAX_EXPANDED_ITEMS],
        "deep": dict(deep),
    }
    raw = {
        "run_id": run_id or None,
        "deep_metrics": dict(_mapping(deep.get("metrics"))),
        "budget": dict(budget),
        "loop": dict(loop),
    }
    return {
        "schema_version": COGNITIVE_STORY_SCHEMA_VERSION,
        "normal": normal,
        "expanded": expanded,
        "raw": raw,
    }
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_story.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/rag/cognitive_story.py tests/test_cognitive_story.py
git add src/rag/cognitive_story.py tests/test_cognitive_story.py
git commit -m "feat(cognitive): cognitive story de 3 niveles (C6)"
```

---

### Task 2: Eventos cognitivos + `cognitive_story` en `with_story`

**Files:**
- Modify: `src/rag/flow_story.py`
- Test: `tests/test_flow_story.py`

**Interfaces:**
- Consumes: `build_cognitive_story` (Task 1).
- Produces: `_COGNITIVE_STEP_PHASES`; `build_flow_events` incluye eventos cognitivos derivados de `flow["cognitive_story"]["normal"]`; `with_story` agrega `cognitive_story` **antes** de eventos/trace/narrative.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_flow_story.py`:

```python
def test_eventos_cognitivos_desde_la_story() -> None:
    flow = {
        "cognitive": {
            "mode": "active",
            "plan": {"complexity": "L3", "needs": ["comparison"]},
            "evidence": {"count": 2, "conflicts": [], "counts": {"fact": 1}},
            "verification": {"action": "answer_with_limits", "count": 1},
        }
    }
    enriched = with_story(flow)
    kinds = [event["kind"] for event in enriched["events"]]
    assert "cognitive_plan" in kinds
    assert "cognitive_evidence" in kinds
    assert "cognitive_verification" in kinds
    plan_event = next(event for event in enriched["events"] if event["kind"] == "cognitive_plan")
    assert plan_event["phase"] == "planning"
    assert plan_event["metrics"]["complexity"] == "L3"
    verification_event = next(
        event for event in enriched["events"] if event["kind"] == "cognitive_verification"
    )
    assert verification_event["status"] == "warn"
    assert enriched["cognitive_story"]["schema_version"] == 1
    assert enriched["traceability"]["cognitive"]["mode"] == "active"


def test_sin_cognitive_no_hay_eventos_nuevos() -> None:
    enriched = with_story({"method": "rag"})
    assert enriched["cognitive_story"]["normal"] == []
    assert all(not event["kind"].startswith("cognitive_") for event in enriched["events"])
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_flow_story.py -q -k cognitivo`
Expected: FAIL (`KeyError: 'cognitive_story'` / kinds ausentes).

- [ ] **Step 3: Implementar**

3a. Constante junto a `JEV_ANSWER_SOURCES`:

```python
#: Paso cognitivo → fase de la historia (el orden lo manda `cognitive_story`).
_COGNITIVE_STEP_PHASES: dict[str, str] = {
    "cognitive_plan": PHASE_PLANNING,
    "cognitive_strategy": PHASE_PLANNING,
    "cognitive_entities": PHASE_UNDERSTANDING,
    "cognitive_runner": PHASE_EVIDENCE,
    "cognitive_evidence": PHASE_EVIDENCE,
    "cognitive_brief": PHASE_PLANNING,
    "cognitive_verification": PHASE_VERIFICATION,
    "cognitive_budget": PHASE_DECISION,
    "cognitive_loop": PHASE_EVIDENCE,
    "cognitive_learning": PHASE_LEARNING,
    "cognitive_deep_run": PHASE_GENERATION,
}
```

3b. Función junto a `_jev_events`:

```python
def _cognitive_events(flow: Mapping, index: int) -> list[dict]:
    """Eventos cognitivos derivados de `cognitive_story.normal` (único origen)."""
    story = flow.get("cognitive_story")
    steps = story.get("normal") if isinstance(story, Mapping) else None
    events: list[dict] = []
    for position, step in enumerate(steps or []):
        if not isinstance(step, Mapping):
            continue
        kind = str(step.get("kind") or "")
        phase = _COGNITIVE_STEP_PHASES.get(kind)
        if phase is None:
            continue
        events.append(
            _event(
                event_id=f"e{index}-cognitive-{position}",
                kind=kind,
                phase=phase,
                status=canonical_status(step.get("status")),
                metrics=dict(step.get("metrics") or {}),
            )
        )
    return events
```

3c. En `build_flow_events`, junto a `events.extend(jev_events)`:

```python
    events.extend(_cognitive_events(flow, index))
```

3d. En `with_story`, calcular la story ANTES de los eventos:

```python
        from src.rag.cognitive_story import build_cognitive_story

        enriched["cognitive_story"] = build_cognitive_story(enriched)
        enriched["events"] = build_flow_events(enriched)
```

(El import puede ir arriba del try interno o a nivel módulo; mantener fail-soft global de `with_story`.)

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_flow_story.py -q`
Expected: todos PASS (los tests viejos sin `cognitive` siguen igual).

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/rag/flow_story.py tests/test_flow_story.py
git add src/rag/flow_story.py tests/test_flow_story.py
git commit -m "feat(cognitive): eventos cognitivos y story en with_story (C6)"
```

---

### Task 3: Sección `cognitive` en trace v2

**Files:**
- Modify: `src/rag/traceability.py`
- Test: `tests/test_traceability_v2.py`

**Interfaces:**
- Consumes: `flow["cognitive"]`.
- Produces: `build_traceability(flow)["cognitive"]` con `{mode, run_id, complexity, strategy_primary, representations, entities_resolved, evidence_counts, conflicts, brief_chars, verification_action, budget_within, loop_rounds, loop_exhausted, learning_count, deep_status, deep_failure_mode}` (todos `None` cuando faltan; shape estable).

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_traceability_v2.py`:

```python
def test_seccion_cognitive_presente_y_estable() -> None:
    flow = _flow()
    flow["cognitive"] = {
        "mode": "active",
        "run_id": "run-1",
        "plan": {"complexity": "L3"},
        "strategy": {"primary": "exact", "representations": [{"representation": "exact"}]},
        "entities": {"resolved": True, "mentions": []},
        "evidence": {"count": 2, "counts": {"fact": 1}, "conflicts": [{"key": "k"}]},
        "brief": {"chars": 200},
        "verification": {"action": "approve"},
        "budget": {"within_budget": True},
        "loop": {"count": 1, "exhausted": False},
        "learning": [{"kind": "conflict"}],
        "deep": {"status": "completed", "failure_mode": ""},
    }
    trace = build_traceability(flow)
    cognitive = trace["cognitive"]
    assert cognitive["mode"] == "active"
    assert cognitive["run_id"] == "run-1"
    assert cognitive["complexity"] == "L3"
    assert cognitive["strategy_primary"] == "exact"
    assert cognitive["representations"] == 1
    assert cognitive["entities_resolved"] is True
    assert cognitive["conflicts"] == 1
    assert cognitive["verification_action"] == "approve"
    assert cognitive["budget_within"] is True
    assert cognitive["loop_rounds"] == 1
    assert cognitive["learning_count"] == 1
    assert cognitive["deep_status"] == "completed"

    empty = build_traceability(_flow())
    assert empty["cognitive"]["mode"] is None
    assert empty["cognitive"]["run_id"] is None
```

(Usar el import existente de `build_traceability` y el fake `_flow` del archivo.)

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_traceability_v2.py -q -k seccion_cognitive`
Expected: FAIL (`KeyError: 'cognitive'`).

- [ ] **Step 3: Implementar**

Agregar helper en `src/rag/traceability.py` (junto a las otras secciones) y la clave en el dict de retorno (junto a `"presentation"`):

```python
def _cognitive_section(flow: Mapping | None) -> dict:
    """Sección cognitiva de la traza (C6): resumen estable, sin texto de UI."""
    cognitive = flow.get("cognitive") if isinstance(flow, Mapping) else None
    if not isinstance(cognitive, Mapping):
        cognitive = {}
    plan = cognitive.get("plan") if isinstance(cognitive.get("plan"), Mapping) else {}
    strategy = (
        cognitive.get("strategy")
        if isinstance(cognitive.get("strategy"), Mapping)
        else {}
    )
    entities = (
        cognitive.get("entities")
        if isinstance(cognitive.get("entities"), Mapping)
        else {}
    )
    evidence = (
        cognitive.get("evidence")
        if isinstance(cognitive.get("evidence"), Mapping)
        else {}
    )
    brief = (
        cognitive.get("brief") if isinstance(cognitive.get("brief"), Mapping) else {}
    )
    verification = (
        cognitive.get("verification")
        if isinstance(cognitive.get("verification"), Mapping)
        else {}
    )
    budget = (
        cognitive.get("budget") if isinstance(cognitive.get("budget"), Mapping) else {}
    )
    loop = cognitive.get("loop") if isinstance(cognitive.get("loop"), Mapping) else {}
    deep = cognitive.get("deep") if isinstance(cognitive.get("deep"), Mapping) else {}
    learning = cognitive.get("learning") if isinstance(cognitive.get("learning"), list) else []
    representations = strategy.get("representations")
    conflicts = evidence.get("conflicts")
    return {
        "mode": cognitive.get("mode"),
        "run_id": cognitive.get("run_id"),
        "complexity": plan.get("complexity"),
        "strategy_primary": strategy.get("primary"),
        "representations": (
            len(representations) if isinstance(representations, list) else None
        ),
        "entities_resolved": entities.get("resolved"),
        "evidence_counts": dict(evidence.get("counts") or {})
        if isinstance(evidence.get("counts"), Mapping)
        else {},
        "conflicts": len(conflicts) if isinstance(conflicts, list) else None,
        "brief_chars": brief.get("chars"),
        "verification_action": verification.get("action"),
        "budget_within": budget.get("within_budget"),
        "loop_rounds": loop.get("count"),
        "loop_exhausted": loop.get("exhausted"),
        "learning_count": len(learning),
        "deep_status": deep.get("status"),
        "deep_failure_mode": deep.get("failure_mode") or None,
    }
```

En el dict retornado por `build_traceability`, agregar `"cognitive": _cognitive_section(flow),` junto a `"presentation"`.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_traceability_v2.py tests/test_traceability.py -q`
Expected: todos PASS.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/rag/traceability.py tests/test_traceability_v2.py
git add src/rag/traceability.py tests/test_traceability_v2.py
git commit -m "feat(cognitive): sección cognitive en trace v2 (C6)"
```

---

### Task 4: Adjuntar `cognitive` antes de la historia

**Files:**
- Modify: `src/agents/runtime/orchestrator.py`
- Modify: `tests/test_cognitive_runtime_shadow.py`

**Interfaces:**
- Consumes: `_build_flow`, `_attach_reasoning_story`, `_flow_with_story`.
- Produces: `_build_flow(..., cognitive: dict | None = None)`; `flow["cognitive"]` presente cuando `with_story` corre (eventos + `cognitive_story` + `traceability.cognitive`); attach tardío eliminado.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_cognitive_runtime_shadow.py`:

```python
@pytest.mark.asyncio
async def test_traza_incluye_cognitive_story_y_eventos(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31?"
    )
    flow = result.flow
    assert flow["cognitive_story"]["normal"]
    kinds = [event["kind"] for event in flow["events"]]
    assert "cognitive_plan" in kinds
    assert flow["traceability"]["cognitive"]["mode"] == "shadow"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_runtime_shadow.py -q -k traza_incluye`
Expected: FAIL (`KeyError: 'cognitive_story'`).

- [ ] **Step 3: Implementar**

3a. `_build_flow`: agregar `cognitive: dict | None = None,` a la firma y, en el dict que retorna envuelto por `_flow_with_story`, incluir el bloque:

```python
            **({"cognitive": cognitive} if cognitive else {}),
```

3b. Call site de `_build_flow` (en el `finally`): pasar

```python
                        cognitive=(
                            cognitive_turn.to_public_dict()
                            if cognitive_turn is not None
                            else None
                        ),
```

3c. Mover el attach antes de `_attach_reasoning_story`:

```python
                    if cognitive_turn is not None and isinstance(result.flow, dict):
                        result.flow["cognitive"] = cognitive_turn.to_public_dict()
                    result.flow = await _attach_reasoning_story(
```

y **eliminar** el attach tardío (`result.flow["cognitive"] = ...` después del bloque de preflight, antes de `record_flow`).

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_runtime_shadow.py tests/test_cognitive_deep_path.py -q`
Expected: todos PASS.

- [ ] **Step 5: Regresión + lint + commit**

```bash
pytest tests/test_cognitive_story.py tests/test_flow_story.py tests/test_traceability_v2.py tests/test_cognitive_runtime_shadow.py tests/test_cognitive_deep_path.py tests/test_architecture.py -q
ruff check src tests
git add src/agents/runtime/orchestrator.py tests/test_cognitive_runtime_shadow.py
git commit -m "feat(cognitive): flow cognitive antes de la historia (C6)"
```

---

### Task 5: Portal — historia + tarjeta técnica

**Files:**
- Create: `portal/src/pages/chat/cognitiveStory.ts`
- Create: `portal/src/pages/chat/story/CognitiveStorySection.tsx`
- Create: `portal/src/pages/chat/story/CognitiveTechnicalCard.tsx`
- Create: `portal/src/pages/chat/cognitiveStory.test.ts`
- Create: `portal/src/pages/chat/story/CognitiveStorySection.test.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.tsx`

**Interfaces:**
- Consumes: `story.technical.raw` (`Flow`, incluye `cognitive_story`).
- Produces: `parseCognitiveStory(value)` + `COGNITIVE_STEP_LABELS`; `<CognitiveStorySection raw={...} />` (normal); `<CognitiveTechnicalCard raw={...} />` (expandido/raw).

- [ ] **Step 1: Escribir los tests que fallan**

`portal/src/pages/chat/cognitiveStory.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseCognitiveStory } from "./cognitiveStory";

const STORY = {
  schema_version: 1,
  normal: [
    {
      kind: "cognitive_plan",
      phase: "planning",
      status: "ok",
      metrics: { complexity: "L3", needs: 2 },
    },
  ],
  expanded: { budget: { within_budget: true } },
  raw: { run_id: "run-1" },
};

describe("parseCognitiveStory", () => {
  it("parsea una story válida", () => {
    const story = parseCognitiveStory(STORY);
    expect(story?.normal).toHaveLength(1);
    expect(story?.normal[0].kind).toBe("cognitive_plan");
    expect(story?.raw.run_id).toBe("run-1");
  });

  it("devuelve null sin story o con shape inválido", () => {
    expect(parseCognitiveStory(undefined)).toBeNull();
    expect(parseCognitiveStory({ normal: "roto" })).toBeNull();
  });
});
```

`portal/src/pages/chat/story/CognitiveStorySection.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CognitiveStorySection } from "./CognitiveStorySection";

describe("CognitiveStorySection", () => {
  it("renderiza los pasos cognitivos", () => {
    render(
      <CognitiveStorySection
        raw={{
          cognitive_story: {
            schema_version: 1,
            normal: [
              {
                kind: "cognitive_plan",
                phase: "planning",
                status: "ok",
                metrics: { complexity: "L3", needs: 2 },
              },
              {
                kind: "cognitive_verification",
                phase: "verification",
                status: "warn",
                metrics: { action: "answer_with_limits", unsupported: 1 },
              },
            ],
            expanded: {},
            raw: {},
          },
        }}
      />,
    );
    expect(screen.getByText("Planeó la consulta")).toBeInTheDocument();
    expect(screen.getByText("Verificó la respuesta")).toBeInTheDocument();
  });

  it("no renderiza nada sin cognitive_story", () => {
    const { container } = render(<CognitiveStorySection raw={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
cd portal
npx vitest run src/pages/chat/cognitiveStory.test.ts src/pages/chat/story/CognitiveStorySection.test.tsx
```

Expected: FAIL (módulos no existen).

- [ ] **Step 3: Implementar**

3a. `portal/src/pages/chat/cognitiveStory.ts`:

```ts
// =============================================================================
// Cognitive story — parser del nivel cognitivo del flow (C6).
// =============================================================================
export interface CognitiveStoryStep {
  kind: string;
  phase: string;
  status: string;
  metrics: Record<string, unknown>;
}

export interface CognitiveStory {
  schemaVersion: number;
  normal: CognitiveStoryStep[];
  expanded: Record<string, unknown>;
  raw: Record<string, unknown>;
}

export const COGNITIVE_STEP_LABELS: Record<
  string,
  { title: string; body: (metrics: Record<string, unknown>) => string }
> = {
  cognitive_plan: {
    title: "Planeó la consulta",
    body: (m) => `Complejidad ${String(m.complexity ?? "—")} · ${String(m.needs ?? 0)} necesidad(es)`,
  },
  cognitive_strategy: {
    title: "Eligió cómo consultar",
    body: (m) => `${String(m.primary ?? "—")} · ${String(m.representations ?? 0)} representación(es)`,
  },
  cognitive_entities: {
    title: "Identificó entidades",
    body: (m) => `${String(m.mentions ?? 0)} mención(es) · resueltas: ${m.resolved ? "sí" : "no"}`,
  },
  cognitive_runner: {
    title: "Consultó una representación",
    body: (m) => `${String(m.representation ?? "—")} · ${String(m.count ?? 0)} resultado(s) · ${String(m.latency_ms ?? 0)} ms`,
  },
  cognitive_evidence: {
    title: "Ensambló la evidencia",
    body: (m) => `${String(m.count ?? 0)} evidencia(s) · ${String(m.conflicts ?? 0)} conflicto(s) · descartadas: ${String(m.dropped ?? 0)}`,
  },
  cognitive_brief: {
    title: "Comprimió el conocimiento",
    body: (m) => `${String(m.chars ?? 0)} caracteres · ${String(m.sections ?? 0)} sección(es)`,
  },
  cognitive_verification: {
    title: "Verificó la respuesta",
    body: (m) => `${String(m.action ?? "—")} · sin respaldo: ${String(m.unsupported ?? 0)} · conflictos: ${String(m.conflicted ?? 0)}`,
  },
  cognitive_budget: {
    title: "Dentro del presupuesto",
    body: (m) => `${String(m.tokens ?? 0)}/${String(m.max_tokens ?? "—")} tokens · ${String(m.llm_calls ?? 0)} llamada(s)`,
  },
  cognitive_loop: {
    title: "Rondas de búsqueda",
    body: (m) => `${String(m.count ?? 0)} ronda(s)${m.extra_round ? " · ronda extra" : ""}${m.exhausted ? " · agotado" : ""}`,
  },
  cognitive_learning: {
    title: "Señales de aprendizaje",
    body: (m) => `${String(m.count ?? 0)} señal(es)`,
  },
  cognitive_deep_run: {
    title: "Investigación profunda",
    body: (m) => `${String(m.status ?? "—")}${m.failure_mode ? ` · ${String(m.failure_mode)}` : ""} · ${String(m.tokens ?? 0)} tokens`,
  },
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

export function parseCognitiveStory(value: unknown): CognitiveStory | null {
  const root = record(value);
  const normal = root.normal;
  if (!Array.isArray(normal)) return null;
  const steps: CognitiveStoryStep[] = [];
  for (const raw of normal) {
    const step = record(raw);
    if (typeof step.kind !== "string") return null;
    steps.push({
      kind: step.kind,
      phase: String(step.phase ?? ""),
      status: String(step.status ?? "ok"),
      metrics: record(step.metrics),
    });
  }
  return {
    schemaVersion: Number(root.schema_version ?? 1),
    normal: steps,
    expanded: record(root.expanded),
    raw: record(root.raw),
  };
}
```

3b. `portal/src/pages/chat/story/CognitiveStorySection.tsx`:

```tsx
// =============================================================================
// CognitiveStorySection — nivel normal: cómo razonó el runtime cognitivo (C6).
// =============================================================================
import { Badge } from "../../../components/ui";
import { COGNITIVE_STEP_LABELS, parseCognitiveStory } from "../cognitiveStory";

export function CognitiveStorySection({ raw }: { raw?: Record<string, unknown> }) {
  const story = parseCognitiveStory(raw?.cognitive_story);
  if (!story || !story.normal.length) return null;
  const runId = String(story.raw.run_id ?? "");
  return (
    <section aria-label="Cómo razonó Zent">
      <div className="mb-2 flex items-center gap-2">
        <span className="eyebrow">Cómo razonó Zent</span>
        {runId ? <Badge tone="neutral">run {runId.slice(0, 8)}</Badge> : null}
      </div>
      <ol className="flex flex-col gap-2">
        {story.normal.map((step, index) => {
          const meta = COGNITIVE_STEP_LABELS[step.kind];
          if (!meta) return null;
          return (
            <li
              key={`${step.kind}-${index}`}
              className="flex gap-3 rounded-md border border-border-soft px-3 py-2"
            >
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-strong text-[11px] text-muted">
                {index + 1}
              </span>
              <div>
                <p className="text-[12.5px] font-medium text-text">{meta.title}</p>
                <p className="text-[12px] text-muted">{meta.body(step.metrics)}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default CognitiveStorySection;
```

3c. `portal/src/pages/chat/story/CognitiveTechnicalCard.tsx`:

```tsx
// =============================================================================
// CognitiveTechnicalCard — nivel expandido/raw del runtime cognitivo (C6).
// =============================================================================
import { parseCognitiveStory } from "../cognitiveStory";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-faint">{label}</dt>
      <dd className="text-text">{value}</dd>
    </div>
  );
}

export function CognitiveTechnicalCard({ raw }: { raw?: Record<string, unknown> }) {
  const story = parseCognitiveStory(raw?.cognitive_story);
  if (!story) return null;
  const expanded = story.expanded;
  const strategy = (expanded.strategy ?? {}) as Record<string, unknown>;
  const evidence = (expanded.evidence ?? {}) as Record<string, unknown>;
  const budget = (expanded.budget ?? {}) as Record<string, unknown>;
  const loop = (expanded.loop ?? {}) as Record<string, unknown>;
  const verification = (expanded.verification ?? {}) as Record<string, unknown>;
  const deep = (expanded.deep ?? {}) as Record<string, unknown>;
  return (
    <article className="rounded-lg border border-border bg-surface p-4">
      <p className="eyebrow mb-2">Runtime cognitivo</p>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
        <Row label="Modo" value={String(story.raw.run_id ? "run profundo" : "observación")} />
        <Row label="Run" value={String(story.raw.run_id ?? "—")} />
        <Row label="Estrategia" value={String(strategy.primary ?? "—")} />
        <Row label="Evidencia" value={String(evidence.count ?? 0)} />
        <Row label="Conflictos" value={String(evidence.conflicts ?? 0)} />
        <Row label="Verificación" value={String(verification.action ?? "—")} />
        <Row label="Budget" value={budget.within_budget ? "dentro" : "excedido"} />
        <Row label="Rondas" value={String(loop.count ?? 0)} />
        <Row label="Deep" value={String(deep.status ?? "—")} />
      </dl>
    </article>
  );
}

export default CognitiveTechnicalCard;
```

3d. `portal/src/pages/chat/story/ExecutionStoryView.tsx`:
- Import: `import { CognitiveStorySection } from "./CognitiveStorySection";` y `import { CognitiveTechnicalCard } from "./CognitiveTechnicalCard";`
- Story v2 branch:

```tsx
      {mode === "story" && traceV2 ? (
        <>
          <TraceV2Story trace={traceV2} onOpenTechnical={() => onModeChange("technical")} />
          <CognitiveStorySection raw={story.technical.raw} />
        </>
      ) : explained && traceability ? (
```

- Technical branch:

```tsx
          {traceV2 ? (
            <>
              <TraceV2Technical trace={traceV2} />
              <CognitiveTechnicalCard raw={story.technical.raw} />
            </>
          ) : null}
```

- [ ] **Step 4: Correr y verificar que pasa**

```bash
cd portal
npx vitest run src/pages/chat/cognitiveStory.test.ts src/pages/chat/story/CognitiveStorySection.test.tsx
npm run typecheck
```

Expected: tests verdes + typecheck limpio.

- [ ] **Step 5: Regresión portal + commit**

```bash
cd portal
npx vitest run
git add src/pages/chat/cognitiveStory.ts src/pages/chat/cognitiveStory.test.ts src/pages/chat/story/CognitiveStorySection.tsx src/pages/chat/story/CognitiveStorySection.test.tsx src/pages/chat/story/CognitiveTechnicalCard.tsx src/pages/chat/story/ExecutionStoryView.tsx
git commit -m "feat(cognitive): vista cognitiva en la historia y tarjeta técnica (C6)"
```

(Si `npx vitest run` completo tarda demasiado, correr al menos los archivos `story/*.test.tsx` y `executionStory*.test.ts`.)

---

### Task 6: Docs + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C6)
- Test: suites backend + portal

- [ ] **Step 1: Docs**

§15 fila C6 → agregar `**shipped**` al final de la celda Contenido y el link del plan `docs/superpowers/plans/2026-10-02-cognitive-runtime-c6-trace-portal.md` en la celda Plan, con nota: "3 niveles derivados en `cognitive_story` + eventos + sección `cognitive` en trace v2 + componentes portal; inspector de runs profundos enlazado por `run_id`; promoción de modos sujeta a evals (W6)."

- [ ] **Step 2: Verificación final backend**

```bash
pytest tests/test_cognitive_story.py tests/test_flow_story.py tests/test_traceability_v2.py tests/test_traceability.py tests/test_cognitive_runtime_shadow.py tests/test_cognitive_deep_path.py tests/test_answer_verification.py tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_cognitive_state.py tests/test_architecture.py tests/test_jev_preflight_flow.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 3: Verificación final portal**

```bash
cd portal
npm run typecheck
npx vitest run
```

Expected: typecheck limpio + tests verdes.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/cognitive-runtime.md
git commit -m "docs(cognitive): C6 traza cognitiva y portal shipped"
```

---

## Criterios de salida C6

- [ ] Sin `cognitive`: eventos/secciones/componentes ausentes; todo igual (tests viejos verdes).
- [ ] Con `cognitive`: `flow["cognitive_story"]` (3 niveles), eventos `cognitive_*` derivados de `normal`, `traceability.cognitive` estable, y `flow["cognitive"]` presente antes de `with_story`.
- [ ] Portal: historia muestra "Cómo razonó Zent" (normal) y técnica la tarjeta del runtime (expandido/raw); sin cognitive no renderiza nada.
- [ ] Sin dependencias/migraciones/API; `ruff check src tests` limpio; `npm run typecheck` limpio.
