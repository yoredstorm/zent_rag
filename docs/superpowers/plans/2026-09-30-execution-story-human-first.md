# Execution Story Human-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir Ver flujo en una historia causal, profesional y auditable, derivada únicamente de estados canónicos existentes, sin perder telemetría ni exponer chain-of-thought.

**Architecture:** `src/rag/execution_narrative.py` construirá una proyección semántica aditiva dentro de `flow_version: 2`; `flow_story.py` la adjuntará sin modificar eventos técnicos. El portal normalizará ese contrato en `executionNarrative.ts`, separará Historia, Rendimiento y Técnico, y conservará fallback honesto para flows antiguos.

**Tech Stack:** Python 3.12, pytest, React 19, TypeScript 5.7, Vitest, Testing Library, Tailwind CSS 4, Radix Tabs, Playwright.

## Global Constraints

- No cambiar lógica de JEV, Evidence Engine, Source Routing, Document Understanding, RAG, prompts, grounding, gates ni respuesta del LLM.
- `ExecutionNarrative` solo agrupa, traduce, resume y formatea estados existentes.
- No almacenar, reconstruir ni mostrar chain-of-thought, scratchpads o prompts internos completos.
- `flow_version` permanece en `2`; contrato nuevo aditivo.
- `EvidenceState` conserva autoridad canónica; JEV permanece advisory.
- Historia no muestra nombres crudos, tokens, modelos, providers, UUIDs, scores, `Knowledge Representation` ni JSON.
- Técnico conserva telemetría completa mediante grupos y árbol clave/valor, sin muro JSON.
- Única fuente para impacto: `applied_decisions[]`.
- Probabilidades: números finitos dentro de `0..1`.
- Drawer de referencia: 440 px. Sin overflow horizontal a 390 px.
- Reutilizar design system actual; base 4 px; colores semánticos existentes.
- Preservar cambios ajenos en `portal/src/components/auth/AuthShell.tsx` y `portal/src/index.css`.

---

## File map

### Backend

- Create `src/rag/execution_narrative.py`: builder puro de outcome, requisitos, evidencia, decisiones, journey, llamadas y verificación.
- Modify `src/rag/flow_story.py`: adjuntar narrativa fail-soft.
- Modify `src/agents/runtime/orchestrator.py`: publicar `generation_package.evidence` ya calculado; jamás recalcular.
- Create `tests/test_execution_narrative.py`: invariantes narrativas.
- Modify `tests/test_flow_story.py`: integración `with_story()`.

### Frontend model

- Create `portal/src/pages/chat/executionNarrative.ts`: tipos, parser y agrupación presentacional.
- Create `portal/src/pages/chat/executionNarrative.test.ts`: contrato y legacy.
- Modify `portal/src/pages/chat/executionStory.ts`: consumir narrativa.

### Frontend presentation

- Create `portal/src/pages/chat/story/ProbabilityDisplay.tsx` and test.
- Create `portal/src/pages/chat/story/StoryHero.tsx`.
- Create `portal/src/pages/chat/story/NarrativeSteps.tsx`.
- Create `portal/src/pages/chat/story/ObservableReflection.tsx`.
- Create `portal/src/pages/chat/story/JevLlmJourney.tsx`.
- Create `portal/src/pages/chat/story/TechnicalValueTree.tsx`.
- Modify `ExecutionStoryView.tsx`, `ExecutionTimeline.tsx`, `JudgmentStory.tsx`, `LearningSummary.tsx`, `ResponseShapeCard.tsx`, `PerformanceStory.tsx`, `TechnicalTrace.tsx` and their tests.
- Delete `StorySummary.tsx` after `StoryHero` replaces every reference.

### QA and docs

- Create `portal/e2e/execution-story.spec.ts`.
- Modify `docs/architecture/execution-story.md`.

---

### Task 1: Canonical outcome and evidence authority

**Files:**
- Create: `src/rag/execution_narrative.py`
- Modify: `src/agents/runtime/orchestrator.py:806-824`
- Test: `tests/test_execution_narrative.py`

**Interfaces:**
- Consumes: `flow`, `events`, `generation_package.evidence`, `verification`, final status.
- Produces: `build_execution_narrative(flow, events) -> dict[str, Any]`.

- [ ] **Step 1: Write failing outcome tests**

Create `tests/test_execution_narrative.py`:

```python
from src.rag.execution_narrative import build_execution_narrative


def _flow(*, complete: bool, overall: str, status: str = "completed") -> dict:
    missing = [] if complete else ["&&&F"]
    return {
        "status": status,
        "generation": {"skipped": False},
        "verification": {
            "overall": overall,
            "checks": [{"key": "grounding", "state": "warn"}],
        },
        "steps": [
            {
                "type": "generation_package",
                "ready": complete,
                "mode": "generate_full" if complete else "generate_with_limits",
                "missing_evidence": missing,
                "evidence": {
                    "evidence_complete": complete,
                    "missing_documentable_evidence": missing,
                    "conflicts": [],
                    "coverage": [],
                },
            },
            {"type": "final", "status": "ok"},
        ],
        "sources": [],
    }


def test_complete_evidence_with_verification_warning_is_not_insufficient() -> None:
    narrative = build_execution_narrative(_flow(complete=True, overall="partial"), [])
    assert narrative["evidence"]["complete"] is True
    assert narrative["evidence"]["missing_documentable_evidence"] == []
    assert narrative["outcome"]["code"] == "ANSWERED_WITH_LIMITS"
    assert narrative["outcome"]["reason_code"] == "verification_partial"


def test_explicit_abstention_precedes_generic_block() -> None:
    flow = _flow(complete=False, overall="blocked")
    flow["verification"]["checks"] = [
        {"key": "answer_gate", "state": "blocked", "detail": "abstain"}
    ]
    flow["generation"]["skipped"] = True
    narrative = build_execution_narrative(flow, [])
    assert narrative["outcome"]["code"] == "ABSTAINED"


def test_retry_success_uses_retried_outcome() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "decisions": [
            {"phase": "post_retrieval", "action": "retrieve_more", "applied": True}
        ]
    }
    narrative = build_execution_narrative(flow, [])
    assert narrative["outcome"]["code"] == "RETRIED_AND_ANSWERED"
```

