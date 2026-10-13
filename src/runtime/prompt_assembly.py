# =============================================================================
# Prompt Assembly — contrato de bloques del prompt (procedencia → trust).
# =============================================================================
# Regla rectora: el contenido entra al prompt con el encabezado de su ORIGEN,
# y la fuente ÚNICA de ese encabezado es el ContextEnvelope
# (`prompt_block_header`). Este módulo no copia contenido: referencia texto ya
# construido y decide orden, encabezado y si el bloque es DATO o INSTRUCCIÓN.
#
# SOLO dos secciones pueden pedir cosas al modelo:
#   - `system_policy`: política del sistema/agente.
#   - `response_contract`: formato de la respuesta pedido por el sistema.
# Todo lo demás (turno del usuario, conversación, memoria, company context,
# evidencia, workflow, observaciones de tools, workspace de razonamiento) es
# DATO: nunca instrucciones, aunque su contenido parezca una orden.
#
# Excepciones documentadas (sin encabezado de origen externo):
#   - `system_policy` / `response_contract`: son la instrucción, no contexto.
#   - `reasoning_workspace`: derivado del propio run, no es contexto de entrada.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from src.runtime.context_envelope import (
    ContextOrigin,
    context_origin,
    prompt_block_header,
)

PROMPT_ASSEMBLY_VERSION = "prompt-assembly-1"

# --- Secciones del prompt ----------------------------------------------------
SYSTEM_POLICY = "system_policy"
USER_TURN = "user_turn"
CONVERSATION = "conversation"
MEMORY = "memory"
COMPANY_CONTEXT = "company_context"
EVIDENCE = "evidence"
WORKFLOW = "workflow"
TOOL_OBSERVATIONS = "tool_observations"
RESPONSE_CONTRACT = "response_contract"
REASONING_WORKSPACE = "reasoning_workspace"

#: Secciones que pueden contener instrucciones para el modelo.
INSTRUCTION_SECTIONS: frozenset[str] = frozenset(
    {SYSTEM_POLICY, RESPONSE_CONTRACT}
)
#: Secciones que son DATO (jamás instrucciones), con su origen canónico.
DATA_SECTIONS: frozenset[str] = frozenset(
    {
        USER_TURN,
        CONVERSATION,
        MEMORY,
        COMPANY_CONTEXT,
        EVIDENCE,
        WORKFLOW,
        TOOL_OBSERVATIONS,
        REASONING_WORKSPACE,
    }
)
#: Secciones que se renderizan sin encabezado de origen (ver cabecera).
HEADERLESS_SECTIONS: frozenset[str] = frozenset(
    {SYSTEM_POLICY, RESPONSE_CONTRACT, REASONING_WORKSPACE}
)
SECTION_ORDER: tuple[str, ...] = (
    SYSTEM_POLICY,
    USER_TURN,
    CONVERSATION,
    MEMORY,
    COMPANY_CONTEXT,
    EVIDENCE,
    WORKFLOW,
    TOOL_OBSERVATIONS,
    RESPONSE_CONTRACT,
    REASONING_WORKSPACE,
)

_SECTION_ORIGIN: dict[str, ContextOrigin] = {
    USER_TURN: ContextOrigin.USER_TURN,
    CONVERSATION: ContextOrigin.CONVERSATION,
    MEMORY: ContextOrigin.MEMORY,
    COMPANY_CONTEXT: ContextOrigin.COMPANY_CONTEXT,
    EVIDENCE: ContextOrigin.EVIDENCE,
    WORKFLOW: ContextOrigin.WORKFLOW,
    TOOL_OBSERVATIONS: ContextOrigin.TOOL_OBSERVATION,
}

#: Orden de los bloques de `request.context` (por procedencia).
CONTEXT_ORIGIN_ORDER: tuple[ContextOrigin, ...] = (
    ContextOrigin.COMPANY_CONTEXT,
    ContextOrigin.MEMORY,
    ContextOrigin.WORKFLOW,
)


@dataclass(frozen=True)
class PromptBlock:
    """Un bloque del prompt: sección, cuerpo y procedencia (si aplica)."""

    section: str
    body: str
    origin: ContextOrigin | None = None

    @property
    def is_instruction(self) -> bool:
        return self.section in INSTRUCTION_SECTIONS

    @property
    def header(self) -> str:
        if self.origin is None or self.section in HEADERLESS_SECTIONS:
            return ""
        return prompt_block_header(self.origin)

    def render(self) -> str:
        header = self.header
        if header:
            return f"{header}:\n{self.body}"
        return self.body


def block(section: str, body: Any) -> PromptBlock:
    """Bloque de una sección con su origen canónico (DATO si no es instrucción)."""
    if section not in INSTRUCTION_SECTIONS and section not in DATA_SECTIONS:
        raise ValueError(f"sección de prompt desconocida: {section}")
    return PromptBlock(
        section=section,
        body=str(body or ""),
        origin=_SECTION_ORIGIN.get(section),
    )


def user_turn_block(body: Any) -> PromptBlock:
    return block(USER_TURN, body)


def conversation_block(body: Any) -> PromptBlock:
    return block(CONVERSATION, body)


def memory_block(body: Any) -> PromptBlock:
    return block(MEMORY, body)


def company_context_block(body: Any) -> PromptBlock:
    return block(COMPANY_CONTEXT, body)


def evidence_block(body: Any) -> PromptBlock:
    return block(EVIDENCE, body)


def workflow_block(body: Any) -> PromptBlock:
    return block(WORKFLOW, body)


def tool_observation_block(body: Any) -> PromptBlock:
    return block(TOOL_OBSERVATIONS, body)


def system_policy_block(body: Any) -> PromptBlock:
    return block(SYSTEM_POLICY, body)


