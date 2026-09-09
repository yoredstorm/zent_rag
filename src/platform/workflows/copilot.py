# =============================================================================
# Phase 32C — AI Workflow Copilot (draft por lenguaje natural)
#
# "Describe what you want to automate" → DRAFT graph (nunca se activa solo).
# Determinístico con heurísticas (función en ES/inglés); si hay LLM
# configurado se puede sustituir por generación por LLM manteniendo el shape.
# =============================================================================
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

_DAILY_RE = re.compile(r"\bdiari[oa]+\b|\bcada d[ií]a\b|\btodos los d[ií]as\b|\bdaily\b")
_TIME_RE = re.compile(r"(\d{1,2})\s*(?:pm|am|p\.m\.|a\.m\.)?|(\d{1,2}):(\d{2})")
_HOUR_RE = re.compile(r"(?:a las|at|a)\s+(\d{1,2})\s*(?:pm|am|p\.m\.|a\.m\.|horas)?", re.I)
_SALES_RE = re.compile(r"\bventas?\b|\bsales\b|ingresos|facturaci[oó]n")
_YESTERDAY_RE = re.compile(r"\bayer\b|\byesterday\b")
_YTD_RE = re.compile(r"\bclientes?\b|\bcustomers?\b|\bcontribuyente\b")
_RUC_RE = re.compile(r"\bruc\b")
_SUNAT_RE = re.compile(r"\bsunat\b|\bcontribuyente\b|\btaxpayer\b")
_EMAIL_RE = re.compile(r"\bcorreo\b|\bemail\b|\ba\s+[\w.@-]+@[\w.-]+\b")
_VERIFY_RE = re.compile(r"\bverific\w*\b|\bvalid\w*\b|\bcheck\b")
_AGENT_RE = re.compile(r"\bagente\b|\bagent\b|\bcomercial\b|\ban\a?lisis\b")


@dataclass
class DraftPlan:
    name: str
    trigger_type: "str"  # noqa: F821
    trigger_config: dict[str, Any]
    steps: list[dict[str, Any]]
    questions: list[str] = field(default_factory=list)
    source_hint: str | None = None
    integration_hint: str | None = None
    matches: list[str] = field(default_factory=list)


MAYBE_QUESTIONS = [
    "¿Qué fuente de datos de ventas usamos?",
    "¿A qué correo(s) enviamos el reporte?",
    "¿A qué hora exacta?",
    "¿Qué agente analiza los resultados?",
]


def _parse_time(prompt: str) -> str | None:
    m = _HOUR_RE.search(prompt)
    if m:
        h = int(m.group(1))
        suffix = m.group(0).lower()
        pm = "pm" in suffix or "p.m." in suffix or "de la tarde" in prompt[: m.end()].lower()
        return f"{h + 12 if pm and h < 12 else h:02d}:00"
    m = _TIME_RE.search(prompt)
    if m:
        if m.group(2):
            h = int(m.group(2))
            tail = prompt[m.end() : m.end() + 6].lower()
            pm = "pm" in tail or "p.m." in tail
            return f"{h + 12 if pm and h < 12 else h:02d}:{m.group(3)}"
        h = int(m.group(1))
        tail = prompt[m.end() : m.end() + 6].lower()
        pm = "pm" in tail or "p.m." in tail
        return f"{h + 12 if pm and h < 12 else h:02d}:00"
    return None


def _schedule_config(prompt: str) -> dict[str, Any]:
    time = _parse_time(prompt)
    if _DAILY_RE.search(prompt) or time:
        return {
            "daily": {"time": time or "18:00", "timezone": "America/Lima"},
        }
    return {"every_minutes": 60}