- [ ] **Step 2: Verify red test**

Run: `pytest tests/test_execution_narrative.py -q`

Expected: `ModuleNotFoundError: No module named 'src.rag.execution_narrative'`.

- [ ] **Step 3: Publish existing public EvidenceState**

Add inside existing `generation_package` step in `orchestrator.py`:

```python
"evidence": (
    generation_package_block.get("evidence")
    if isinstance(generation_package_block.get("evidence"), dict)
    else {}
),
```

Do not call `build_evidence_state()` here.

- [ ] **Step 4: Implement outcome builder**

Create module with exact helpers and precedence:

```python
"""Presentational projection of canonical execution state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

NARRATIVE_SCHEMA_VERSION = 1


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _step(flow: Mapping[str, Any], kind: str) -> dict[str, Any]:
    return next(
        (item for item in _records(flow.get("steps")) if str(item.get("type") or "") == kind),
        {},
    )


def _verification(flow: Mapping[str, Any]) -> dict[str, Any]:
    block = _record(flow.get("verification"))
    return {
        "overall": str(block.get("overall") or "not_verified"),
        "checks": _records(block.get("checks")),
        "primary_available": block.get("primary_available"),
        "fallback_used": bool(block.get("fallback_used")),
        "fallback_code": block.get("fallback_code"),
        "affected_outcome": block.get("affected_outcome"),
        "corrections": _records(block.get("corrections")),
    }


def _evidence(flow: Mapping[str, Any]) -> dict[str, Any]:
    package = _step(flow, "generation_package")
    state = _record(package.get("evidence"))
    missing = list(state.get("missing_documentable_evidence") or package.get("missing_evidence") or [])
    conflicts = list(state.get("conflicts") or package.get("contradictions") or [])
    declared = state.get("evidence_complete")
    complete = bool(declared) if declared is not None else bool(package.get("ready"))
    return {
        "complete": complete,
        "generation_mode": str(state.get("generation_mode") or package.get("mode") or ""),
        "missing_documentable_evidence": missing,
        "conflicts": conflicts,
        "requirements": list(state.get("coverage") or []),
        "documents": [],
        "document_count": 0,
        "passage_count": 0,
        "searches": [],
    }


def _explicit_abstention(verification: Mapping[str, Any]) -> bool:
    return any(
        check.get("key") == "answer_gate" and check.get("detail") == "abstain"
        for check in _records(verification.get("checks"))
    )


def _applied_retry(flow: Mapping[str, Any]) -> bool:
    decisions = _records(_record(flow.get("jev_preflight")).get("decisions"))
    return any(
        item.get("applied") is True
        and item.get("action") in {"retrieve_more", "search_knowledge"}
        for item in decisions
    )


def _outcome(flow: Mapping[str, Any], evidence: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    status = str(flow.get("status") or "")
    generation = _record(flow.get("generation"))
    answer_delivered = any(item.get("type") == "final" for item in _records(flow.get("steps"))) or generation.get("skipped") is False
    overall = str(verification.get("overall") or "not_verified")
    if _explicit_abstention(verification):
        code, reason = "ABSTAINED", "explicit_abstention"
    elif status in {"failed", "error"} and not answer_delivered:
        code, reason = "FAILED", "execution_failed"
    elif overall == "blocked" and not answer_delivered:
        code, reason = "BLOCKED", "verification_blocked"
    elif answer_delivered and (not evidence.get("complete") or overall == "partial" or verification.get("affected_outcome") is True):
        code = "ANSWERED_WITH_LIMITS"
        reason = "verification_partial" if overall == "partial" else "evidence_incomplete"
    elif answer_delivered and _applied_retry(flow):
        code, reason = "RETRIED_AND_ANSWERED", "retry_applied"
    elif answer_delivered:
        code, reason = "ANSWERED", "answer_delivered"
    else:
        code, reason = "BLOCKED", "answer_not_delivered"
    return {
        "code": code,
        "reason_code": reason,
        "evidence_state": "complete" if evidence.get("complete") else "incomplete",
        "verification_state": overall,
        "final_status": status,
        "material_fallback": verification.get("affected_outcome") is True,
        "answer_delivered": answer_delivered,
    }


def build_execution_narrative(flow: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = _evidence(flow)
    verification = _verification(flow)
    return {
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "outcome": _outcome(flow, evidence, verification),
        "summary": {},
        "understanding": {},
        "requirements": [],
        "journey": [],
        "judgments": [],
        "applied_decisions": [],
        "evidence": evidence,
        "model_calls": [],
        "verification": verification,
        "response_shape": {},
        "learning": {},
        "diagnostics": [],
        "source_event_count": len(events),
    }


__all__ = ["NARRATIVE_SCHEMA_VERSION", "build_execution_narrative"]
```

- [ ] **Step 5: Verify green and lint**

Run:

```bash
pytest tests/test_execution_narrative.py -q
ruff check src/rag/execution_narrative.py src/agents/runtime/orchestrator.py tests/test_execution_narrative.py
```

Expected: `3 passed`; Ruff `0`.

- [ ] **Step 6: Commit**

```bash
git add src/rag/execution_narrative.py src/agents/runtime/orchestrator.py tests/test_execution_narrative.py
git commit -m "feat(story): add canonical narrative outcome"
```

