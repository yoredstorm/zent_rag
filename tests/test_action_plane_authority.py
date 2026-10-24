# =============================================================================
# Plano de acción — autorización explícita en toda ejecución.
# =============================================================================
# Contrato (Parte G):
#   * toda ejecución de capability atraviesa autorización; el dispatcher puede
#     delegarla al handler, pero CADA handler declara y verifica su permiso;
#   * un caller nuevo de `run_workflow` sin permisos NO hereda permisos de
#     sistema: el contexto de sistema se declara explícitamente;
#   * los argumentos del modelo no pueden introducir identidad ni permisos.
# =============================================================================
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from src.platform.workflows.engine import (
    SYSTEM_NODE_PERMS,
    resolve_workflow_permissions,
)

ROOT = Path(__file__).resolve().parents[1]

#: Handler del dispatcher -> permiso estático que debe verificar en su cuerpo.
HANDLER_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "_agent_handler": ("agents:execute",),
    "_workflow_handler": ("workflows:run",),
    "_tool_handler": ("agents:execute", "tool.permission"),
}

#: Sitios que ejecutan workflows SIN permisos explícitos: deben declarar
#: `system_context=True` (disparadores internos con autorización propia).
WORKFLOW_SYSTEM_CALLERS: dict[str, int] = {
    # P02 movió schedule/hook/event a ingress.py, que pasa permissions= o
    # system_context de forma explícita. Queda el resume de aprobación.
    "src/platform/workflows/engine.py": 1,
}


def _deps_source() -> str:
    return (ROOT / "src" / "api" / "deps.py").read_text(
        encoding="utf-8", errors="replace"
    )


def _function_body(source: str, name: str) -> str:
    match = re.search(
        rf"\n([ \t]*)(?:async )?def {re.escape(name)}\(", source
    )
    assert match is not None, f"handler {name} no encontrado en deps.py"
    indent = match.group(1)
    rest = source[match.end() :]
    # El cuerpo termina donde aparece el siguiente def al mismo nivel.
    stop = re.search(rf"\n{re.escape(indent)}(?:async )?def ", rest)
    return rest if stop is None else rest[: stop.start()]


def test_handlers_verifican_su_permiso() -> None:
    source = _deps_source()
    for handler, permissions in HANDLER_PERMISSIONS.items():
        body = _function_body(source, handler)
        assert "permission_satisfied(" in body, (
            f"{handler} no verifica permisos: la ejecución quedaría autorizada "
            "solo por el dispatch"
        )
        for permission in permissions:
            assert permission in body, f"{handler} no declara {permission}"


def test_dispatch_no_trata_authorized_ausente_como_autorizado() -> None:
    source = (ROOT / "src" / "runtime" / "dispatcher.py").read_text(
        encoding="utf-8", errors="replace"
    )
    # Un `authorized` presente pero denegado corta antes de ejecutar.
    assert "authorized is not None and not authorized.authorized" in source
    # La ejecución no se condiciona a que `authorized` esté presente: la
    # ausencia delega en el handler, que verifica (contrato de arriba).
    assert "result = await fn(request, decision)" in source


def test_workflow_sin_permisos_es_fail_closed() -> None:
    assert resolve_workflow_permissions(None) == frozenset()
    assert resolve_workflow_permissions(frozenset()) == frozenset()


def test_workflow_contexto_de_sistema_es_explicito() -> None:
    assert resolve_workflow_permissions(None, system_context=True) == SYSTEM_NODE_PERMS
    assert "external_actions:execute" in SYSTEM_NODE_PERMS


def test_workflow_permisos_explicitos_nunca_se_amplian() -> None:
    explicit = frozenset({"workflows:run"})
    assert resolve_workflow_permissions(explicit) == explicit
    assert resolve_workflow_permissions(explicit, system_context=True) == explicit


def test_callers_de_sistema_declaran_system_context() -> None:
    """Todo `run_workflow(` sin `permissions=` declara `system_context=True`."""
    found: dict[str, int] = {}
    offenders: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for match in re.finditer(r"await run_workflow\(", text):
            tail = text[match.end() : match.end() + 1400]
            stop = re.search(r"\n    (?:async )?def |\n\n\n", tail)
            block = tail if stop is None else tail[: stop.start()]
            if "permissions=" in block:
                continue
            found[rel] = found.get(rel, 0) + 1
            if "system_context=True" not in block:
                offenders.append(f"{rel}:{text[:match.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "Callers de run_workflow sin permisos que no declaran contexto de "
        f"sistema (fail-open de permisos): {offenders}"
    )
    assert found == WORKFLOW_SYSTEM_CALLERS, (
        "Cambió el inventario de callers de sistema de workflows.\n"
        f"  esperado: {WORKFLOW_SYSTEM_CALLERS}\n"
        f"  hallado:  {found}"
    )


