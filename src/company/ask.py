# =============================================================================
# Company Intelligence Studio — "Ask your Company" (§12)
# =============================================================================
# Pipeline: pregunta -> Judgment Fabric -> CompanyContextCompiler ->
# traversal del grafo -> conocimiento/SQL si hace falta -> respuesta con
# evidencia.
#
# Reglas:
#   - El JEV CLASIFICA la intención; nunca inventa hechos. Si no está
#     disponible, un router determinista decide (fail-soft).
#   - La respuesta se compone de hechos del grafo. Cuando un camino tiene
#     eslabones no confirmados, el lenguaje es hipotético ("puede verse
#     afectado"), jamás asertivo.
#   - La evidencia viaja siempre: ids, relaciones, candidatos, memoria,
#     fragmentos de documento. Sin evidencia no hay respuesta.
# =============================================================================
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable
from uuid import UUID

from src.company.context import CompanyContextCompiler, ContextBudget
from src.company.service import CompanyGraphService
from src.company.studio import CompanyStudioService, entity_type_label
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

MAX_EVIDENCE = 12


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyIntent(StrEnum):
    """Intenciones que la Studio sabe responder con el grafo."""

    ENTITY_LOOKUP = "entity_lookup"
    REPRESENTATION = "representation"
    PROCESS_OF = "process_of"
    DEPENDENCY = "dependency"
    IMPACT = "impact"
    SOURCE_OF_TRUTH = "source_of_truth"
    KNOWLEDGE_GAPS = "knowledge_gaps"
    CHANGES = "changes"
    LEARNED = "learned"
    KNOWLEDGE = "knowledge"


INTENT_CRITERIA = {
    CompanyIntent.ENTITY_LOOKUP.value: (
        "the user asks what an entity is or wants a definition"
    ),
    CompanyIntent.REPRESENTATION.value: (
        "the user asks where a concept is stored or represented in data"
    ),
    CompanyIntent.PROCESS_OF.value: (
        "the user asks which process uses, produces or owns something"
    ),
    CompanyIntent.DEPENDENCY.value: (
        "the user asks what depends on something"
    ),
    CompanyIntent.IMPACT.value: (
        "the user asks what would be affected if something changes or fails"
    ),
    CompanyIntent.SOURCE_OF_TRUTH.value: (
        "the user asks which source is authoritative or the source of truth"
    ),
    CompanyIntent.KNOWLEDGE_GAPS.value: (
        "the user asks what knowledge is missing, undocumented or incomplete"
    ),
    CompanyIntent.CHANGES.value: (
        "the user asks what changed over time"
    ),
    CompanyIntent.LEARNED.value: (
        "the user asks what Zent has learned about something"
    ),
    CompanyIntent.KNOWLEDGE.value: (
        "the question needs document knowledge, not the company graph"
    ),
}

# Palabras que orientan la intención cuando no hay juez disponible. El orden
# desempata: las señales más específicas van primero.
_INTENT_HINTS: tuple[tuple[CompanyIntent, tuple[str, ...]], ...] = (
    (
        CompanyIntent.IMPACT,
        ("afecta", "afectaria", "afectaría", "impacto", "impact", "cambia", "cambiaria",
         "falla", "fallara", "unavailable", "no estuviera", "dejara de"),
    ),
    (
        CompanyIntent.DEPENDENCY,
        ("depende", "dependen", "depends", "dependencia", "que usa", "qué usa",
         "quien usa", "quién usa", "consumidores"),
    ),
    (
        CompanyIntent.SOURCE_OF_TRUTH,
        ("fuente de verdad", "autoritativa", "authoritative", "source of truth",
         "que fuente manda", "qué fuente manda", "confiable", "conflicts"),
    ),
    (
        CompanyIntent.KNOWLEDGE_GAPS,
        ("falta", "incompleto", "hueco", "gap", "sin documentar", "no documentado",
         "missing", "undocumented"),
    ),
    (
        CompanyIntent.LEARNED,
        ("aprendio", "aprendió", "learned", "memoria", "memory", "patron", "patrón",
         "que sabe zent", "qué sabe zent"),
    ),
    (
        CompanyIntent.CHANGES,
        ("cambio", "cambió", "changed", "version", "versión", "antes",
         "el año pasado", "historico", "histórico"),
    ),
    (
        CompanyIntent.REPRESENTATION,
        ("donde se representa", "dónde se representa", "representa", "almacena",
         "stored", "where is", "columna", "campo", "field", "tabla"),
    ),
    (
        CompanyIntent.PROCESS_OF,
        ("proceso", "process", "flujo", "workflow que", "quien produce", "quién produce"),
    ),
    (
        CompanyIntent.ENTITY_LOOKUP,
        ("que es", "qué es", "what is", "significa", "means", "definicion", "definición"),
    ),
)