---

### Task 2: Requirements and document-grouped evidence

**Files:**
- Modify: `src/rag/execution_narrative.py`
- Modify: `tests/test_execution_narrative.py`

**Interfaces:**
- Consumes: `anchor_roles`, canonical coverage, `flow.sources` passages.
- Produces: `_requirements()`, `_group_documents()`, exact document/passage counts.

- [ ] **Step 1: Add failing tests**

Append:

```python
def test_requirements_distinguish_sources_from_user_input() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["steps"].insert(0, {
        "type": "anchor_roles",
        "fields": ["FCLAS"],
        "rules": ["&&&F"],
        "examples": ["QNNF0SME"],
        "requirement_coverage": [
            {"label": "FCLAS", "status": "FOUND", "evidence_refs": ["a"]},
            {"label": "&&&F", "status": "FOUND", "evidence_refs": ["b"]},
        ],
    })
    result = build_execution_narrative(flow, [])
    by_label = {item["label"]: item for item in result["requirements"]}
    assert by_label["FCLAS"]["kind"] == "DOCUMENTABLE"
    assert by_label["&&&F"]["source_required"] is True
    assert by_label["QNNF0SME"]["kind"] == "USER_INPUT"
    assert by_label["QNNF0SME"]["source_required"] is False


def test_four_passages_become_two_documents() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["sources"] = [
        {"evidence_id": "a", "document_id": "cat", "title": "Rec2_Cat10.pdf", "page": 1, "content": "FCLAS"},
        {"evidence_id": "b", "document_id": "rules", "title": "Rec2_Rules.pdf", "page": 4, "content": "&&&F"},
        {"evidence_id": "c", "document_id": "cat", "title": "Rec2_Cat10.pdf", "page": 2, "content": "Fare basis"},
        {"evidence_id": "d", "document_id": "cat", "title": "Rec2_Cat10.pdf", "page": 3, "content": "Mask"},
    ]
    evidence = build_execution_narrative(flow, [])["evidence"]
    assert evidence["document_count"] == 2
    assert evidence["passage_count"] == 4
    assert len(evidence["documents"]) == 2


def test_duplicate_evidence_id_is_counted_once() -> None:
    flow = _flow(complete=True, overall="verified")
    source = {"evidence_id": "same", "document_id": "cat", "title": "Cat.pdf", "content": "FCLAS"}
    flow["sources"] = [source, dict(source)]
    evidence = build_execution_narrative(flow, [])["evidence"]
    assert evidence["passage_count"] == 1
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_execution_narrative.py -q`

Expected: three new tests fail on empty requirements/documents.

- [ ] **Step 3: Implement stable grouping**

Add `hashlib` and `re`. Implement:

```python
def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _display_name(source: Mapping[str, Any]) -> str:
    for key in ("display_name", "source_title", "document_title", "title", "filename"):
        value = _text(source.get(key))
        if value and not re.fullmatch(r"[0-9a-fA-F-]{32,36}", value):
            return value
    return "Documento sin título"


def _document_key(source: Mapping[str, Any]) -> str:
    document_id = _text(source.get("document_id"))
    if document_id:
        return f"document:{document_id}"
    return f"source:{_text(source.get('source_id'))}:{_normalized(source.get('filename') or source.get('title'))}"


def _passage_key(source: Mapping[str, Any]) -> str:
    evidence_id = _text(source.get("evidence_id"))
    if evidence_id:
        return f"evidence:{evidence_id}"
    excerpt = _text(source.get("excerpt") or source.get("content") or source.get("snippet"))
    digest = hashlib.sha256(_normalized(excerpt).encode("utf-8")).hexdigest()[:16]
    return f"fallback:{_text(source.get('page'))}:{_normalized(source.get('section'))}:{digest}"
```

`_group_documents()` must preserve every unique passage, increment counts from final grouped arrays, use `document_id` first, and append `SOURCE_NAME_MISSING` diagnostic when display name resolves to “Documento sin título”. `_requirements()` must create `DOCUMENTABLE` rows from fields/rules/references/entities and `USER_INPUT` rows from examples. Connect canonical coverage by label; never mark example missing.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_execution_narrative.py -q`

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/rag/execution_narrative.py tests/test_execution_narrative.py
git commit -m "feat(story): normalize requirements and sources"
```

---

### Task 3: JEV decisions, causal journey, model calls, and integration

**Files:**
- Modify: `src/rag/execution_narrative.py`
- Modify: `src/rag/flow_story.py`
- Modify: `tests/test_execution_narrative.py`
- Modify: `tests/test_flow_story.py`

**Interfaces:**
- Consumes: `jev_preflight.packs`, `jev_preflight.decisions`, canonical events, typed `llm` steps.
- Produces: judgments, one canonical applied-decision collection, causal journey, model calls, `with_story()["execution_narrative"]`.

- [ ] **Step 1: Add failing projection tests**

Append tests asserting:

```python
def test_one_applied_decision_drives_summary_and_journey() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [{
            "phase": "post_retrieval",
            "questions": [
                {"id": "needs_more_evidence", "type": "noul", "decision": "yes", "certainty": 0.62},
                {"id": "needs_tool", "type": "noul", "decision": "yes", "certainty": 0.91},
                {"id": "tool", "type": "choice", "decision": "search_knowledge", "confidence": 0.79},
                {"id": "satisfied", "type": "noul", "decision": "no", "certainty": 0.72},
            ],
        }],
        "decisions": [{"phase": "post_retrieval", "action": "retrieve_more", "applied": True, "reasons": ["evidence_gap"]}],
        "summary": {"decisions_influenced": 99},
    }
    result = build_execution_narrative(flow, [])
    assert len(result["judgments"]) == 4
    assert len(result["applied_decisions"]) == 1
    assert result["summary"]["decisions_influenced"] == 1
    assert sum(item["kind"] == "JEV_CHANGED_PATH" for item in result["journey"]) == 1


def test_zero_applied_decisions_stays_zero() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [{"phase": "pre_generation", "questions": [{"id": "satisfied", "decision": "yes"}]}],
        "decisions": [{"phase": "pre_generation", "action": "answer", "applied": False}],
    }
    result = build_execution_narrative(flow, [])
    assert result["summary"]["decisions_influenced"] == 0
    assert result["applied_decisions"] == []


def test_two_llm_calls_have_distinct_purposes() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["steps"] = [
        {"id": "llm-1", "type": "llm", "action": {"tool": "search_knowledge"}, "latency_ms": 7700},
        {"id": "llm-2", "type": "llm", "action": {"answer": "ready"}, "latency_ms": 5700},
        *flow["steps"],
    ]
    calls = build_execution_narrative(flow, [])["model_calls"]
    assert [item["purpose"] for item in calls] == ["ANALYSIS", "ANSWER"]
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_execution_narrative.py -q`

Expected: failures on empty decisions, journey and model calls.

- [ ] **Step 3: Implement canonical collections**

Implement `_applied_decisions()` filtering only `applied is True`; IDs must be stable from phase and ordinal. Implement `_judgments()` from pack questions and link by phase to applied decision. Preserve raw probability, certainty, distribution and `confidence_band`; do not create thresholds.

Implement `_model_calls()` with exact precedence:

```python
if action.get("answer") is not None:
    purpose = "ANSWER"
elif action.get("revision") is not None:
    purpose = "REVISION"
elif action.get("tool") is not None or index == 1:
    purpose = "ANALYSIS"
else:
    purpose = "UNKNOWN"
```

Implement `_journey()` with stable integer `sequence`. Emit only observed nodes. `JEV_CHANGED_PATH` count equals `len(applied_decisions)`. Emit `SEARCH_RETRIED` only for applied retrieval actions. Link `decision_id`. Model nodes reference `call_id`. Verification/delivery nodes use canonical states.

Set:

```python
summary["decisions_influenced"] = len(applied_decisions)
```

Never read historical `summary.decisions_influenced` as authority.

- [ ] **Step 4: Test `with_story()` integration**

Add:

```python
def test_with_story_adds_narrative_without_replacing_events() -> None:
    flow = {
        "status": "completed",
        "generation": {"skipped": False},
        "verification": {"overall": "verified", "checks": [{"key": "grounding", "state": "ok"}]},
        "steps": [{"type": "final", "status": "ok"}],
        "sources": [],
    }
    enriched = with_story(flow)
    assert enriched["flow_version"] == 2
    assert isinstance(enriched["events"], list)
    assert enriched["execution_narrative"]["schema_version"] == 1
    assert enriched["execution_narrative"]["outcome"]["code"] == "ANSWERED"
```

- [ ] **Step 5: Integrate fail-soft**

Inside `with_story()`:

```python
from src.rag.execution_narrative import build_execution_narrative

events = build_flow_events(enriched)
enriched["events"] = events
enriched["execution_narrative"] = build_execution_narrative(enriched, events)
```

Keep original outer fail-soft behavior. Narrative failure must preserve response and raw flow.

- [ ] **Step 6: Verify backend regression**

Run:

```bash
pytest tests/test_execution_narrative.py tests/test_flow_story.py tests/test_agent_flow_v2.py -q
ruff check src/rag/execution_narrative.py src/rag/flow_story.py tests/test_execution_narrative.py tests/test_flow_story.py
```

Expected: selected tests pass; Ruff `0`.

- [ ] **Step 7: Commit**

```bash
git add src/rag/execution_narrative.py src/rag/flow_story.py tests/test_execution_narrative.py tests/test_flow_story.py
git commit -m "feat(story): project causal execution narrative"
```

---

### Task 4: Frontend narrative contract and safe percentages

**Files:**
- Create: `portal/src/pages/chat/executionNarrative.ts`
- Create: `portal/src/pages/chat/executionNarrative.test.ts`
- Create: `portal/src/pages/chat/story/ProbabilityDisplay.tsx`
- Create: `portal/src/pages/chat/story/ProbabilityDisplay.test.tsx`
- Modify: `portal/src/pages/chat/executionStory.ts`

**Interfaces:**
- Consumes: raw `flow.execution_narrative`.
- Produces: `normalizeExecutionNarrative()`, `ExecutionStory.executionNarrative`, `formatProbability()`.

- [ ] **Step 1: Write failing parser tests**

Create `executionNarrative.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { normalizeExecutionNarrative } from "./executionNarrative";

describe("normalizeExecutionNarrative", () => {
  it("preserva outcome, fuentes y decisiones", () => {
    const result = normalizeExecutionNarrative({
      schema_version: 1,
      outcome: { code: "RETRIED_AND_ANSWERED", reason_code: "retry_applied" },
      summary: { decisions_influenced: 1 },
      understanding: { fields: ["FCLAS"], rules: ["&&&F"], examples: ["QNNF0SME"] },
      requirements: [],
      journey: [{ id: "j1", kind: "SEARCH_RETRIED", sequence: 4 }],
      judgments: [],
      applied_decisions: [{ id: "d1", action: "retrieve_more", impact_code: "retrieve_more" }],
      evidence: {
        complete: true,
        documents: [{ document_key: "doc:a", display_name: "Rules.pdf", passage_count: 2, passages: [] }],
        document_count: 1,
        passage_count: 2,
      },
      model_calls: [],
      verification: { overall: "verified", checks: [] },
      diagnostics: [],
    });
    expect(result?.outcome.code).toBe("RETRIED_AND_ANSWERED");
    expect(result?.evidence.documentCount).toBe(1);
    expect(result?.appliedDecisions).toHaveLength(1);
  });

  it("rechaza una versión no soportada", () => {
    expect(normalizeExecutionNarrative({ schema_version: 99 })).toBeNull();
  });
});
```