def response_contract_block(body: Any) -> PromptBlock:
    return block(RESPONSE_CONTRACT, body)


def reasoning_workspace_block(body: Any) -> PromptBlock:
    return block(REASONING_WORKSPACE, body)


def _order_index(section: str) -> int:
    return SECTION_ORDER.index(section) if section in SECTION_ORDER else len(
        SECTION_ORDER
    )


def assemble(blocks: Iterable[PromptBlock]) -> str:
    """Renderiza los bloques en el orden canónico, omitiendo vacíos."""
    ordered = sorted(blocks, key=lambda item: _order_index(item.section))
    return "\n\n".join(item.render() for item in ordered if item.body.strip())


@dataclass(frozen=True)
class PromptContext:
    """Contrato del prompt del run: bloques por sección, sin contenido duplicado."""

    blocks: tuple[PromptBlock, ...] = ()
    version: str = PROMPT_ASSEMBLY_VERSION

    def with_block(self, item: PromptBlock) -> "PromptContext":
        return PromptContext(blocks=(*self.blocks, item))

    def section(self, name: str) -> tuple[PromptBlock, ...]:
        return tuple(item for item in self.blocks if item.section == name)

    def data_blocks(self) -> tuple[PromptBlock, ...]:
        return tuple(item for item in self.blocks if not item.is_instruction)

    def instruction_blocks(self) -> tuple[PromptBlock, ...]:
        return tuple(item for item in self.blocks if item.is_instruction)

    def unmarked_data_blocks(self) -> tuple[PromptBlock, ...]:
        """Datos que se renderizarían sin encabezado (deuda, no señal)."""
        return tuple(
            item
            for item in self.data_blocks()
            if not item.header and item.section not in HEADERLESS_SECTIONS
        )

    def violations(self) -> tuple[str, ...]:
        """Invariantes del contrato: datos sin marca y órdenes fuera de política."""
        violations: list[str] = []
        for item in self.unmarked_data_blocks():
            violations.append(f"unmarked_data_block:{item.section}")
        if self.instruction_blocks() and not self.section(SYSTEM_POLICY):
            violations.append("contract_without_system_policy")
        for item in self.blocks:
            if item.section in HEADERLESS_SECTIONS and item.body.strip():
                continue
            if item.section not in SECTION_ORDER:
                violations.append(f"unknown_section:{item.section}")
        return tuple(violations)

    def render(self) -> str:
        return assemble(self.blocks)


def context_blocks(context: Any) -> tuple[PromptBlock, ...]:
    """Bloques de `request.context` agrupados por ORIGEN (sobre).

    `company_context` compilado y memorias llevan su encabezado del sobre; el
    resto es data del negocio (workflow). Todos son DATOS, nunca instrucciones.
    """
    if not isinstance(context, dict):
        return (workflow_block(_json_body(context)),)
    groups: dict[ContextOrigin, dict] = {}
    for key, value in context.items():
        origin = context_origin(str(key))
        groups.setdefault(origin, {})[str(key)] = value
    out: list[PromptBlock] = []
    for origin in CONTEXT_ORIGIN_ORDER:
        group = groups.get(origin)
        if not group:
            continue
        if origin is ContextOrigin.COMPANY_CONTEXT:
            out.append(company_context_block(_json_body(group)))
        elif origin is ContextOrigin.MEMORY:
            out.append(memory_block(_json_body(group)))
        else:
            out.append(workflow_block(_json_body(group)))
    return tuple(out)


def _json_body(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def render_context_blocks(context: Any, *, max_chars: int | None = None) -> str:
    """Contexto del run como bloques con encabezado del sobre (truncable).

    Respeta el orden por procedencia del contexto (company, memory, workflow):
    el orden canónico de secciones aplica al prompt completo, no a este bloque.
    """
    rendered = "\n\n".join(
        item.render() for item in context_blocks(context) if item.body.strip()
    )
    if max_chars is not None and len(rendered) > int(max_chars):
        return rendered[: int(max_chars)] + "...(truncado)"
    return rendered


def narrative_user_prompt(question: str, evidence: str) -> str:
    """Prompt de usuario del fast path narrativo: turno + evidencia (sobre)."""
    return assemble((user_turn_block(question), evidence_block(evidence)))


def prompt_sections() -> dict[str, dict[str, Any]]:
    """Vista pública del contrato (diagnóstico/story)."""
    return {
        section: {
            "instruction": section in INSTRUCTION_SECTIONS,
            "header": (
                ""
                if section in HEADERLESS_SECTIONS
                else prompt_block_header(_SECTION_ORIGIN[section])
                if section in _SECTION_ORIGIN
                else ""
            ),
        }
        for section in SECTION_ORDER
    }


__all__ = [
    "COMPANY_CONTEXT",
    "CONVERSATION",
    "CONTEXT_ORIGIN_ORDER",
    "DATA_SECTIONS",
    "EVIDENCE",
    "HEADERLESS_SECTIONS",
    "INSTRUCTION_SECTIONS",
    "MEMORY",
    "PROMPT_ASSEMBLY_VERSION",
    "PromptBlock",
    "PromptContext",
    "REASONING_WORKSPACE",
    "RESPONSE_CONTRACT",
    "SECTION_ORDER",
    "SYSTEM_POLICY",
    "TOOL_OBSERVATIONS",
    "USER_TURN",
    "WORKFLOW",
    "assemble",
    "block",
    "company_context_block",
    "context_blocks",
    "conversation_block",
    "evidence_block",
    "memory_block",
    "narrative_user_prompt",
    "prompt_sections",
    "reasoning_workspace_block",
    "render_context_blocks",
    "response_contract_block",
    "system_policy_block",
    "tool_observation_block",
    "user_turn_block",
    "workflow_block",
]