_QUESTION_STOPWORDS = frozenset(
    {
        "que", "qué", "cual", "cuál", "cuales", "cuáles", "quien", "quién", "donde",
        "dónde", "como", "cómo", "cuando", "cuándo", "porque", "por qué", "para",
        "con", "sin", "los", "las", "del", "una", "uno", "unos", "unas", "este",
        "esta", "estos", "estas", "sobre", "entre", "desde", "hasta", "the", "and",
        "for", "with", "what", "which", "who", "where", "when", "why", "how", "is",
        "are", "does", "do", "of", "in", "on", "to", "a", "an",
    }
)


def question_tokens(question: str, *, limit: int = 24) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKD", question or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    tokens: list[str] = []
    for raw in text.lower().split():
        token = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
        if len(token) < 3 or token.isdigit() or token in _QUESTION_STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens[:limit])


def lexical_intent(question: str) -> tuple[CompanyIntent, float]:
    """Router determinista de respaldo. Devuelve (intención, confianza).

    Cuenta señales por intención en vez de quedarse con la primera: una
    pregunta puede mencionar "tabla" y "aprendió", y la señal específica
    (aprendió) debe ganar. El orden de `_INTENT_HINTS` desempata.
    """
    text = " ".join(question.lower().split())
    best_intent = CompanyIntent.ENTITY_LOOKUP
    best_score = 0
    for intent, hints in _INTENT_HINTS:
        score = sum(1 for hint in hints if hint in text)
        if score > best_score:
            best_intent, best_score = intent, score
    if best_score == 0:
        return CompanyIntent.ENTITY_LOOKUP, 0.35
    confidence = min(0.85, 0.45 + 0.15 * best_score)
    return best_intent, confidence


@dataclass(frozen=True, kw_only=True)
class AskEvidence:
    kind: str
    ref: str
    label: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "label": self.label,
            "detail": self.detail,
        }


@dataclass(frozen=True, kw_only=True)
class CompanyAnswer:
    question: str
    intent: str
    answer: str
    certainty: str
    decision: dict
    evidence: tuple[AskEvidence, ...] = ()
    data: dict = field(default_factory=dict)
    context_used: dict = field(default_factory=dict)
    followups: tuple[str, ...] = ()
    answered_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "intent": self.intent,
            "answer": self.answer,
            "certainty": self.certainty,
            "decision": self.decision,
            "evidence": [item.to_dict() for item in self.evidence[:MAX_EVIDENCE]],
            "data": self.data,
            "context_used": self.context_used,
            "followups": list(self.followups),
            "answered_at": self.answered_at.isoformat(),
        }