Create `ProbabilityDisplay.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProbabilityDisplay, formatProbability } from "./ProbabilityDisplay";

describe("ProbabilityDisplay", () => {
  it("muestra 0.7091 como 70.9%", () => {
    render(<ProbabilityDisplay value={0.7091} />);
    expect(screen.getByText("70.9%")).toBeTruthy();
  });

  it("no muestra valores fuera de 0..1", () => {
    expect(formatProbability(709.1)).toBeNull();
    const { container } = render(<ProbabilityDisplay value={709.1} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Verify red**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/executionNarrative.test.ts src/pages/chat/story/ProbabilityDisplay.test.tsx
```

Expected: missing-module failures.

- [ ] **Step 3: Implement typed normalization**

Create explicit types for outcome, requirement, journey item, judgment, decision, evidence document/passage, model call, verification and diagnostic. Public normalized root:

```ts
export type NarrativeOutcomeCode =
  | "ANSWERED"
  | "ANSWERED_WITH_LIMITS"
  | "RETRIED_AND_ANSWERED"
  | "ABSTAINED"
  | "FAILED"
  | "BLOCKED";

export type ExecutionNarrative = {
  schemaVersion: 1;
  outcome: { code: NarrativeOutcomeCode; reasonCode: string };
  summary: { decisionsInfluenced: number };
  understanding: Record<string, unknown>;
  requirements: NarrativeRequirement[];
  journey: NarrativeJourneyItem[];
  judgments: NarrativeJudgment[];
  appliedDecisions: NarrativeDecision[];
  evidence: NarrativeEvidence;
  modelCalls: NarrativeModelCall[];
  verification: NarrativeVerification;
  diagnostics: NarrativeDiagnostic[];
  raw: Record<string, unknown>;
};
```

`normalizeExecutionNarrative(value)` must guard every collection, translate snake_case to camelCase, sort journey/model calls by sequence, reject unsupported schema versions, and never recalculate outcome or evidence completeness.

- [ ] **Step 4: Implement one probability formatter**

```tsx
export function formatProbability(value: number | undefined): string | null {
  if (value === undefined || !Number.isFinite(value) || value < 0 || value > 1) return null;
  const formatted = new Intl.NumberFormat("es-PE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(value * 100);
  return `${formatted}%`;
}

export function ProbabilityDisplay({ value, label }: { value?: number; label?: string }) {
  const formatted = formatProbability(value);
  if (!formatted) return null;
  return (
    <span className="tabular-nums text-muted">
      {label ? `${label}: ` : ""}{formatted}
    </span>
  );
}
```

- [ ] **Step 5: Attach once to `ExecutionStory`**

Add `executionNarrative: ExecutionNarrative | null` to type. At builder start:

```ts
const executionNarrative = normalizeExecutionNarrative(safe.execution_narrative);
```

Return same object. Preserve current fields for legacy compatibility; do not derive parallel decisions from it.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/executionNarrative.test.ts src/pages/chat/story/ProbabilityDisplay.test.tsx src/pages/chat/executionStory.test.ts
npm --prefix portal run typecheck
```

Expected: tests pass; typecheck `0`.

Commit:

```bash
git add portal/src/pages/chat/executionNarrative.ts portal/src/pages/chat/executionNarrative.test.ts portal/src/pages/chat/story/ProbabilityDisplay.tsx portal/src/pages/chat/story/ProbabilityDisplay.test.tsx portal/src/pages/chat/executionStory.ts
git commit -m "feat(story): consume execution narrative contract"
```

---

### Task 5: Five-second hero and strict view modes

**Files:**
- Create: `portal/src/pages/chat/story/StoryHero.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.test.tsx`
- Delete: `portal/src/pages/chat/story/StorySummary.tsx`

**Interfaces:**
- Consumes: narrative, `totalMs`, `costUsd`.
- Produces: canonical hero and strict Historia/Rendimiento/Técnico separation.

- [ ] **Step 1: Write failing view tests**

Fixture with four passages/two documents and one applied retry. Assert in Historia:

```tsx
expect(screen.getByText("Respuesta completada")).toBeTruthy();
expect(screen.getByText("2 documentos · 4 fragmentos")).toBeTruthy();
expect(screen.getByText("Pidió ampliar la búsqueda")).toBeTruthy();
expect(screen.queryByText("V2_PROMOTED")).toBeNull();
expect(screen.queryByText("canonical_version")).toBeNull();
expect(screen.queryByText("semantic units")).toBeNull();
expect(screen.queryByText("legacy chunks used")).toBeNull();
```

Select Técnico; assert all technical values appear there.

- [ ] **Step 2: Verify red**

Run: `npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx`

Expected: failure because `KnowledgeRepresentation` currently renders outside Técnico.

- [ ] **Step 3: Apply design checkpoint**

```text
Intent: business operator understands execution without RAG vocabulary; calm, precise, auditable.
Hierarchy: outcome first; one-sentence action second; sources/JEV/time/cost compact.
Palette: graphite surfaces; teal decision/activity; green verified; amber material limit.
Depth: existing borders plus tonal steps; no decorative shadow.
Surfaces: overlay drawer, surface hero, soft disclosure hover.
Typography: Geist 14/600 outcome, 12.5 body, 11 labels; tabular numbers.
Spacing: 4 px base; p-4 hero; 12–16 px group rhythm.
```

- [ ] **Step 4: Implement `StoryHero`**

Use exact mapping:

```ts
const OUTCOME_META = {
  ANSWERED: { label: "Respuesta completada", tone: "ok" },
  RETRIED_AND_ANSWERED: { label: "Respuesta completada", tone: "ok" },
  ANSWERED_WITH_LIMITS: { label: "Respondió con límites", tone: "warn" },
  ABSTAINED: { label: "No respondió sin respaldo suficiente", tone: "warn" },
  BLOCKED: { label: "No pudo completar la respuesta", tone: "warn" },
  FAILED: { label: "La ejecución falló", tone: "danger" },
} as const;
```

Render sentence, sources, JEV impact, time, cost. No telemetry-quality badge in Historia. Legacy fallback uses existing headline and known metrics; omits unknown JEV impact.

- [ ] **Step 5: Use controlled Radix Tabs**

Replace hand-rolled tabs with existing `Tabs`, `TabsList`, `TabsTrigger`. Composition:

```tsx
<StoryHero story={story} />
{mode === "story" ? <ExecutionTimeline story={story} /> : null}
{mode === "performance" ? <PerformanceStory story={story} /> : null}
{mode === "technical" ? <TechnicalTrace story={story} /> : null}
```

Move `KnowledgeRepresentation` exclusively into `TechnicalTrace`. Story-only extras must never render in Performance/Técnico.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx
npm --prefix portal run typecheck
```

