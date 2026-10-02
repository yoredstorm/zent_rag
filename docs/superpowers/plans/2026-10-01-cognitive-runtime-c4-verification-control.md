# Cognitive Runtime C4 — Verificación + Control de Turno Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unificar la verificación de la respuesta contra la evidencia (AnswerVerifier), alimentar el KnowledgeBrief al prompt en modo `limited`, y trazar budget/loop/learning signals del turno — con enforcement de políticas y del budget diferido a C5.

**Architecture:** Módulos puros en `src/runtime/` (`verification.py`, `turn_reports.py`, `learning_signal.py`); el orquestador ensambla evidencia **antes** de armar el prompt (idempotente), inyecta el brief solo en `limited`/`active`, y en el `finally` finaliza verificación/budget/loop/learning (persistiendo gaps solo en `limited`/`active` vía un `gap_recorder` inyectado). `shadow` sigue siendo observación pura.

**Tech Stack:** Python del repo, pytest + pytest-asyncio, Postgres ya existente (no en tests nuevos salvo persistencia fake), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` (§5 JEV, §7 budget/loop, S9/S10, fase C4 §15).

## Global Constraints

- `RAG_COGNITIVE_OS_ENABLED` default `off`; con `off` el runtime actual queda intacto (cero imports de los módulos nuevos, flow sin bloque `cognitive`).
- `shadow`: observación pura (respuesta, prompt y llamadas LLM sin cambio; nada se persiste).
- `limited`/`active`: el **único** cambio de comportamiento en C4 es el bloque de brief en el `system_prompt`; la verificación NO modifica la respuesta (enforcement de políticas → C5); el budget se reporta, no bloquea (enforcement → C5).
- Deterministic first: verificación, budget, loop y learning son código puro, sin LLM.
- Conflictos/outdated/unsupported se declaran, nunca se ocultan.
- Sin dependencias nuevas, sin migraciones, sin cambios de contrato API.
- Código/comentarios en español; tests en `tests/test_*.py`. Cada tarea: tests verdes, lint limpio, commit. Branch `feat/cognitive-runtime-c4` desde `master`.

---

### Task 1: AnswerVerifier único (determinista)

**Files:**
- Create: `src/runtime/verification.py`
- Test: `tests/test_answer_verification.py`

**Interfaces:**
- Consumes: `src.runtime.evidence_assembly.EvidencePackage`.
- Produces:
  - `ClaimVerdict(text, status, support, unit_ids, reason)` con `status` en `supported|partially_supported|unsupported|conflicted|outdated`.
  - `AnswerVerification(verdicts, action, supported, partially_supported, unsupported, conflicted, outdated)` con `action` en `approve|answer_with_limits|revise|abstain` y `to_public_dict(max_claims=8)`.
  - `extract_claims(answer, *, max_claims=12) -> tuple[str, ...]`.
  - `verify_answer(answer, package, *, support_threshold=0.6, partial_threshold=0.25) -> AnswerVerification`.

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c4
pytest tests/test_evidence_assembly.py tests/test_knowledge_brief.py -q
```

Expected: PASS.

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_answer_verification.py`:

```python
# =============================================================================
# AnswerVerifier — verificación determinista respuesta vs evidencia (C4).
# =============================================================================
from __future__ import annotations

from src.runtime.evidence_assembly import EvidencePackage, EvidenceUnit
from src.runtime.verification import extract_claims, verify_answer


def _package() -> EvidencePackage:
    return EvidencePackage(
        units=(
            EvidenceUnit(
                unit_id="U1",
                kind="excerpt",
                text="El campo FCLAS determina la clase tarifaria del registro",
                evidence_ids=("E1",),
                score=0.9,
            ),
            EvidenceUnit(
                unit_id="U2",
                kind="fact",
                text="Rule X aplica Category 31",
                canonical_ids=("c1",),
                validity="historical",
                score=0.8,
            ),
            EvidenceUnit(
                unit_id="U3",
                kind="fact",
                text="Rule X aplica Category 32",
                canonical_ids=("c1",),
                validity="current",
                conflict=True,
                score=0.8,
            ),
        ),
        conflicts=(),
    )


def test_claim_soportado() -> None:
    report = verify_answer(
        "El campo FCLAS determina la clase tarifaria del registro.", _package()
    )
    assert report.verdicts[0].status == "supported"
    assert report.action == "approve"


def test_claim_no_soportado() -> None:
    report = verify_answer("El sistema usa blockchain cuántico.", _package())
    assert report.verdicts[0].status == "unsupported"


def test_claim_conflictuado() -> None:
    report = verify_answer(
        "Rule X aplica Category 32 en la actualidad.", _package()
    )
    assert report.verdicts[0].status == "conflicted"
    assert report.action == "answer_with_limits"


def test_claim_desactualizado() -> None:
    historical = EvidencePackage(
        units=(
            EvidenceUnit(
                unit_id="U1",
                kind="fact",
                text="Rule X aplica Category 31",
                canonical_ids=("c1",),
                validity="historical",
                score=0.8,
            ),
        )
    )
    report = verify_answer("Rule X aplica Category 31.", historical)
    assert report.verdicts[0].status == "outdated"
    assert report.action == "answer_with_limits"


