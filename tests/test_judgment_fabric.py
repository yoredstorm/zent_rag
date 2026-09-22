# =============================================================================
# Judgment Fabric — candidates, risk policy, selection, policy, learning.
# =============================================================================
# Sin APIs externas. Cubre los ítems de la sección 19 del brief:
# candidate filtering (agent/workflow/tool), tenant isolation, RBAC, target
# inválido, low confidence fallback, high risk, action_warranted, budget,
# explicit target, legacy paths, event judgment, language golden y explicación.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import (
    CostClass,
    DecisionContext,
    RiskLevel,
    RoutingDecision,
)
from src.decision.budget import budget_summary, cheap_path_hints, enrich_budget
from src.decision.candidates import (
    REASON_CAPABILITY,
    REASON_CROSS_TENANT,
    REASON_DISABLED,
    REASON_PERMISSION,
    REASON_RISK,
    REASON_SOURCES,
    Candidate,
    CandidateKind,
    CandidatePolicy,
    CandidateRegistry,
    candidate_kind_for_capability,
    filter_candidates,
    resolve_candidates,
)
from src.decision.event_judgment import (
    ACTION_CLARIFY,
    ACTION_DETERMINISTIC,
    ACTION_ESCALATE_AGENT,
    ACTION_IGNORE,
    judge_event,
)
from src.decision.explanation import confidence_band, explain_decision, route_label
from src.decision.policy import (
    REASON_ALLOWED,
    REASON_CAPABILITY_DENIED,
    REASON_HUMAN,
    REASON_LOW_CONFIDENCE,
    REASON_MISSING_TARGET,
    REASON_NOT_WARRANTED,
    REASON_TARGET_NOT_ALLOWED,
    authorize_decision,
    evaluate_policy,
)
from src.decision.risk_policy import (
    FALLBACK_CLARIFY,
    FALLBACK_HUMAN,
    FALLBACK_RESPOND,
    DecisionRiskPolicy,
)
from src.decision.selection import (
    POLICY_EXECUTE,
    select_target,
    selection_outcome,
)
from src.runtime.dispatcher import CapabilityDispatcher, DispatchRequest, with_target


class FakeJudge:
    def __init__(self, answers: dict | None = None) -> None:
        self.answers = answers or {}
        self.calls = 0
        self.questions: dict = {}
        self.state: dict = {}

    async def judge(self, *, state, questions, context=None):
        self.calls += 1
        self.questions = questions
        self.state = state
        return {
            "answers": self.answers,
            "provider": "jev",
            "model": "fake",
            "latency_ms": 4.0,
        }


def _candidate(
    cid: str,
    *,
    kind: str = CandidateKind.AGENT.value,
    risk: RiskLevel = RiskLevel.MEDIUM,
    permission: str = "agents:execute",
    sources: tuple[str, ...] = (),
    tenant_id: str | None = None,
    enabled: bool = True,
    status: str = "active",
    capabilities: tuple[str, ...] = ("agent.execute",),
) -> Candidate:
    return Candidate(
        id=cid,
        kind=kind,
        name=cid,
        description=f"candidate {cid}",
        capabilities=capabilities,
        required_sources=sources,
        risk_level=risk,
        required_permission=permission,
        cost_class=CostClass.STANDARD,
        tenant_id=tenant_id,
        enabled=enabled,
        status=status,
    )


# ---------------------------------------------------------------------------
# Candidate resolver
# ---------------------------------------------------------------------------


def test_candidate_kind_por_capability() -> None:
    assert candidate_kind_for_capability("agent.execute") == "agent"
    assert candidate_kind_for_capability("workflow.resume") == "workflow"
    assert candidate_kind_for_capability("tool.send_email") == "tool"
    assert candidate_kind_for_capability("knowledge.answer") is None


