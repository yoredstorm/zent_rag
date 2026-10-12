# =============================================================================
# Narrative Fast Path — explicación documental en una generación.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.domain.reasoning import QueryMode
from src.intelligence.reasoning.classifier import deterministic_shape
from src.runtime.deterministic_authority import requires_deterministic_decision

NARRATIVE_FAST_PATH = "NARRATIVE_FAST_PATH"
ROUTE_DETERMINISTIC = "DETERMINISTIC_FAST_PATH"
ROUTE_SCENARIO = "SCENARIO_ANALYSIS"
ROUTE_AGENT = "AGENT"

#: Tiers de modelo. El código decide; el modelo no elige su propio tier.
TIER_FAST = "FAST"
TIER_STANDARD = "STANDARD"
TIER_REASONING = "REASONING"
#: Narrative Fast Path con modelo dedicado de baja latencia.
TIER_FAST_NARRATIVE = TIER_FAST

#: Modo de respuesta documental: sólo evidencia del paquete final.
EVIDENCE_ONLY = "EVIDENCE_ONLY"

VERIFIED_GROUNDED = "VERIFIED_GROUNDED"
PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
UNSUPPORTED = "UNSUPPORTED"
TRUNCATED = "TRUNCATED"
CITATION_ERROR = "CITATION_ERROR"
PARTIALLY_COMPLETE_BUT_GROUNDED = "PARTIALLY_COMPLETE_BUT_GROUNDED"

_FOOTER_RE = re.compile(
    r"(?im)^(?:page\s+\d+|p[aá]gina\s+\d+|confidential|all rights reserved|©.*)$"
)
_META_RE = re.compile(
    r"(?im)^(?:parser_engine|parser_version|bbox|chunk_id|evidence_id)\s*[:=].*$"
)
# Cortesía al arranque («buenas, ¿qué significa X?»): el mensaje completo no es
# la consulta. El modelo reformula la pregunta material antes de buscar.
_CONVERSATIONAL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"hola|buenas(?:\s+(?:tardes|noches|d[ií]as))?|buenos\s+d[ií]as|"
    r"hey|hi|hello|saludos|qu[eé]\s+tal|gracias"
    r")\b",
    re.IGNORECASE,
)

_SOURCE_IDENTITY_KEYS = (
    "organization_id",
    "workspace_id",
    "source_id",
    "document_id",
    "external_id",
    "title",
    "filename",
    "original_filename",
    "page_start",
    "page_end",
    "section_path",
    "parser_engine",
    "parser_version",
    "representation_kind",
    "canonical_evidence_id",
)


@dataclass(frozen=True)
class NarrativeRoute:
    route: str
    eligible: bool
    query_mode: str
    shape: str
    blueprint: str
    reason: str
    jev: str = "skip"
    llm_calls: int = 1

    def to_public_dict(self) -> dict:
        return {
            "route": self.route,
            "mode": self.route,
            "eligible": self.eligible,
            "query_mode": self.query_mode,
            "reasoning_shape": self.shape,
            "blueprint": self.blueprint,
            "reason": self.reason,
            "jev": self.jev,
            "llm_calls": self.llm_calls if self.eligible else 0,
        }


