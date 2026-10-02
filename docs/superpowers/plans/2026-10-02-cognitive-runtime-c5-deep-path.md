# Cognitive Runtime C5 — Deep Path L3+ (DAG vía runtime) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En modo `active`, las consultas L3+ de conocimiento se responden con el DAG cognitivo existente (planificar → ejecutar → sintetizar), persistiendo el run y linkeándolo a la traza (`flow["cognitive"]["run_id"]`), con fallback legacy fail-soft y enforcement mínimo de verificación.

**Architecture:** El orquestador inyecta `cognitive_service` + `cognitive_executor` (ya existentes en `deps`), corre el DAG como rama previa a la generación normal (si hay respuesta, no se llama al LLM legacy) y mueve el cierre del turno (`ensure`/`finalize`/enforcement) al inicio del `finally` para que la traza y el enforcement precedan al armado del flow. El executor ya enforce su `CognitiveBudget`; si el run falla (p. ej. `budget_limit`) se cae al camino normal.

**Tech Stack:** Python del repo, pytest + pytest-asyncio, Postgres real solo en tests existentes del repo cognitivo (aquí fakes), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` (S8/S9, §7, fase C5 §15).

## Global Constraints

- `RAG_COGNITIVE_OS_ENABLED` default `off`; con `off`/`shadow`/`limited` el deep path NO corre (solo `active`).
- Deep path solo si: `active`, `turn.plan.complexity in {L3,L4,L5}`, `turn.plan.requires_knowledge`, `not sql_mode`, sin `preflight_skip_answer`.
- Fail-soft total: cualquier error/timeout/sin-respuesta del DAG → se sigue el camino legacy sin cambiar la respuesta.
- Enforcement C5 (solo `active`): verificación `answer_with_limits|revise` agrega nota determinista de límites; `abstain` se traza, no reescribe (diferido a W6).
- Budget: el executor aplica `CognitiveBudget`; un run `failed`/sin respuesta cae a legacy. El reporte `turn.budget` sigue siendo informativo.
- Sin dependencias nuevas, sin migraciones (tablas 104/105/108 ya existen), sin cambios de contrato API.
- Código/comentarios en español; tests en `tests/test_*.py`. Cada tarea: tests verdes, lint limpio, commit. Branch `feat/cognitive-runtime-c5` desde `master`.

---

### Task 1: Nota de límites determinista

**Files:**
- Modify: `src/runtime/verification.py`
- Test: `tests/test_answer_verification.py`

**Interfaces:**
- Consumes: `AnswerVerification` (C4).
- Produces: `limits_note(verification) -> str` (vacío si `approve`/sin faltantes; texto con "Límites de esta respuesta: …").

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c5
pytest tests/test_answer_verification.py -q
```

Expected: PASS.

- [ ] **Step 2: Escribir el test que falla**

Agregar a `tests/test_answer_verification.py`:

```python
def test_limits_note_vacia_en_approve() -> None:
    from src.runtime.verification import limits_note

    assert limits_note(verify_answer("", _package())) == ""


def test_limits_note_declara_faltantes() -> None:
    from src.runtime.verification import limits_note

    report = verify_answer(
        "El sistema usa blockchain cuántico.", _package()
    )
    note = limits_note(report)
    assert note.startswith("Límites de esta respuesta:")
    assert "sin respaldo" in note
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_answer_verification.py -q -k limits_note`
Expected: FAIL (`ImportError: cannot import name 'limits_note'`).

- [ ] **Step 4: Implementar**

Agregar al final de `src/runtime/verification.py`:

```python
def limits_note(verification: AnswerVerification) -> str:
    """Nota determinista de límites para respuestas con evidencia incompleta."""
    parts: list[str] = []
    if verification.unsupported:
        parts.append(f"{verification.unsupported} afirmación(es) sin respaldo")
    if verification.partially_supported:
        parts.append(f"{verification.partially_supported} con respaldo parcial")
    if verification.conflicted:
        parts.append(f"{verification.conflicted} en conflicto entre fuentes")
    if verification.outdated:
        parts.append(f"{verification.outdated} desactualizada(s)")
    if not parts:
        return ""
    return (
        "Límites de esta respuesta: "
        + "; ".join(parts)
        + ". Verifica en las fuentes citadas."
    )
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_answer_verification.py -q`
Expected: `9 passed`.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/runtime/verification.py tests/test_answer_verification.py
git add src/runtime/verification.py tests/test_answer_verification.py
git commit -m "feat(cognitive): nota de límites determinista (C5)"
```

---

### Task 2: Estado del turno para el deep path

**Files:**
- Modify: `src/runtime/cognitive_state.py`
- Test: `tests/test_cognitive_state.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `CognitiveTurn.run_id: str | None`, `CognitiveTurn.deep: dict | None`; `to_public_dict()` con `"run_id"` y `"deep"`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_cognitive_state.py`:

```python
def test_turn_publica_run_id_y_deep(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    turn = CognitiveTurn(query="q")
    payload = turn.to_public_dict()
    assert payload["run_id"] is None
    assert payload["deep"] is None
    turn.run_id = "run-123"
    turn.deep = {"status": "completed", "metrics": {"tokens": 120}}
    payload = turn.to_public_dict()
    assert payload["run_id"] == "run-123"
    assert payload["deep"]["metrics"]["tokens"] == 120
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_state.py -q -k run_id`
Expected: FAIL (`KeyError: 'run_id'`).

- [ ] **Step 3: Implementar**

En `src/runtime/cognitive_state.py`, campos después de `learning`:

```python
    run_id: str | None = None
    deep: dict | None = None
```

Y en `to_public_dict()`, antes del return:

```python
        payload["run_id"] = self.run_id
        payload["deep"] = dict(self.deep) if self.deep is not None else None
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_state.py -q`
Expected: todos PASS.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/cognitive_state.py tests/test_cognitive_state.py
git add src/runtime/cognitive_state.py tests/test_cognitive_state.py
git commit -m "feat(cognitive): run_id y deep en el estado del turno (C5)"
```

---

### Task 3: Deep path en el orquestador + enforcement + deps

**Files:**
- Modify: `src/agents/runtime/orchestrator.py` (constructor; `DEEP_PATH_TIMEOUT_SECONDS`; `_run_deep_reasoning`; rama deep en generación; cierre al inicio del `finally`; `_enforce_cognitive_verification`)
- Modify: `src/api/deps.py` (inyectar `cognitive_service`/`cognitive_executor`)
- Test: `tests/test_cognitive_deep_path.py`

**Interfaces:**
- Consumes: `CognitiveScope` (`src.core.domain.cognitive`), `LLMResponse`, `cognitive_runtime_mode`, `limits_note`.
- Produces: constructor `cognitive_service`/`cognitive_executor`; `_run_deep_reasoning(...) -> LLMResponse | None`; `_enforce_cognitive_verification(turn, *, result)`; rama deep en la cadena de generación.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_cognitive_deep_path.py`:

```python
# =============================================================================
# Deep path C5 — DAG cognitivo para L3+ en modo active.
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
    def __init__(self, content: str = "Respuesta legacy") -> None:
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


class FakeCognitiveService:
    def __init__(self, *, boom: bool = False) -> None:
        self.boom = boom
        self.calls: list[dict] = []

    async def create_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("planner caído")
        return {"run": {"id": str(uuid4())}, "tasks": [], "agents": []}


class FakeCognitiveExecutor:
    def __init__(
        self,
        *,
        answer: str | None = "Registro 1 OPEN",
        status: str = "completed",
        failure_mode: str = "",
        boom: bool = False,
    ) -> None:
        self.answer = answer
        self.status = status
        self.failure_mode = failure_mode
        self.boom = boom
        self.calls: list[dict] = []

    async def execute_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("executor caído")
        plan = {"final_answer": self.answer} if self.answer else {}
        return {
            "run": {
                "id": str(kwargs.get("run_id")),
                "status": self.status,
                "failure_mode": self.failure_mode,
                "plan": plan,
            },
            "tasks": [],
            "messages": [],
            "executions": [],
            "metrics": {
                "tokens": 120,
                "cost_usd": 0.01,
                "latency_ms": 50.0,
                "llm_calls": 2,
                "has_answer": bool(self.answer),
            },
        }


def _organization() -> Organization:
    return Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)