Expected: tests pass; typecheck `0`.

Commit:

```bash
git add portal/src/pages/chat/story/StoryHero.tsx portal/src/pages/chat/story/ExecutionStoryView.tsx portal/src/pages/chat/story/ExecutionStoryView.test.tsx portal/src/pages/chat/story/StorySummary.tsx
git commit -m "feat(story): add human-first execution hero"
```

---

### Task 6: Causal timeline and progressive disclosure

**Files:**
- Create: `portal/src/pages/chat/story/NarrativeSteps.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionTimeline.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.test.tsx`
- Modify: `portal/src/pages/chat/story/ResponseShapeCard.tsx`
- Modify: `portal/src/pages/chat/story/LearningSummary.tsx`

**Interfaces:**
- Consumes: journey, requirements, evidence, model calls, verification.
- Produces: 5–6 human steps; compact legacy timeline when narrative absent.

- [ ] **Step 1: Write failing narrative tests**

Assert:

```tsx
expect(screen.getByText("Entendió tu consulta")).toBeTruthy();
expect(screen.getByText("FCLAS")).toBeTruthy();
expect(screen.getByText("&&&F")).toBeTruthy();
expect(screen.getByText(/QNNF0SME era el valor/)).toBeTruthy();
expect(screen.getByText("Buscó nuevamente")).toBeTruthy();
expect(screen.getByText("Analizó la evidencia")).toBeTruthy();
expect(screen.getByText("Redactó la respuesta")).toBeTruthy();
expect(screen.getByText("Evidencia documental completa")).toBeTruthy();
expect(screen.getByText("Verificación parcial")).toBeTruthy();
expect(screen.queryByText("Evidencia insuficiente")).toBeNull();
expect(screen.queryByText(/tokens/i)).toBeNull();
```

- [ ] **Step 2: Verify red**

Run: `npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx`

Expected: old phase timeline lacks required copy.

- [ ] **Step 3: Implement narrative blocks**

Export exact components:

```ts
export function UnderstandingStep({ narrative }: { narrative: ExecutionNarrative }): JSX.Element;
export function EvidenceStep({ narrative }: { narrative: ExecutionNarrative }): JSX.Element;
export function RetryStep({ item, narrative }: { item: NarrativeJourneyItem; narrative: ExecutionNarrative }): JSX.Element;
export function ModelStep({ narrative }: { narrative: ExecutionNarrative }): JSX.Element;
export function VerificationStep({ narrative }: { narrative: ExecutionNarrative }): JSX.Element;
```

Rules:

- `DOCUMENTABLE`: “Necesitaba confirmar”.
- `USER_INPUT`: “valor que vamos a evaluar”.
- Documents/passages separate.
- Source card title always `displayName`; passage detail includes page, section, excerpt.
- Retry with link explains linked impact; without link only says another search occurred.
- Model step lists purpose labels, never generic duplicate “LLM”.
- Verification copy derives only from `verification.overall` and checks.

- [ ] **Step 4: Rebuild timeline around canonical groups**

Render order:

1. understanding/requirements;
2. initial evidence;
3. JEV review;
4. observed retries;
5. model work;
6. verification.

Retain vertical rail. Remove durations, tokens and technical toggle from Historia. Each step: summary plus optional native `<details>`. When narrative absent, use compact current phases without adding claims.

- [ ] **Step 5: Compact response shape and learning**

`ResponseShapeCard`: closed `<details>` summary “Cómo decidió explicarlo”.

Zero learning state:

```text
Memoria · No fue necesaria en esta respuesta.
Aprendizaje · Esta respuesta no generó observaciones nuevas.
```