def test_agent_candidates_filtran_disabled_permission_y_riesgo() -> None:
    raw = [
        _candidate("inventory_agent"),
        _candidate("draft_agent", enabled=False, status="draft"),
        _candidate("no_perm", permission="agents:admin"),
        _candidate("critical_agent", risk=RiskLevel.CRITICAL),
        _candidate("high_agent", risk=RiskLevel.HIGH),
    ]
    result = filter_candidates(
        raw,
        policy=CandidatePolicy(
            permissions=frozenset({"agents:execute"}), capability="agent.execute"
        ),
        kind="agent",
    )
    assert result.ids() == ("inventory_agent", "high_agent")
    reasons = {r.candidate_id: r.reason for r in result.rejected}
    assert reasons["draft_agent"] == REASON_DISABLED
    assert reasons["no_perm"] == REASON_PERMISSION
    assert reasons["critical_agent"] == REASON_RISK


def test_workflow_candidates_requieren_capability_y_status() -> None:
    raw = [
        _candidate(
            "wf_ok",
            kind="workflow",
            permission="workflows:run",
            capabilities=("workflow.start", "workflow.execute"),
        ),
        _candidate(
            "wf_draft",
            kind="workflow",
            permission="workflows:run",
            enabled=False,
            status="draft",
            capabilities=("workflow.start",),
        ),
        _candidate(
            "wf_other",
            kind="workflow",
            permission="workflows:run",
            capabilities=("workflow.resume",),
        ),
    ]
    result = filter_candidates(
        raw,
        policy=CandidatePolicy(
            permissions=frozenset({"workflows:run"}), capability="workflow.start"
        ),
        kind="workflow",
    )
    assert result.ids() == ("wf_ok",)
    reasons = {r.candidate_id: r.reason for r in result.rejected}
    assert reasons["wf_draft"] == REASON_DISABLED
    assert reasons["wf_other"] == REASON_CAPABILITY


def test_tool_candidates_source_aware() -> None:
    raw = [
        _candidate(
            "query_database",
            kind="tool",
            permission="tool:query_database",
            sources=("sql",),
            capabilities=("tool.execute",),
        ),
        _candidate(
            "call_api",
            kind="tool",
            permission="tool:call_api",
            sources=("api",),
            capabilities=("tool.execute",),
        ),
    ]
    result = filter_candidates(
        raw,
        policy=CandidatePolicy(
            permissions=frozenset({"tool:query_database", "tool:call_api"}),
            sources=frozenset({"sql"}),
            capability="tool.execute",
        ),
        kind="tool",
    )
    assert result.ids() == ("query_database",)
    assert result.rejected[0].reason == REASON_SOURCES


def test_tenant_isolation_rechaza_otro_tenant() -> None:
    raw = [
        _candidate("mio", tenant_id="org-a"),
        _candidate("ajeno", tenant_id="org-b"),
        _candidate("sin_tenant"),
    ]
    result = filter_candidates(
        raw,
        policy=CandidatePolicy(permissions=frozenset({"*"}), tenant_id="org-a"),
        kind="agent",
    )
    assert result.ids() == ("mio", "sin_tenant")
    assert {r.candidate_id: r.reason for r in result.rejected}["ajeno"] == REASON_CROSS_TENANT


def test_allowlist_de_tenant() -> None:
    raw = [_candidate("a"), _candidate("b")]
    result = filter_candidates(
        raw,
        policy=CandidatePolicy(
            permissions=frozenset({"*"}), allowed_ids=frozenset({"b"})
        ),
        kind="agent",
    )
    assert result.ids() == ("b",)


@pytest.mark.asyncio
async def test_registry_tenant_scoped_por_provider() -> None:
    registry = CandidateRegistry()
    seen: list = []

    async def provider(organization_id, context=None):
        seen.append(organization_id)
        return [_candidate("agent_x", tenant_id=str(organization_id))]

    registry.register("agent", provider)
    org = uuid4()
    result = await resolve_candidates(
        registry,
        "agent",
        organization_id=org,
        policy=CandidatePolicy(permissions=frozenset({"*"}), tenant_id=str(org)),
    )
    assert result.ids() == ("agent_x",)
    assert seen == [org]


# ---------------------------------------------------------------------------
# Risk policy
# ---------------------------------------------------------------------------


