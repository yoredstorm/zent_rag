# =============================================================================
# Finalizer — cierre del run: presupuesto, prompt y entrega final.
# =============================================================================
# El finalizer NO decide si el run puede finalizar (eso es FinalizationPolicy).
# Construye la respuesta final con parámetros explícitos y una sola fuente de
# presupuesto (RunBudgetLedger). La contabilidad sigue en `run_accounting`.
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# --- Parseo de la respuesta final del modelo (JSON o prosa) -------------------
_ANSWER_FIELD_RE = re.compile(r'"answer"\s*:\s*"', re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
}


def decode_json_string(body: str) -> str:
    """Deshace los escapes del campo `answer`. Corta en la comilla sin escapar."""
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            if nxt == "u":
                hexpart = body[index + 2 : index + 6]
                if len(hexpart) == 4 and all(
                    c in "0123456789abcdefABCDEF" for c in hexpart
                ):
                    out.append(chr(int(hexpart, 16)))
                    index += 6
                    continue
                break  # escape cortado por truncamiento
            out.append(_JSON_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        if char == "\\":
            break  # barra final: escape cortado por truncamiento
        if char == '"':
            break
        out.append(char)
        index += 1
    return "".join(out).strip()


def salvage_answer(content: str) -> str | None:
    """Rescata el texto de `"answer": "…"` cuando el JSON no se pudo parsear.

    Pasa cuando la generación se corta por tokens: el envoltorio queda abierto y,
    sin esto, el usuario vería el JSON crudo. Determinista: sólo deshace los
    escapes del propio campo, no inventa texto.
    """
    match = _ANSWER_FIELD_RE.search(content or "")
    if match is None:
        return None
    salvaged = decode_json_string(content[match.end() :])
    return salvaged or None


def looks_like_envelope(text: str) -> bool:
    """El texto es (o intenta ser) el envoltorio `{"answer": "…"}`, no prosa."""
    body = text.lstrip("`").lstrip()
    return body.startswith("{") and _ANSWER_FIELD_RE.search(text) is not None


def tool_shaped(text: str) -> bool:
    """JSON de tool que no parseó (p.ej. ``top_k: III``). No es respuesta."""
    body = (text or "").strip()
    return body.startswith("{") and '"tool"' in body


def parse_action(content: str) -> dict:
    """Extrae el primer objeto JSON válido de la respuesta del LLM.

    Fallback: respuesta sin JSON se trata como answer directa; un envoltorio
    truncado se rescata campo por campo para no mostrar JSON al usuario.
    """
    text = (content or "").strip()
    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    if looks_like_envelope(text):
        salvaged = salvage_answer(text)
        if salvaged:
            logger.warning("answer JSON malformed or truncated; salvaged text field")
            return {"answer": salvaged}
    return {"answer": text}


def clean_answer(answer: str, *, titles: Any = ()) -> str:
    """Higiene del texto final: rótulos internos, escapes y bloque de fuentes.

    El prompt de composición no nombra las secciones ni pide una lista de
    fuentes; esto cubre prompts viejos, modelos que igual los copian y respuestas
    en caché. Se registra porque no es silencioso: cambia el texto que ve el usuario.
    """
    try:
        from src.infrastructure.observability.metrics import (
            zent_response_section_labels_stripped_total,
        )
        from src.intelligence.response.contract import normalize_answer_text

        hygiene = normalize_answer_text(answer, titles=titles)
        if hygiene.changed:
            if hygiene.labels_stripped:
                zent_response_section_labels_stripped_total.inc(
                    hygiene.labels_stripped
                )
            logger.warning(
                "answer text normalized",
                labels_stripped=hygiene.labels_stripped,
                markdown_escapes_fixed=hygiene.markdown_escapes_fixed,
                sources_normalized=hygiene.sources_normalized,
                answer_chars=len(answer),
            )
        return hygiene.text
    except Exception as exc:  # noqa: BLE001 — la respuesta nunca se rompe por esto
        logger.warning("answer cleanup failed", error=str(exc)[:150])
        return answer


def direct_answer(action: dict) -> str | None:
    """Texto final para el usuario. None si es una llamada a tool."""
    if action.get("tool"):
        return None
    answer = action.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    if tool_shaped(answer):
        return None
    return clean_answer(answer)


def parse_finalize_answer(content: str) -> str | None:
    """Respuesta final del cierre: None = no hay texto entregable."""
    return direct_answer(parse_action(content))


def fact_check_enabled(settings: Any) -> bool:
    """Chequeo determinista de figuras encendido (default on)."""
    return str(
        getattr(settings, "RUNTIME_ANSWER_FACT_CHECK", "on") or "on"
    ).strip().lower() not in {"off", "0", "false", "no"}


def figure_check(answer: str, history: list[str], question: str) -> list[str]:
    """Figuras/fechas del texto que la evidencia del run no contiene (sin LLM)."""
    from src.intelligence.response.entities import ungrounded_figures

    return list(ungrounded_figures(answer, "\n".join(history or ()), question) or ())


def figures_revision_step(figures: list[str]) -> dict:
    """Step `answer_revision` por figuras sin respaldo (mismo formato)."""
    return {
        "type": "answer_revision",
        "detail": f"figuras sin respaldo: {', '.join(figures[:5])}",
        "figures": figures[:5],
    }


def figures_feedback_note(figures: list[str]) -> str:
    """Observación untrusted con la corrección pedida al modelo."""
    from src.intelligence.response.entities import figures_note

    return f"OBSERVATION (untrusted): {figures_note(figures)}"


@dataclass(frozen=True)
class FinalizeBudget:
    """Presupuesto aprobado para la llamada de cierre."""

    ledger: object
    max_tokens: int
    call_plan: object


async def plan_finalize_budget(
    result: object,
    config: dict,
    *,
    prompt: str,
    question: str,
    configured_max_tokens: int,
    answer_max_tokens: int,
) -> FinalizeBudget | None:
    """Arma el tope de UNA llamada de cierre desde el ledger del run.

    None = el ledger no da margen: el cierre no genera y el caller aplica su
    fallback determinista (nunca una respuesta vacía).
    """
    from src.runtime.run_budget import (
        EXHAUSTED,
        RunBudgetLedger,
        estimate_prompt_tokens,
        lookup_token_rates,
        plan_response_budget,
    )

    per_call = int(configured_max_tokens or 0) or int(answer_max_tokens)
    model_limit = int(answer_max_tokens)
    ledger = RunBudgetLedger.from_config(result, config)
    rates = await lookup_token_rates(str(config.get("model") or ""))
    call_plan = plan_response_budget(
        ledger,
        estimated_prompt_tokens=estimate_prompt_tokens(prompt),
        desired_completion_tokens=min(per_call, model_limit),
        model_output_limit=model_limit,
        question=question,
        followup_llm=False,
        input_cost_per_1k=None if rates is None else rates[0],
        output_cost_per_1k=None if rates is None else rates[1],
    )
    if (
        call_plan.budget_pressure == EXHAUSTED
        or call_plan.allowed_completion_tokens <= 0
    ):
        return None
    return FinalizeBudget(
        ledger=ledger,
        max_tokens=int(call_plan.allowed_completion_tokens),
        call_plan=call_plan,
    )


FINALIZE_TEMPLATE = """You already collected tool observations. Answer the user now.

Rules:
- Write ONLY the final text for the user (Markdown allowed). No JSON, no wrappers,
  no labels like "answer:" or "direct_answer:".
- Do not call tools.
- Domain facts and rules must be supported by the observations. User-provided
  values are valid scenario data: apply them against documented rules; do not
  treat them as missing evidence. Deterministic results derived from grounded
  premises are valid even if not written verbatim.
- If a domain premise is missing, state exactly which one; never fill it with
  model knowledge.

USER QUESTION: {question}

{analytical_workspace}
{response_shape}
## HISTORY
{history}

Final answer (text only, no JSON):"""


def build_finalize_prompt(
    *,
    question: str,
    history: list[str],
    analytical_workspace: str = "",
    response_shape: str = "",
) -> str:
    """Prompt del cierre estándar: última generación sin tools.

    El caller aporta el workspace analítico (si hay razonamiento) y el contrato
    de forma; acá solo se formatea (misma plantilla de siempre).
    """
    return FINALIZE_TEMPLATE.format(
        question=question,
        history="\n".join(list(history or ())[-10:]),
        analytical_workspace=analytical_workspace,
        response_shape=response_shape,
    )


def citations_from_evidence(draft: str, selection: Any) -> list[dict[str, Any]]:
    """Citas del run ligadas a `evidence_id` (la numeración no rompe provenance)."""
    if selection is None or getattr(selection, "empty", True):
        return []
    cited: set[str] = set()
    for match in re.finditer(r"\[(?:Doc|doc)\s*[: ]?\s*(\d{1,3})\b", draft or ""):
        index = int(match.group(1)) - 1
        if 0 <= index < len(selection.items):
            cited.add(selection.items[index].evidence_id)
    from src.runtime.evidence import citations_payload

    return citations_payload(selection, cited_ids=cited)


def limits_note(missing_labels: list[str]) -> str:
    """Nota determinista de límites: qué no está en las fuentes consultadas."""
    if not missing_labels:
        return ""
    listed = ", ".join(str(label) for label in missing_labels[:4])
    return (
        "\n\nNota: las fuentes consultadas no cubren "
        f"{listed}. Lo anterior responde sólo lo que sí está respaldado."
    )


def finalize_answer_delivery(
    result: object,
    *,
    answer: str,
    reason: str,
    selection: object = None,
) -> None:
    """Entrega final: answer + citas + status + step `final` (una sola fuente)."""
    result.answer = answer
    result.citations = citations_from_evidence(answer, selection)
    result.status = "completed"
    result.steps.append(
        {
            "type": "final",
            "answer": answer[:500],
            "detail": f"finalized after {reason}",
        }
    )


def is_provider_failure(reason: str) -> bool:
    """Fallo del proveedor de modelos, no un límite del agente."""
    text = str(reason or "").lower()
    return any(
        marker in text
        for marker in (
            "todos los modelos del router fallaron",
            "circuit breaker is open",
            "ratelimiterror",
            "notfounderror",
            "model not found",
            "engine_overloaded",
            "model busy",
        )
    )


def budget_answer(history: list[str], reason: str) -> str:
    """Respuesta de cierre cuando el presupuesto se agotó: nunca vacía.

    Determinista: junta EVIDENCIA real de las observaciones (las que traen
    documentos), sin instrucciones internas ni inventos. Un fallo del
    proveedor de modelos no se disfraza de límite del agente.
    """
    fragmentos: list[str] = []
    for item in reversed(history):
        if not item.startswith("OBSERVATION") or "[Doc" not in item:
            continue
        cuerpo = item.split(":", 1)[-1].strip() if ":" in item else item
        # La primera línea suele ser la instrucción ("(untrusted data...)"); se
        # arranca en el primer documento.
        inicio = cuerpo.find("[Doc")
        if inicio > 0:
            cuerpo = cuerpo[inicio:]
        if cuerpo:
            fragmentos.append(cuerpo[:1200])
        if len(fragmentos) >= 2:
            break
    if is_provider_failure(reason):
        if not fragmentos:
            return (
                "No pude completar la respuesta: el proveedor de modelos no está "
                "disponible (los modelos del router fallaron). Reintentá en unos "
                "segundos."
            )
        evidencia = "\n\n".join(fragmentos)
        return (
            "No pude cerrar la explicación completa: el proveedor de modelos no "
            "está disponible. Esto es lo que quedó reunido de las fuentes (sin "
            f"agregar nada):\n\n{evidencia}"
        )
    motivo = {
        "max_tokens exceeded": "el presupuesto de tokens del agente",
        "max_execution_seconds exceeded": "el tiempo máximo de ejecución del agente",
        "max_cost exceeded": "el costo máximo del agente",
        "max_steps exceeded": "el máximo de pasos del agente",
    }.get(reason, f"el límite del agente ({reason})")
    if not fragmentos:
        return (
            f"No pude completar la respuesta: se alcanzó {motivo} antes de reunir "
            "evidencia. Reformulá la pregunta o ampliá los límites del agente."
        )
    evidencia = "\n\n".join(fragmentos)
    return (
        f"No pude cerrar la explicación completa: se alcanzó {motivo}. "
        "Esto es lo que quedó reunido de las fuentes (sin agregar nada):\n\n"
        f"{evidencia}"
    )


async def generate_finalize_response(
    generate,
    *,
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
) -> object | None:
    """Llama al generador elegido por el caller; None si falla.

    El caller decide streaming vs generate (on_delta y consulta ejecutable);
    acá solo se ejecuta con el presupuesto ya aprobado y nunca se rompe el run.
    """
    try:
        return await generate(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Finalize answer failed", error=str(exc)[:200])
        return None


def ensure_answer(result: object, history: list[str], *, reason: str) -> None:
    """Cierra sin respuesta vacía: el usuario nunca ve "(sin respuesta)".

    El finalize puede no correr (sin observaciones usables, error del provider,
    presupuesto agotado). En ese caso se devuelve lo reunido, tal cual, marcado
    como incompleto: nunca se inventa y nunca se deja el string vacío.
    """
    if (result.answer or "").strip():
        return
    if result.status not in ("limit_reached", "error", "completed"):
        return
    result.answer = budget_answer(history, reason)
    result.steps.append(
        {
            "type": "final",
            "answer": result.answer[:500],
            "detail": f"cierre determinista ({reason})",
        }
    )
