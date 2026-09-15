# =============================================================================
# Execution Narrative — historia de negocio de un run (Cognitive Workflows, Fase 8).
#
# Solo datos estructurados (outputs, decisiones, estados); nunca chain of
# thought. Se expone como `story` en `run_detail` y la muestra el inspector.
# =============================================================================
from __future__ import annotations

from typing import Any


def _business_name(node_type: str) -> str:
    from src.platform.workflows.node_catalog import metadata_for

    meta = metadata_for(node_type)
    return str(meta.get("business_name") or node_type)


def _decision_text(output: dict[str, Any]) -> str:
    for key in ("decision", "risk", "label", "summary"):
        value = output.get(key)
        if value:
            return str(value)[:120]
    return ""


def _is_simulated(step: dict[str, Any], output: dict[str, Any]) -> bool:
    return str(step.get("status") or "") == "simulated" or bool(output.get("simulated"))


def run_story(run: dict[str, Any] | None) -> list[str]:
    """Convierte el detalle del run en frases ordenadas de negocio."""
    if not run:
        return []
    story: list[str] = []
    payload = run.get("trigger_payload") if isinstance(run.get("trigger_payload"), dict) else {}
    payload_keys = [key for key in payload if not str(key).startswith("_")][:4]
    if payload_keys:
        summary = ", ".join(f"{key}={str(payload[key])[:60]}" for key in payload_keys)
        story.append(f"Se recibió la señal con: {summary}.")
    else:
        story.append("Se inició el flujo.")

    for step in run.get("steps") or []:
        if not isinstance(step, dict):
            continue
        node_type = str(step.get("node_type") or step.get("step_type") or "")
        output = step.get("output") if isinstance(step.get("output"), dict) else {}
        status = str(step.get("status") or "")
        if node_type.startswith("trigger_") or node_type == "end" or status == "skipped":
            continue
        if node_type == "kb_query":
            operation = str(output.get("operation") or "search")
            count = output.get("count")
            if count is None:
                count = len(output.get("evidence_ids") or output.get("documents") or [])
            story.append(f"Se consultó conocimiento ({operation}): {count} coincidencias.")
        elif node_type == "query_business_data":
            rows = output.get("rows")
            suffix = f": {len(rows)} filas." if isinstance(rows, list) and rows else "."
            story.append(f"Se consultaron datos de negocio{suffix}")
        elif node_type == "llm":
            decision = _decision_text(output)
            suffix = f": {decision}." if decision else "."
            story.append(f"El agente analizó la situación{suffix}")
        elif node_type == "condition":
            condition = str(output.get("condition") or "")[:100]
            outcome = "sí" if output.get("result") else "no"
            story.append(f"Se evaluó la condición «{condition}» y la respuesta fue {outcome}.")
        elif node_type == "join":
            branches = list((output.get("branches") or {}).keys())
            if branches:
                story.append("Se unieron las ramas: " + ", ".join(str(name) for name in branches) + ".")
        elif node_type == "merge":
            origin = output.get("selected_label") or output.get("selected_from") or "la primera rama"
            story.append(f"Se eligió el resultado de {origin}.")
        elif node_type == "filter":
            story.append(
                f"Se filtró la lista: {output.get('count', 0)} de {output.get('total', 0)} elementos."
            )
        elif node_type == "for_each":
            story.append(
                f"Se repitió el proceso para {output.get('items_processed', 0)} elementos."
            )
        elif node_type == "human_approval":
            if _is_simulated(step, output):
                story.append("Se simuló una solicitud de aprobación humana.")
            else:
                action = str(output.get("action") or "acción sensible")[:100]
                story.append(f"Se solicitó aprobación humana: {action}.")
        elif node_type == "notify":
            if _is_simulated(step, output):
                story.append("Se simuló un aviso al equipo.")
            else:
                story.append(f"Se envió un aviso por {output.get('channel') or 'Zent'}.")
        elif node_type == "business_result":
            if _is_simulated(step, output):
                story.append("Se simuló publicar un resultado de negocio.")
            else:
                story.append("Se publicó un resultado de negocio.")
        elif node_type == "marketplace_action":
            label = f" ({output.get('action_id')})" if output.get("action_id") else ""
            story.append(f"Se ejecutó una acción de integración{label}.")
        elif node_type == "api_call":
            story.append("Se consultó un servicio externo.")
        else:
            name = _business_name(node_type)
            if name and name != node_type:
                story.append(f"Se ejecutó «{name}».")

    errors = [step for step in run.get("steps") or [] if isinstance(step, dict) and step.get("error")]
    if errors:
        story.append(f"El run terminó con {len(errors)} error(es).")
    elif run.get("status"):
        story.append(f"El run terminó en estado «{run.get('status')}».")
    return story


__all__ = ["run_story"]