def narrative_route(question: str) -> NarrativeRoute:
    """Código decide la ruta. Fechas en el tópico no activan JEV ni escenario."""
    classification = deterministic_shape(question)
    mode = classification.query_mode
    mode_value = mode.value if mode else ""
    shape = classification.shape.value
    if (
        mode is QueryMode.INFORMATIONAL
        and not classification.scenario_payload
        and not classification.is_complex
    ):
        if _CONVERSATIONAL_PREFIX_RE.search(question or ""):
            # La cortesía no es la consulta: sin ruta narrativa, el agente
            # decide la query material (la intención material manda).
            return NarrativeRoute(
                route=ROUTE_AGENT,
                eligible=False,
                query_mode="INFORMATIONAL",
                shape=shape,
                blueprint="conversational_knowledge",
                reason="conversational_prefix",
                jev="skip",
                llm_calls=0,
            )
        blueprint = (
            "definition_explanation"
            if re.search(r"\bqu[eé]\s+(?:es|significa)\b", question or "", re.I)
            else "technical_explanation"
        )
        return NarrativeRoute(
            route=NARRATIVE_FAST_PATH,
            eligible=True,
            query_mode="INFORMATIONAL",
            shape=shape,
            blueprint=blueprint,
            reason=classification.routing_reason,
            jev="skip",
            llm_calls=1,
        )
    why_case = bool(re.search(r"\bpor\s+qu[eé]\b|\bwhy\s+did\b", question or "", re.I))
    has_mask = bool(re.search(r"[&%#*]{2,}", question or ""))
    has_verdict = bool(re.search(r"\bcumpl\w*", question or "", re.I))
    if why_case and not has_mask and not has_verdict:
        return NarrativeRoute(
            route=ROUTE_SCENARIO,
            eligible=False,
            query_mode=mode_value or "SCENARIO",
            shape=shape,
            blueprint="scenario_analysis",
            reason="why_instance",
            jev="if_material",
            llm_calls=0,
        )
    executable = requires_deterministic_decision(question) or mode is QueryMode.EXECUTABLE
    if executable:
        return NarrativeRoute(
            route=ROUTE_DETERMINISTIC,
            eligible=False,
            query_mode=mode_value or "EXECUTABLE",
            shape=shape,
            blueprint="",
            reason="executable_decision",
            jev="skip",
            llm_calls=0,
        )
    if mode is QueryMode.SCENARIO or (
        classification.is_complex and mode is not QueryMode.INFORMATIONAL
    ):
        return NarrativeRoute(
            route=ROUTE_SCENARIO,
            eligible=False,
            query_mode=mode_value or "SCENARIO",
            shape=shape,
            blueprint="scenario_analysis",
            reason=classification.routing_reason or "scenario_or_complex",
            jev="if_material",
            llm_calls=0,
        )
    return NarrativeRoute(
        route=ROUTE_AGENT,
        eligible=False,
        query_mode=mode_value,
        shape=shape,
        blueprint="",
        reason=classification.routing_reason or "not_informational",
    )


@dataclass(frozen=True)
class GroundedAnswerPolicy:
    """Firewall de conocimiento externo para respuestas documentales.

    En EVIDENCE_ONLY el modelo sólo explica el paquete final de evidencia,
    aplica personalidad, organiza/formatea y declara limitaciones. No agrega
    categorías, reglas ni documentación que la evidencia no contenga.
    """

    mode: str = EVIDENCE_ONLY

    @property
    def evidence_only(self) -> bool:
        return self.mode == EVIDENCE_ONLY

    def instructions(self) -> str:
        if not self.evidence_only:
            return ""
        return _EVIDENCE_ONLY_RULES


def grounded_answer_policy(*, knowledge_question: bool = True) -> GroundedAnswerPolicy:
    """Pregunta documental de conocimiento → EVIDENCE_ONLY. El código decide."""
    return GroundedAnswerPolicy(mode=EVIDENCE_ONLY if knowledge_question else "STANDARD")


_EVIDENCE_ONLY_RULES = (
    "Reglas de grounding documental (obligatorias):\n"
    "- Responde sólo con la información contenida en la evidencia recuperada. "
    "Cita con [Doc: N].\n"
    "- Podés aplicar la personalidad del agente, organizar y formatear, y "
    "declarar limitaciones.\n"
    "- No recomiendes categorías, records, tablas, reglas ni documentos que no "
    "aparezcan en la evidencia.\n"
    "- No sugieras documentación, organismos o proveedores específicos que la "
    "evidencia no mencione; sólo si el usuario pidió consejo general, presentalo "
    "explícitamente como recomendación general.\n"
    "- No agregues reglas de conocimiento propio ni completes huecos con "
    "entrenamiento general.\n"
    "- Interpretá cada aspecto de la pregunta en su sentido material: si la "
    "evidencia lo trata con otra terminología (por ejemplo, campos y overrides "
    "de fecha para «cambio de fechas»), ESA es la respuesta. Explicá lo que la "
    "evidencia sí describe y no conviertas la diferencia de palabras en una "
    "limitación.\n"
    "- La limitación va UNA única vez, en una sola frase al FINAL, y SÓLO si un "
    "aspecto pedido en la pregunta quedó sin ningún respaldo en la evidencia. "
    "Si todos los aspectos pedidos están respaldados, terminá con el contenido: "
    "no agregues advertencia ni nota sobre «otros aspectos no cubiertos». Nunca "
    "encabeza la respuesta, nunca es la «Conclusión» y nunca contradice lo que "
    "la evidencia sí explica.\n"
    "- Si falta un concepto, esa frase final dice que no encontraste respaldo "
    "suficiente en las fuentes para esta ejecución. Nunca afirmes que el "
    "documento o el corpus no contiene el tema.\n"
    "- La sección \"Implicación práctica\" sólo puede aparecer si se deriva "
    "directamente de la evidencia; si es una inferencia, presentala como "
    "\"Inferencia práctica basada en las reglas anteriores…\" y debe ser "
    "sostenible con la evidencia. Sin recomendaciones arbitrarias."
)