def test_risk_policy_thresholds_por_nivel() -> None:
    policy = DecisionRiskPolicy()
    low = policy.thresholds("low")
    high = policy.thresholds("high")
    critical = policy.thresholds("critical")
    assert low.choice_threshold < high.choice_threshold < critical.choice_threshold
    assert high.warrant_required is True
    assert critical.warrant_required is True
    assert high.on_low_confidence == FALLBACK_HUMAN
    assert low.on_low_confidence == FALLBACK_RESPOND
    assert policy.thresholds("unknown").risk == "low"


def test_risk_policy_tenant_override_y_settings() -> None:
    policy = DecisionRiskPolicy.from_settings(
        object(),
        tenant_policy={
            "risk_policy": {"high": {"choice_threshold": 0.95, "on_low_confidence": "stop"}}
        },
    )
    # `stop` no es acción válida: se conserva la anterior.
    assert policy.thresholds("high").choice_threshold == 0.95
    assert policy.thresholds("high").on_low_confidence == FALLBACK_HUMAN


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _selection_set(*ids: str, risk: RiskLevel = RiskLevel.MEDIUM):
    return filter_candidates(
        [_candidate(cid, risk=risk) for cid in ids],
        policy=CandidatePolicy(permissions=frozenset({"agents:execute"}), capability="agent.execute"),
        kind="agent",
    )


@pytest.mark.asyncio
async def test_explicit_target_tiene_prioridad_y_no_gasta_jev() -> None:
    judge = FakeJudge()
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b"),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
        explicit_target="a",
    )
    assert judge.calls == 0
    assert selection.target_id == "a"
    assert selection.policy_action == POLICY_EXECUTE
    assert selection.reason == "explicit_target"


@pytest.mark.asyncio
async def test_target_invalido_se_rechaza_y_cae_al_fallback() -> None:
    judge = FakeJudge(
        {
            "target": {"type": "choice", "choice": "hacked", "confidence": 0.99},
            "action_warranted": {"type": "noul", "noul": 0.9},
        }
    )
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b", risk=RiskLevel.HIGH),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
    )
    assert selection.target_id is None
    assert selection.reason == "invalid_target"
    assert selection.policy_action == FALLBACK_HUMAN


@pytest.mark.asyncio
async def test_low_confidence_fallback_por_riesgo() -> None:
    judge = FakeJudge(
        {"target": {"type": "choice", "choice": "a", "confidence": 0.55}}
    )
    medium = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b", risk=RiskLevel.MEDIUM),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
    )
    assert medium.target_id is None
    assert medium.policy_action == FALLBACK_CLARIFY
    assert medium.reason == "low_confidence"


@pytest.mark.asyncio
async def test_action_warranted_false_bloquea_high_risk() -> None:
    judge = FakeJudge(
        {
            "target": {"type": "choice", "choice": "a", "confidence": 0.95},
            "action_warranted": {"type": "noul", "noul": 0.2},
        }
    )
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b", risk=RiskLevel.HIGH),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
    )
    assert selection.target_id is None
    assert selection.reason == "action_not_warranted"
    assert selection.warranted is False


@pytest.mark.asyncio
async def test_dos_senales_no_se_mezclan_con_max() -> None:
    """Choice alto con warrant bajo NO ejecuta (nunca max)."""
    judge = FakeJudge(
        {
            "target": {"type": "choice", "choice": "a", "confidence": 0.99},
            "action_warranted": {"type": "noul", "noul": 0.55},
        }
    )
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b", risk=RiskLevel.HIGH),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
    )
    assert selection.policy_action != POLICY_EXECUTE


@pytest.mark.asyncio
async def test_single_candidate_no_gasta_jev() -> None:
    judge = FakeJudge()
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("only"),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
    )
    assert judge.calls == 0
    assert selection.target_id == "only"
    assert selection.reason == "single_candidate"


@pytest.mark.asyncio
async def test_default_target_de_tenant() -> None:
    judge = FakeJudge()
    selection = await select_target(
        judge,
        capability="agent.execute",
        candidates=_selection_set("a", "b"),
        user_request="x",
        risk_policy=DecisionRiskPolicy(),
        tenant_policy={"default_targets": {"agent": "b"}},
        budget={"prefer_cheap": True},
    )
    # No hay juicio (judge sin respuestas) → fallback de política para medium.
    assert selection.policy_action in {FALLBACK_CLARIFY, FALLBACK_RESPOND}
    resolved = selection_outcome(
        selection, candidates=_selection_set("a", "b"), tenant_policy={"default_targets": {"agent": "b"}}
    )
    assert resolved.policy_action in {POLICY_EXECUTE, FALLBACK_CLARIFY, FALLBACK_RESPOND}


