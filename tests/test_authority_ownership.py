# =============================================================================
# Authority Ownership Ratchets — dueño único de cada estado crítico del run.
# =============================================================================
# Regla: cada hecho mutable crítico del run tiene UN writer lógico (o un reducer
# explícito y testeado). Este test es el contrato estructural: si aparece un
# writer nuevo, un bypass de autoridad o un `ToolContext` construido con
# identidad no confiable, CI falla ANTES de que el cambio llegue a producción.
#
# Las tablas de abajo están fijadas al estado real del repo (medido, no
# aspiracional). Bajar un número es el trabajo pendiente; subirlo exige
# justificación escrita acá y en docs/architecture/ownership/.
#
# Familias:
#   phase_writes ............ escritores de `RunPhase` del run.
#   result_totals ........... escritores de los totales de costo/tokens.
#   answer_writes ........... escritores de la vista de respuesta.
#   decision_writes ......... escritores del estado de decisión.
#   authority_flag_writes ... escritores de los flags de autoridad determinista.
#   terminal_mapper ......... llamadas a `terminal_phase_for` (mapper de cierre).
#   tool_context ............ construcciones de ToolContext (frontera de confianza).
# =============================================================================
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# -----------------------------------------------------------------------------
# Patrones (todos con lookahead negativo para no capturar comparaciones `==`).
# -----------------------------------------------------------------------------
_PATTERNS: dict[str, re.Pattern[str]] = {
    "phase_writes": re.compile(r"\.phase\s*=\s*"),
    "result_totals": re.compile(
        r"\bresult\.(cost|total_tokens|prompt_tokens|completion_tokens|"
        r"embedding_tokens|cost_status)\s*(\+=|=)(?!=)"
    ),
    "answer_writes": re.compile(
        r"state\.answer\.(text|status|answer_state|citations)\s*="
    ),
    "decision_writes": re.compile(
        r"\.decisions\.(final_state|finalization|envelope|envelope_public)\s*="
    ),
    "authority_flag_writes": re.compile(
        r"\.decisions\.(requires_deterministic|external_authority)\s*="
    ),
    "terminal_mapper": re.compile(r"terminal_phase_for\("),
    "closure_writes": re.compile(r"\.closure\s*="),
}

# -----------------------------------------------------------------------------
# Allowlists: archivo -> (cantidad, justificación).
# -----------------------------------------------------------------------------
PHASE_WRITES: dict[str, tuple[int, str]] = {
    "src/runtime/run_state.py": (
        6,
        "Autoridad de fase: `try_advance` (no terminal), `_apply_terminal` "
        "(aplicador único, privado) y las comparaciones `self.phase == ...` de "
        "los invariantes. Desde la fase de hardening los terminales NO se "
        "alcanzan por try_advance: solo el aplicador canónico los asigna.",
    ),
    "src/agents/runtime/agent_runtime.py": (
        1,
        "Comparación `state.phase == RunPhase.FINALIZED` del bloqueo estricto. "
        "La asignación terminal se rutea por `apply_closure_override` "
        "(`strict_block`), restringido a fases no-concluyentes.",
    ),
    "src/decision/preflight.py": (
        1,
        "Preflight de decisión: compara la fase del run de conversación "
        "canónica del motor de decisión (`pack.phase == phase`), no la del AgentRun.",
    ),
}

RESULT_TOTALS: dict[str, tuple[int, str]] = {
    "src/runtime/run_budget.py": (
        10,
        "RunBudgetLedger: escritura canónica de totales (account_llm_usage, "
        "account_embedding_usage, account_judge_usage, account_charge). Los hits "
        "son la implementación de la autoridad, no writers competidores.",
    ),
    "src/runtime/run_accounting.py": (
        4,
        "Solo `cost_status` (procedencia del precio). Los totales del run y del "
        "juez pasan por el ledger desde S5: el juez ya no escribe tokens acá.",
    ),
    "src/runtime/answer_gate.py": (
        2,
        "`AnswerGateResult` (no el run): el gate guarda el usage del juez en su "
        "propio veredicto. No es un writer de los totales del run; el patrón "
        "matchea porque el objeto local se llama `result`. Documentado para que "
        "un writer real del run acá rompa CI con revisión.",
    ),
}

ANSWER_WRITES: dict[str, tuple[int, str]] = {
    "src/runtime/run_state.py": (
        4,
        "finalize_state: writer canónico del cierre (text/status/answer_state/"
        "citations).",
    ),
    "src/agents/runtime/agent_runtime.py": (
        2,
        "strict fail-closed: reemplaza el texto por el mensaje no concluyente. "
        "Solo actúa con el modo estricto encendido; debe consumir la resolución "
        "de la política (S2/S3).",
    ),
}