def _retrieval() -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Registro 1 OPEN | Registro 2 CLOSE",
                score=0.9,
                metadata={"filename": "secuencia.txt"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _build(
    *,
    organization: Organization,
    llm: FakeLLM,
    service: FakeCognitiveService,
    executor: FakeCognitiveExecutor,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=FakeVectorStore(_retrieval()),
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        cognitive_service=service,
        cognitive_executor=executor,
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


_L3_QUERY = "Compara el total de la columna 7 entre 2024 y 2025"


@pytest.mark.asyncio
async def test_active_l3_usa_el_dag(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    service = FakeCognitiveService()
    executor = FakeCognitiveExecutor(answer="Registro 1 OPEN")
    orchestrator = _build(
        organization=organization, llm=llm, service=service, executor=executor
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method == "cognitive_os"
    assert result.llm_response is not None
    assert result.llm_response.content == "Registro 1 OPEN"
    assert llm.calls == []  # el LLM legacy no se invoca
    cognitive = result.flow["cognitive"]
    assert cognitive["run_id"]
    assert cognitive["deep"]["metrics"]["tokens"] == 120
    assert service.calls and executor.calls


@pytest.mark.asyncio
async def test_limited_no_usa_el_dag(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")
    organization = _organization()
    llm = FakeLLM()
    service = FakeCognitiveService()
    executor = FakeCognitiveExecutor()
    orchestrator = _build(
        organization=organization, llm=llm, service=service, executor=executor
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method != "cognitive_os"
    assert len(llm.calls) == 1
    assert service.calls == []


@pytest.mark.asyncio
async def test_deep_sin_respuesta_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(answer=None)
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method != "cognitive_os"
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["run_id"]


@pytest.mark.asyncio
async def test_deep_budget_limit_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(
        answer=None, status="failed", failure_mode="budget_limit"
    )
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["deep"]["failure_mode"] == "budget_limit"


@pytest.mark.asyncio
async def test_deep_boom_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(boom=True),
        executor=FakeCognitiveExecutor(),
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.llm_response is not None
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_active_agrega_nota_de_limites(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(
        answer="El sistema usa blockchain cuántico."
    )
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert "Límites de esta respuesta:" in result.llm_response.content
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_deep_path.py -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'cognitive_service'`).

- [ ] **Step 3: Implementar**

3a. Constructor: agregar al final de la firma `cognitive_service: object | None = None,` y `cognitive_executor: object | None = None,`; asignar `self._cognitive_service = cognitive_service` y `self._cognitive_executor = cognitive_executor` junto a `self._gap_recorder`.

3b. Constante module-level junto a los imports:

```python
#: Tope del deep path L3+ (el executor además aplica su CognitiveBudget).
DEEP_PATH_TIMEOUT_SECONDS = 90.0
```

3c. Método nuevo junto a `_finalize_cognitive_turn`:

```python
    async def _run_deep_reasoning(
        self,
        *,
        query: str,
        organization_id: UUID,
        user_id: UUID | None,
        role: str,
        workspace_id: UUID | None,
        cognitive_turn: CognitiveTurn,
    ) -> LLMResponse | None:
        """DAG cognitivo para L3+ en active. None = seguir el camino legacy."""
        try:
            from src.core.domain.cognitive import CognitiveScope

            groups = (
                list(await self._resolve_user_groups(organization_id, user_id))
                if user_id
                else []
            )
            scope = CognitiveScope(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
                groups=tuple(groups),
            )
            created = await self._cognitive_service.create_run(  # type: ignore[union-attr]
                query=query, scope=scope, created_by=user_id
            )
            run_info = created.get("run") if isinstance(created, dict) else None
            run_id = str((run_info or {}).get("id") or "")
            if not run_id:
                return None
            cognitive_turn.run_id = run_id
            started = time.perf_counter()
            result = await asyncio.wait_for(
                self._cognitive_executor.execute_run(  # type: ignore[union-attr]
                    organization_id=organization_id,
                    run_id=UUID(run_id),
                    scope=scope,
                ),
                timeout=DEEP_PATH_TIMEOUT_SECONDS,
            )
            run_after = result.get("run") if isinstance(result, dict) else None
            plan = (run_after or {}).get("plan") or {}
            answer = str(plan.get("final_answer") or "").strip()
            metrics = result.get("metrics") or {}
            cognitive_turn.deep = {
                "status": str((run_after or {}).get("status") or ""),
                "failure_mode": str((run_after or {}).get("failure_mode") or ""),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "metrics": {
                    key: metrics.get(key)
                    for key in (
                        "tasks",
                        "evidence_count",
                        "claims",
                        "conflicts",
                        "llm_calls",
                        "tokens",
                        "cost_usd",
                        "latency_ms",
                        "has_answer",
                    )
                    if metrics.get(key) is not None
                },
            }
            if not answer:
                return None
            return LLMResponse(
                content=answer,
                model="cognitive_os",
                total_tokens=int(metrics.get("tokens") or 0),
                latency_ms=float(metrics.get("latency_ms") or 0.0),
                finish_reason="stop",
            )
        except Exception as exc:  # noqa: BLE001 — deep nunca rompe el run
            logger.warning("Cognitive deep path failed", error=str(exc)[:200])
            return None
```

3d. Rama deep: justo antes de `async with trace_span("rag.llm", ...)`:

```python
            deep_response = None
            if (
                self._cognitive_service is not None
                and self._cognitive_executor is not None
                and cognitive_turn is not None
                and cognitive_turn.plan is not None
                and cognitive_turn.plan.complexity.value in {"L3", "L4", "L5"}
                and cognitive_turn.plan.requires_knowledge
                and not sql_mode
                and preflight_skip_answer is None
                and cognitive_runtime_mode() == "active"
            ):
                deep_response = await self._run_deep_reasoning(
                    query=query,
                    organization_id=organization_id,
                    user_id=user_id,
                    role=role,
                    workspace_id=workspace_id,
                    cognitive_turn=cognitive_turn,
                )
```

Y en la cadena de generación, entre `preflight_skip_answer` y `extracted`:

```python
                elif deep_response is not None:
                    llm_response = deep_response
                    result.method = "cognitive_os"
                    if on_delta is not None:
                        await on_delta(deep_response.content)
```

3e. Enforcement: método nuevo:

```python
    def _enforce_cognitive_verification(
        self, turn: CognitiveTurn, *, result: Any
    ) -> None:
        """C5 (solo active): respuestas con límites/revise agregan la nota."""
        try:
            if (
                turn.verification is None
                or result.llm_response is None
                or cognitive_runtime_mode() != "active"
                or turn.verification.action not in {"answer_with_limits", "revise"}
            ):
                return
            from src.runtime.verification import limits_note

            note = limits_note(turn.verification)
            content = str(result.llm_response.content or "")
            if note and note not in content:
                result.llm_response.content = f"{content}\n\n{note}"
        except Exception as exc:  # noqa: BLE001 — enforcement fail-soft
            logger.warning(
                "Cognitive verification enforcement failed", error=str(exc)[:200]
            )
```

3f. Cierre al inicio del `finally`: mover `ensure` + `finalize` (hoy dentro del armado del flow) a inmediatamente después de `result.total_latency_ms = round(...)`, y llamar enforcement:

```python
            if cognitive_turn is not None:
                await self._ensure_cognitive_evidence(
                    cognitive_turn,
                    retrieval_context=locals().get("retrieval_context"),
                    adaptive=adaptive,
                )
                await self._finalize_cognitive_turn(
                    cognitive_turn, result=result, adaptive=adaptive
                )
                self._enforce_cognitive_verification(cognitive_turn, result=result)
```

Eliminar las llamadas viejas a `_ensure_cognitive_evidence`/`_finalize_cognitive_turn` del bloque de armado del flow, conservando el attach `result.flow["cognitive"] = cognitive_turn.to_public_dict()`.

3g. `src/api/deps.py`: en `RAGOrchestrator(...)` agregar:

```python
            cognitive_service=get_cognitive_service(),
            cognitive_executor=get_cognitive_executor(),
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_deep_path.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Regresión + lint + commit**

```bash
pytest tests/test_cognitive_deep_path.py tests/test_cognitive_runtime_shadow.py tests/test_cognitive_state.py tests/test_answer_verification.py tests/test_turn_reports.py tests/test_learning_signal.py tests/test_architecture.py tests/test_jev_preflight_flow.py -q
ruff check src tests
git add src/agents/runtime/orchestrator.py src/api/deps.py tests/test_cognitive_deep_path.py
git commit -m "feat(cognitive): deep path L3+ con persistencia y enforcement (C5)"
```

---

### Task 4: Docs + estado de fase + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C5)
- Test: suite C1–C5

- [ ] **Step 1: Docs**

§15 fila C5 → `active L3+ (default off) — **shipped**` + Plan: `docs/superpowers/plans/2026-10-02-cognitive-runtime-c5-deep-path.md`, con nota: "Deep path usa el DAG existente (runs persistidos 104/105/108 + link `flow['cognitive']['run_id']` → inspector); enforcement C5 = nota de límites en `active`; `abstain` automático y contabilidad de costo del DAG quedan para W6/C6; promoción sujeta a evals."

- [ ] **Step 2: Verificación final**

```bash
pytest tests/test_cognitive_deep_path.py tests/test_answer_verification.py tests/test_turn_reports.py tests/test_learning_signal.py tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_cognitive_domain.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_graph_temporal_runners.py tests/test_tabular_runner.py tests/test_cognitive_plan.py tests/test_knowledge_strategy.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py tests/test_retrieval_planner.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/cognitive-runtime.md
git commit -m "docs(cognitive): C5 deep path L3+ shipped"
```

---

## Criterios de salida C5

- [ ] `off`/`shadow`/`limited`: el DAG no corre; comportamiento intacto.
- [ ] `active` + L3+: respuesta del DAG (`method="cognitive_os"`, LLM legacy no invocado si hay respuesta), run persistido, `flow["cognitive"]["run_id"]` + `deep` (status/failure_mode/métricas).
- [ ] Fallback legacy fail-soft en: sin respuesta, run `failed`/`budget_limit`, error/timeout del planner o executor.
- [ ] Enforcement `active`: `answer_with_limits|revise` agrega nota determinista; `abstain` solo traza.
- [ ] Sin dependencias, migraciones ni cambios de contrato API; `ruff check src tests` limpio.