def test_accion_revise_y_abstain() -> None:
    revise = verify_answer(
        "El sistema usa blockchain cuántico. "
        "La plataforma vuela drones autónomos. "
        "El campo FCLAS determina la clase tarifaria del registro.",
        _package(),
    )
    assert revise.action == "revise"
    abstain = verify_answer(
        "El sistema usa blockchain cuántico. "
        "La plataforma vuela drones autónomos. "
        "El clima marciano es seco.",
        _package(),
    )
    assert abstain.action == "abstain"


def test_answer_vacio_y_claims() -> None:
    empty = verify_answer("", _package())
    assert empty.verdicts == ()
    assert empty.action == "approve"
    claims = extract_claims(
        "El campo FCLAS determina la clase. La regla aplica al registro.",
        max_claims=1,
    )
    assert claims == ("El campo FCLAS determina la clase.",)


def test_payload_publico_serializable() -> None:
    import json

    payload = verify_answer(
        "El campo FCLAS determina la clase tarifaria del registro.", _package()
    ).to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["action"] == "approve"
    assert payload["supported"] == 1
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_answer_verification.py -q`
Expected: FAIL (`ModuleNotFoundError: src.runtime.verification`).

- [ ] **Step 4: Implementar**

`src/runtime/verification.py`:

```python
# =============================================================================
# AnswerVerifier — verificación determinista de la respuesta (S9, C4).
# =============================================================================
# Extrae claims por oración y las contrasta con el paquete de evidencia por
# overlap de tokens. Declara soporte, conflicto y desactualización; NUNCA
# reescribe la respuesta (el enforcement de políticas es C5).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.runtime.evidence_assembly import EvidencePackage

DEFAULT_SUPPORT_THRESHOLD = 0.6
DEFAULT_PARTIAL_THRESHOLD = 0.25
MAX_CLAIMS = 12

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_TOKEN_RE = re.compile(r"[\wÁÉÍÓÚÑáéíóúñ]{3,}", re.UNICODE)


@dataclass(frozen=True)
class ClaimVerdict:
    text: str
    status: str
    support: float
    unit_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_public_dict(self) -> dict:
        return {
            "text": self.text[:200],
            "status": self.status,
            "support": round(float(self.support), 4),
            "unit_ids": list(self.unit_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AnswerVerification:
    verdicts: tuple[ClaimVerdict, ...] = ()
    action: str = "approve"
    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    conflicted: int = 0
    outdated: int = 0

    def to_public_dict(self, *, max_claims: int = 8) -> dict:
        return {
            "action": self.action,
            "count": len(self.verdicts),
            "supported": self.supported,
            "partially_supported": self.partially_supported,
            "unsupported": self.unsupported,
            "conflicted": self.conflicted,
            "outdated": self.outdated,
            "claims": [
                verdict.to_public_dict()
                for verdict in self.verdicts[: max(0, max_claims)]
            ],
        }


def extract_claims(answer: str, *, max_claims: int = MAX_CLAIMS) -> tuple[str, ...]:
    """Claims por oración, determinista, sin duplicados ni vacíos."""
    claims: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(answer or ""):
        text = " ".join(raw.split())
        if len(text) < 12:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(text)
        if len(claims) >= max(0, int(max_claims)):
            break
    return tuple(claims)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "")}


def support_ratio(text: str, evidence_texts: list[str]) -> float:
    """Overlap de tokens del claim contra el mejor fragmento (0..1)."""
    claim_tokens = _tokens(text)
    if not claim_tokens:
        return 0.0
    best = 0.0
    for evidence in evidence_texts:
        evidence_tokens = _tokens(evidence)
        if not evidence_tokens:
            continue
        overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
        if overlap > best:
            best = overlap
    return best


def _classify(
    claim: str,
    package: EvidencePackage,
    *,
    support_threshold: float,
    partial_threshold: float,
) -> ClaimVerdict:
    scored: list[tuple[float, object]] = []
    for unit in package.units:
        ratio = support_ratio(claim, [unit.text])
        if ratio > 0:
            scored.append((ratio, unit))
    scored.sort(key=lambda entry: (-entry[0], str(getattr(entry[1], "unit_id", ""))))
    if not scored:
        return ClaimVerdict(claim, "unsupported", 0.0, reason="sin_evidencia")
    best_ratio, best_unit = scored[0]
    best_ids = tuple(
        str(getattr(unit, "unit_id", ""))
        for ratio, unit in scored
        if ratio >= partial_threshold
    )
    if best_ratio < partial_threshold:
        return ClaimVerdict(
            claim, "unsupported", best_ratio, reason="overlap_insuficiente"
        )
    if best_ratio < support_threshold:
        return ClaimVerdict(
            claim, "partially_supported", best_ratio, unit_ids=best_ids, reason="parcial"
        )
    conflict_units = [
        unit for ratio, unit in scored
        if ratio >= support_threshold and bool(getattr(unit, "conflict", False))
    ]
    if conflict_units:
        return ClaimVerdict(
            claim, "conflicted", best_ratio, unit_ids=best_ids, reason="conflicto_retenido"
        )
    if str(getattr(best_unit, "validity", "") or "") == "historical":
        has_current = any(
            ratio >= partial_threshold
            and str(getattr(unit, "validity", "") or "") == "current"
            for ratio, unit in scored
        )
        if not has_current:
            return ClaimVerdict(
                claim,
                "outdated",
                best_ratio,
                unit_ids=best_ids,
                reason="solo_evidencia_historica",
            )
    return ClaimVerdict(
        claim, "supported", best_ratio, unit_ids=best_ids, reason="overlap"
    )