@dataclass(frozen=True)
class NarrativeModelPolicy:
    """Modelo de la generación narrativa. Configurable, no silencioso."""

    tier: str
    model: str
    source: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "narrative_model": self.model,
            "narrative_model_tier": self.tier,
            "narrative_model_source": self.source,
        }


def narrative_model_for(
    agent_config: object,
    fallback_model: str = "",
) -> NarrativeModelPolicy:
    """agent.config.narrative_model > modelo del agente.

    No cambia el modelo por su cuenta: si el agente no configura uno, usa el
    modelo elegido por el agente.
    """
    config = agent_config if isinstance(agent_config, dict) else {}
    explicit = str(config.get("narrative_model") or "").strip()
    fallback = str(fallback_model or "").strip()
    if explicit:
        return NarrativeModelPolicy(
            tier=TIER_FAST_NARRATIVE,
            model=explicit,
            source="agent.config.narrative_model",
        )
    return NarrativeModelPolicy(
        tier=TIER_STANDARD,
        model=fallback,
        source="agent.model",
    )


def jev_needed(
    *,
    sufficiency_ambiguous: bool = False,
    conflicts: int = 0,
    blueprint_ambiguous: bool = False,
    authority_uncertain: bool = False,
    query_ambiguous: bool = False,
) -> bool:
    """JEV solo si cambia la respuesta. Mencionar fechas no basta."""
    return bool(
        sufficiency_ambiguous
        or conflicts > 0
        or blueprint_ambiguous
        or authority_uncertain
        or query_ambiguous
    )


def compress_narrative_context(
    blocks: list[str],
    *,
    max_chars: int,
    needles: tuple[str, ...] = (),
    max_block_chars: int = 1600,
) -> str:
    """Contexto de secciones. Sin pies de página, metadata de parser ni headers repetidos.

    Cada bloque se recorta a `max_block_chars` conservando la ventana alrededor
    de lo que la pregunta nombra (`needles`): sin esto, dos o tres fragmentos
    largos consumen el presupuesto y el pasaje que explica el aspecto no entra.
    """
    seen_headers: set[str] = set()
    kept: list[str] = []
    used = 0
    for block in blocks:
        lines: list[str] = []
        for line in str(block or "").splitlines():
            stripped = line.strip()
            if not stripped or _FOOTER_RE.match(stripped) or _META_RE.match(stripped):
                continue
            if stripped.startswith("#"):
                key = stripped.lower()
                if key in seen_headers:
                    continue
                seen_headers.add(key)
            lines.append(stripped)
        piece = "\n".join(lines).strip()
        if not piece:
            continue
        if len(piece) > max_block_chars:
            if needles:
                from src.runtime.evidence import relevance_window

                piece = relevance_window(
                    piece, needles, budget=max_block_chars
                ).strip()
            else:
                piece = piece[:max_block_chars]
        if not piece:
            continue
        if used + len(piece) > max_chars and kept:
            break
        kept.append(piece[: max(0, max_chars - used)])
        used += len(kept[-1])
    return "\n\n".join(kept)