Render full MemoryImpact only for material non-zero data.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx
npm --prefix portal run typecheck
```

Expected: tests pass; typecheck `0`.

Commit:

```bash
git add portal/src/pages/chat/story/NarrativeSteps.tsx portal/src/pages/chat/story/ExecutionTimeline.tsx portal/src/pages/chat/story/ExecutionStoryView.test.tsx portal/src/pages/chat/story/ResponseShapeCard.tsx portal/src/pages/chat/story/LearningSummary.tsx
git commit -m "feat(story): render causal execution journey"
```

---

### Task 7: Observable JEV reflections and JEV–LLM journey

**Files:**
- Create: `portal/src/pages/chat/story/ObservableReflection.tsx`
- Create: `portal/src/pages/chat/story/JevLlmJourney.tsx`
- Modify: `portal/src/pages/chat/story/JudgmentStory.tsx`
- Modify: `portal/src/pages/chat/story/JudgmentStory.test.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionTimeline.tsx`

**Interfaces:**
- Consumes: judgments, applied decisions, journey, `ProbabilityDisplay`.
- Produces: JEV summary, expandable questions, correction loop, compact interaction map.

- [ ] **Step 1: Write failing impact tests**

For one applied decision:

```tsx
expect(screen.getByText("JEV hizo 4 comprobaciones.")).toBeTruthy();
expect(screen.getByText("1 influyó en la ejecución.")).toBeTruthy();
expect(screen.getByText("Zent realizó una segunda búsqueda.")).toBeTruthy();
```

For zero applied decisions:

```tsx
expect(screen.getByText("JEV revisó el camino, pero no necesitó cambiarlo.")).toBeTruthy();
expect(screen.queryByText(/requiere atención/i)).toBeNull();
```

For ambiguous 55/45 tool choice:

```tsx
expect(screen.getByText(/no vio una opción claramente superior/i)).toBeTruthy();
expect(screen.getByText(/dejó la decisión al agente/i)).toBeTruthy();
```

- [ ] **Step 2: Verify red**

Run: `npm --prefix portal run test -- src/pages/chat/story/JudgmentStory.test.tsx`

Expected: copy/impact assertions fail against current pack-based cards.

- [ ] **Step 3: Refactor judgments around canonical impact**

Required behavior:

```ts
const checks = narrative.judgments.length;
const influenced = narrative.appliedDecisions.length;
```

- Question row shows human label and answer.
- Default shows `confidenceBand`, not raw score.
- Detail distinguishes `Resultado más probable` from `Certeza de la decisión`.
- Alternatives remain inside disclosure.
- Every percentage uses `ProbabilityDisplay`.
- Linked decision renders its impact.
- No link renders “No cambió la ejecución”.
- Low certainty without impact remains neutral.
- Remove all inline `value * 100` formatting.

- [ ] **Step 4: Implement observable reflection**

Accessible heading: `Cómo Zent comprobó su camino`.

Render chronological real questions/checks with evaluator, answer, certainty and impact. Render correction only if journey contains `ANSWER_REVISED`. Never emit first-person dialogue, quotes not present in source, or private reasoning.

- [ ] **Step 5: Implement compact JEV–LLM map**

Closed `<details>` summary: `Cómo colaboraron JEV y el modelo`.

Render only observed journey nodes as vertical list. No horizontal SVG/graph; no overflow at 390 px.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/story/JudgmentStory.test.tsx src/pages/chat/story/ExecutionStoryView.test.tsx
npm --prefix portal run typecheck
```

Expected: tests pass; typecheck `0`.

Commit:

```bash
git add portal/src/pages/chat/story/ObservableReflection.tsx portal/src/pages/chat/story/JevLlmJourney.tsx portal/src/pages/chat/story/JudgmentStory.tsx portal/src/pages/chat/story/JudgmentStory.test.tsx portal/src/pages/chat/story/ExecutionTimeline.tsx
git commit -m "feat(story): explain JEV questions and impact"
```

---

### Task 8: Purpose-aware Performance and structured Technical view