def verify_answer(
    answer: str,
    package: EvidencePackage,
    *,
    support_threshold: float = DEFAULT_SUPPORT_THRESHOLD,
    partial_threshold: float = DEFAULT_PARTIAL_THRESHOLD,
) -> AnswerVerification:
    """Veredicto por claim + acción sugerida. No modifica la respuesta."""
    claims = extract_claims(answer)
    if not claims:
        return AnswerVerification()
    verdicts = tuple(
        _classify(
            claim,
            package,
            support_threshold=support_threshold,
            partial_threshold=partial_threshold,
        )
        for claim in claims
    )
    supported = sum(1 for verdict in verdicts if verdict.status == "supported")
    partially = sum(1 for verdict in verdicts if verdict.status == "partially_supported")
    unsupported = sum(1 for verdict in verdicts if verdict.status == "unsupported")
    conflicted = sum(1 for verdict in verdicts if verdict.status == "conflicted")
    outdated = sum(1 for verdict in verdicts if verdict.status == "outdated")
    total = len(verdicts)
    unsupported_ratio = unsupported / total
    if total >= 3 and supported == 0:
        action = "abstain"
    elif unsupported_ratio > 0.5:
        action = "revise"
    elif conflicted or outdated or unsupported:
        action = "answer_with_limits"
    else:
        action = "approve"
    return AnswerVerification(
        verdicts=verdicts,
        action=action,
        supported=supported,
        partially_supported=partially,
        unsupported=unsupported,
        conflicted=conflicted,
        outdated=outdated,
    )
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_answer_verification.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/runtime/verification.py tests/test_answer_verification.py
git add src/runtime/verification.py tests/test_answer_verification.py
git commit -m "feat(cognitive): answer verifier determinista (C4)"
```

---

### Task 2: Reportes de budget y loop

**Files:**
- Create: `src/runtime/turn_reports.py`
- Test: `tests/test_turn_reports.py`

**Interfaces:**
- Consumes: `adaptive` (dict del runtime), complejidad (`L0..L5`).
- Produces:
  - `BudgetReport(complexity, max_llm_calls, max_tokens, max_seconds, llm_calls, tokens, elapsed_ms, within_budget)` + `to_public_dict()`.
  - `build_budget_report(*, complexity, llm_calls, tokens, elapsed_ms) -> BudgetReport`.
  - `LoopRound(attempt, strategy, sufficient, quality_score, reason)` + `to_public_dict()`.
  - `LoopReport(rounds, extra_round, max_rounds, exhausted)` + `to_public_dict()`.
  - `build_loop_report(adaptive, *, max_rounds=3) -> LoopReport`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_turn_reports.py`:

```python
# =============================================================================
# Reportes del turno — budget por profundidad y loop controlado (C4).
# =============================================================================
from __future__ import annotations

from src.runtime.turn_reports import build_budget_report, build_loop_report


def test_budget_dentro_y_fuera() -> None:
    ok = build_budget_report(complexity="L1", llm_calls=1, tokens=900, elapsed_ms=1500)
    assert ok.max_llm_calls == 1
    assert ok.max_tokens == 1500
    assert ok.within_budget is True
    over = build_budget_report(complexity="L0", llm_calls=1, tokens=500, elapsed_ms=100)
    assert over.max_llm_calls == 0
    assert over.within_budget is False
    payload = ok.to_public_dict()
    assert payload["complexity"] == "L1"
    assert payload["within_budget"] is True


def test_budget_complejidad_desconocida() -> None:
    report = build_budget_report(complexity=None, llm_calls=1, tokens=10, elapsed_ms=1)
    assert report.complexity == "L1"
    assert report.within_budget is True


def test_loop_sin_rondas() -> None:
    report = build_loop_report({})
    assert report.rounds == ()
    assert report.extra_round is False
    assert report.exhausted is False


def test_loop_con_rondas_y_extra() -> None:
    adaptive = {
        "attempts": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False, "quality_score": 0.2},
            {"attempt": 2, "strategy": "exact", "sufficient": True, "quality_score": 0.8},
        ],
        "preflight_extra_round": True,
        "preflight_action": "retrieve_more",
    }
    report = build_loop_report(adaptive, max_rounds=3)
    assert [round_.attempt for round_ in report.rounds] == [1, 2]
    assert report.rounds[0].reason == "insuficiente"
    assert report.rounds[1].reason == "suficiente"
    assert report.extra_round is True
    assert report.exhausted is False


def test_loop_agotado() -> None:
    adaptive = {
        "attempts": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False},
            {"attempt": 2, "strategy": "hybrid", "sufficient": False},
            {"attempt": 3, "strategy": "hybrid", "sufficient": False},
        ]
    }
    report = build_loop_report(adaptive, max_rounds=3)
    assert report.exhausted is True
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_turn_reports.py -q`
Expected: FAIL (`ModuleNotFoundError: src.runtime.turn_reports`).