def prompt_char_budget(question: str, *, evidence_items: int, detail: str = "") -> int:
    text = f"{question or ''} {detail or ''}".lower()
    if any(token in text for token in ("en profundidad", "tutorial", "desde cero", "deep")):
        return 16_000
    if evidence_items <= 2 or "en una línea" in text or "breve" in text:
        return 5_000
    return 8_000


def output_token_budget(blueprint: str, *, detail: str = "") -> int:
    """Target de salida. No es el `max_tokens` de la llamada: eso lo corta el ledger."""
    from src.runtime.run_budget import desired_output_token_budget

    return desired_output_token_budget(blueprint, detail=detail)


def completeness_for_finish(finish_reason: str, verification: str) -> tuple[str, str]:
    """Grounding y completeness no se mezclan. Truncado con soporte sigue grounded."""
    truncated = str(finish_reason or "").lower() in {"length", "max_tokens"}
    grounded = verification in {VERIFIED_GROUNDED, "COMPLETE"}
    if truncated and grounded:
        return TRUNCATED, PARTIALLY_COMPLETE_BUT_GROUNDED
    if truncated:
        return TRUNCATED, TRUNCATED
    if grounded:
        return "COMPLETE", VERIFIED_GROUNDED
    return "COMPLETE", verification or PARTIALLY_GROUNDED


def source_identity(metadata: dict | None) -> dict:
    meta = metadata if isinstance(metadata, dict) else {}
    found = {
        key: meta[key]
        for key in _SOURCE_IDENTITY_KEYS
        if meta.get(key) not in (None, "", [], {})
    }
    found["identity_status"] = (
        "OK" if found.get("document_id") or found.get("source_id") else "WEAK"
    )
    return found


def personality_instruction(tone: str = "", instructions: str = "") -> str:
    parts = [
        "Aplica el tono del agente. No cambies hechos, evidencia ni citas."
    ]
    if tone:
        parts.append(f"Tono: {tone}.")
    if instructions:
        parts.append(instructions.strip()[:400])
    return " ".join(parts)


def narrative_frame_lines(concept_plan: object) -> list[str]:
    """Líneas «entidad/aspecto» que la pregunta pide cubrir (puras).

    El prompt las usa para exigir el sentido material de cada aspecto; sin
    frames no se agrega nada.
    """
    lines: list[str] = []
    for frame in getattr(concept_plan, "frames", ()) or ():
        if frame.entity and frame.aspect:
            lines.append(f"- entidad: {frame.entity}; aspecto: {frame.aspect}")
        elif frame.entity:
            lines.append(f"- entidad: {frame.entity}")
        elif frame.aspect:
            lines.append(f"- aspecto: {frame.aspect}")
    return lines


def narrative_context_blocks(active: object, *, question: str) -> list[str]:
    """Bloques `[Doc: N]` del contexto narrativo desde la selección activa.

    Usa el match vigente de cada item (no el contenido suelto): el zip
    items/matches mantiene el contexto alineado.
    """
    from src.knowledge.structure.document_bundle import narrative_context_text

    blocks: list[str] = []
    items = list(getattr(active, "items", ()) or ())
    matches = list(getattr(active, "matches", ()) or ())
    for index, (item, match) in enumerate(zip(items, matches), start=1):
        meta = item.metadata if isinstance(item.metadata, dict) else {}
        text = narrative_context_text(
            question=question,
            canonical=match.content or item.content or "",
            metadata=meta,
        )
        label = item.title or "fuente"
        page = f" pág. {item.page}" if item.page else ""
        blocks.append(f"[Doc: {index}] {label}{page}\n{text}")
    return blocks


def coverage_gap_prompt_note(final_coverage: object) -> str:
    """Nota de aspectos SIN respaldo para el system prompt (texto puro).

    El caller decide cuándo agregarla (solo si hay frase de limitación); acá
    se arma el texto con la terminología del sistema, nunca con la del modelo.
    """
    from src.runtime.narrative_coverage import MISSING, PARTIAL_MATERIAL

    gaps = [
        item.aspect or item.label
        for item in final_coverage or ()
        if item.status in {MISSING, PARTIAL_MATERIAL}
    ]
    return (
        "Aspectos SIN respaldo en la evidencia recuperada: "
        f"{', '.join(gaps) or 'ninguno'}. No los cubras con conocimiento propio "
        "ni los menciones al inicio o en la «Conclusión»: la frase de limitación "
        "la agrega el sistema, una sola vez, al final."
    )


