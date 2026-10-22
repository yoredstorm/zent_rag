from src.platform.workflows.operations import (
    VIEW_STATUSES,
    authorize_action,
    chaos_observation,
    classify_fault,
    operational_status,
    project_business_timeline,
    redact_payload,
    sandbox_replay_allowed,
    signal_decision,
)


def test_view_status_comes_from_the_stored_engine_status() -> None:
    assert operational_status({"status": "RUNNING"}) == "running"
    assert operational_status({"status": "WAITING"}) == "waiting"
    assert operational_status({"status": "WAITING", "waiting_event_type": "approval.decided"}) == "pending_approval"
    assert operational_status({"status": "SUSPENDED"}) == "needs_human"
    assert operational_status({"status": "WAITING", "waiting_for": {"retry_at": "2026-10-22T00:00:00Z"}}) == "retry_scheduled"
    assert operational_status({"status": "EXPIRED"}) == "expired"
    assert operational_status({"status": "COMPLETED"}) == "completed"
    assert "ghost" not in VIEW_STATUSES
    assert operational_status({"status": "NOT_A_STATUS"}) == "NOT_A_STATUS"


def test_signal_races_do_not_double_execute() -> None:
    assert signal_decision(instance_status="RUNNING", duplicate=False, correlation_matches=True, event_matches=True) == "queued"
    assert signal_decision(instance_status="WAITING", duplicate=True, correlation_matches=True, event_matches=True) == "duplicate_ignored"
    assert signal_decision(instance_status="WAITING", duplicate=False, correlation_matches=False, event_matches=True) == "correlation_mismatch"
    assert signal_decision(instance_status="WAITING", duplicate=False, correlation_matches=True, event_matches=False) == "event_mismatch"
    assert signal_decision(instance_status="WAITING", duplicate=False, correlation_matches=True, event_matches=True) == "resume_once"


def test_actions_require_permission_and_sandbox_for_replay() -> None:
    assert authorize_action("cancel", {"workflows:run"}) is True
    assert authorize_action("cancel", set()) is False
    assert authorize_action("drop_database", {"admin:*"}) is False
    assert sandbox_replay_allowed(sandbox=False) is False
    assert sandbox_replay_allowed(sandbox=True) is True


def test_timeline_redacts_and_classifies() -> None:
    steps = project_business_timeline(
        {
            "runs": [{"instance_seq": 1, "status": "failed", "started_at": "t0", "error": "contract_mismatch", "duration_ms": 10}],
            "signals": [{"event_type": "payment.succeeded", "status": "pending", "received_at": "t1", "payload": {"api_key": "sek", "sku": "arroz"}}],
            "events": [{"kind": "causal_link", "created_at": "t2", "node_id": "route", "payload": {}}],
        }
    )
    assert steps[0]["step"] == "trigger"
    assert steps[0]["fault"] == "contract"
    assert steps[1]["payload"]["api_key"] == "[redactado]"
    assert steps[1]["payload"]["sku"] == "arroz"
    assert classify_fault("low_confidence") == "low_confidence"
    assert classify_fault("permiso denegado") == "policy"
    assert redact_payload({"token": "abc"})["token"] == "[redactado]"


def test_chaos_does_not_pass_when_the_dependency_is_down() -> None:
    redis = chaos_observation("redis_down", dependency_available=False)
    llm = chaos_observation("llm_cut", dependency_available=False)
    assert redis["passed"] is False
    assert redis["result"] == "UNVERIFIED"
    assert llm["passed"] is False
    live = chaos_observation("duplicate_webhook", dependency_available=True)
    assert live["passed"] is False
    assert live["result"] == "OBSERVED"