- [ ] **Step 3: Implementar**

`src/runtime/turn_reports.py`:

```python
# =============================================================================
# Reportes del turno — budget por profundidad y loop controlado (C4).
# =============================================================================
# Determinista y sin I/O: mide lo que el run ya hizo. C4 reporta; el
# enforcement duro (bloquear/reencaminar) es C5.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

_PROFILE_LLM_CALLS = {"L0": 0, "L1": 1, "L2": 1, "L3": 4, "L4": 8, "L5": 12}
_PROFILE_TOKENS = {
    "L0": 0,
    "L1": 1_500,
    "L2": 4_000,
    "L3": 12_000,
    "L4": 16_000,
    "L5": 24_000,
}
_PROFILE_SECONDS = {"L0": 5.0, "L1": 20.0, "L2": 45.0, "L3": 90.0, "L4": 120.0, "L5": 180.0}


@dataclass(frozen=True)
class BudgetReport:
    complexity: str
    max_llm_calls: int
    max_tokens: int
    max_seconds: float
    llm_calls: int
    tokens: int
    elapsed_ms: float
    within_budget: bool

    def to_public_dict(self) -> dict:
        return {
            "complexity": self.complexity,
            "max_llm_calls": self.max_llm_calls,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "llm_calls": self.llm_calls,
            "tokens": self.tokens,
            "elapsed_ms": round(float(self.elapsed_ms), 1),
            "within_budget": self.within_budget,
        }


def build_budget_report(
    *,
    complexity: str | None,
    llm_calls: int,
    tokens: int,
    elapsed_ms: float,
) -> BudgetReport:
    """Perfil por profundidad; complejidad desconocida cae a L1 (least sufficient)."""
    level = str(complexity or "L1").upper()
    if level not in _PROFILE_TOKENS:
        level = "L1"
    max_calls = _PROFILE_LLM_CALLS[level]
    max_tokens = _PROFILE_TOKENS[level]
    max_seconds = _PROFILE_SECONDS[level]
    calls = max(0, int(llm_calls))
    used = max(0, int(tokens))
    elapsed = max(0.0, float(elapsed_ms))
    return BudgetReport(
        complexity=level,
        max_llm_calls=max_calls,
        max_tokens=max_tokens,
        max_seconds=max_seconds,
        llm_calls=calls,
        tokens=used,
        elapsed_ms=elapsed,
        within_budget=(
            calls <= max_calls and used <= max_tokens and elapsed <= max_seconds * 1000
        ),
    )


@dataclass(frozen=True)
class LoopRound:
    attempt: int
    strategy: str
    sufficient: bool | None
    quality_score: float | None
    reason: str

    def to_public_dict(self) -> dict:
        payload = {
            "attempt": self.attempt,
            "strategy": self.strategy,
            "sufficient": self.sufficient,
            "reason": self.reason,
        }
        if self.quality_score is not None:
            payload["quality_score"] = round(float(self.quality_score), 4)
        return payload


@dataclass(frozen=True)
class LoopReport:
    rounds: tuple[LoopRound, ...] = ()
    extra_round: bool = False
    max_rounds: int = 3
    exhausted: bool = False

    def to_public_dict(self) -> dict:
        return {
            "rounds": [round_.to_public_dict() for round_ in self.rounds],
            "count": len(self.rounds),
            "extra_round": self.extra_round,
            "max_rounds": self.max_rounds,
            "exhausted": self.exhausted,
        }


def build_loop_report(adaptive: dict, *, max_rounds: int = 3) -> LoopReport:
    """Rondas reales del run, con su razón medida (nunca inferida)."""
    rounds: list[LoopRound] = []
    for raw in list((adaptive or {}).get("attempts") or []):
        if not isinstance(raw, dict):
            continue
        sufficient = raw.get("sufficient")
        quality = raw.get("quality_score")
        if sufficient is False:
            reason = "insuficiente"
        elif sufficient is True:
            reason = "suficiente"
        else:
            reason = "sin_medicion"
        rounds.append(
            LoopRound(
                attempt=int(raw.get("attempt") or len(rounds) + 1),
                strategy=str(raw.get("strategy") or ""),
                sufficient=bool(sufficient) if sufficient is not None else None,
                quality_score=(
                    float(quality) if quality is not None else None
                ),
                reason=reason,
            )
        )
    extra = bool((adaptive or {}).get("preflight_extra_round"))
    if extra:
        rounds.append(
            LoopRound(
                attempt=len(rounds) + 1,
                strategy="preflight_extra",
                sufficient=None,
                quality_score=None,
                reason=str((adaptive or {}).get("preflight_action") or "extra"),
            )
        )
    cap = max(1, int(max_rounds))
    return LoopReport(
        rounds=tuple(rounds),
        extra_round=extra,
        max_rounds=cap,
        exhausted=len(rounds) >= cap,
    )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_turn_reports.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/turn_reports.py tests/test_turn_reports.py
git add src/runtime/turn_reports.py tests/test_turn_reports.py
git commit -m "feat(cognitive): reportes de budget y loop del turno (C4)"
```