**Files:**
- Create: `portal/src/pages/chat/story/TechnicalValueTree.tsx`
- Modify: `portal/src/pages/chat/story/PerformanceStory.tsx`
- Modify: `portal/src/pages/chat/story/TechnicalTrace.tsx`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.test.tsx`

**Interfaces:**
- Consumes: model calls, raw flow, diagnostics, knowledge representation.
- Produces: purpose-aware performance and complete structured telemetry.

- [ ] **Step 1: Write failing view tests**

Performance:

```tsx
expect(screen.getByText("Analizó la evidencia")).toBeTruthy();
expect(screen.getByText("Redactó la respuesta")).toBeTruthy();
expect(screen.getByText("Tokens procesados")).toBeTruthy();
```

Technical:

```tsx
expect(screen.getByText("Representación del conocimiento")).toBeTruthy();
expect(screen.getByText("V2_PROMOTED")).toBeTruthy();
expect(screen.getByText("Diagnósticos técnicos")).toBeTruthy();
expect(screen.queryByText("Ver traza técnica")).toBeNull();
```

- [ ] **Step 2: Verify red**

Run: `npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx`

Expected: current views lack purpose labels and still expose JSON trace control.

- [ ] **Step 3: Drive Performance from model calls**

When narrative calls exist, one row per call with purpose, duration, input/output tokens and cost. Model/provider remain expanded detail. Keep wall-clock, attributed/unattributed time and overlap note. Historia receives none of these fields.

- [ ] **Step 4: Implement recursive technical tree**

Create:

```tsx
export function TechnicalValueTree({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-faint">No disponible</span>;
  if (typeof value !== "object") return <span className="break-all text-text">{String(value)}</span>;
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>);
  if (!entries.length) return <span className="text-faint">Vacío</span>;
  return (
    <div className={depth ? "border-l border-border-soft pl-3" : ""}>
      {entries.map(([key, child]) => {
        const expandable = child !== null && typeof child === "object";
        return expandable ? (
          <details key={key} className="py-1">
            <summary className="cursor-pointer break-all text-muted">{key}</summary>
            <TechnicalValueTree value={child} depth={depth + 1} />
          </details>
        ) : (
          <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-3 border-b border-border-soft py-1.5 text-[11.5px]">
            <span className="break-all text-faint">{key}</span>
            <TechnicalValueTree value={child} depth={depth + 1} />
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5: Reorganize Technical**

Sections: ejecución, representación del conocimiento, JEV, evidencia, modelo/tokens, verificación, observabilidad, diagnósticos, payload completo through `TechnicalValueTree`. Remove JSON `CodeBlock`. Preserve raw values.

- [ ] **Step 6: Verify and commit**

Run:

```bash
npm --prefix portal run test -- src/pages/chat/story/ExecutionStoryView.test.tsx
npm --prefix portal run typecheck
npm --prefix portal run lint
```

Expected: tests pass; typecheck/lint `0`.

Commit:

```bash
git add portal/src/pages/chat/story/TechnicalValueTree.tsx portal/src/pages/chat/story/PerformanceStory.tsx portal/src/pages/chat/story/TechnicalTrace.tsx portal/src/pages/chat/story/ExecutionStoryView.test.tsx
git commit -m "feat(story): separate performance and technical telemetry"
```

---

### Task 9: Compatibility, responsive QA, docs, full verification

**Files:**
- Modify: `portal/src/pages/chat/executionStory.test.ts`
- Modify: `portal/src/pages/chat/executionStory.agent.test.ts`
- Modify: `portal/src/pages/chat/executionStory.jev.test.ts`
- Modify: `portal/src/pages/chat/story/ExecutionStoryView.test.tsx`
- Create: `portal/e2e/execution-story.spec.ts`
- Modify: `docs/architecture/execution-story.md`

**Interfaces:**
- Consumes: Tasks 1–8.
- Produces: backward compatibility, responsive proof, updated docs, verified build.

- [ ] **Step 1: Add legacy and no-fabrication tests**

Without narrative:

```ts
expect(story.executionNarrative).toBeNull();
expect(story.phases.length).toBeGreaterThan(0);
expect(story.narrative).not.toContain("JEV");
```

Telemetry partial plus valid answer:

```ts
expect(story.headlineStatus).toBe("ok");
expect(story.telemetry.quality).toBe("partial");
```

Assert Historia never contains `70910%`, UUID source title, technical event names or serialized JSON.

- [ ] **Step 2: Run full unit suite**

Run: `npm --prefix portal run test`

Expected: all Vitest files pass. Rerun any wait-related flake alone before changing code.

- [ ] **Step 3: Add responsive Playwright coverage**

Use existing authenticated fixture and flow mocking pattern. At 440 and 390 widths:

```ts
await expect(page.getByRole("heading", { name: "Ver flujo" })).toBeVisible();
await expect(page.getByText("Respuesta completada")).toBeVisible();
await expect(page.getByText("Cómo Zent comprobó su camino")).toBeVisible();
const overflow = await page.locator('[role="dialog"]').evaluate(
  (element) => element.scrollWidth > element.clientWidth,
);
expect(overflow).toBe(false);
```

Switch tabs by accessible name. Assert `V2_PROMOTED` only after Técnico.

- [ ] **Step 4: Update architecture docs**

Document additive contract, outcome precedence, Evidence Engine authority, applied-decisions invariant, source grouping, observable reflection versus chain-of-thought, structured technical payload and legacy behavior. Remove outdated statement mapping generic blocked state to evidence insufficiency.

- [ ] **Step 5: Verify backend**

Run:

```bash
pytest tests/test_execution_narrative.py tests/test_flow_story.py tests/test_agent_flow_v2.py tests/test_rag_flow.py -q
ruff check src/rag/execution_narrative.py src/rag/flow_story.py src/agents/runtime/orchestrator.py tests/test_execution_narrative.py tests/test_flow_story.py
```

Expected: selected tests pass; Ruff `0`.

- [ ] **Step 6: Verify frontend**

Run:

```bash
npm --prefix portal run typecheck
npm --prefix portal run lint
npm --prefix portal run test
npm --prefix portal run build
```

Expected: all commands `0`.

- [ ] **Step 7: Run focused Playwright**

Run built preview using existing project workflow, then:

```bash
npm --prefix portal run e2e -- e2e/execution-story.spec.ts
```

Expected: both viewports pass; console/page errors empty.

- [ ] **Step 8: Inspect authority boundary**

Run:

```bash
git diff --check
git diff -- src/rag src/agents/runtime portal/src/pages/chat docs/architecture/execution-story.md
```

Confirm zero changes to JEV decision logic, Evidence Engine algorithms, routing, RAG prompts, LLM generation or grounding.

- [ ] **Step 9: Commit final QA**

```bash
git add portal/src/pages/chat/executionStory.test.ts portal/src/pages/chat/executionStory.agent.test.ts portal/src/pages/chat/executionStory.jev.test.ts portal/src/pages/chat/story/ExecutionStoryView.test.tsx portal/e2e/execution-story.spec.ts docs/architecture/execution-story.md
git commit -m "test(story): cover coherent execution narrative"
```

---

## Final acceptance checklist

- [ ] Historia responde comprensión, requisitos, evidencia, preguntas JEV, impacto, retries, modelo y verificación.
- [ ] Evidencia completa más verificación parcial nunca muestra “Evidencia insuficiente”.
- [ ] Hero, JEV y timeline consumen el mismo `applied_decisions[]`.
- [ ] Documentos y fragmentos tienen conteos distintos.
- [ ] Historia nunca usa UUID como título.
- [ ] `0.7091` muestra `70.9%`; fuera de rango no muestra porcentaje.
- [ ] Historia no contiene Knowledge Representation, tokens, raw scores, provider/model, UUIDs o JSON.
- [ ] Rendimiento contiene tiempos, llamadas, tokens y costo.
- [ ] Técnico contiene telemetría completa, diagnósticos y Knowledge Representation estructurados.
- [ ] Reflexión observable solo contiene preguntas, efectos, retries, correcciones y checks reales.
- [ ] Legacy degrada sin explicaciones inventadas.
- [ ] Sin overflow horizontal a 440 px o 390 px.
- [ ] pytest, Ruff, typecheck, lint, Vitest, build y Playwright focalizado pasan.