def test_selection_outcome_usa_default_target() -> None:
    from dataclasses import replace

    selection = select_target.__wrapped__ if False else None  # noqa: F841
    from src.decision.selection import TargetSelection

    base = TargetSelection(
        capability="agent.execute",
        kind="agent",
        policy_action="default_target",
        reason="low_confidence",
    )
    resolved = selection_outcome(
        base,
        candidates=_selection_set("a", "b"),
        tenant_policy={"default_targets": {"agent": "b"}},
    )
    assert resolved.target_id == "b"
    assert resolved.policy_action == POLICY_EXECUTE
    assert replace(base, policy_action="default_target").policy_action == "default_target"


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


def _context(**kwargs) -> DecisionContext:
    defaults = dict(
        user_request="x",
        organization_id=uuid4(),
        permissions=frozenset({"agents:execute"}),
        available_capabilities=("agent.execute",),
        tenant_policy={},
        budget={},
    )
    defaults.update(kwargs)
    return DecisionContext(**defaults)


def _decision(**kwargs) -> RoutingDecision:
    defaults = dict(
        capability="agent.execute", resolved=True, confidence=0.95, provider="jev"
    )
    defaults.update(kwargs)
    return RoutingDecision(**defaults)


def test_policy_target_fuera_del_set_no_autoriza() -> None:
    result = evaluate_policy(
        _decision(),
        _context(),
        target="otro",
        candidate_ids=("a", "b"),
        risk="medium",
    )
    assert result.authorized is False
    assert result.reason == REASON_TARGET_NOT_ALLOWED


def test_policy_capability_no_permitida() -> None:
    result = evaluate_policy(
        _decision(),
        _context(available_capabilities=("knowledge.answer", "respond_directly")),
        target="a",
        candidate_ids=("a",),
    )
    assert result.authorized is False
    assert result.reason == REASON_CAPABILITY_DENIED


def test_policy_high_risk_exige_warrant() -> None:
    no_warrant = evaluate_policy(
        _decision(confidence=0.95),
        _context(),
        target="a",
        candidate_ids=("a",),
        risk="high",
    )
    assert no_warrant.authorized is False
    assert no_warrant.reason == REASON_NOT_WARRANTED
    ok = evaluate_policy(
        _decision(confidence=0.95),
        _context(),
        target="a",
        candidate_ids=("a",),
        action_warranted=0.8,
        risk="high",
    )
    assert ok.authorized is True
    assert ok.requires_human is True  # high risk pide confirmación humana
    assert ok.executable is False


def test_policy_low_confidence_y_missing_target() -> None:
    low = evaluate_policy(
        _decision(confidence=0.4),
        _context(),
        target="a",
        candidate_ids=("a",),
        risk="medium",
    )
    assert low.reason == REASON_LOW_CONFIDENCE
    missing = evaluate_policy(_decision(), _context(), target=None)
    assert missing.reason == REASON_MISSING_TARGET


def test_policy_budget_block() -> None:
    result = evaluate_policy(
        _decision(),
        _context(budget={"on_limit": "block", "remaining_ok": False}),
        target="a",
        candidate_ids=("a",),
        risk="low",
    )
    assert result.authorized is False
    assert result.reason == "budget_block"


def test_policy_low_risk_allowed() -> None:
    result = evaluate_policy(
        _decision(confidence=0.9),
        _context(),
        target="a",
        candidate_ids=("a",),
        risk="low",
    )
    assert result.authorized is True
    assert result.reason == REASON_ALLOWED
    assert result.executable is True


def test_authorize_decision_legacy_sigue_igual() -> None:
    decision = _decision(capability="tool.send_email", confidence=0.9)
    context = _context(available_capabilities=("knowledge.answer", "respond_directly"))
    out = authorize_decision(decision, context)
    assert out.capability == "knowledge.answer"
    assert out.fallback_used is True
    assert out.metadata["authorization_denied"] is True