def concept_coverage_rows(final_coverage: object) -> list[dict]:
    """Filas de cobertura por concepto para la traza del fast path."""
    return [
        {
            "id": item.concept_id,
            "label": item.label,
            "status": item.status,
            "epistemic": item.epistemic,
        }
        for item in final_coverage or ()
    ]


def narrative_frame_rows(concept_plan: object) -> list[dict]:
    """Filas de frames (entidad/aspecto/relación) para la traza."""
    return [
        {
            "id": frame.frame_id,
            "entity": frame.entity,
            "aspect": frame.aspect,
            "relation": frame.relation,
        }
        for frame in getattr(concept_plan, "frames", ()) or ()
    ]


def entity_coverage_rows(final_coverage: object) -> list[dict]:
    """Filas de cobertura por entidad (rol QUALIFIER cuando hay aspecto)."""
    from src.runtime.narrative_coverage import QUALIFIER

    return [
        {
            "label": item.entity,
            "status": item.entity_status,
            "role": QUALIFIER if item.aspect else item.role,
        }
        for item in final_coverage or ()
        if item.entity
    ]


def aspect_coverage_rows(final_coverage: object) -> list[dict]:
    """Filas de cobertura por aspecto (status del aspecto o del concepto)."""
    return [
        {
            "label": item.aspect or item.label,
            "status": item.aspect_status or item.status,
            "role": item.role,
        }
        for item in final_coverage or ()
    ]


def final_aspect_statuses(final_coverage: object) -> list[str]:
    """Estados finales por aspecto para la traza (sin inventar)."""
    return [
        item.aspect_status or item.status for item in final_coverage or ()
    ]


def fast_path_overrun(overrun: dict, *, max_tokens: int) -> tuple[bool, str]:
    """¿El cierre narrativo se pasó del ledger? (tolerancia explícita).

    Devuelve `(large_overrun, stop_reason)`: razón de corte vacía si no hay
    corte. El costo manda sobre tokens cuando ambos se pasaron.
    """
    from src.runtime.run_budget import COST_BUDGET, TOKEN_BUDGET

    tolerance = max(128, int(max_tokens or 0) // 50)
    token_over = int((overrun or {}).get("token_overrun") or 0)
    cost_over = float((overrun or {}).get("cost_overrun_usd") or 0)
    if token_over > tolerance or cost_over > 0.01:
        return True, COST_BUDGET if cost_over > 0.01 else TOKEN_BUDGET
    return False, ""


def patch_narrative_verification(
    steps: list[dict], *, finish_reason: str, completeness: str
) -> None:
    """Completa el `verification_input` del step narrative_evidence (in place).

    Sin step no hace nada: la traza es observacional, nunca rompe el cierre.
    """
    for step in reversed(steps or []):
        if step.get("type") != "narrative_evidence":
            continue
        recorded = step.get("verification_input")
        if isinstance(recorded, dict):
            recorded["finish_reason"] = finish_reason
            recorded["completeness"] = completeness
            recorded["truncated"] = finish_reason.lower() in {"length", "max_tokens"}
        break


def mark_partial_grounded(steps: list[dict], gap_items: object) -> bool:
    """Marca PARTIAL_GROUNDED y agrega los gaps como UNSUPPORTED (in place).

    Devuelve True si aplicó (encontró el step de verificación).
    """
    for step in reversed(steps or []):
        recorded = (
            step.get("verification_input")
            if step.get("type") == "narrative_evidence"
            else None
        )
        if not isinstance(recorded, dict):
            continue
        supports = list(recorded.get("supports") or [])
        for item in gap_items or ():
            supports.append(
                {
                    "claim": item.aspect or item.label,
                    "status": "UNSUPPORTED",
                    "doc_number": None,
                    "evidence_id": "",
                }
            )
        recorded["supports"] = supports
        recorded["verification"] = "PARTIAL"
        recorded["grounding"] = "PARTIAL"
        return True
    return False