---

### Task 3: Learning signals

**Files:**
- Create: `src/runtime/learning_signal.py`
- Test: `tests/test_learning_signal.py`

**Interfaces:**
- Consumes: `EntityResolution`, `EvidencePackage`, `AnswerVerification`, `CognitivePlan` (solo `requires_knowledge`).
- Produces:
  - `LearningSignal(kind, concept, detail, priority)` + `to_public_dict()`.
  - `build_learning_signals(*, entities=None, package=None, verification=None, requires_knowledge=False, max_signals=6) -> tuple[LearningSignal, ...]` con kinds `unresolved_entity|conflict|verification_failure|evidence_gap`.
  - `PERSISTABLE_KINDS = frozenset({"unresolved_entity", "evidence_gap"})` (mapean a `CONTEXT_MISSING`).

- [ ] **Step 1: Escribir el test que falla**

`tests/test_learning_signal.py`:

```python
# =============================================================================
# Learning signals — qué aprendió/falta del turno (S10, C4).
# =============================================================================
from __future__ import annotations

from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.evidence_assembly import (
    EvidenceConflict,
    EvidencePackage,
    EvidenceUnit,
)
from src.runtime.learning_signal import (
    PERSISTABLE_KINDS,
    build_learning_signals,
)
from src.runtime.verification import AnswerVerification, ClaimVerdict


def test_entidad_sin_resolver() -> None:
    entities = EntityResolution(
        mentions=(
            MentionResolution(mention="Record 99", status="unresolved", matches=()),
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
    signals = build_learning_signals(entities=entities)
    assert len(signals) == 1
    assert signals[0].kind == "unresolved_entity"
    assert signals[0].concept == "Record 99"
    assert "unresolved_entity" in PERSISTABLE_KINDS


def test_conflicto_y_verificacion() -> None:
    package = EvidencePackage(
        units=(
            EvidenceUnit(unit_id="U1", kind="fact", text="A", conflict=True),
            EvidenceUnit(unit_id="U2", kind="fact", text="B", conflict=True),
        ),
        conflicts=(
            EvidenceConflict(key="c1|rule x|aplica", unit_ids=("U1", "U2"), values=("a", "b")),
        ),
    )
    verification = AnswerVerification(
        verdicts=(
            ClaimVerdict(text="Claim sin respaldo en fuentes", status="unsupported", support=0.0),
        ),
        action="revise",
        unsupported=1,
    )
    signals = build_learning_signals(package=package, verification=verification)
    kinds = [signal.kind for signal in signals]
    assert "conflict" in kinds
    assert "verification_failure" in kinds


def test_evidence_gap_solo_si_requiere_conocimiento() -> None:
    empty = EvidencePackage()
    assert build_learning_signals(package=empty, requires_knowledge=True)
    assert build_learning_signals(package=empty, requires_knowledge=False) == ()


def test_cap_y_payload() -> None:
    entities = EntityResolution(
        mentions=tuple(
            MentionResolution(mention=f"X{i}", status="unresolved", matches=())
            for i in range(10)
        )
    )
    signals = build_learning_signals(entities=entities, max_signals=3)
    assert len(signals) == 3
    payload = signals[0].to_public_dict()
    assert payload["kind"] == "unresolved_entity"
    assert payload["priority"] > 0
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_learning_signal.py -q`
Expected: FAIL (`ModuleNotFoundError: src.runtime.learning_signal`).

- [ ] **Step 3: Implementar**

`src/runtime/learning_signal.py`:

```python
# =============================================================================
# Learning signals — observaciones del turno para Knowledge Health (S10, C4).
# =============================================================================
# Determinista: entidades sin resolver, conflictos retenidos, claims sin
# respaldo y falta de evidencia. No entrena pesos: alimenta gaps/health.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.evidence_assembly import EvidencePackage
    from src.runtime.verification import AnswerVerification

PERSISTABLE_KINDS = frozenset({"unresolved_entity", "evidence_gap"})


@dataclass(frozen=True)
class LearningSignal:
    kind: str
    concept: str
    detail: str
    priority: float

    def to_public_dict(self) -> dict:
        return {
            "kind": self.kind,
            "concept": self.concept[:160],
            "detail": self.detail[:240],
            "priority": round(float(self.priority), 4),
        }


def build_learning_signals(
    *,
    entities: "EntityResolution | None" = None,
    package: "EvidencePackage | None" = None,
    verification: "AnswerVerification | None" = None,
    requires_knowledge: bool = False,
    max_signals: int = 6,
) -> tuple[LearningSignal, ...]:
    """Señales medibles del turno, en orden determinista de prioridad."""
    signals: list[LearningSignal] = []
    if entities is not None:
        for mention in entities.mentions:
            if mention.status != "resolved":
                signals.append(
                    LearningSignal(
                        kind="unresolved_entity",
                        concept=mention.mention,
                        detail=f"entidad no resuelta ({mention.status})",
                        priority=0.7 if mention.status == "ambiguous" else 0.6,
                    )
                )
    if package is not None:
        for conflict in package.conflicts:
            signals.append(
                LearningSignal(
                    kind="conflict",
                    concept=conflict.key,
                    detail="valores en conflicto: " + ", ".join(conflict.values[:3]),
                    priority=0.65,
                )
            )
        if requires_knowledge and not package.units:
            signals.append(
                LearningSignal(
                    kind="evidence_gap",
                    concept="sin_evidencia",
                    detail="la consulta requiere conocimiento y no hubo evidencia",
                    priority=0.55,
                )
            )
    if verification is not None:
        unsupported = [
            verdict
            for verdict in verification.verdicts
            if verdict.status == "unsupported"
        ]
        for verdict in unsupported[:3]:
            signals.append(
                LearningSignal(
                    kind="verification_failure",
                    concept=verdict.text[:120],
                    detail="claim sin respaldo en la evidencia del turno",
                    priority=0.5,
                )
            )
    signals.sort(key=lambda signal: (-signal.priority, signal.kind, signal.concept))
    return tuple(signals[: max(0, int(max_signals))])
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_learning_signal.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/learning_signal.py tests/test_learning_signal.py
git add src/runtime/learning_signal.py tests/test_learning_signal.py
git commit -m "feat(cognitive): learning signals del turno (C4)"
```

---

### Task 4: Evidencia antes del prompt + brief en `limited`

**Files:**
- Modify: `src/agents/runtime/orchestrator.py` (`_ensure_cognitive_evidence`; ensamblado antes del prompt; inyección del brief)
- Modify: `tests/test_cognitive_runtime_shadow.py`