def test_policy_human_review_requiere_confirmacion() -> None:
    result = evaluate_policy(
        _decision(confidence=0.95),
        _context(),
        target="a",
        candidate_ids=("a",),
        action_warranted=0.9,
        risk="high",
        require_human_confirmation=True,
    )
    assert result.reason == REASON_HUMAN
    assert result.requires_human is True
    assert result.executable is False


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_summary_no_expone_saldos() -> None:
    summary = budget_summary(
        {
            "granted": 100.0,
            "remaining": 5.0,
            "used_credits": 95.0,
            "trial_credits": 100.0,
            "on_limit": "cheap-mode",
        }
    )
    assert summary["budget_class"] == "low"
    assert summary["remaining_ratio"] == pytest.approx(0.05)
    assert summary["cost_pressure"] is True
    assert "trial_credits" not in summary
    assert "remaining" not in summary
    assert cheap_path_hints(summary)["prefer_deterministic"] is True
    assert budget_summary(None)["budget_class"] == "unknown"
    assert budget_summary({"granted": 10.0, "remaining": 0.0})["budget_class"] == "depleted"
    assert enrich_budget({"granted": 10.0, "remaining": 9.0})["summary"]["budget_class"] == "healthy"


# ---------------------------------------------------------------------------
# Dispatcher end-to-end (fabric)
# ---------------------------------------------------------------------------


class FakeDispatchHandler:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, request, decision):
        from src.runtime.dispatcher import DispatchResult

        self.calls.append({"agent_id": request.agent_id, "capability": decision.capability})
        return DispatchResult(capability=decision.capability, handler="agent_runtime", answer="ok")


@pytest.mark.asyncio
async def test_dispatcher_resuelve_target_y_politica_autoriza() -> None:
    registry = CandidateRegistry()
    agent_a = str(uuid4())
    agent_b = str(uuid4())

    async def provider(organization_id, context=None):
        return [
            _candidate(agent_a, tenant_id=str(organization_id)),
            _candidate(agent_b, tenant_id=str(organization_id)),
        ]

    registry.register("agent", provider)
    judge = FakeJudge(
        {
            "target": {"type": "choice", "choice": agent_b, "confidence": 0.93},
            "action_warranted": {"type": "noul", "noul": 0.8},
        }
    )
    dispatcher = CapabilityDispatcher()
    handler = FakeDispatchHandler()
    dispatcher.register("agent_runtime", handler)
    dispatcher.configure_target_selection(
        candidates=registry, judge=judge, mode="on"
    )
    org = uuid4()
    request = DispatchRequest(
        organization_id=org,
        query="necesito la política de devoluciones",
        permissions=frozenset({"agents:execute"}),
        role="admin",
    )
    decision = _decision()
    resolution = await dispatcher.resolve_target(decision, request)
    assert resolution is not None
    assert resolution.executable is True
    assert resolution.selection.target_id == agent_b
    request = with_target(request, resolution.selection.kind, resolution.selection.target_id)
    result = await dispatcher.dispatch(decision, request, authorized=resolution.policy)
    assert result.completed is True
    assert str(handler.calls[0]["agent_id"]) == agent_b


@pytest.mark.asyncio
async def test_dispatcher_sin_politica_no_ejecuta() -> None:
    dispatcher = CapabilityDispatcher()
    handler = FakeDispatchHandler()
    dispatcher.register("agent_runtime", handler)
    decision = _decision()
    denied_policy = evaluate_policy(
        decision,
        _context(budget={"on_limit": "block", "remaining_ok": False}),
        target="a",
        candidate_ids=("a",),
        risk="low",
    )
    result = await dispatcher.dispatch(
        decision,
        DispatchRequest(organization_id=uuid4(), query="x"),
        authorized=denied_policy,
    )
    assert result.status == "denied"
    assert handler.calls == []