# -----------------------------------------------------------------------------
# Contrato behavioral (P1-H): la ausencia de `authorized` delega en el handler;
# un `authorized` denegado corta ANTES de ejecutar; un veredicto observacional
# (shadow) no ejecuta. Nada de esto depende de convención.
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_denegado_no_llama_al_handler() -> None:
    from src.core.domain.decision import RoutingDecision
    from src.decision.policy import AuthorizedDecision
    from src.runtime.dispatcher import CapabilityDispatcher, DispatchRequest

    calls: list[str] = []

    async def handler(request, decision):
        calls.append("executed")
        raise AssertionError("un handler denegado no debe ejecutarse")

    dispatcher = CapabilityDispatcher()
    dispatcher.register("agent_runtime", handler)
    decision = RoutingDecision(
        provider="rules",
        resolved=True,
        capability="agent.execute",
        confidence=0.99,
    )
    denied = AuthorizedDecision(
        decision=decision, authorized=False, reason="capability_denied"
    )
    result = await dispatcher.dispatch(
        decision,
        DispatchRequest(
            organization_id=uuid4(),
            user_id=uuid4(),
            role="customer",
            permissions=frozenset(),
            query="q",
        ),
        authorized=denied,
    )
    assert result.status == "denied"
    assert calls == []


@pytest.mark.asyncio
async def test_dispatch_observacional_no_ejecuta() -> None:
    """Un veredicto shadow (`acting=False`) es observación, nunca ejecución."""
    from src.core.domain.decision import RoutingDecision
    from src.runtime.dispatcher import CapabilityDispatcher, DispatchRequest

    calls: list[str] = []

    async def handler(request, decision):
        calls.append("executed")
        raise AssertionError("una decisión observacional no debe ejecutarse")

    dispatcher = CapabilityDispatcher()
    dispatcher.register("agent_runtime", handler)
    decision = RoutingDecision(
        provider="jev",
        resolved=True,
        capability="agent.execute",
        confidence=0.99,
        metadata={"acting": False},
    )
    result = await dispatcher.dispatch(
        decision,
        DispatchRequest(
            organization_id=uuid4(),
            user_id=uuid4(),
            role="customer",
            permissions=frozenset(),
            query="q",
        ),
    )
    assert result.status == "unavailable"
    assert result.error == "decision_is_observational"
    assert calls == []


def test_tool_con_permiso_no_ejecuta_sin_permiso_del_tenant() -> None:
    """Contrato del chat embed (permisos vacíos): una tool privilegiada no corre.

    El handler del dispatcher exige `agents:execute` y `tool.permission`; el
    chat público (rol customer, permissions=frozenset()) no puede ejecutar tools
    con permiso declarado. Es la autorización equivalente del path embed.
    """
    from src.agents.tools.base import Tool, ToolContext
    from src.agents.tools.registry import tool_allowed
    from src.platform.auth.scopes import permission_satisfied

    class PrivilegedTool(Tool):
        name = "marketplace_action"
        description = "efecto externo"
        input_schema: dict = {"type": "object"}
        permission = "external_actions:execute"

        async def execute(self, ctx, arguments):  # pragma: no cover - no corre
            raise AssertionError("no debe ejecutarse")

    tool = PrivilegedTool()
    ctx = ToolContext(tenant_id=uuid4(), role="customer", permissions=frozenset())
    assert permission_satisfied(frozenset(), "agents:execute") is False
    assert tool_allowed(tool, [tool.name], ctx) is False
    authorized_ctx = ToolContext(
        tenant_id=uuid4(),
        role="admin",
        permissions=frozenset({"agents:execute", "external_actions:execute"}),
    )
    assert tool_allowed(tool, [tool.name], authorized_ctx) is True


def test_deep_path_cognitivo_usa_el_tenant_del_run() -> None:
    """La ejecución cognitiva profunda recibe la identidad del run autenticado.

    No hay camino donde el org del DAG provenga del modelo o de un payload: el
    call site pasa la misma variable de organización del turno.
    """
    source = (ROOT / "src" / "agents" / "runtime" / "orchestrator.py").read_text(
        encoding="utf-8", errors="replace"
    )
    marker = "self._run_deep_reasoning("
    assert marker in source
    call = source.split(marker, 1)[1]
    block = call[: call.find(")") + 1]
    assert "organization_id=organization_id" in block, block
    assert "user_id=user_id" in block
    assert "role=role" in block


def test_ejecucion_de_tools_solo_en_guards() -> None:
    """Ratchet: un Tool se ejecuta únicamente por `execute_tool_guarded`.

    `tool.execute(...)` fuera de `src/agents/tools/guards.py` es un bypass del
    contrato MODEL PROPOSES → POLICY AUTHORIZES → RUNTIME EXECUTES: la tool
    corre sin schema, timeout ni rate limit.
    """
    pattern = re.compile(r"\btool\.execute\(")
    found: dict[str, int] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        matches = pattern.findall(path.read_text(encoding="utf-8", errors="replace"))
        if matches:
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            found[rel] = len(matches)
    assert found == {"src/agents/tools/guards.py": 1}, (
        "ejecución de tools fuera del guard de ejecución: "
        f"{found} (esperado únicamente src/agents/tools/guards.py)"
    )
