# =============================================================================
# Failure taxonomy — clasificación única y contrato de reason codes (F6).
# =============================================================================
# Reglas verificadas acá:
#   - todo el vocabulario cerrado (reason codes, stop reasons, answer states,
#     status de intento de provider) está clasificado o es explícitamente una
#     señal de control (None);
#   - prohibido mezclar realidades: provider timeout != evidencia insuficiente;
#     permiso denegado != tool fallida; retrieval caído != «no hay información»;
#   - un `reason_code` literal emitido en el runtime pertenece al catálogo
#     (`reason-codes-1`): un código nuevo rompe CI.
from __future__ import annotations

import re
from pathlib import Path

from src.runtime import reason_codes as rc
from src.runtime.answer_state import (
    ABSTAINED_STATES,
    OPERATIONAL_FAILURE_STATES,
    UNDETERMINED_STATES,
)
from src.runtime.failure_taxonomy import (
    FAILURE_TAXONOMY_VERSION,
    FailureClass,
    classify_answer_state,
    classify_provider_attempt,
    classify_reason_code,
    classify_stop_reason,
)
from src.runtime.run_budget import STOP_REASONS

ROOT = Path(__file__).resolve().parents[1]

#: Módulos que EMITEN reason_code (contrato del catálogo).
_RUNTIME_PATHS = (
    ROOT / "src" / "runtime",
    ROOT / "src" / "agents" / "runtime",
)

#: `reason_code="X"` / `"reason_code": "X"` — el literal debe ser del catálogo.
_REASON_CODE_LITERAL = re.compile(
    r"reason_code[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_]+)[\"']"
)


class TestCoberturaDelVocabulario:
    def test_version(self) -> None:
        assert FAILURE_TAXONOMY_VERSION == "failure-taxonomy-1"

    def test_stop_reasons_clasificados(self) -> None:
        for code in sorted(STOP_REASONS):
            info = classify_stop_reason(code)
            assert info is not None, code
            assert info.reason_code == code

    def test_estados_de_respuesta_clasificados(self) -> None:
        for state in sorted(
            OPERATIONAL_FAILURE_STATES | ABSTAINED_STATES | UNDETERMINED_STATES
        ):
            assert classify_answer_state(state) is not None, state

    def test_todo_el_vocabulario_de_answer_state_cubierto(self) -> None:
        """Cada ANSWER_STATE_* es un fallo clasificado o el resultado derivado."""
        from src.runtime import answer_state

        for name, value in vars(answer_state).items():
            if not name.startswith("ANSWER_STATE_") or not isinstance(value, str):
                continue
            if value == answer_state.ANSWER_STATE_DERIVED:
                assert classify_answer_state(value) is None
                continue
            assert classify_answer_state(value) is not None, value

    def test_status_de_intento_de_provider_clasificados(self) -> None:
        for status in (
            "rate_limited",
            "timeout",
            "circuit_open",
            "auth_error",
            "provider_error",
            "error",
        ):
            assert classify_provider_attempt(status) is not None, status
        assert classify_provider_attempt("success") is None

    def test_reason_codes_conocidos_y_señales_de_control(self) -> None:
        # Los códigos de fallo están clasificados...
        for code in (
            rc.RETRIEVAL_UNAVAILABLE,
            rc.BUDGET_EXHAUSTED,
            rc.EVIDENCE_INSUFFICIENT,
            rc.TOOL_NOT_AUTHORIZED,
            rc.AUTHORITY_MISSING_FOR_EXECUTABLE,
        ):
            assert classify_reason_code(code) is not None, code
        # ...y las señales de control no son fallos.
        for code in (
            rc.READY,
            rc.NEED_DRAFT,
            rc.TOOL_AUTHORIZED,
            rc.RETRIEVAL_ALLOWED,
            rc.READY_TO_FINALIZE,
            rc.ANALYSIS_INCOMPLETE,
            rc.REASONING_INCOMPLETE,
            rc.TERMINATION_SATISFIED,
        ):
            assert classify_reason_code(code) is None, code

    def test_desconocido_no_se_inventa(self) -> None:
        assert classify_reason_code("NOPE_NEW_CODE") is None
        assert classify_stop_reason("NOPE") is None
        assert classify_answer_state("NOPE") is None


class TestNoMezclaDeRealidades:
    def test_retrieval_caido_no_es_evidencia_insuficiente(self) -> None:
        failed = classify_answer_state("RETRIEVAL_UNAVAILABLE")
        insufficient = classify_answer_state("INSUFFICIENT_EVIDENCE")
        assert failed.failure_class is FailureClass.RETRIEVAL_FAILURE
        assert failed.operational is True
        assert insufficient.failure_class is FailureClass.EVIDENCE_INSUFFICIENT
        assert insufficient.operational is False

    def test_permiso_denegado_no_es_tool_fallida(self) -> None:
        denied = classify_reason_code("TOOL_NOT_AUTHORIZED")
        tool_failed = classify_reason_code("TOOL_FAILED_PERMANENT_NO_RETRY")
        assert denied.failure_class is FailureClass.AUTHORIZATION_ERROR
        assert denied.user_visible is False
        assert tool_failed.failure_class is FailureClass.DEPENDENCY_ERROR

    def test_timeout_de_provider_no_es_evidencia(self) -> None:
        timeout = classify_provider_attempt("timeout")
        assert timeout.failure_class is FailureClass.TIMEOUT
        assert timeout.operational is True

    def test_rate_limit_no_es_fallo_de_provider_generico(self) -> None:
        rate = classify_stop_reason("PROVIDER_RATE_LIMIT")
        failure = classify_stop_reason("PROVIDER_FAILURE")
        assert rate.failure_class is FailureClass.RATE_LIMIT
        assert failure.failure_class is FailureClass.PROVIDER_FAILURE

    def test_autoridad_ausente_no_es_evidencia(self) -> None:
        missing = classify_reason_code("AUTHORITY_MISSING_FOR_EXECUTABLE")
        assert missing.failure_class is FailureClass.AUTHORITY_MISSING
        assert missing.operational is False


class TestContratoDeReasonCodesEnElRuntime:
    def test_literales_emitidos_pertenecen_al_catalogo(self) -> None:
        offenders: list[str] = []
        for base in _RUNTIME_PATHS:
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    for match in _REASON_CODE_LITERAL.finditer(line):
                        code = match.group(1)
                        if not rc.is_known_reason_code(code):
                            offenders.append(
                                f"{path.relative_to(ROOT)}:{number}: {code}"
                            )
        assert not offenders, (
            "reason_code fuera del catálogo (reason-codes-1): registrarlo en "
            f"src/runtime/reason_codes.py o corregir el emisor: {offenders}"
        )

    def test_catalogo_sin_strings_paralelos(self) -> None:
        # Un mismo concepto no puede tener dos formas (mayúsculas/minúsculas).
        lowered: dict[str, str] = {}
        for code in sorted(rc.ALL_REASON_CODES):
            key = code.lower()
            assert key not in lowered, f"{code} duplica {lowered[key]}"
            lowered[key] = code
