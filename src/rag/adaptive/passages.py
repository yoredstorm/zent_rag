# =============================================================================
# Passage Judge — JEV juzga passages individuales SÓLO donde hace falta.
# =============================================================================
# Capa opcional entre retrieval/rerank y generación. Determinístico primero:
#   - reglas fuertes (structured / exact match / score alto) no van a JEV;
#   - injection se detecta por patrón antes de cualquier llamada;
#   - JEV trabaja sólo en zona incierta, top candidatos, conflictos y casos
#     sensibles, con preguntas atómicas independientes por passage.
#
# JEV no decide la etiqueta final: el código compone KEEP / DROP_IRRELEVANT /
# DROP_WEAK / FLAG_CONTRADICTION / DROP_INJECTION a partir de las respuestas.
# Un passage con instrucciones sospechosas NUNCA entra al contexto del LLM:
# se mantiene como evidencia textual sanitizada/etiquetada si hace falta.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.core.domain.adaptive import EvidenceItem, EvidenceQuality, EvidenceSet
from src.decision.batch import build_post_retrieval_questions, noul_for
from src.decision.judgment import PHASE_POST_RETRIEVAL, JudgmentContext, call_phase_judge
from src.rag.adaptive.settings import AdaptiveRagSettings

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
_URL_RE = re.compile(r"https?://\S+", re.I)
_ACTION_WORDS_RE = re.compile(
    r"(envi|env[ií]|compart|revel|ignor|olvid|ejecut|call|post|fetch|send|share|reveal|ignore)",
    re.I,
)

# Patrones de instrucciones dirigidas al asistente dentro de un documento.
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.I),
    re.compile(r"disregard\s+(prior|previous|all)\s+(instructions?|prompts?)", re.I),
    re.compile(r"forget\s+everything", re.I),
    re.compile(r"system\s*prompt\s*:", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions)", re.I),
    re.compile(r"(send|share|exfiltrate)\s+(the\s+)?(credentials?|passwords?|api\s*keys?|tokens?)", re.I),
    re.compile(r"call\s+(this\s+)?(url|endpoint|webhook)", re.I),
    re.compile(r"<<\s*SYS\s*>>", re.I),
    re.compile(r"\[INST\].*\[/INST\]", re.I | re.S),
    re.compile(r"you\s+are\s+now\s+(DAN|an?\s+unfiltered)", re.I),
    # Español (el corpus del producto es es-first).
    re.compile(r"ignor[aá]\s+(todas?\s+)?(las\s+)?(instrucciones|indicaciones)", re.I),
    re.compile(r"(olvid[aá]|omit[aá])\s+(todas?\s+)?(las\s+)?(instrucciones|reglas)", re.I),
    re.compile(
        r"(envi[aá]|env[ií]e|compart[ae]|revel[aá])\s+(las?\s+)?"
        r"(credenciales?|contrase[nñ]as?|claves?|tokens?|prompt|instrucciones?)",
        re.I,
    ),
]

_REDACTED = "[contenido omitido: posible prompt injection]"


class PassageVerdict(StrEnum):
    KEEP = "KEEP"
    DROP_IRRELEVANT = "DROP_IRRELEVANT"
    DROP_WEAK = "DROP_WEAK"
    FLAG_CONTRADICTION = "FLAG_CONTRADICTION"
    DROP_INJECTION = "DROP_INJECTION"


def has_injection_indicators(text: str) -> bool:
    """Detección determinística. Reutiliza los patrones del policy de agentes."""
    try:
        from src.agents.policies.authorization import has_injection_indicators as _shared

        if _shared(text):
            return True
    except Exception:  # noqa: BLE001 — policy opcional, patrones locales igual corren
        pass
    return any(pattern.search(text or "") for pattern in _INJECTION_PATTERNS)


def sanitize_passage(text: str) -> tuple[str, int]:
    """Redacta líneas con instrucciones sospechosas. Devuelve (texto, redactados)."""
    redacted = 0
    lines: list[str] = []
    for line in (text or "").splitlines() or [""]:
        if _is_injection_sentence(line):
            lines.append(_REDACTED)
            redacted += 1
        else:
            lines.append(line)
    return "\n".join(lines), redacted


def _is_injection_sentence(sentence: str) -> bool:
    if not sentence.strip():
        return False
    if has_injection_indicators(sentence):
        return True
    # URL + verbo de acción en el mismo tramo: sospechoso aunque no matchee patrón.
    return bool(_URL_RE.search(sentence) and _ACTION_WORDS_RE.search(sentence))