class CompanyAskService:
    """Responde preguntas sobre la compañía con evidencia del grafo."""

    def __init__(
        self,
        graph: CompanyGraphService,
        studio: CompanyStudioService,
        *,
        compiler: CompanyContextCompiler | None = None,
        judge: Callable | None = None,
        knowledge_search: Callable | None = None,
    ) -> None:
        self._graph = graph
        self._studio = studio
        self._compiler = compiler
        self._judge = judge
        self._knowledge = knowledge_search

    async def ask(
        self,
        organization_id: UUID,
        question: str,
        *,
        agent_id: UUID | None = None,
        workflow_id: UUID | None = None,
        entity_id: UUID | None = None,
        budget: ContextBudget | None = None,
        as_of: datetime | None = None,
        allow_knowledge: bool = True,
    ) -> CompanyAnswer:
        """Responde una pregunta sobre la compañía.

        `entity_id` es el contexto de página: permite preguntas como "¿qué
        aprendió Zent sobre esta tabla?" sin repetir el nombre en el texto.
        """
        if not question.strip():
            raise ValueError("question must not be empty")

        # 1. Contexto empresarial acotado (nunca el grafo completo).
        compiled = None
        if self._compiler is not None:
            try:
                compiled = await self._compiler.compile(
                    organization_id,
                    question,
                    agent_id=agent_id,
                    workflow_id=workflow_id,
                    budget=budget,
                    as_of=as_of,
                )
            except Exception as exc:  # noqa: BLE001 - el ask nunca se cae
                logger.warning("company ask compile failed", error=str(exc)[:150])
        context_used = (
            compiled.to_dict() if compiled is not None else {"available": False}
        )

        # 2. Judgment Fabric clasifica la intención (fail-soft a router léxico).
        intent, decision = await self._resolve_intent(
            organization_id, question, compiled
        )

        # 3. Ejecuta la intención contra el grafo.
        try:
            answer, evidence, data, certainty = await self._execute(
                organization_id,
                question,
                intent,
                compiled,
                as_of=as_of,
                entity_id=entity_id,
            )
        except ValueError as exc:
            return CompanyAnswer(
                question=question,
                intent=intent.value,
                answer=str(exc),
                certainty="unknown",
                decision=decision,
                context_used=_context_summary(context_used),
                followups=_FOLLOWUPS,
            )

        # 4. Conocimiento documental solo si hace falta.
        if intent is CompanyIntent.KNOWLEDGE and allow_knowledge:
            extra_answer, extra_evidence = await self._knowledge_answer(
                organization_id, question
            )
            if extra_answer:
                answer = extra_answer
                evidence = (*evidence, *extra_evidence)

        return CompanyAnswer(
            question=question,
            intent=intent.value,
            answer=answer,
            certainty=certainty,
            decision=decision,
            evidence=tuple(evidence),
            data=data,
            context_used=_context_summary(context_used),
            followups=_FOLLOWUPS,
        )

    # ------------------------------------------------------------------
    # Clasificación
    # ------------------------------------------------------------------
    async def _resolve_intent(
        self,
        organization_id: UUID,
        question: str,
        compiled,
    ) -> tuple[CompanyIntent, dict]:
        fallback, confidence = lexical_intent(question)
        if self._judge is None:
            return fallback, {
                "provider": "lexical",
                "intent": fallback.value,
                "confidence": confidence,
                "fallback_used": True,
                "reason": "judge_unavailable",
            }
        state = {
            "user_request": question[:2000],
            "available_intents": list(INTENT_CRITERIA),
        }
        if compiled is not None:
            state.update(compiled.to_jev_state())
        questions = {
            "intent": {
                "type": "choice",
                "instructions": (
                    "Clasifica la pregunta sobre la compañía en UNA intención. "
                    "No inventes hechos."
                ),
                "criteria": INTENT_CRITERIA,
            }
        }
        try:
            payload = await self._judge(state=state, questions=questions)
        except Exception as exc:  # noqa: BLE001 - el juez nunca rompe el ask
            logger.warning("company ask judge failed", error=str(exc)[:150])
            payload = None
        choice = None
        if isinstance(payload, dict):
            answers = payload.get("answers") or payload
            entry = answers.get("intent") if isinstance(answers, dict) else None
            if isinstance(entry, dict):
                choice = entry.get("choice")
            elif isinstance(entry, str):
                choice = entry
        if choice in INTENT_CRITERIA:
            return CompanyIntent(choice), {
                "provider": payload.get("provider", "jev") if isinstance(payload, dict) else "jev",
                "intent": choice,
                "confidence": float(
                    (payload.get("answers") or {}).get("intent", {}).get("confidence", 0.0)
                    if isinstance(payload, dict)
                    else 0.0
                ),
                "fallback_used": False,
            }
        return fallback, {
            "provider": "lexical",
            "intent": fallback.value,
            "confidence": confidence,
            "fallback_used": True,
            "reason": "judge_abstained_or_invalid",
        }

    # ------------------------------------------------------------------
    # Ejecución por intención
    # ------------------------------------------------------------------
    async def _execute(
        self,
        organization_id: UUID,
        question: str,
        intent: CompanyIntent,
        compiled,
        *,
        as_of: datetime | None,
        entity_id: UUID | None = None,
    ) -> tuple[str, list[AskEvidence], dict, str]:
        if intent is CompanyIntent.KNOWLEDGE_GAPS:
            gaps = await self._studio.knowledge_gaps(organization_id, limit=50)
            items = gaps["items"]
            if not items:
                return (
                    "No hay huecos de conocimiento detectados en este momento.",
                    [],
                    gaps,
                    "confirmed",
                )
            lines = [f"Hay {len(items)} huecos de conocimiento detectados:"]
            for item in items[:5]:
                lines.append(f"- {item.get('subject')}: {item.get('detail')}")
            return (
                "\n".join(lines),
                [
                    AskEvidence(
                        kind="knowledge_gap",
                        ref=str(item.get("id") or item.get("subject")),
                        label=str(item.get("subject")),
                        detail={"gap_kind": item.get("gap_kind"), "origin": item.get("origin")},
                    )
                    for item in items[:MAX_EVIDENCE]
                ],
                gaps,
                "confirmed",
            )

        if intent is CompanyIntent.CHANGES:
            changes = await self._studio.changes(organization_id, limit=20)
            items = changes["items"]
            if not items:
                return (
                    "No se registraron cambios en el período consultado.",
                    [],
                    changes,
                    "confirmed",
                )
            lines = [f"Cambios recientes ({changes['since'][:10]} en adelante):"]
            for item in items[:6]:
                lines.append(f"- {item['at'][:10]} {item['title']} ({item['kind']})")
            return (
                "\n".join(lines),
                [
                    AskEvidence(
                        kind="change",
                        ref=str(item.get("entity_id") or item.get("candidate_id") or item["at"]),
                        label=item["title"],
                        detail={"kind": item["kind"], "status": item.get("status")},
                    )
                    for item in items[:MAX_EVIDENCE]
                ],
                changes,
                "confirmed",
            )

        if intent is CompanyIntent.SOURCE_OF_TRUTH:
            truth = await self._studio.source_of_truth(organization_id)
            target = await self._target_entity(organization_id, question, compiled)
            entries = truth["items"]
            if target is not None:
                entries = [
                    item
                    for item in entries
                    if item["concept_id"] == str(target.id)
                ] or entries
            if not entries:
                return (
                    "No hay conceptos con autoridad configurada todavía.",
                    [],
                    truth,
                    "confirmed",
                )
            entry = entries[0]
            sources = entry["sources"]
            if not sources:
                answer = (
                    f"{entry['concept']} no tiene fuente autoritativa configurada. "
                    "Es un hueco de conocimiento."
                )
                certainty = "confirmed"
            else:
                lines = [f"Fuentes registradas para {entry['concept']}:"]
                for source in sources:
                    lines.append(
                        f"- {source['authority_level']}: {source['source_name']}"
                    )
                answer = "\n".join(lines)
                certainty = "confirmed"
            evidence = [
                AskEvidence(
                    kind="authority",
                    ref=f"{entry['concept']}:{source['source_name']}",
                    label=source["source_name"],
                    detail={"authority_level": source["authority_level"]},
                )
                for source in sources[:MAX_EVIDENCE]
            ]
            conflicts = truth.get("conflicts") or []
            if conflicts:
                answer += f"\n\nHay {len(conflicts)} conflicto(s) registrados entre fuentes."
            return answer, evidence, {"entry": entry, "conflicts": conflicts}, certainty

        target = await self._target_entity(
            organization_id, question, compiled, entity_id=entity_id
        )
        if target is None:
            if intent is CompanyIntent.KNOWLEDGE and self._knowledge is not None:
                return ("", [], {}, "unknown")
            raise ValueError(
                "No encontré ninguna entidad del grafo relacionada con la pregunta. "
                "Nombrá la entidad o preguntá desde su página."
            )
        return await self._answer_about_entity(
            organization_id, question, intent, target, as_of=as_of
        )

    async def _answer_about_entity(
        self,
        organization_id: UUID,
        question: str,
        intent: CompanyIntent,
        target,
        *,
        as_of: datetime | None,
    ) -> tuple[str, list[AskEvidence], dict, str]:
        evidence: list[AskEvidence] = [
            AskEvidence(
                kind="entity",
                ref=str(target.id),
                label=target.canonical_name,
                detail={
                    "entity_type": target.entity_type,
                    "status": target.status.value,
                    "confidence": target.confidence,
                },
            )
        ]

        if intent in (CompanyIntent.IMPACT, CompanyIntent.DEPENDENCY):
            direction = "in" if intent is CompanyIntent.DEPENDENCY else "both"
            impact = await self._studio.impact(
                organization_id, target.id, direction=direction, max_depth=3
            )
            paths = impact["paths"]
            affected = impact["affected"]
            buckets = ", ".join(
                f"{len(items)} {name}" for name, items in affected.items()
            )
            if intent is CompanyIntent.DEPENDENCY:
                lines = [
                    f"Lo que depende de {target.canonical_name}: {buckets or 'nada registrado'}"
                ]
            else:
                lines = [
                    f"Si {target.canonical_name} cambia o falla, se vería afectado: "
                    f"{buckets or 'nada registrado'}"
                ]
            hypothetical = False
            for path in paths[:4]:
                if path["certainty"] == "may":
                    hypothetical = True
                chain = " ".join(
                    f"{step['relationship_type']}" for step in path["explanation"]
                )
                lines.append(
                    f"- {target.canonical_name} hasta {path['target']} "
                    f"({path['hops']} saltos, {path['certainty']}): {chain}"
                )
            if hypothetical:
                lines.append(
                    "Algunos caminos incluyen relaciones no confirmadas: el impacto "
                    "es potencial, no definitivo."
                )
            for path in paths[:MAX_EVIDENCE]:
                evidence.append(
                    AskEvidence(
                        kind="path",
                        ref=path["target_id"],
                        label=path["target"],
                        detail={
                            "hops": path["hops"],
                            "certainty": path["certainty"],
                            "explanation": path["explanation"],
                        },
                    )
                )
            return (
                "\n".join(lines),
                evidence,
                impact,
                "may" if hypothetical else "confirmed",
            )

        if intent is CompanyIntent.PROCESS_OF:
            if target.entity_type in ("process", "workflow"):
                page = await self._studio.process_page(organization_id, target.id)
                lines = [f"Proceso {target.canonical_name}:"]
                steps = page["steps"]["observed"] or page["steps"]["designed"]
                if steps:
                    lines.append(
                        "Pasos: " + " ".join(str(step.get("name")) for step in steps[:12])
                    )
                deviation = page.get("deviation") or {}
                if deviation.get("available") and deviation.get("rework_frequency"):
                    lines.append(
                        f"Retrabajo observado en {deviation['rework_frequency']:.0%} de "
                        f"{deviation['runs']} corridas."
                    )
                done = await self._done_by(organization_id, target.id)
                if done:
                    lines.append("Sistemas y participantes: " + ", ".join(done))
                for item in page["systems"][:6]:
                    evidence.append(
                        AskEvidence(
                            kind="system",
                            ref=item["id"],
                            label=item["name"],
                            detail={"status": item["status"]},
                        )
                    )
                for item in page["agents"][:4]:
                    evidence.append(
                        AskEvidence(
                            kind="agent",
                            ref=item["id"],
                            label=item["name"],
                            detail={"status": item["status"]},
                        )
                    )
                return (
                    "\n".join(lines),
                    evidence,
                    page,
                    "confirmed" if steps else "unknown",
                )
            # La pregunta puede ser "¿qué proceso usa X?": X no es un proceso.
            page = await self._related_processes(organization_id, target)
            if not page["processes"]:
                return (
                    f"No hay procesos ni workflows relacionados con "
                    f"{target.canonical_name} en el grafo.",
                    evidence,
                    page,
                    "confirmed",
                )
            lines = [f"Procesos relacionados con {target.canonical_name}:"]
            for item in page["processes"]:
                lines.append(
                    f"- {item['name']} ({item['entity_type']}) "
                    f"vía {item['relationship_type']} [{item['status']}]"
                )
                evidence.append(
                    AskEvidence(
                        kind="process",
                        ref=item["id"],
                        label=item["name"],
                        detail={
                            "relationship_type": item["relationship_type"],
                            "status": item["status"],
                        },
                    )
                )
            return "\n".join(lines), evidence, page, "confirmed"

        if intent is CompanyIntent.LEARNED:
            memory = await self._studio.entity_memory(organization_id, target.id)
            patterns = memory["patterns"]
            findings = memory["findings"]
            if not patterns and not findings:
                return (
                    f"Zent todavía no aprendió nada operativo sobre {target.canonical_name}.",
                    evidence,
                    memory,
                    "confirmed",
                )
            lines = [f"Lo que Zent aprendió sobre {target.canonical_name}:"]
            for item in patterns[:5]:
                lines.append(
                    f"- {item['pattern_key']}: éxito {item['success_rate']:.0%} "
                    f"({item['support_count']} observaciones)"
                )
            for item in findings[:3]:
                lines.append(f"- Finding: {item.get('observed', '')[:160]}")
            for item in patterns[:MAX_EVIDENCE]:
                evidence.append(
                    AskEvidence(
                        kind="memory",
                        ref=str(item["id"]),
                        label=item["pattern_key"],
                        detail={
                            "success_rate": item["success_rate"],
                            "support_count": item["support_count"],
                            "status": item["status"],
                        },
                    )
                )
            for item in findings[:4]:
                evidence.append(
                    AskEvidence(
                        kind="finding",
                        ref=str(item.get("id")),
                        label=str(item.get("category")),
                        detail={"observed": item.get("observed")},
                    )
                )
            return "\n".join(lines), evidence, memory, "confirmed"

        if intent is CompanyIntent.REPRESENTATION:
            detail = await self._studio.entity_detail(organization_id, target.id)
            mappings = detail["technical_mappings"]
            mapped_by = detail.get("mapped_by_concepts") or []
            if not mappings and mapped_by:
                # Entidad técnica: los conceptos se mapean HACIA ella.
                lines = [
                    f"{target.canonical_name} es {entity_type_label(target.entity_type)} "
                    "y estos conceptos de negocio lo representan:"
                ]
                for item in mapped_by[:6]:
                    values = ", ".join(str(value) for value in item["values"])
                    suffix = f" (valores: {values})" if values else ""
                    lines.append(f"- {item['concept']}{suffix} [{item['status']}]")
                for item in mapped_by[:MAX_EVIDENCE]:
                    evidence.append(
                        AskEvidence(
                            kind="mapping",
                            ref=item["id"],
                            label=item["concept"],
                            detail={"values": item["values"], "status": item["status"]},
                        )
                    )
                return "\n".join(lines), evidence, detail, "confirmed"
            if not mappings and not mapped_by:
                related_lines = [
                    f"- {item['entity_type']} {item['display_name']}"
                    for group in ("data", "systems")
                    for item in detail["related"].get(group, [])[:6]
                ]
                answer = (
                    f"{target.canonical_name} todavía no tiene mapeo técnico "
                    "confirmado."
                )
                if related_lines:
                    answer += "\nContexto en el grafo:\n" + "\n".join(related_lines)
                return answer, evidence, detail, "unknown"
            lines = [f"Dónde se representa {target.canonical_name}:"]
            for mapping in mappings[:6]:
                values = ", ".join(str(value) for value in mapping["values"])
                suffix = f" (valores: {values})" if values else ""
                lines.append(
                    f"- {mapping['target_type']} {mapping['target']}{suffix} "
                    f"[{mapping['status']}]"
                )
            for mapping in mappings[:MAX_EVIDENCE]:
                evidence.append(
                    AskEvidence(
                        kind="mapping",
                        ref=mapping["id"],
                        label=f"{mapping['target']} ({mapping['target_type']})",
                        detail={
                            "values": mapping["values"],
                            "status": mapping["status"],
                        },
                    )
                )
            certainty = (
                "confirmed"
                if all(item["status"] in ("confirmed", "auto_confirmed") for item in mappings)
                and mappings
                else "may"
            )
            return "\n".join(lines), evidence, detail, certainty

        # ENTITY_LOOKUP y KNOWLEDGE: descripción desde el grafo.
        detail = await self._studio.entity_detail(organization_id, target.id)
        lines = [
            f"{target.canonical_name} es {entity_type_label(target.entity_type)} "
            f"({target.status.value})."
        ]
        if target.description:
            lines.append(target.description)
        if target.aliases:
            lines.append("Aliases: " + ", ".join(target.aliases[:8]))
        if detail["authority"]:
            lines.append(
                "Fuentes: "
                + ", ".join(
                    f"{item['authority_level']}={item['source_name']}"
                    for item in detail["authority"][:4]
                )
            )
        for group, items in detail["related"].items():
            if items:
                lines.append(
                    f"{group}: " + ", ".join(item["display_name"] for item in items[:6])
                )
        for group, items in detail["related"].items():
            for item in items[:3]:
                evidence.append(
                    AskEvidence(
                        kind=group,
                        ref=item["id"],
                        label=item["display_name"],
                        detail={"status": item["status"]},
                    )
                )
        return "\n".join(lines), evidence, detail, "confirmed"

    async def _related_processes(
        self, organization_id: UUID, entity
    ) -> dict:
        """Procesos y workflows ligados a la entidad, en ambas direcciones."""
        outgoing = await self._graph.find_relationships(
            organization_id, from_entity_id=entity.id, current_only=True, limit=50
        )
        incoming = await self._graph.find_relationships(
            organization_id, to_entity_id=entity.id, current_only=True, limit=50
        )
        ids = {item.to_entity_id for item in outgoing} | {
            item.from_entity_id for item in incoming
        }
        related = []
        for entity_id in list(ids)[:50]:
            candidate = await self._graph.get_entity(organization_id, entity_id)
            if candidate is None or candidate.entity_type not in ("process", "workflow"):
                continue
            relationship = next(
                (
                    item
                    for item in [*outgoing, *incoming]
                    if item.to_entity_id == candidate.id
                    or item.from_entity_id == candidate.id
                ),
                None,
            )
            related.append(
                {
                    "id": str(candidate.id),
                    "name": candidate.canonical_name,
                    "entity_type": candidate.entity_type,
                    "status": candidate.status.value,
                    "relationship_type": (
                        relationship.relationship_type if relationship else ""
                    ),
                }
            )
        return {"entity": entity.canonical_name, "processes": related}

    async def _done_by(self, organization_id: UUID, entity_id: UUID) -> list[str]:
        relationships = await self._graph.find_relationships(
            organization_id,
            from_entity_id=entity_id,
            relationship_types=("USES", "DEPENDS_ON", "ASSISTED_BY", "AUTOMATES"),
            current_only=True,
            limit=20,
        )
        names: list[str] = []
        for relationship in relationships:
            entity = await self._graph.get_entity(
                organization_id, relationship.to_entity_id
            )
            if entity is not None:
                names.append(entity.canonical_name)
        return names[:8]

    # ------------------------------------------------------------------
    # Objetivo y conocimiento documental
    # ------------------------------------------------------------------
    async def _target_entity(
        self,
        organization_id: UUID,
        question: str,
        compiled,
        *,
        entity_id: UUID | None = None,
    ):
        """Entidad mencionada. Usa el contexto de página, el compilado y el grafo.

        El orden importa: si la pregunta no nombra nada y viene un `entity_id`
        (la página desde la que se pregunta), se usa ese contexto.
        """
        tokens = question_tokens(question)
        candidates: list = []
        if compiled is not None:
            for bucket in ("concepts", "processes", "systems", "rules"):
                for item in getattr(compiled, bucket):
                    candidates.append(item)
        if candidates:
            best = _best_match(question, candidates) if tokens else None
            if best is not None:
                entity = await self._graph.get_entity(
                    organization_id, UUID(str(best["id"]))
                )
                if entity is not None:
                    return entity
        for token in tokens[:6]:
            found = await self._graph.find_entities(
                organization_id, query=token, limit=5
            )
            if found:
                return found[0]
        if entity_id is not None:
            return await self._graph.get_entity(organization_id, entity_id)
        return None

    async def _knowledge_answer(
        self, organization_id: UUID, question: str
    ) -> tuple[str, list[AskEvidence]]:
        if self._knowledge is None:
            return "", []
        try:
            chunks = await self._knowledge(organization_id, question, limit=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("company ask knowledge failed", error=str(exc)[:150])
            return "", []
        if not chunks:
            return "", []
        lines = ["Según los documentos indexados:"]
        evidence: list[AskEvidence] = []
        for chunk in chunks[:5]:
            excerpt = str(chunk.get("content") or "")[:240]
            lines.append(f"- {excerpt}")
            evidence.append(
                AskEvidence(
                    kind="document",
                    ref=str(chunk.get("document_id") or ""),
                    label=str(chunk.get("title") or "")[:120],
                    detail={"score": chunk.get("score")},
                )
            )
        return "\n".join(lines), evidence


def _best_match(question: str, candidates: list[dict]) -> dict | None:
    tokens = set(question_tokens(question))
    if not tokens:
        return candidates[0] if candidates else None
    best: tuple[int, dict] | None = None
    for item in candidates:
        haystack = " ".join(
            [
                str(item.get("name") or ""),
                str(item.get("display_name") or ""),
                *[str(alias) for alias in item.get("aliases") or ()],
            ]
        ).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score and (best is None or score > best[0]):
            best = (score, item)
    return best[1] if best else None


def _context_summary(context_used: dict) -> dict:
    return {
        "tokens_estimate": context_used.get("tokens_estimate"),
        "truncated": context_used.get("truncated"),
        "concepts": len(context_used.get("concepts") or ()),
        "mappings": len(context_used.get("mappings") or ()),
        "processes": len(context_used.get("processes") or ()),
        "systems": len(context_used.get("systems") or ()),
        "memories": len(context_used.get("memories") or ()),
    }


_FOLLOWUPS: tuple[str, ...] = (
    "¿Qué procesos usan esta entidad?",
    "¿Qué fuente manda sobre ella?",
    "¿Qué se vería afectado si cambia?",
    "¿Qué conocimiento falta?",
)


__all__ = [
    "CompanyAnswer",
    "CompanyAskService",
    "CompanyIntent",
    "INTENT_CRITERIA",
    "AskEvidence",
    "lexical_intent",
    "question_tokens",
]