**Interfaces:**
- Consumes: `_assemble_cognitive_evidence` (C3), `KnowledgeBrief.render_text()`, `cognitive_runtime_mode()`.
- Produces: `_ensure_cognitive_evidence(turn, *, retrieval_context, adaptive)` idempotente; bloque `[Conocimiento canónico …]` en `system_prompt` solo en `limited`/`active`.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_cognitive_runtime_shadow.py`, agregar (los fakes ya existen):

```python
@pytest.mark.asyncio
async def test_limited_inyecta_brief_en_el_prompt(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")
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
    system_prompt = str(llm.calls[0].get("system_prompt") or "")
    assert "[Conocimiento canónico" in system_prompt
    assert "kn:" in system_prompt
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["brief"] is not None


@pytest.mark.asyncio
async def test_shadow_no_inyecta_brief(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    await _execute(orchestrator, organization.id, "¿Qué significa el Byte 105?")
    system_prompt = str(llm.calls[0].get("system_prompt") or "")
    assert "[Conocimiento canónico" not in system_prompt
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_runtime_shadow.py -q -k "brief_en_el_prompt or no_inyecta"`
Expected: FAIL (`test_limited_inyecta_brief_en_el_prompt`).

- [ ] **Step 3: Implementar**

3a. Método nuevo en el orquestador, junto a `_assemble_cognitive_evidence`:

```python
    async def _ensure_cognitive_evidence(
        self,
        turn: CognitiveTurn,
        *,
        retrieval_context: object | None,
        adaptive: dict,
    ) -> None:
        """Ensambla evidencia+brief una sola vez, antes de lo que los necesite."""
        if turn.evidence is not None:
            return
        await self._assemble_cognitive_evidence(
            turn, retrieval_context=retrieval_context, adaptive=adaptive
        )
```

3b. Antes de armar `context_snippets` (justo después del bloque de retrieval y antes de `render_evidence`, ~línea 3446), agregar:

```python
            if cognitive_turn is not None:
                await self._ensure_cognitive_evidence(
                    cognitive_turn,
                    retrieval_context=retrieval_context,
                    adaptive=adaptive,
                )
```

3c. Inyección del brief después de `custom_instructions` (~línea 3530), antes del bloque `response_plan`:

```python
            if (
                cognitive_turn is not None
                and cognitive_turn.brief is not None
                and cognitive_runtime_mode() in {"limited", "active"}
            ):
                brief_text = cognitive_turn.brief.render_text()
                if brief_text:
                    system_prompt = (
                        f"{system_prompt}\n\n"
                        "[Conocimiento canónico — usa solo lo que esté respaldado]\n"
                        f"{brief_text}"
                    )
```

3d. En el `finally`, reemplazar la llamada directa a `_assemble_cognitive_evidence` por la idempotente:

```python
                    if cognitive_turn is not None:
                        await self._ensure_cognitive_evidence(
                            cognitive_turn,
                            retrieval_context=locals().get("retrieval_context"),
                            adaptive=adaptive,
                        )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_runtime_shadow.py -q`
Expected: todos PASS (los tests de shadow/off siguen sin bloque y sin brief en prompt).

- [ ] **Step 5: Regresión + lint + commit**

```bash
pytest tests/test_cognitive_runtime_shadow.py tests/test_cognitive_state.py tests/test_answer_verification.py tests/test_turn_reports.py tests/test_learning_signal.py tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_architecture.py tests/test_jev_preflight_flow.py -q
ruff check src tests
git add src/agents/runtime/orchestrator.py tests/test_cognitive_runtime_shadow.py
git commit -m "feat(cognitive): brief canónico en el prompt limited (C4)"
```

---

### Task 5: Finalización del turno (verificación + reportes + learning)

**Files:**
- Modify: `src/runtime/cognitive_state.py` (campos `verification`, `budget`, `loop`, `learning`)
- Modify: `src/agents/runtime/orchestrator.py` (constructor `gap_recorder`; `_finalize_cognitive_turn`; llamada en el `finally`)
- Modify: `src/api/deps.py` (`gap_recorder=get_intelligence_store()`)
- Modify: `tests/test_cognitive_state.py`, `tests/test_cognitive_runtime_shadow.py`

**Interfaces:**
- Consumes: `verify_answer`, `build_budget_report`, `build_loop_report`, `build_learning_signals`, `PERSISTABLE_KINDS`, `result.llm_response`, `adaptive`.
- Produces:
  - `CognitiveTurn.verification/budget/loop/learning` + `to_public_dict()` con las 4 claves.
  - `RAGOrchestrator(gap_recorder=...)`; `_finalize_cognitive_turn(turn, *, result, adaptive)`.
  - Persistencia de gaps (`record_gap`) solo en `limited`/`active`, kinds persistables, fail-soft.

- [ ] **Step 1: Escribir los tests que fallan**

1a. `tests/test_cognitive_state.py`:

```python
def test_turn_publica_verificacion_budget_loop_learning(monkeypatch) -> None:
    from src.runtime.turn_reports import build_budget_report, build_loop_report
    from src.runtime.verification import verify_answer
    from src.runtime.evidence_assembly import EvidencePackage

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    turn = CognitiveTurn(query="q")
    turn.verification = verify_answer("", EvidencePackage())
    turn.budget = build_budget_report(complexity="L1", llm_calls=1, tokens=100, elapsed_ms=10)
    turn.loop = build_loop_report({})
    payload = turn.to_public_dict()
    assert payload["verification"]["action"] == "approve"
    assert payload["budget"]["complexity"] == "L1"
    assert payload["loop"]["count"] == 0
    assert payload["learning"] == []
```

1b. `tests/test_cognitive_runtime_shadow.py`:

```python
class FakeGapRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_gap(self, **kwargs):
        self.calls.append(kwargs)
        return "gap-1"


@pytest.mark.asyncio
async def test_limited_finaliza_verificacion_reportes_y_gaps(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")
    recorder = FakeGapRecorder()
    organization = _organization()
    llm = FakeLLM(content="El sistema usa blockchain cuántico.")
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=FakeKnowledgeModel(),
        gap_recorder=recorder,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["verification"]["action"] in {"revise", "abstain", "answer_with_limits"}
    assert cognitive["budget"]["llm_calls"] == 1
    assert "loop" in cognitive
    assert recorder.calls  # el claim sin respaldo se persistió como gap
    assert recorder.calls[0]["gap_type"] == "CONTEXT_MISSING"


@pytest.mark.asyncio
async def test_shadow_no_persiste_gaps(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    recorder = FakeGapRecorder()
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(content="El sistema usa blockchain cuántico."),
        vector_store=FakeVectorStore(_retrieval()),
        gap_recorder=recorder,
    )
    result = await _execute(orchestrator, organization.id, "¿Qué significa el Byte 105?")
    assert result.flow["cognitive"]["verification"] is not None
    assert recorder.calls == []
```

1c. Ampliar `_build` con `gap_recorder: Any = None` y pasarlo al constructor (`gap_recorder=gap_recorder`).

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: FAIL (`KeyError: 'verification'` / `TypeError: unexpected keyword 'gap_recorder'`).

- [ ] **Step 3: Implementar**

3a. `src/runtime/cognitive_state.py`: bajo TYPE_CHECKING agregar `from src.runtime.learning_signal import LearningSignal`, `from src.runtime.turn_reports import BudgetReport, LoopReport`, `from src.runtime.verification import AnswerVerification`; campos:

```python
    verification: "AnswerVerification | None" = None
    budget: "BudgetReport | None" = None
    loop: "LoopReport | None" = None
    learning: tuple["LearningSignal", ...] = ()
```

En `to_public_dict()`, antes del return:

```python
        payload["verification"] = (
            self.verification.to_public_dict()
            if self.verification is not None
            else None
        )
        payload["budget"] = (
            self.budget.to_public_dict() if self.budget is not None else None
        )
        payload["loop"] = self.loop.to_public_dict() if self.loop is not None else None
        payload["learning"] = [signal.to_public_dict() for signal in self.learning]
```

3b. Orquestador: constructor `gap_recorder: object | None = None` + `self._gap_recorder = gap_recorder` (junto a `self._learning`). Método:

```python
    async def _finalize_cognitive_turn(
        self,
        turn: CognitiveTurn,
        *,
        result: Any,
        adaptive: dict,
    ) -> None:
        """Verificación + budget + loop + learning. Nunca lanza."""
        try:
            from src.runtime.learning_signal import (
                PERSISTABLE_KINDS,
                build_learning_signals,
            )
            from src.runtime.turn_reports import (
                build_budget_report,
                build_loop_report,
            )
            from src.runtime.verification import verify_answer

            usage = result.llm_response
            answer = str(getattr(usage, "content", "") or "")
            package = turn.evidence
            if package is not None:
                turn.verification = verify_answer(answer, package)
            complexity = (
                turn.plan.complexity.value if turn.plan is not None else None
            )
            tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
            turn.budget = build_budget_report(
                complexity=complexity,
                llm_calls=1 if usage else 0,
                tokens=tokens,
                elapsed_ms=float(getattr(result, "total_latency_ms", 0.0) or 0.0),
            )
            turn.loop = build_loop_report(adaptive)
            turn.learning = build_learning_signals(
                entities=turn.entities,
                package=package,
                verification=turn.verification,
                requires_knowledge=bool(
                    turn.plan.requires_knowledge if turn.plan is not None else False
                ),
            )
            if (
                self._gap_recorder is not None
                and cognitive_runtime_mode() in {"limited", "active"}
            ):
                for signal in turn.learning:
                    if signal.kind not in PERSISTABLE_KINDS:
                        continue
                    try:
                        await self._gap_recorder.record_gap(  # type: ignore[union-attr]
                            organization_id=result.organization_id,
                            gap_type="CONTEXT_MISSING",
                            concept=signal.concept,
                            hints=[signal.detail],
                            question=turn.query,
                            impact=signal.priority,
                        )
                    except Exception as gap_exc:  # noqa: BLE001
                        logger.warning(
                            "Cognitive gap record failed", error=str(gap_exc)[:160]
                        )
        except Exception as exc:  # noqa: BLE001 — observación fail-soft
            logger.warning(
                "Cognitive turn finalize failed", error=str(exc)[:200]
            )
```

3c. En el `finally`, después de `_ensure_cognitive_evidence` y antes del attach:

```python
                    if cognitive_turn is not None:
                        await self._finalize_cognitive_turn(
                            cognitive_turn, result=result, adaptive=adaptive
                        )
```

3d. `src/api/deps.py`: en `RAGOrchestrator(...)` agregar `gap_recorder=get_intelligence_store(),`.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: todos PASS.

- [ ] **Step 5: Regresión + lint + commit**

```bash
pytest tests/test_answer_verification.py tests/test_turn_reports.py tests/test_learning_signal.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py -q
ruff check src tests
git add src/runtime/cognitive_state.py src/agents/runtime/orchestrator.py src/api/deps.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py
git commit -m "feat(cognitive): verificación, budget, loop y learning del turno (C4)"
```

---

### Task 6: Docs + estado de fase + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C4; notas de diferimiento)
- Test: suite C1–C4

- [ ] **Step 1: Docs**

- §15 fila C4 → `limited (default off) — **shipped**` + Plan: `docs/superpowers/plans/2026-10-01-cognitive-runtime-c4-verification-control.md`.
- Agregar en la misma fila (o nota al pie de la tabla): "C4: brief en prompt + verificación/budget/loop/learning trazados y gaps persistidos; el enforcement de políticas de verificación y el bloqueo por budget quedan para C5; promoción de modo sujeta a evals (W6)."

- [ ] **Step 2: Verificación final**

```bash
pytest tests/test_answer_verification.py tests/test_turn_reports.py tests/test_learning_signal.py tests/test_evidence_assembly.py tests/test_knowledge_brief.py tests/test_cognitive_domain.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_graph_temporal_runners.py tests/test_tabular_runner.py tests/test_cognitive_plan.py tests/test_knowledge_strategy.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py tests/test_retrieval_planner.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/cognitive-runtime.md
git commit -m "docs(cognitive): C4 verificación y control de turno shipped"
```

---

## Criterios de salida C4

- [ ] `off`: runtime intacto; `shadow`: observación pura (prompt/respuesta/LLM sin cambio; sin persistencia).
- [ ] `limited`/`active`: el único cambio de respuesta es el bloque `[Conocimiento canónico …]` en el prompt; verificación/budget/loop/learning trazados; gaps persistables (`unresolved_entity`, `evidence_gap`) escritos vía `gap_recorder` fail-soft.
- [ ] Verificación determinista con acción declarada (`approve|answer_with_limits|revise|abstain`) — sin enforcement en C4.
- [ ] Budget por profundidad reportado (L0 0 calls … L5 12 calls) sin bloquear; loop con rondas reales + ronda extra y cap.
- [ ] Sin dependencias, migraciones ni cambios de contrato API; `ruff check src tests` limpio.