@pytest.mark.asyncio
async def test_dispatcher_selection_off_no_resuelve() -> None:
    registry = CandidateRegistry()
    dispatcher = CapabilityDispatcher()
    dispatcher.configure_target_selection(candidates=registry, mode="off")
    assert dispatcher.selection_enabled() is False
    resolution = await dispatcher.resolve_target(
        _decision(), DispatchRequest(organization_id=uuid4(), query="x")
    )
    assert resolution is None


# ---------------------------------------------------------------------------
# Event judgment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evento_deterministico_no_gasta_jev() -> None:
    class NoDispatcher:
        async def resolve_target(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("no debe llamarse")

    judgment = await judge_event(
        {
            "event_type": "inventory.stock.low@v2",
            "organization_id": str(uuid4()),
            "deterministic_action": "workflow.start",
        },
        dispatcher=NoDispatcher(),
    )
    assert judgment.action == ACTION_DETERMINISTIC
    assert judgment.deterministic is True
    assert judgment.jev_used is False


@pytest.mark.asyncio
async def test_evento_sin_capability_hint_se_ignora() -> None:
    judgment = await judge_event(
        {"event_type": "inventory.low", "organization_id": str(uuid4()), "message": "stock bajo"},
        dispatcher=None,
    )
    assert judgment.action == ACTION_IGNORE
    assert judgment.reason == "no_capability_hint"


@pytest.mark.asyncio
async def test_evento_escala_agente_con_politica() -> None:
    class FakeDispatcher:
        async def resolve_target(self, decision, request):
            from src.decision.policy import AuthorizedDecision
            from src.decision.selection import TargetSelection

            selection = TargetSelection(
                capability=decision.capability,
                kind="agent",
                target_id="inventory_agent",
                choice="inventory_agent",
                confidence=0.92,
                policy_action=POLICY_EXECUTE,
                reason="ok",
                jev_used=True,
            )
            policy = AuthorizedDecision(
                decision=decision, authorized=True, target_id="inventory_agent"
            )
            return type(
                "Resolution",
                (),
                {"selection": selection, "policy": policy, "executable": True},
            )()

    judgment = await judge_event(
        {
            "event_type": "inventory.stock.low",
            "organization_id": str(uuid4()),
            "message": "el stock del SKU-7788 bajó del mínimo",
            "capability": "agent.execute",
        },
        dispatcher=FakeDispatcher(),
    )
    assert judgment.action == ACTION_ESCALATE_AGENT
    assert judgment.target_id == "inventory_agent"
    assert judgment.executable is True


@pytest.mark.asyncio
async def test_evento_sin_target_cae_a_clarify() -> None:
    class FakeDispatcher:
        async def resolve_target(self, decision, request):
            from src.decision.policy import AuthorizedDecision
            from src.decision.selection import TargetSelection

            selection = TargetSelection(
                capability=decision.capability,
                kind="agent",
                policy_action="ask_clarification",
                reason="no_candidates",
            )
            policy = AuthorizedDecision(
                decision=decision, authorized=False, reason="no_candidates"
            )
            return type(
                "Resolution",
                (),
                {"selection": selection, "policy": policy, "executable": False},
            )()

    judgment = await judge_event(
        {
            "event_type": "inventory.stock.low",
            "organization_id": str(uuid4()),
            "message": "stock bajo",
            "capability": "agent.execute",
        },
        dispatcher=FakeDispatcher(),
    )
    assert judgment.action == ACTION_CLARIFY
    assert judgment.executable is False


# ---------------------------------------------------------------------------
# Explanation + language golden
# ---------------------------------------------------------------------------


def test_explicacion_usuario_no_muestra_cot() -> None:
    decision = _decision()
    decision.metadata = {"reason": "ok", "model": "jev-latest", "questions": ["capability"]}
    user_view = explain_decision(decision, evidence_count=3)
    assert user_view["route"] == "agente"
    assert user_view["confidence"] == "alta"
    assert user_view["sources_consulted"] == 3
    assert "questions_evaluated" not in user_view
    admin_view = explain_decision(decision, mode="admin", evidence_count=3)
    assert admin_view["questions_evaluated"] == ["capability"]
    assert "chain" not in str(admin_view).lower()
    assert route_label("knowledge.answer") == "base de conocimiento"
    assert confidence_band(0.5) == "baja"


def test_language_golden_cobertura_y_canonical() -> None:
    from src.rag.evaluation.language_golden import (
        canonicalize,
        compare_language_modes,
        coverage,
        default_cases,
        term_preservation,
    )

    report = coverage()
    assert report["total"]["all"] >= 10
    for kind in ("business", "technical", "casual", "typos", "spanglish", "sql", "fields", "codes", "aviation", "abbreviations"):
        assert kind in report["by_kind"], kind
    # Códigos/SKUs/field names intactos.
    assert "sku-7788" in canonicalize("¿Hay stock del SKU-7788?")
    assert "invoice_status" in canonicalize("¿Qué significa invoice_status?")
    assert "2026-01-01" in canonicalize("SELECT * FROM pedidos WHERE fecha > '2026-01-01'")
    # Abreviaturas expandidas.
    assert "cantidad" in canonicalize("cant prod x dpto")
    comparison = compare_language_modes()
    assert comparison["modes"]["raw"]["term_preservation"] >= 0.5
    assert comparison["modes"]["canonical"]["term_preservation"] >= 0.5
    assert comparison["decision"]["status"] == "sin_traduccion_obligatoria"
    case = default_cases()[0]
    assert term_preservation(case, mode="raw") == 1.0


# ---------------------------------------------------------------------------
# Learning / costs (estructura, sin datos)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learning_report_estructura() -> None:
    from src.decision.learning import (
        CALIBRATION_BUCKETS,
        confidence_calibration,
        decision_learning_report,
        model_comparison,
    )

    report = await decision_learning_report(days=1)
    assert "totals" in report and "mismatches" in report
    calibration = await confidence_calibration(days=1)
    assert [b["bucket"] for b in calibration["buckets"]] == list(CALIBRATION_BUCKETS)
    assert all("accuracy" in bucket for bucket in calibration["buckets"])
    models = await model_comparison(days=1)
    assert models["flow"] == ["candidate", "shadow", "evaluation", "manual_promote"]


def test_cost_breakdown_categoriza_eventos() -> None:
    from src.runtime.cost_breakdown import CATEGORY_ORDER, categorize

    assert categorize("jev_judge:pre_retrieval") == "jev_pre_retrieval"
    assert categorize("jev_judge:evidence") == "jev_evidence"
    assert categorize("jev_judge:grounding") == "jev_grounding"
    assert categorize("jev_judge:tool_routing") == "jev_agent_step"
    assert categorize("decision") == "routing"
    assert categorize("agent_run") == "agents"
    assert categorize("workflow_run") == "workflows"
    assert categorize("tool") == "tools"
    assert categorize("desconocido") == "other"
    assert set(CATEGORY_ORDER) >= {"jev_evidence", "llm", "embeddings", "reranker"}


@pytest.mark.asyncio
async def test_cost_breakdown_estructura() -> None:
    from src.runtime.cost_breakdown import cost_breakdown

    report = await cost_breakdown(days=1)
    assert "total_cost" in report and "jev_cost" in report
    assert "per_result" in report
    assert isinstance(report["categories"], list)


# ---------------------------------------------------------------------------
# Workflow AI node (UX amigable)
# ---------------------------------------------------------------------------


def test_ai_decision_usa_threshold_central() -> None:
    from src.runtime.ai_decision import (
        default_confidence_min,
        interpret,
        parse_config,
        to_business_explanation,
        to_output,
    )

    default = default_confidence_min(risk="medium")
    config = parse_config({"question": "¿Aprobar?"}, default_confidence_min=default)
    assert config.confidence_min == pytest.approx(default)
    explicit = parse_config({"question": "¿Aprobar?", "confidence_min": 0.9})
    assert explicit.confidence_min == pytest.approx(0.9)
    outcome = interpret(config, None)
    output = to_output(outcome)
    assert "explanation" in output
    assert set(output["explanation"]) == {
        "decision",
        "confidence",
        "needs_review",
        "action_on_doubt",
        "provider",
    }
    assert "noul" not in str(output["explanation"]).lower()
    assert to_business_explanation(outcome)["confidence"] in {"alta", "media", "baja"}
