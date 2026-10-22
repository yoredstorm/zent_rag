# =============================================================================
# Planner structured-output hardening.
#
# These tests cover provider output variants that used to become
# `planner.invalid_llm_output`: markdown fences, trailing DSML, native tool
# calls, reasoning-only responses and business aliases.
# =============================================================================
from __future__ import annotations

from src.platform.workflows.json_output import parse_json_object
from src.platform.workflows.planner_session import (
    _action_from_tool_calls,
    _normalize_action_mapping,
    _normalize_matches,
    _normalize_plan_payload,
    _normalize_spec_payload,
    _parse_action_text,
)


def test_parse_json_object_ignores_trailing_dsml() -> None:
    raw = '{"ok": true}\n<|DSML| invoke name="capability.search">'
    assert parse_json_object(raw) == {"ok": True}


def test_parse_json_object_ignores_markdown_fence() -> None:
    raw = '```json\n{"action": "clarify", "questions": ["falta el canal"]}\n```'
    assert parse_json_object(raw) == {
        "action": "clarify",
        "questions": ["falta el canal"],
    }


def test_parse_action_text_selects_action_over_example() -> None:
    raw = (
        'Ejemplo: {"foo": 1}\n'
        '{"action":"tool","tool":"capability.search","arguments":{"query":"stock"}}'
    )
    action = _parse_action_text(raw)
    assert action is not None
    assert action["action"] == "tool"
    assert action["tool"] == "capability.search"


def test_parse_action_text_accepts_bare_plan() -> None:
    raw = '{"schema_version":"2.0","goal":"x","steps":[{"id":"s1","type":"stop","goal":"fin"}]}'
    action = _parse_action_text(raw)
    assert action is not None
    assert action["action"] == "plan"
    assert action["plan"]["steps"][0]["type"] == "stop"


def test_normalize_action_mapping_aliases() -> None:
    assert _normalize_action_mapping({"action": "final", "plan": {"steps": []}})[
        "action"
    ] == "plan"
    tool = _normalize_action_mapping(
        {"action": "call_tool", "name": "capability.search", "args": '{"query":"x"}'}
    )
    assert tool == {
        "action": "tool",
        "tool": "capability.search",
        "arguments": {"query": "x"},
    }


def test_action_from_native_tool_call() -> None:
    action = _action_from_tool_calls(
        [
            {
                "function": {
                    "name": "resource.resolve",
                    "arguments": '{"need":"stock"}',
                }
            }
        ]
    )
    assert action == {
        "action": "tool",
        "tool": "resource.resolve",
        "arguments": {"need": "stock"},
    }


def test_normalize_spec_aliases_and_unknown_keys() -> None:
    normalized = _normalize_spec_payload(
        {
            "goal": "Vender arroz",
            "trigger": "conversation.message",
            "actions": ["catalog.products.search"],
            "state": ["cart"],
            "missing": ["método de pago"],
            "confidence_score": 0.7,
            "unexpected": "drop me",
        }
    )
    assert normalized["trigger_event"] == "conversation.message"
    assert normalized["external_actions"] == ["catalog.products.search"]
    assert normalized["durable_state"] == ["cart"]
    assert normalized["missing_information"] == ["método de pago"]
    assert normalized["confidence"] == 0.7
    assert "unexpected" not in normalized


def test_normalize_plan_aliases() -> None:
    payload = {
        "goal": "Vender arroz",
        "steps": [
            {
                "id": "t1",
                "type": "agent",
                "description": "Atender al cliente",
                "depends": [],
                "params": {"agent_id": "a1"},
            },
            {
                "id": "s1",
                "type": "action",
                "goal": "Buscar producto",
                "dependsOn": ["t1"],
                "params": {"capability_ref": "catalog.products.search"},
            },
        ],
    }
    normalized = _normalize_plan_payload(payload)
    assert normalized is not None
    assert normalized["schema_version"] == "2.0"
    assert normalized["steps"][0]["type"] == "agent_analysis"
    assert normalized["steps"][0]["goal"] == "Atender al cliente"
    assert normalized["steps"][1]["type"] == "capability_call"
    assert normalized["steps"][1]["depends_on"] == ["t1"]
    assert normalized["steps"][1]["params"]["capability"] == "catalog.products.search"


def test_normalize_matches_aliases() -> None:
    matches = _normalize_matches(
        [
            {"need": "catálogo", "capability": "catalog.products.search"},
            {"goal": "stock", "action_id": "inventory.stock.get"},
            {"need": "sin ref"},
        ]
    )
    assert [item["capability_ref"] for item in matches] == [
        "catalog.products.search",
        "inventory.stock.get",
    ]
