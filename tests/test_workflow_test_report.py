from src.platform.workflows.test_report import (
    ROLE_SCENARIOS,
    bind_certificate,
    draft_to_scenario,
    evidence_status,
    explain_report,
    mask_value,
    property_findings,
    publication_blockers,
    role_scenario,
)


def _mission_graph() -> dict:
    return {
        "nodes": [{"id": "pay", "type": "capability_call"}],
        "metadata": {"mission": {"role": "Mentor"}},
    }


def test_levels_never_call_unverified_effects_passed() -> None:
    assert evidence_status("preview", unverified=False, observed="PASSED") == "PREVIEW"
    assert evidence_status("simulation", unverified=True, observed="PASSED") == "UNVERIFIED"
    assert evidence_status("sandbox", unverified=True, observed="PASSED") == "UNVERIFIED"
    assert evidence_status("provider", unverified=True, observed="PASSED") == "UNVERIFIED"
    assert evidence_status("provider", unverified=False, observed="PASSED") == "PASSED"


def test_role_examples_compile_without_a_vertical_engine() -> None:
    for role in ("ventas", "mentor", "tutor", "auditor", "soporte", "bienestar"):
        scenario = role_scenario(role)
        assert scenario.scenario_id
        assert scenario.max_segments <= 100
    sales = property_findings(ROLE_SCENARIOS["ventas"])
    assert any(item["code"] == "duplicate_signal" for item in sales)
    wellness = role_scenario("bienestar")
    assert "clinical.diagnose" in wellness.forbidden_effects
    tutor = draft_to_scenario(ROLE_SCENARIOS["tutor"])
    assert tutor.responses[0].capability_ref == "learning.exercise.evaluate"


def test_publication_blocks_stale_or_unverified_and_keeps_legacy() -> None:
    graph = _mission_graph()
    assert publication_blockers(graph, None)[0]["code"] == "certification_required"
    cert = bind_certificate(
        level="simulation",
        state="SIMULATION_PASSED",
        graph=graph,
        semantic_plan_hash="plan",
        capability_snapshot_hash="snap",
        unverified=1,
    )
    codes = {item["code"] for item in publication_blockers(graph, cert, semantic_plan_hash="plan", capability_snapshot_hash="snap")}
    assert "unverified_effects" in codes
    assert cert["publishable"] is False
    ready = bind_certificate(
        level="provider",
        state="READY_TO_PUBLISH",
        graph=graph,
        semantic_plan_hash="plan",
        capability_snapshot_hash="snap",
        unverified=0,
    )
    assert publication_blockers(
        graph, ready, semantic_plan_hash="plan", capability_snapshot_hash="snap", production_enabled=True
    ) == []
    disabled = publication_blockers(
        graph, ready, semantic_plan_hash="plan", capability_snapshot_hash="snap"
    )
    assert disabled[-1]["code"] == "production_disabled"
    changed = dict(graph)
    changed["nodes"] = [{"id": "other", "type": "end"}]
    assert publication_blockers(changed, ready)[0]["code"] == "certificate_stale"
    legacy = {"nodes": [{"id": "pay", "type": "capability_call"}], "metadata": {}}
    assert publication_blockers(legacy, None) == []


def test_report_explains_gaps_and_masks_secrets() -> None:
    report = explain_report(level="simulation", result="UNVERIFIED", unverified=["payments.checkout.create"], failed=[], duration_ms=40)
    assert report["result"] == "UNVERIFIED"
    assert "proveedor real" in report["gaps"][0]
    assert "pase" in report["why"]
    masked = mask_value({"sku": "arroz", "api_key": "sek", "note": "x" * 300})
    assert masked["api_key"] == "[enmascarado]"
    assert masked["sku"] == "arroz"
    assert masked["note"].endswith("…")


def test_properties_reject_unauthorized_effects_and_open_budget() -> None:
    findings = property_findings(
        {"allowed_effects": ["inventory.stock.get"], "max_segments": 4, "budget_ms": 0},
        observed_effects=["payments.checkout.create"],
    )
    codes = {item["code"] for item in findings}
    assert "unauthorized_effect" in codes
    assert "budget" in codes