def build_draft(prompt: str) -> DraftPlan:
    """Heurísticas: convierte el deseo en un borrador de workflow."""
    p = prompt.lower()
    matches: list[str] = []
    if _SALES_RE.search(p):
        matches.append("sales")
    if _YESTERDAY_RE.search(p):
        matches.append("compare_yesterday")
    if _VERIFY_RE.search(p):
        matches.append("verify")
    if _SUNAT_RE.search(p) or _RUC_RE.search(p):
        matches.append("taxpayer")
    if _YTD_RE.search(p):
        matches.append("customers")
    if _AGENT_RE.search(p):
        matches.append("agent_analysis")
    if _EMAIL_RE.search(p):
        matches.append("email")
    if matches and "agent_analysis" not in matches and "email" not in matches:
        matches.append("agent_analysis")

    if matches and "taxpayer" in matches:
        # Verificación de contribuyente para clientes nuevos.
        steps: list[dict[str, Any]] = [
            {
                "type": "condition",
                "config": {"field": "trigger.ruc", "operator": "!=", "value": ""},
                "then": [
                    {
                        "type": "marketplace_action",
                        "config": {
                            "install_id": "{{_pack.demo_echo_install}}",
                            "action_id": "demo.echo",
                            "inputs": {"text": "{{trigger.ruc}}"},
                        },
                    },
                    {
                        "type": "llm",
                        "config": {
                            "prompt": ("Explica el estado del contribuyente con RUC {{trigger.ruc}} "
                                "según {{steps.0.output.echo}}")
                        },
                    },
                    {
                        "type": "notify",
                        "config": {
                                "channel": "in_app",
                                "title": "Verificación de contribuyente",
                                "message": "{{steps.1.output.text}}",
                            },
                    },
                ],
                "else": [
                    {
                        "type": "notify",
                        "config": {
                            "channel": "in_app",
                            "title": "Cliente sin RUC",
                            "message": "El cliente nuevo no aportó RUC",
                        },
                    }
                ],
            }
        ]
        return DraftPlan(
            name="Verificar cliente nuevo (RUC)",
            trigger_type="event",
            trigger_config={"event_type": "customer.created", "filters": {}},
            steps=steps,
            questions=[
                "¿Qué integración de verificación usamos (SUNAT o sandbox demo)?",
                "¿Notificamos por correo además de in-app?",
            ],
            integration_hint="sunat|demo-echo",
            matches=matches,
        )

    # Default: brief ejecutivo diario de ventas.
    steps = [
        {
            "type": "query_business_data",
            "config": {"ask": "Ventas del día (ingresos, tickets, ticket promedio)"},
        },
        {
            "type": "query_business_data",
            "config": {
                "ask": (
                    "Ventas del día anterior para comparar"
                    if "yesterday" in matches
                    else "Comparativa de ventas vs período anterior"
                ),
            },
        },
        {
            "type": "llm",
            "config": {
                "prompt": ("Compara las ventas de hoy ({{nodes.n1.output.answer}}) con el período anterior "
                            "({{nodes.n2.output.answer}}). Resumen en 3 bullets: variación, anomalías, oportunidades.")
            },
        },
        {
            "type": "notify",
            "config": {
                "channel": "in_app",
                "title": "Brief diario de ventas",
                "message": "{{nodes.n3.output.text}}",
            },
        },
        {
            "type": "business_result",
            "config": {
                "title": "Brief diario de ventas",
                "section": "reports",
                "importance": "INFO",
                "summary": "{{nodes.n3.output.text}}",
                "metrics": {},
            },
        },
    ]
    questions: list[str] = []
    if "sales" in matches:
        questions.append(MAYBE_QUESTIONS[0])  # fuente de ventas
    questions.append(MAYBE_QUESTIONS[1])  # correos
    if not _TIME_RE.search(p):
        questions.append("¿A qué hora exacta?")
    return DraftPlan(
        name="Brief ejecutivo de ventas diario",
        trigger_type="schedule",
        trigger_config=_schedule_config(p),
        steps=steps,
        questions=[q for q in dict.fromkeys(questions) if q][:3],
        source_hint="sales",
        matches=matches,
    )


def randomized_id(prefix: str = "n") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"
