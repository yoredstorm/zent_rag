# =============================================================================
# Observabilidad de la cadena determinista: build info + mapping de steps
# =============================================================================
# - build_info expone SHA (o BUILD_SHA_UNAVAILABLE), timestamp y versiones de
#   cada motor;
# - cada step nuevo de la cadena determinista tiene mapping canónico (no
#   desaparece ni se cuenta como no mapeado);
# - un tipo desconocido se preserva y se marca unmapped (sección técnica).
# =============================================================================
from __future__ import annotations

from src.runtime.agent_flow import step_to_flow
from src.runtime.build_info import build_info

_DETERMINISTIC_STEP_TYPES = (
    "build",
    "query_semantics",
    "rule_retrieval",
    "rule_evaluation",
    "requirement_graph",
    "premise_closure",
    "grounding",
    "deterministic_operation",
    "derived_claim",
    "answer_state",
    "decision_envelope",
    "derived_guard",
    "finalization",
)


class TestBuildInfo:
    def test_exposes_versions_and_sha_visibility(self) -> None:
        info = build_info()
        assert info["git_sha_display"]
        if not info["git_sha"]:
            assert info["git_sha_display"] == "BUILD_SHA_UNAVAILABLE"
        for key in (
            "rule_retrieval_version",
            "rule_compiler_version",
            "grounding_version",
            "decision_envelope_version",
            "derived_guard_version",
            "deterministic_authority_version",
            "query_semantics_version",
            "rule_evaluation_version",
            "premise_closure_version",
            "query_local_rules_version",
        ):
            assert info.get(key), key


class TestStepMapping:
    def test_every_deterministic_step_is_mapped(self) -> None:
        for step_type in _DETERMINISTIC_STEP_TYPES:
            entry = step_to_flow({"type": step_type, "status": "ok", "detail": "x"})
            assert entry["type"] == step_type
            assert not entry.get("unmapped"), step_type
            assert entry["name"] != step_type, step_type

    def test_unknown_step_is_preserved_as_technical(self) -> None:
        entry = step_to_flow(
            {"type": "paso_futuro", "status": "ok", "payload": {"x": 1}}
        )
        assert entry["unmapped"] is True
        assert entry["payload"] == {"x": 1}
        assert entry["name"] == "paso_futuro"