def sanitize_for_evidence(text: str) -> tuple[str, int]:
    """Sanitiza por oración (los chunks suelen ser una sola línea)."""
    redacted = 0
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        if _is_injection_sentence(sentence):
            out.append(_REDACTED)
            redacted += 1
        else:
            out.append(sentence)
    return " ".join(part for part in out if part).strip(), redacted


@dataclass
class PassageJudgment:
    """Estado por passage: determinístico primero, JEV sólo si hizo falta."""

    index: int
    item: EvidenceItem
    verdict: str = PassageVerdict.KEEP.value
    relevant: bool | None = None
    usable: bool | None = None
    contradicts: bool | None = None
    injection: bool | None = None
    injection_deterministic: bool = False
    jev_used: bool = False
    sanitized: bool = False
    reason: str = ""

    @property
    def dropped(self) -> bool:
        return self.verdict in {
            PassageVerdict.DROP_IRRELEVANT.value,
            PassageVerdict.DROP_WEAK.value,
            PassageVerdict.DROP_INJECTION.value,
        }

    @property
    def flagged(self) -> bool:
        return self.verdict in {
            PassageVerdict.FLAG_CONTRADICTION.value,
            PassageVerdict.DROP_INJECTION.value,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Sin contenido completo: ids, etiqueta y señales atómicas."""
        return {
            "index": self.index,
            "verdict": self.verdict,
            "relevant": self.relevant,
            "usable": self.usable,
            "contradicts": self.contradicts,
            "injection": self.injection,
            "injection_suspected": bool(self.injection or self.injection_deterministic),
            "jev_used": self.jev_used,
            "sanitized": self.sanitized,
            "reason": self.reason,
            "document_id": self.item.document_id,
            "chunk_id": self.item.chunk_id,
            "score": round(float(self.item.score or 0.0), 4),
            "citation": self.item.citation,
        }


@dataclass
class PassageSelection:
    """Candidatos preseleccionados por reglas + estado determinístico."""

    items: list[EvidenceItem]
    candidates: list[EvidenceItem] = field(default_factory=list)
    judgments: list[PassageJudgment] = field(default_factory=list)
    zone: str = "empty"
    deterministic_skips: int = 0
    reasons: dict[int, str] = field(default_factory=dict)

    def candidate_index(self, item: EvidenceItem) -> int | None:
        for index, candidate in enumerate(self.candidates):
            if candidate is item:
                return index
        return None

    def apply_jev_answers(self, payload: Any) -> None:
        """Compone etiquetas desde preguntas atómicas. Nunca ejecuta nada."""
        for index, candidate in enumerate(self.candidates):
            judgment = next(
                (j for j in self.judgments if j.index == self.candidate_index(candidate)),
                None,
            )
            if judgment is None:
                continue
            relevant = noul_for(payload, f"passage_{index}_relevant", default=None)
            usable = noul_for(payload, f"passage_{index}_usable", default=None)
            contradicts = noul_for(payload, f"passage_{index}_contradicts", default=None)
            injection = noul_for(payload, f"passage_{index}_injection", default=None)
            if relevant is None and usable is None and contradicts is None and injection is None:
                continue
            judgment.jev_used = True
            judgment.relevant = None if relevant is None else relevant >= 0.5
            judgment.usable = None if usable is None else usable >= 0.5
            judgment.contradicts = None if contradicts is None else contradicts >= 0.5
            # La inyección determinística no se desmiente con JEV.
            if injection is not None:
                judgment.injection = (
                    True if judgment.injection_deterministic else injection >= 0.5
                )
            _compose(judgment)

    def result(self) -> "PassageJudgeResult":
        return PassageJudgeResult(
            judgments=list(self.judgments),
            items=list(self.items),
            candidates=list(self.candidates),
            zone=self.zone,
            deterministic_skips=self.deterministic_skips,
            answers={},
        )


@dataclass
class PassageJudgeResult:
    judgments: list[PassageJudgment] = field(default_factory=list)
    items: list[EvidenceItem] = field(default_factory=list)
    candidates: list[EvidenceItem] = field(default_factory=list)
    zone: str = "empty"
    deterministic_skips: int = 0
    answers: dict[str, Any] = field(default_factory=dict)
    jev_used: bool = False

    @property
    def kept(self) -> list[PassageJudgment]:
        return [j for j in self.judgments if not j.dropped]

    @property
    def dropped(self) -> list[PassageJudgment]:
        return [j for j in self.judgments if j.dropped]

    @property
    def flagged(self) -> list[PassageJudgment]:
        return [j for j in self.judgments if j.flagged]

    @property
    def injection_suspected(self) -> int:
        return sum(1 for j in self.judgments if j.injection or j.injection_deterministic)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "jev_used": self.jev_used,
            "candidates": len(self.candidates),
            "deterministic_skips": self.deterministic_skips,
            "kept": len(self.kept),
            "dropped": len(self.dropped),
            "flagged": len(self.flagged),
            "injection_suspected": self.injection_suspected,
            "judgments": [j.to_public_dict() for j in self.judgments],
        }


def _compose(judgment: PassageJudgment) -> None:
    """Etiqueta final compuesta en código. Determinístico manda."""
    if judgment.injection or judgment.injection_deterministic:
        judgment.verdict = PassageVerdict.DROP_INJECTION.value
        judgment.reason = "prompt_injection"
        return
    if judgment.contradicts:
        judgment.verdict = PassageVerdict.FLAG_CONTRADICTION.value
        judgment.reason = "contradiction"
        return
    if judgment.relevant is False:
        judgment.verdict = PassageVerdict.DROP_IRRELEVANT.value
        judgment.reason = "irrelevant"
        return
    if judgment.usable is False:
        judgment.verdict = PassageVerdict.DROP_WEAK.value
        judgment.reason = "weak"
        return
    judgment.verdict = PassageVerdict.KEEP.value
    judgment.reason = judgment.reason or "ok"


def _strong_zone(quality: EvidenceQuality | None, settings: AdaptiveRagSettings) -> bool:
    """Regla determinística fuerte: no gastar JEV en evidencia ya resuelta."""
    if quality is None:
        return False
    if quality.reason in {"structured", "exact_match"}:
        return True
    return quality.sufficient and quality.score >= 0.75


def _weak_score(item: EvidenceItem, settings: AdaptiveRagSettings) -> bool:
    return float(item.score or 0.0) < max(0.05, settings.evidence_min_score * 0.5)


def _conflict_requested(query: str) -> bool:
    return bool(
        re.search(
            r"\b(compara|comparar|contradic|versus|vs\.?|difference|diferenc)\w*\b",
            query or "",
            re.IGNORECASE,
        )
    )


def select_passages(
    evidence: EvidenceSet,
    *,
    quality: EvidenceQuality | None,
    settings: AdaptiveRagSettings,
    max_candidates: int | None = None,
) -> PassageSelection:
    """Preselección determinística. Devuelve candidatos acotados para JEV."""
    items = list(evidence.items)
    selection = PassageSelection(items=items)
    if not items:
        return selection

    limit = max(1, int(max_candidates or settings.passage_judge_max or 5))
    strong = _strong_zone(quality, settings)
    selection.zone = "strong" if strong else "uncertain"

    candidates: list[EvidenceItem] = []
    for index, item in enumerate(items):
        judgment = PassageJudgment(index=index, item=item)
        sanitized_text, redacted = sanitize_for_evidence(item.content or "")
        if redacted:
            judgment.injection_deterministic = True
            judgment.sanitized = True
            judgment.reason = "deterministic_injection"
            item.content = sanitized_text
        if _is_weak(item, settings):
            judgment.verdict = PassageVerdict.DROP_WEAK.value
            judgment.reason = judgment.reason or "weak_score"
            judgment.usable = False
            selection.deterministic_skips += 1
            selection.judgments.append(judgment)
            continue
        selection.judgments.append(judgment)
        if judgment.injection_deterministic:
            # El passage sospechoso se juzga (y se mantiene fuera del prompt).
            _compose(judgment)
            candidates.append(item)
            continue
        if not settings.passage_judge_enabled:
            selection.deterministic_skips += 1
            _compose(judgment)
            continue
        if strong and not _conflict_requested(evidence.query):
            selection.deterministic_skips += 1
            judgment.reason = "strong_deterministic"
            _compose(judgment)
            continue
        candidates.append(item)

    # Acotar: mejores scores primero, sin perder los sospechosos de injection.
    if len(candidates) > limit:
        injection_first = [c for c in candidates if has_injection_indicators(c.content or "")]
        rest = [c for c in candidates if c not in injection_first]
        rest.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        candidates = (injection_first + rest)[:limit]
    selection.candidates = candidates
    return selection


def _is_weak(item: EvidenceItem, settings: AdaptiveRagSettings) -> bool:
    if item.source_type == "sql":
        return False
    return _weak_score(item, settings)


def apply_passages(
    evidence: EvidenceSet,
    selection: PassageSelection,
    *,
    retrieval: Any | None = None,
) -> PassageJudgeResult:
    """Aplica el veredicto: drops fuera del contexto, flags etiquetados.

    - DROP_*: se quitan de la evidencia y del retrieval_context (nunca al LLM).
    - FLAG_CONTRADICTION: se mantiene pero etiquetado para la política final.
    - DROP_INJECTION: fuera del prompt; queda como evidencia textual sanitizada
      en metadata (`injection_suspected=true`), sin secretos.
    """
    result = selection.result()
    dropped_items: set[int] = set()
    for judgment in result.judgments:
        if not judgment.dropped:
            continue
        dropped_items.add(judgment.index)
        if judgment.verdict == PassageVerdict.DROP_INJECTION.value:
            judgment.item.metadata["injection_suspected"] = "true"
            judgment.item.metadata["injection_verdict"] = "DROP_INJECTION"
    if dropped_items:
        kept: list[EvidenceItem] = []
        for index, item in enumerate(evidence.items):
            if index in dropped_items:
                if item.metadata.get("injection_suspected") == "true":
                    # Evidencia textual sanitizada: fuera del prompt, visible en traza.
                    kept.append(item)
                continue
            kept.append(item)
        evidence.items = kept
    if retrieval is not None:
        chunks = list(getattr(retrieval, "chunks", None) or [])
        if dropped_items and chunks:
            retrieval.chunks = [
                chunk
                for index, chunk in enumerate(chunks)
                if index not in dropped_items
            ]
    _record_metrics(result)
    return result


def summarize(selection: PassageSelection) -> dict[str, Any]:
    """Resumen para el evidence gate: relevancia, contradicciones, injection."""
    candidate_ids = {id(c) for c in selection.candidates}
    judged = [j for j in selection.judgments if id(j.item) in candidate_ids]
    relevant_yes = sum(1 for j in judged if j.relevant is True)
    return {
        "judged": len(judged),
        "kept": sum(1 for j in selection.judgments if not j.dropped),
        "dropped": sum(1 for j in selection.judgments if j.dropped),
        "passage_relevance": (relevant_yes / len(judged)) if judged else 0.0,
        "contradictions": sum(
            1
            for j in selection.judgments
            if j.contradicts or j.verdict == PassageVerdict.FLAG_CONTRADICTION.value
        ),
        "injection_suspected": sum(
            1 for j in selection.judgments if j.injection or j.injection_deterministic
        ),
    }


def _record_metrics(result: PassageJudgeResult) -> None:
    try:
        import src.infrastructure.observability.metrics as m

        for judgment in result.judgments:
            m.zent_adaptive_passage_judge_total.labels(verdict=judgment.verdict).inc()
        if result.injection_suspected:
            m.zent_adaptive_injection_suspected_total.labels(stage="passage").inc(
                result.injection_suspected
            )
    except Exception:  # noqa: BLE001
        pass


async def judge_passages(
    evidence: EvidenceSet,
    *,
    judge: Any,
    settings: AdaptiveRagSettings,
    quality: EvidenceQuality | None = None,
    selection: PassageSelection | None = None,
    organization_id: UUID | None = None,
    request_id: UUID | None = None,
    cache: Any = None,
) -> PassageJudgeResult:
    """Ejecuta la fase POST_RETRIEVAL para los candidatos (sin evidence gate).

    El evidence gate comparte la misma llamada cuando está habilitado; acá se
    usa para caminos sin gate (p. ej. evidence ya determinísticamente fuerte).
    """
    chosen = selection or select_passages(
        evidence, quality=quality, settings=settings
    )
    if not chosen.candidates or judge is None or not settings.passage_judge_enabled:
        return chosen.result()
    state = passage_state(evidence, chosen)
    questions = build_post_retrieval_questions(passages=chosen.candidates).to_jevy()
    try:
        payload = await call_phase_judge(
            judge,
            phase=PHASE_POST_RETRIEVAL,
            state=state,
            questions=questions,
            context=JudgmentContext(
                phase=PHASE_POST_RETRIEVAL,
                organization_id=organization_id,
                request_id=request_id,
            ),
            cache=cache,
        )
    except Exception:  # noqa: BLE001 — el passage judge nunca rompe el request
        payload = None
    if isinstance(payload, dict):
        chosen.apply_jev_answers(payload)
        result = chosen.result()
        result.answers = {
            key: value
            for key, value in (payload.get("answers") or {}).items()
            if str(key).startswith("passage_")
        }
        result.jev_used = True
        return result
    return chosen.result()


def passage_state(evidence: EvidenceSet, selection: PassageSelection) -> dict[str, Any]:
    """State compartido de la fase: request + candidatos numerados.

    El preview usa contenido ya sanitizado: una inyección nunca vuelve como
    instrucción ni siquiera al propio JEV.
    """
    lines: list[str] = []
    for index, item in enumerate(selection.candidates):
        snippet = " ".join((item.content or "").split())[:600]
        lines.append(f"[{index}] {snippet}")
    preview = "\n".join(lines)[:4000]
    return {
        "user_request": (evidence.query or "")[:2000],
        "passage_candidates": preview,
        "evidence_preview": preview or evidence.preview(1500),
        "n_items": evidence.size,
    }