DECISION_WRITES: dict[str, tuple[int, str]] = {
    "src/runtime/run_state.py": (
        1,
        "finalize_state: fija decisions.final_state desde el answer_state. Deuda "
        "P0 (S2): la fase terminal debe derivarse del envelope, no del texto.",
    ),
    "src/runtime/finalization_policy.py": (
        1,
        "resolve_closure publica la resolución de la política. Es el writer "
        "lógico del estado de decisión de cierre.",
    ),
}

AUTHORITY_FLAG_WRITES: dict[str, tuple[int, str]] = {
    "src/agents/runtime/orchestrator.py": (
        2,
        "Deuda P0 (S2/S3): escritura directa de requires_deterministic en el "
        "camino RAG (y en la proyección de cierre). Debe pasar por "
        "observe_prep/observe_external_authority y bajar a 0.",
    ),
}

TERMINAL_MAPPER: dict[str, tuple[int, str]] = {
    "src/runtime/run_state.py": (
        2,
        "Definición del mapper + la llamada de respaldo en `finish()` cuando el "
        "caller no pasa `oracle_phase`. `finish()` sin `phase_override` NO usa "
        "el mapper como autoridad: aplica FAILED (`closure_authority_missing`).",
    ),
    "src/runtime/finalization_policy.py": (
        2,
        "Oráculo legacy dentro de `resolve_closure_phase` y en la resolución de "
        "fallo `closure_authority_failure`: la divergencia contra la resolución "
        "es un invariante crítico, nunca la fuente de la fase.",
    ),
}

#: Escritor del campo de resolución del cierre (`DecisionState.closure`).
CLOSURE_WRITES: dict[str, tuple[int, str]] = {
    "src/runtime/run_state.py": (
        1,
        "`DecisionState.observe_closure` es el escritor único del campo `closure`; "
        "el reducer vive en `finalization_policy.resolve_closure_phase`.",
    ),
}

#: ToolContext: frontera de confianza. Solo puede construirse en estos sitios,
#: y `tenant_id` debe venir de un atributo de un objeto confiable (nunca de
#: argumentos, dicts ni literales).
TOOL_CONTEXT_SITES: dict[str, int] = {
    "src/agents/runtime/agent_runtime.py": 1,
    "src/api/deps.py": 1,
}

#: Estados críticos -> autoridad canónica (símbolo que debe existir).
#: El mapa vivo vive en docs/architecture/ownership/01-ownership-map-before.md.
AUTHORITY_REGISTRY: dict[str, tuple[str, str]] = {
    "terminal_phase": ("src.runtime.finalization_policy", "evaluate_finalization"),
    "finalization_contract": ("src.runtime.decision_envelope", "DecisionEnvelope"),
    "run_state": ("src.runtime.run_state", "AgentRunState"),
    "cost_totals": ("src.runtime.run_budget", "RunBudgetLedger"),
    "accounting_recorder": ("src.runtime.run_accounting", "record_llm_call"),
    "evidence_measure": ("src.runtime.evidence", "assess_sufficiency"),
    "tool_authorization": ("src.agents.tools.registry", "tool_allowed"),
    "tool_execution": ("src.agents.tools.guards", "execute_tool_guarded"),
    "trusted_context": ("src.core.domain.entities", "TenantContext"),
    "knowledge_scope": ("src.core.domain.knowledge_scope", "KnowledgeScope"),
    "failure_classification": ("src.runtime.failure_taxonomy", "classify_failure"),
    "answer_state_vocabulary": ("src.runtime.answer_state", "select_answer_state"),
    "run_guards": ("src.runtime.run_guards", "evaluate_transition"),
    "enforcement_stages": ("src.runtime.enforcement", "enforcement_stages"),
}


#: Autoridades añadidas por la fase de convergencia y por el hardening de
#: autoridad: deben existir y estar declaradas en el mapa AFTER
#: (05-ownership-map-after.md).
POST_PHASE_AUTHORITIES: dict[str, tuple[str, str]] = {
    "closure_resolution": (
        "src.runtime.finalization_policy",
        "resolve_closure_phase",
    ),
    "evidence_condition": (
        "src.runtime.evidence_semantics",
        "classify_evidence_condition",
    ),
    "workflow_permissions": (
        "src.platform.workflows.engine",
        "resolve_workflow_permissions",
    ),
    # Hardening H0–H9 (ver 08-hardening-report.md)
    "closure_failure_resolution": (
        "src.runtime.finalization_policy",
        "closure_authority_failure",
    ),
    "authorization_matrix": (
        "src.decision.preflight",
        "resolve_authorization",
    ),
    "shadow_authority": (
        "src.decision.settings",
        "DecisionEngineSettings",
    ),
    "safety_floor": (
        "src.runtime.run_state",
        "strict_mode_enabled",
    ),
    "terminal_application": (
        "src.runtime.run_state",
        "AgentRunState",
    ),
    "config_validation": (
        "src.core.config_rules",
        "assert_runtime_config",
    ),
    "guard_classification": (
        "src.runtime.run_guards",
        "GUARD_CLASS",
    ),
}


def _src_files() -> list[Path]:
    return [
        path
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts and not path.name.startswith("test_")
    ]


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _counts(pattern: re.Pattern[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in _src_files():
        found = len(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
        if found:
            counts[_rel(path)] = found
    return dict(counts)


def _expanded(allowlist: dict[str, tuple[int, str]]) -> dict[str, int]:
    return {path: count for path, (count, _) in allowlist.items()}


def _assert_family(
    family: str, allowlist: dict[str, tuple[int, str]], pattern: re.Pattern[str]
) -> None:
    found = _counts(pattern)
    expected = _expanded(allowlist)
    assert found == expected, (
        f"{family}: writers fuera de la allowlist de autoridad.\n"
        f"  esperado: {expected}\n"
        f"  hallado:  {found}\n"
        "Un estado crítico nuevo con más de un writer exige reducer explícito "
        "y justificación en tests/test_authority_ownership.py + "
        "docs/architecture/ownership/."
    )


# -----------------------------------------------------------------------------
# Ratchets por familia.
# -----------------------------------------------------------------------------
def test_phase_writers_match_allowlist() -> None:
    _assert_family("phase_writes", PHASE_WRITES, _PATTERNS["phase_writes"])


def test_cost_total_writers_match_allowlist() -> None:
    _assert_family("result_totals", RESULT_TOTALS, _PATTERNS["result_totals"])


def test_answer_writers_match_allowlist() -> None:
    _assert_family("answer_writes", ANSWER_WRITES, _PATTERNS["answer_writes"])


def test_decision_writers_match_allowlist() -> None:
    _assert_family(
        "decision_writes", DECISION_WRITES, _PATTERNS["decision_writes"]
    )


def test_authority_flag_writers_match_allowlist() -> None:
    _assert_family(
        "authority_flag_writes",
        AUTHORITY_FLAG_WRITES,
        _PATTERNS["authority_flag_writes"],
    )


def test_terminal_mapper_call_sites_match_allowlist() -> None:
    _assert_family(
        "terminal_mapper", TERMINAL_MAPPER, _PATTERNS["terminal_mapper"]
    )


def test_closure_writers_match_allowlist() -> None:
    _assert_family("closure_writes", CLOSURE_WRITES, _PATTERNS["closure_writes"])


def test_allowlists_declaran_justificacion() -> None:
    for family, allowlist in (
        ("phase_writes", PHASE_WRITES),
        ("result_totals", RESULT_TOTALS),
        ("answer_writes", ANSWER_WRITES),
        ("decision_writes", DECISION_WRITES),
        ("authority_flag_writes", AUTHORITY_FLAG_WRITES),
        ("terminal_mapper", TERMINAL_MAPPER),
        ("closure_writes", CLOSURE_WRITES),
    ):
        assert allowlist, f"{family}: allowlist vacía"
        for path, (count, justification) in allowlist.items():
            assert count >= 1, f"{family}/{path}: cantidad inválida"
            assert (ROOT / path).exists(), f"{family}/{path}: archivo inexistente"
            assert len(justification.strip()) >= 40, (
                f"{family}/{path}: la justificación debe explicar el writer y "
                "su condición de retiro (deuda rastreada)."
            )


# -----------------------------------------------------------------------------
# Frontera de confianza: ToolContext.
# -----------------------------------------------------------------------------
def _tool_context_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else ""
            )
            if name == "ToolContext":
                calls.append(node)
    return calls


def test_tool_context_construido_solo_en_sitios_declarados() -> None:
    found: dict[str, int] = {}
    for path in _src_files():
        calls = _tool_context_calls(path)
        if calls:
            found[_rel(path)] = len(calls)
    assert found == TOOL_CONTEXT_SITES, (
        "ToolContext es la frontera de confianza: construirlo fuera de los "
        "sitios declarados puede introducir identidad no confiable.\n"
        f"  esperado: {TOOL_CONTEXT_SITES}\n"
        f"  hallado:  {found}"
    )


def test_tool_context_tenant_id_viene_de_atributo_confiable() -> None:
    """tenant_id debe ser un atributo de un objeto confiable.

    Prohibido: dict/args (`data["organization_id"]`, `args.get(...)`),
    literales, llamadas. Permitido: `agent.organization_id`,
    `request.organization_id`, `ctx.tenant_id`.
    """
    offenders: list[str] = []
    for rel_path in TOOL_CONTEXT_SITES:
        path = ROOT / rel_path
        for call in _tool_context_calls(path):
            for keyword in call.keywords:
                if keyword.arg != "tenant_id":
                    continue
                if not isinstance(keyword.value, ast.Attribute):
                    offenders.append(
                        f"{rel_path}:{call.lineno} tenant_id no es atributo "
                        f"({ast.dump(keyword.value)[:80]})"
                    )
                elif keyword.value.attr not in {
                    "organization_id",
                    "tenant_id",
                }:
                    offenders.append(
                        f"{rel_path}:{call.lineno} tenant_id desde "
                        f"`{keyword.value.attr}`, no desde la identidad "
                        "confiable"
                    )
    assert not offenders, "\n".join(offenders)


# -----------------------------------------------------------------------------
# Registro de autoridad: cada estado crítico declara su autoridad y existe.
# -----------------------------------------------------------------------------
def test_authority_registry_symbols_exist() -> None:
    import importlib

    missing: list[str] = []
    for state, (module_name, symbol) in AUTHORITY_REGISTRY.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — el test debe explicar el fallo
            missing.append(f"{state}: import {module_name} falló ({exc})")
            continue
        if not hasattr(module, symbol):
            missing.append(f"{state}: {module_name}.{symbol} no existe")
    assert not missing, "\n".join(missing)


def test_authority_registry_declara_estados_criticos() -> None:
    required = {
        "terminal_phase",
        "finalization_contract",
        "run_state",
        "cost_totals",
        "evidence_measure",
        "tool_authorization",
        "tool_execution",
        "trusted_context",
        "knowledge_scope",
        "failure_classification",
        "answer_state_vocabulary",
        "run_guards",
        "enforcement_stages",
    }
    assert required <= set(AUTHORITY_REGISTRY), (
        "El registro de autoridad perdió estados críticos: "
        f"{sorted(required - set(AUTHORITY_REGISTRY))}"
    )


# -----------------------------------------------------------------------------
# El mapa de ownership es parte del contrato: si el registro gana un estado,
# el documento tiene que declararlo en el mismo commit.
# -----------------------------------------------------------------------------
def test_ownership_map_declara_el_registro() -> None:
    ownership = ROOT / "docs" / "architecture" / "ownership"
    map_doc = ownership / "01-ownership-map-before.md"
    baseline_doc = ownership / "00-baseline.md"
    duplicates_doc = ownership / "02-duplicated-authorities.md"
    adr_doc = ownership / "03-adr-decisions.md"
    after_doc = ownership / "05-ownership-map-after.md"
    report_doc = ownership / "06-final-report.md"
    missing = [
        path.name
        for path in (
            map_doc,
            baseline_doc,
            duplicates_doc,
            adr_doc,
            after_doc,
            report_doc,
        )
        if not path.exists()
    ]
    assert not missing, f"documentos de ownership faltantes: {missing}"

    baseline_text = baseline_doc.read_text(encoding="utf-8")
    assert "5cd3dec1812955c28dd6ce338f56322022a2079c" in baseline_text, (
        "00-baseline.md debe declarar el BASELINE_SHA verificado con CI verde"
    )

    map_text = map_doc.read_text(encoding="utf-8")
    absent = [state for state in AUTHORITY_REGISTRY if state not in map_text]
    assert not absent, (
        "01-ownership-map-before.md no declara estos estados críticos del "
        f"registro: {absent}"
    )
    assert "tests/test_authority_ownership.py" in map_text, (
        "el mapa debe referenciar el ratchet que lo protege"
    )

    after_text = after_doc.read_text(encoding="utf-8")
    absent_after = [
        state for state in POST_PHASE_AUTHORITIES if state not in after_text
    ]
    assert not absent_after, (
        "05-ownership-map-after.md no declara las autoridades de la fase: "
        f"{absent_after}"
    )


def test_post_phase_authorities_exist() -> None:
    import importlib

    missing: list[str] = []
    for state, (module_name, symbol) in POST_PHASE_AUTHORITIES.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — el test debe explicar el fallo
            missing.append(f"{state}: import {module_name} falló ({exc})")
            continue
        if not hasattr(module, symbol):
            missing.append(f"{state}: {module_name}.{symbol} no existe")
    assert not missing, "\n".join(missing)

