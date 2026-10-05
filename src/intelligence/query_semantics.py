# =============================================================================
# Query semantics — QUÉ ES cada token de la pregunta (no sólo su forma)
# =============================================================================
# El contrato viejo: «si la cadena no aparece literalmente en una fuente, no
# puedo responder». El contrato nuevo separa:
#
#   SOURCE_REQUIREMENT / RULE_REQUIREMENT / FIELD_REQUIREMENT
#       premisas del DOMINIO: deben estar respaldadas por evidencia.
#   USER_INPUT / USER_EXAMPLE / RUNTIME_VALUE / RUNTIME_PATTERN / RUNTIME_PARAMETER
#       datos del ESCENARIO: se aplican contra las premisas; no se buscan.
#   REFERENCE / DOMAIN_ENTITY / OPTIONAL_CONTEXT
#       contexto citado: documentable sólo cuando se pregunta por él.
#
# La FORMA del token (3-8 mayúsculas, código mixto, máscara) es una feature,
# nunca la autoridad final: el mismo `FCLAS` es FIELD_REQUIREMENT en un contexto
# y `ASDFGRE` es USER_INPUT en otro aunque compartan la misma silueta.
#
# Determinista primero (cues + posición + relaciones + intención). El LLM sólo
# entra si el clasificador determinista queda por debajo del umbral Y el
# llamador lo habilita (una única llamada estructurada, sin cadena de pensamiento).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any, Iterable, Sequence

from src.intelligence.response.anchors import Anchor

QUERY_SEMANTICS_VERSION = "query-semantics-1"

#: Umbral por debajo del cual se permite (nunca obliga) una clasificación LLM.
DEFAULT_LLM_THRESHOLD = 0.55


class QueryIntent(StrEnum):
    """Qué OPERACIÓN pide la pregunta. Las operaciones no son búsquedas."""

    LOOKUP = "LOOKUP"
    SOURCE_LOOKUP = "SOURCE_LOOKUP"
    DEFINITION = "DEFINITION"
    EXPLAIN = "EXPLAIN"
    APPLY_RULE = "APPLY_RULE"
    VALIDATE = "VALIDATE"
    COMPARE = "COMPARE"
    CALCULATE = "CALCULATE"
    TRANSFORM = "TRANSFORM"
    INFER = "INFER"
    TRACE = "TRACE"
    SUMMARIZE = "SUMMARIZE"


#: Intenciones que NO deben comportarse como búsquedas literales.
REASONING_INTENTS: frozenset[str] = frozenset(
    {
        QueryIntent.APPLY_RULE.value,
        QueryIntent.VALIDATE.value,
        QueryIntent.CALCULATE.value,
        QueryIntent.COMPARE.value,
        QueryIntent.TRANSFORM.value,
        QueryIntent.INFER.value,
    }
)

#: Intenciones que exigen evidencia textual (lookup/definición).
SOURCE_INTENTS: frozenset[str] = frozenset(
    {
        QueryIntent.LOOKUP.value,
        QueryIntent.SOURCE_LOOKUP.value,
        QueryIntent.DEFINITION.value,
        QueryIntent.EXPLAIN.value,
    }
)


class QuerySemanticRole(StrEnum):
    """Rol semántico de un objeto de la consulta (independiente del lexical_kind)."""

    # --- premisas del dominio: evidence_required=True ---------------------
    SOURCE_REQUIREMENT = "SOURCE_REQUIREMENT"
    RULE_REQUIREMENT = "RULE_REQUIREMENT"
    FIELD_REQUIREMENT = "FIELD_REQUIREMENT"
    DEFINITION_REQUIREMENT = "DEFINITION_REQUIREMENT"
    REFERENCE = "REFERENCE"
    DOMAIN_ENTITY = "DOMAIN_ENTITY"
    # --- datos del escenario: evidence_required=False ---------------------
    USER_INPUT = "USER_INPUT"
    USER_EXAMPLE = "USER_EXAMPLE"
    RUNTIME_VALUE = "RUNTIME_VALUE"
    RUNTIME_PATTERN = "RUNTIME_PATTERN"
    RUNTIME_PARAMETER = "RUNTIME_PARAMETER"
    OPTIONAL_CONTEXT = "OPTIONAL_CONTEXT"


#: Roles que exigen aparición/semántica documental.
DOCUMENTABLE_SEMANTIC_ROLES: frozenset[str] = frozenset(
    {
        QuerySemanticRole.SOURCE_REQUIREMENT.value,
        QuerySemanticRole.RULE_REQUIREMENT.value,
        QuerySemanticRole.FIELD_REQUIREMENT.value,
        QuerySemanticRole.DEFINITION_REQUIREMENT.value,
        QuerySemanticRole.REFERENCE.value,
        QuerySemanticRole.DOMAIN_ENTITY.value,
    }
)

#: Roles de escenario: jamás cuentan como evidencia faltante.
RUNTIME_ROLES: frozenset[str] = frozenset(
    {
        QuerySemanticRole.USER_INPUT.value,
        QuerySemanticRole.USER_EXAMPLE.value,
        QuerySemanticRole.RUNTIME_VALUE.value,
        QuerySemanticRole.RUNTIME_PATTERN.value,
        QuerySemanticRole.RUNTIME_PARAMETER.value,
        QuerySemanticRole.OPTIONAL_CONTEXT.value,
    }
)


def is_documentable_semantic_role(role: str) -> bool:
    return str(role or "") in DOCUMENTABLE_SEMANTIC_ROLES


def is_runtime_semantic_role(role: str) -> bool:
    return str(role or "") in RUNTIME_ROLES


@dataclass(frozen=True, kw_only=True)
class QuerySemanticObject:
    """Un valor de la consulta con su rol contextual y sus exigencias."""

    value: str
    lexical_kind: str
    semantic_role: str
    semantic_type: str = ""
    evidence_required: bool = False
    runtime_value: bool = False
    requires_semantics: tuple[str, ...] = ()
    field_scope: str = ""
    confidence: float = 1.0
    decided_by: str = "deterministic"
    cues: tuple[str, ...] = ()

    @property
    def documentable(self) -> bool:
        return bool(self.evidence_required) and is_documentable_semantic_role(
            self.semantic_role
        )

    @property
    def runtime(self) -> bool:
        return self.runtime_value or is_runtime_semantic_role(self.semantic_role)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "value": self.value,
            "lexical_kind": self.lexical_kind,
            "semantic_role": self.semantic_role,
            "evidence_required": self.evidence_required,
            "runtime_value": self.runtime_value,
            "confidence": round(float(self.confidence), 4),
            "decided_by": self.decided_by,
        }
        if self.semantic_type:
            payload["semantic_type"] = self.semantic_type
        if self.requires_semantics:
            payload["requires_semantics"] = list(self.requires_semantics)
        if self.field_scope:
            payload["field_scope"] = self.field_scope
        if self.cues:
            payload["cues"] = list(self.cues[:4])
        return payload


@dataclass(frozen=True, kw_only=True)
class QuerySemantics:
    """Interpretación semántica completa de la pregunta."""

    question: str
    intent: str
    intent_confidence: float
    objects: tuple[QuerySemanticObject, ...] = ()
    decided_by: str = "deterministic"
    version: str = QUERY_SEMANTICS_VERSION

    @property
    def runtime_inputs(self) -> tuple[QuerySemanticObject, ...]:
        return tuple(
            obj
            for obj in self.objects
            if obj.semantic_role
            in (
                QuerySemanticRole.USER_INPUT.value,
                QuerySemanticRole.USER_EXAMPLE.value,
                QuerySemanticRole.RUNTIME_VALUE.value,
                QuerySemanticRole.RUNTIME_PARAMETER.value,
            )
        )

    @property
    def runtime_patterns(self) -> tuple[QuerySemanticObject, ...]:
        return tuple(
            obj
            for obj in self.objects
            if obj.semantic_role == QuerySemanticRole.RUNTIME_PATTERN.value
        )

    @property
    def field_requirements(self) -> tuple[QuerySemanticObject, ...]:
        return tuple(
            obj
            for obj in self.objects
            if obj.semantic_role == QuerySemanticRole.FIELD_REQUIREMENT.value
        )

    @property
    def documentable_objects(self) -> tuple[QuerySemanticObject, ...]:
        return tuple(obj for obj in self.objects if obj.documentable)

    @property
    def requires_reasoning(self) -> bool:
        return self.intent in REASONING_INTENTS

    def by_role(self, role: str) -> tuple[QuerySemanticObject, ...]:
        return tuple(obj for obj in self.objects if obj.semantic_role == role)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "intent": self.intent,
            "intent_confidence": round(float(self.intent_confidence), 4),
            "decided_by": self.decided_by,
            "objects": [obj.to_public_dict() for obj in self.objects[:16]],
            "runtime_inputs": [obj.value for obj in self.runtime_inputs[:8]],
            "runtime_patterns": [obj.value for obj in self.runtime_patterns[:8]],
            "field_requirements": [obj.value for obj in self.field_requirements[:8]],
            "documentable": [obj.value for obj in self.documentable_objects[:12]],
        }


# -----------------------------------------------------------------------------
# Cues deterministas (ES/EN). Chicos a propósito: lo obvio por regla.
# -----------------------------------------------------------------------------

#: El valor ES dato del escenario (llega, se posee, se declara).
_RUNTIME_ARRIVAL_RE = re.compile(
    r"(?:\b(?:me\s+(?:viene|llega|lleg[oó]|dan|entregan|env[ií]an|mandan|"
    r"devolvi[oó]|retorn[oó])|"
    r"recib[ií]|recibo|tengo|tengo\s+el|"
    r"en\s+(?:el|la|mi)\s+(?:boleto|ticket|registro|record|sistema|pedido|archivo|"
    r"documento|tabla)\s+(?=[A-Z0-9&*?%#])[A-Za-z0-9&*?%#_-]{2,}|"
    r"en\s+el\s+(?:boleto|ticket|registro|record|sistema|pedido|archivo|documento)\s+"
    r"(?:viene|dice|aparece|figura)|"
    r"viene\s+(?:as[ií]|como)|viene\s+con|el\s+valor\s+(?:que\s+)?(?:tengo|recib[ií]|me\s+dan)|"
    r"dato\s+(?:del?\s+)?(?:usuario|entrada)|"
    r"i\s+(?:got|received|have)|comes?\s+as|shows?\s+as)\b)",
    re.IGNORECASE,
)

#: Posesión/atribución directa («mi farebasis ASDFGRE», «mi código es X»).
_POSSESSION_RE = re.compile(
    r"(?:\b(?:mi|mis|nuestro|nuestra)\s+\w{0,24}\s*(?:es|=|:)?\s*|"
    r"\b(?:el|la)\s+valor\s+de\s+\w{0,24}\s*(?:es|=|:)?\s*|"
    r"\b(?:c[oó]digo|valor|dato|input|entrada)\s+(?:es|=|:)\s*)",
    re.IGNORECASE,
)

#: «por ejemplo», «ejemplo:» → user example.
_USER_EXAMPLE_RE = re.compile(
    r"(?:\b(?:por\s+ejemplo|ejemplo|p\.?\s*ej\.?|for\s+example|e\.g\.)\s*:?\s*)",
    re.IGNORECASE,
)

#: El usuario pregunta si algo aparece LITERALMENTE en la fuente.
_SOURCE_LOOKUP_RE = re.compile(
    r"(?:\b(?:aparece|figura|menciona|contiene|incluye|"
    r"est[aá]\s+(?:en|dentro)|se\s+encuentra|"
    r"literal(?:mente)?|textual(?:mente)?|en\s+(?:el|los)\s+(?:documento|documentos|"
    r"fuente|fuentes|pdf|manual)|d[oó]nde\s+(?:est[aá]|aparece|dice)|"
    r"busca(?:r)?\s+en\s+(?:el\s+)?documento|"
    r"does\s+it\s+appear|is\s+it\s+in\s+the|find\s+in\s+the|"
    r"does\s+the\s+(?:document|source|text)\s+(?:mention|contain|include))\b)",
    re.IGNORECASE,
)

#: Pregunta por definición/significado del propio token.
_DEFINITION_RE = re.compile(
    r"(?:\b(?:qu[eé]\s+significa|qu[eé]\s+es|significado\s+de|define|"
    r"definici[oó]n\s+de|explica(?:me)?|c[oó]mo\s+funciona|"
    r"what\s+does\s+.+?\s+mean|what\s+is|define|explain)\b)",
    re.IGNORECASE,
)

#: Contexto explícito de campo («el campo FCLAS», «FCLAS del record»).
_FIELD_CONTEXT_RE = re.compile(
    r"(?:\b(?:campo|field|columna|column|variable|atributo|attribute|"
    r"record|registro|layout|estructura|structure)\b)",
    re.IGNORECASE,
)

#: El token es la contraparte contra la que se prueba un valor.
_APPLICATION_RE = re.compile(
    r"(?:\b(?:contra|versus|vs\.?|compar[aá]|compare|coteja|cotejar|chequea|"
    r"chequear|valida\w*|cumpl\w*|acept\w*|matche\w*|coincid\w*|aplic\w*|"
    r"pass\w*|pasa\b|aprueba\w*|"
    r"corresponde|match(?:es|ea)?|against|does\s+it\s+match)\b)",
    re.IGNORECASE,
)

#: Operación aritmética / fórmula.
_CALCULATE_RE = re.compile(
    r"(?:\b(?:cu[aá]nto\s+(?:es|vale|da|ser[ií]a|sale)|calcula|calcular|"
    r"total|suma(?:r)?|resta(?:r)?|multiplica(?:r)?|divide(?:r)?|promedio|"
    r"precio\s+final|monto\s+final|fee|tarifa\s+final|impuesto|"
    r"aplica\s+la\s+f[oó]rmula|formula|f[oó]rmula|"
    r"what\s+is\s+the\s+total|calculate|compute)\b)",
    re.IGNORECASE,
)

#: Comparación explícita.
_COMPARE_RE = re.compile(
    r"(?:\b(?:compara|comparar|diferencia|mayor\s+que|menor\s+que|"
    r"es\s+mayor|es\s+menor|>=|<=|>|<|versus|vs\.?|better\s+than)\b)",
    re.IGNORECASE,
)

#: Transformación de cadenas.
_TRANSFORM_RE = re.compile(
    r"(?:\b(?:conviert[ea]|convertir|transforma(?:r)?|formatea(?:r)?|"
    r"normaliza(?:r)?|traduce\s+a|convert\s+to|format\s+as)\b)",
    re.IGNORECASE,
)

#: Inferencia explícita.
_INFER_RE = re.compile(
    r"(?:\b(?:se\s+deduce|se\s+concluye|se\s+infiere|se\s+desprende|"
    r"implica|por\s+lo\s+tanto|en\s+consecuencia|derivar|derive|infer)\b)",
    re.IGNORECASE,
)

#: Trazabilidad.
_TRACE_RE = re.compile(
    r"(?:\b(?:c[oó]mo\s+llegaste|c[oó]mo\s+obtuviste|de\s+d[oó]nde\s+sacaste|"
    r"traza(?:r)?|trace|muestra\s+el\s+razonamiento)\b)",
    re.IGNORECASE,
)

#: Resumen.
_SUMMARIZE_RE = re.compile(
    r"(?:\b(?:resume|resumen|sintetiza|summarize|summary)\b)",
    re.IGNORECASE,
)

#: Comodines de patrón (mismo alfabeto que anchors).
_PATTERN_SYMBOLS = "&*?%#$@!~^"

#: Cues de longitud/posición alrededor del patrón (para requirements derivados).
_PATTERN_LENGTH_CUE_RE = re.compile(
    r"\b(?:tama[nñ]o|longitud|length|posiciones|positions|caracteres|characters)\b",
    re.IGNORECASE,
)


def detect_query_intent(question: str) -> tuple[str, float]:
    """Intención determinista con confianza discreta (no inventa probabilidad)."""
    text = str(question or "")
    if not text.strip():
        return QueryIntent.LOOKUP.value, 0.4
    checks: tuple[tuple[str, re.Pattern[str], float], ...] = (
        (QueryIntent.SOURCE_LOOKUP.value, _SOURCE_LOOKUP_RE, 0.9),
        (QueryIntent.TRACE.value, _TRACE_RE, 0.9),
        (QueryIntent.CALCULATE.value, _CALCULATE_RE, 0.85),
        (QueryIntent.COMPARE.value, _COMPARE_RE, 0.8),
        (QueryIntent.TRANSFORM.value, _TRANSFORM_RE, 0.8),
        (QueryIntent.INFER.value, _INFER_RE, 0.75),
        (QueryIntent.SUMMARIZE.value, _SUMMARIZE_RE, 0.8),
        (QueryIntent.DEFINITION.value, _DEFINITION_RE, 0.85),
        (QueryIntent.APPLY_RULE.value, _APPLICATION_RE, 0.8),
    )
    for intent, pattern, confidence in checks:
        if pattern.search(text):
            if intent == QueryIntent.APPLY_RULE.value:
                return classify_validate_vs_apply(text), confidence
            return intent, confidence
    return QueryIntent.LOOKUP.value, 0.6


def classify_validate_vs_apply(question: str) -> str:
    """APPLY_RULE vs VALIDATE: «¿cumple?» pregunta por un resultado concreto."""
    if re.search(
        r"\b(cumpl\w*|acept\w*|v[aá]lid\w*|valid\w*|pass\w*|aprueba\w*|pasa\b|"
        r"matche\w*|match(?:es|ea)?|aplic\w*|coincid\w*)\b",
        question or "",
        re.IGNORECASE,
    ):
        return QueryIntent.VALIDATE.value
    return QueryIntent.APPLY_RULE.value


def _window(question: str, value: str, *, before: int = 56, after: int = 24) -> str:
    """Ventana de contexto alrededor de la PRIMERA aparición del valor."""
    text = question or ""
    if not value:
        return ""
    index = text.lower().find(value.lower())
    if index < 0:
        return ""
    start = max(0, index - before)
    end = min(len(text), index + len(value) + after)
    return text[start:end]


def _field_window(question: str, value: str) -> str:
    """Ventana ESTRECHA para detectar contexto de campo (evita «record» lejano)."""
    return _window(question, value, before=18, after=6)


def _cues_matched(window: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0).strip() for match in pattern.finditer(window or "")))


def _has_pattern_symbols(value: str) -> bool:
    return any(char in _PATTERN_SYMBOLS for char in (value or ""))


_CONTRA_RE = re.compile(r"(?:contra|versus|vs\.?|against)", re.IGNORECASE)


def _assigned_value(question: str, value: str) -> bool:
    """¿El token es el valor de una asignación («account=12345678»)?"""
    if not value:
        return False
    v = re.escape(value)
    return bool(
        re.search(rf"(?:=|:)\s*{v}(?:$|[\s,.;?)])", question or "", re.IGNORECASE)
    )


def _followed_by_contra(question: str, value: str) -> bool:
    """¿El token está ANTES de la contraparte? («X contra &&&F»)"""
    if not value:
        return False
    return bool(
        re.search(
            rf"(?:^|[\s(]){re.escape(value)}\s*(?:contra|versus|vs\.?|against)\s",
            question or "",
            re.IGNORECASE,
        )
    )


def _adjacent_to_mask(question: str, value: str) -> bool:
    """¿El token está pegado al patrón? («FCLAS &&&F»: es el CAMPO, no el valor)."""
    if not value:
        return False
    v = re.escape(value)
    return bool(
        re.search(rf"(?:^|[\s(]){v}\s*[&*?%#@!~^]", question or "", re.IGNORECASE)
        or re.search(
            rf"[&*?%#@!~^]\S*\s+{v}(?:$|[\s,.;?)])",
            question or "",
            re.IGNORECASE,
        )
    )


def _compared_against(question: str, value: str) -> bool:
    """¿El token está enfrentado explícitamente a una regla/patrón? («X contra Y»)"""
    if not value:
        return False
    v = re.escape(value)
    return bool(
        re.search(rf"(?:^|[\s(]){v}\s*(?:contra|versus|vs\.?|against)\s", question, re.IGNORECASE)
        or re.search(
            rf"(?:contra|versus|vs\.?|against)\s+{v}(?:$|[\s,.;?)])",
            question,
            re.IGNORECASE,
        )
    )


@dataclass(frozen=True)
class _ClassificationContext:
    question: str
    intent: str
    apply_intent: str
    field_values: frozenset[str]
    runtime_values: frozenset[str]
    mask_values: frozenset[str]
    mask_field_adjacent: bool = False


def _classify_anchor(anchor: Anchor, ctx: _ClassificationContext) -> QuerySemanticObject:
    value = str(anchor.value or "").strip()
    kind = str(anchor.kind or "")
    window = _window(ctx.question, value)
    arrival = _cues_matched(window, _RUNTIME_ARRIVAL_RE)
    possession = _cues_matched(window, _POSSESSION_RE)
    example = _cues_matched(window, _USER_EXAMPLE_RE)
    source_lookup = _cues_matched(window, _SOURCE_LOOKUP_RE)
    definition = _cues_matched(window, _DEFINITION_RE)
    application = _cues_matched(window, _APPLICATION_RE)
    runtime_cues = (*arrival, *possession)
    is_runtime_ctx = bool(runtime_cues) or bool(example)

    def _obj(
        role: str,
        *,
        semantic_type: str = "",
        requires: tuple[str, ...] = (),
        evidence_required: bool | None = None,
        runtime_value: bool | None = None,
        confidence: float = 0.9,
        field_scope: str = "",
        cues: tuple[str, ...] = (),
    ) -> QuerySemanticObject:
        if evidence_required is None:
            evidence_required = role in DOCUMENTABLE_SEMANTIC_ROLES
        if runtime_value is None:
            runtime_value = role in RUNTIME_ROLES - {QuerySemanticRole.OPTIONAL_CONTEXT.value}
        return QuerySemanticObject(
            value=value,
            lexical_kind=kind,
            semantic_role=role,
            semantic_type=semantic_type,
            evidence_required=bool(evidence_required),
            runtime_value=bool(runtime_value),
            requires_semantics=requires,
            field_scope=field_scope,
            confidence=confidence,
            cues=(*cues, *runtime_cues)[:4] if cues or runtime_cues else (),
        )

    # 1. Forma máscara: puede ser definición documental o instancia de runtime.
    if kind == "mascara" or _has_pattern_symbols(value):
        if possession and _followed_by_contra(ctx.question, value):
            # «mi valor AB@C contra @@#C»: el token ANTES de la contraparte es
            # el VALOR del escenario, no el patrón.
            return _obj(
                QuerySemanticRole.USER_INPUT.value,
                semantic_type="runtime_input",
                confidence=0.88,
                cues=possession,
            )
        if arrival or possession:
            return _obj(
                QuerySemanticRole.RUNTIME_PATTERN.value,
                semantic_type="pattern_candidate",
                requires=pattern_semantic_requirements(value),
                confidence=0.93,
                cues=arrival,
            )
        if source_lookup or definition:
            return _obj(
                QuerySemanticRole.RULE_REQUIREMENT.value,
                semantic_type="pattern_definition",
                requires=pattern_semantic_requirements(value),
                confidence=0.9,
                cues=(*source_lookup, *definition),
            )
        if (
            ctx.apply_intent in REASONING_INTENTS
            and not ctx.field_values
            and not ctx.mask_field_adjacent
            and ctx.runtime_values
        ):
            # «mi valor ABCFXYZ contra &&&F»: el patrón es la contraparte de un
            # valor del escenario → instancia de runtime (semántica, no literal).
            return _obj(
                QuerySemanticRole.RUNTIME_PATTERN.value,
                semantic_type="pattern_application",
                requires=pattern_semantic_requirements(value),
                confidence=0.88,
                cues=application,
            )
        if ctx.apply_intent in REASONING_INTENTS and ctx.field_values:
            # «FCLAS &&&F acepta QNNF0SME»: el patrón acompaña al campo como
            # regla del campo (compat: RULE_ANCHOR), pero su semántica alcanza.
            return _obj(
                QuerySemanticRole.RULE_REQUIREMENT.value,
                semantic_type="field_pattern",
                requires=pattern_semantic_requirements(value),
                confidence=0.85,
                field_scope=next(iter(sorted(ctx.field_values)), ""),
                cues=application,
            )
        return _obj(
            QuerySemanticRole.RULE_REQUIREMENT.value,
            semantic_type="pattern_definition",
            requires=pattern_semantic_requirements(value),
            confidence=0.8,
        )

    # 2. El usuario pregunta si el token aparece literalmente: SOURCE_REQUIREMENT.
    if source_lookup:
        return _obj(
            QuerySemanticRole.SOURCE_REQUIREMENT.value,
            semantic_type="literal_presence",
            confidence=0.92,
            cues=source_lookup,
        )

    # 3. Pregunta por el significado del token: premise del dominio.
    if definition:
        return _obj(
            QuerySemanticRole.DEFINITION_REQUIREMENT.value,
            semantic_type="definition",
            confidence=0.9,
            cues=definition,
        )

    # 3b. Valor enfrentado explícitamente a un patrón/regla («X contra &&&F»):
    # es la entrada que se evalúa, no una premisa documental. Un CAMPO nombrado
    # («el campo FCLAS contra &&&F») no se convierte en valor por el «contra».
    if _compared_against(ctx.question, value) and not (
        kind == "sigla"
        and _FIELD_CONTEXT_RE.search(_field_window(ctx.question, value))
    ):
        return _obj(
            QuerySemanticRole.USER_INPUT.value,
            semantic_type="runtime_input",
            confidence=0.88,
            cues=("contra",),
        )

    # 4b. El token ES el valor de un parámetro con nombre («status ACTIVE»).
    if not is_runtime_ctx and any(
        match.group(2).strip().lower() == value.lower()
        for match in _KEYWORD_VALUE_RE.finditer(ctx.question)
    ):
        return _obj(
            QuerySemanticRole.RUNTIME_PARAMETER.value,
            semantic_type="parameter_value",
            confidence=0.85,
            cues=("keyword_value",),
        )

    # 4. Dato del escenario (posesión/llegada/ejemplo explícito).
    if example:
        return _obj(
            QuerySemanticRole.USER_EXAMPLE.value,
            semantic_type="example",
            confidence=0.9,
            cues=example,
        )
    if is_runtime_ctx:
        # Un dato del usuario nunca es una premisa; si el token parece campo
        # (contexto de campo ADYACENTE: «el campo FCLAS»), el campo manda aunque
        # otra parte de la oración tenga posesión.
        if kind == "sigla" and _FIELD_CONTEXT_RE.search(
            _field_window(ctx.question, value)
        ):
            return _obj(
                QuerySemanticRole.FIELD_REQUIREMENT.value,
                semantic_type="field",
                confidence=0.85,
                cues=arrival,
            )
        return _obj(
            QuerySemanticRole.USER_INPUT.value,
            semantic_type="runtime_input",
            confidence=0.9,
            cues=runtime_cues,
        )

    # 5. Códigos mixtos y siglas: dominio por defecto.
    if kind == "codigo":
        if _assigned_value(ctx.question, value):
            # «account=12345678»: el valor asignado es dato del escenario,
            # aunque parezca un identificador.
            return _obj(
                QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="assigned_value",
                confidence=0.85,
                cues=("assignment",),
            )
        if re.search(
            rf"{re.escape(value)}\s*(?:=|:)\s*\d", ctx.question
        ):
            # «tax_rate=0.18»: el nombre es el parámetro que el usuario aporta.
            return _obj(
                QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="parameter",
                confidence=0.85,
                cues=("assignment",),
            )
        if ctx.apply_intent in REASONING_INTENTS and (
            ctx.field_values or ctx.mask_values
        ):
            # Compat histórica: valor contra una regla/campo = entrada a evaluar.
            return _obj(
                QuerySemanticRole.USER_INPUT.value,
                semantic_type="runtime_input",
                confidence=0.8,
                cues=application,
            )
        return _obj(QuerySemanticRole.REFERENCE.value, semantic_type="identifier")
    if kind == "sigla":
        # Sigla enfrentada a un patrón en validación («ABCF cumple &&&F»): es el
        # valor a evaluar. Pegada al patrón («FCLAS &&&F») sigue siendo campo.
        if (
            ctx.apply_intent in REASONING_INTENTS
            and ctx.mask_values
            and not _adjacent_to_mask(ctx.question, value)
            and not _FIELD_CONTEXT_RE.search(_field_window(ctx.question, value))
        ):
            return _obj(
                QuerySemanticRole.USER_INPUT.value,
                semantic_type="runtime_input",
                confidence=0.8,
            )
        # Sin contexto que la ancle (campo, definición, runtime), una sigla es
        # AMBIGUA: candidata a campo con confianza baja. No se inventa el rol.
        return _obj(
            QuerySemanticRole.FIELD_REQUIREMENT.value,
            semantic_type="field_candidate",
            confidence=0.5,
        )
    if kind == "rango":
        return _obj(QuerySemanticRole.RULE_REQUIREMENT.value, semantic_type="range_rule")
    return _obj(QuerySemanticRole.REFERENCE.value)


class ContextualQueryRoleClassifier:
    """Clasificador de roles contextual: forma + posición + cues + intención.

    Entrada: pregunta + anchors (+ entidades, opcional).
    Salida: `QuerySemantics` con objetos tipados. Nunca lanza; fail-soft a los
    roles históricos por forma cuando algo falta.
    """

    def __init__(self, *, llm_threshold: float = DEFAULT_LLM_THRESHOLD) -> None:
        self._threshold = float(llm_threshold)

    @property
    def llm_threshold(self) -> float:
        return self._threshold

    def classify(
        self,
        question: str,
        anchors: Sequence[Anchor] = (),
        entities: Sequence[Any] = (),
        *,
        intent: str | None = None,
    ) -> QuerySemantics:
        text = str(question or "")
        anchor_list = list(anchors or ())
        if intent:
            resolved_intent, intent_confidence = str(intent), 0.95
        else:
            resolved_intent, intent_confidence = detect_query_intent(text)
            if resolved_intent == QueryIntent.APPLY_RULE.value:
                resolved_intent = classify_validate_vs_apply(text)

        # Pre-pasada: qué valores son claramente de campo / runtime, para que un
        # código mixto sepa contra qué se está evaluando.
        field_values: set[str] = set()
        mask_values: set[str] = set()
        runtime_values: set[str] = set()
        for anchor in anchor_list:
            value = str(anchor.value or "")
            if not value:
                continue
            window = _window(text, value)
            field_ctx = _field_window(text, value)
            if anchor.kind == "sigla" and _FIELD_CONTEXT_RE.search(field_ctx or ""):
                field_values.add(value)
            if anchor.kind == "mascara" or _has_pattern_symbols(value):
                mask_values.add(value)
            if _RUNTIME_ARRIVAL_RE.search(window or "") or _POSSESSION_RE.search(window or ""):
                runtime_values.add(value)
            if _compared_against(text, value):
                runtime_values.add(value)

        # Un valor del escenario enfrentado a un patrón en una operación de
        # validación («ABCF cumple &&&F»): es input, no campo. Se reconoce por
        # relación (patrón presente, token no pegado al patrón), no por forma.
        if resolved_intent in REASONING_INTENTS and mask_values:
            for anchor in anchor_list:
                value = str(anchor.value or "")
                if not value or _has_pattern_symbols(value):
                    continue
                if anchor.kind not in ("sigla", "codigo"):
                    continue
                if _adjacent_to_mask(text, value) or _compared_against(text, value):
                    continue
                if _FIELD_CONTEXT_RE.search(_field_window(text, value) or ""):
                    continue
                runtime_values.add(value)

        # «FCLAS &&&F»: el patrón acompaña al CAMPO (no es instancia de runtime).
        mask_field_adjacent = False
        if mask_values:
            for anchor in anchor_list:
                value = str(anchor.value or "")
                if (
                    anchor.kind == "sigla"
                    and value
                    and not _has_pattern_symbols(value)
                    and _adjacent_to_mask(text, value)
                ):
                    mask_field_adjacent = True
                    break

        # Sin verbo explícito («¿Resultado?»), si hay un patrón y un valor del
        # escenario la operación es APLICAR la regla, no buscar. Genérico: no
        # depende de palabras mágicas como «cumple».
        if (
            resolved_intent == QueryIntent.LOOKUP.value
            and mask_values
            and any(not _has_pattern_symbols(v) for v in runtime_values)
        ):
            resolved_intent = QueryIntent.APPLY_RULE.value
            intent_confidence = 0.75

        ctx = _ClassificationContext(
            question=text,
            intent=resolved_intent,
            apply_intent=resolved_intent,
            field_values=frozenset(field_values),
            runtime_values=frozenset(runtime_values),
            mask_values=frozenset(mask_values),
            mask_field_adjacent=mask_field_adjacent,
        )
        objects: list[QuerySemanticObject] = []
        seen: set[str] = set()
        for anchor in anchor_list:
            value = str(anchor.value or "").strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            provider_role = _provider_semantic_role(anchor)
            if provider_role:
                obj = QuerySemanticObject(
                    value=value,
                    lexical_kind=str(anchor.kind or ""),
                    semantic_role=provider_role,
                    semantic_type="provider",
                    evidence_required=provider_role in DOCUMENTABLE_SEMANTIC_ROLES,
                    runtime_value=provider_role in RUNTIME_ROLES,
                    requires_semantics=(
                        pattern_semantic_requirements(value)
                        if provider_role == QuerySemanticRole.RUNTIME_PATTERN.value
                        else ()
                    ),
                    confidence=1.0,
                    decided_by="provider",
                )
            else:
                obj = _classify_anchor(anchor, ctx)
            objects.append(obj)

        for entity in entities or ():
            value = str(getattr(entity, "label", entity) or "").strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            objects.append(
                QuerySemanticObject(
                    value=value,
                    lexical_kind="entidad",
                    semantic_role=QuerySemanticRole.DOMAIN_ENTITY.value,
                    semantic_type="entity",
                    evidence_required=True,
                    confidence=0.85,
                )
            )

        runtime_params = extract_runtime_parameters(text)
        param_keys: set[str] = set()
        for param in runtime_params:
            cue = str(param.cues[0]) if param.cues else ""
            key = f"{cue}={param.value}".lower()
            if key in param_keys:
                continue
            param_keys.add(key)
            if param.value.lower() in seen and cue not in ("", "tengo"):
                # Ya representado por un anchor con el mismo valor.
                continue
            objects.append(param)

        # Un número nombrado en una pregunta de búsqueda literal ES un
        # requirement de fuente («¿el documento menciona age 20?»): 20 debe
        # aparecer, no es dato del escenario.
        if resolved_intent == QueryIntent.SOURCE_LOOKUP.value:
            for match in re.finditer(r"\b\d{1,6}\b", text):
                value = match.group(0)
                if value.lower() in seen:
                    continue
                seen.add(value.lower())
                objects.append(
                    QuerySemanticObject(
                        value=value,
                        lexical_kind="numero",
                        semantic_role=QuerySemanticRole.SOURCE_REQUIREMENT.value,
                        semantic_type="literal_number",
                        evidence_required=True,
                        confidence=0.8,
                        cues=("source_lookup",),
                    )
                )

        confidence = min(
            [intent_confidence, *(obj.confidence for obj in objects)] or [intent_confidence]
        )
        return QuerySemantics(
            question=text,
            intent=resolved_intent,
            intent_confidence=intent_confidence,
            objects=tuple(objects),
            decided_by="deterministic" if confidence >= self._threshold else "low_confidence",
        )


def _provider_semantic_role(anchor: Anchor) -> str:
    """Rol declarado por un plugin de dominio, normalizado al vocabulario nuevo."""
    from src.rag.longcontext.roles import normalize_role

    declared = normalize_role(getattr(anchor, "role", "") or "")
    mapping = {
        "rule_anchor": QuerySemanticRole.RULE_REQUIREMENT.value,
        "field_anchor": QuerySemanticRole.FIELD_REQUIREMENT.value,
        "example_value": QuerySemanticRole.USER_INPUT.value,
        "reference": QuerySemanticRole.REFERENCE.value,
        "entity": QuerySemanticRole.DOMAIN_ENTITY.value,
        "runtime_pattern": QuerySemanticRole.RUNTIME_PATTERN.value,
        "runtime_value": QuerySemanticRole.USER_INPUT.value,
    }
    # Un rol explícito del vocabulario nuevo pasa tal cual.
    if str(getattr(anchor, "role", "") or "") in {role.value for role in QuerySemanticRole}:
        return str(anchor.role)
    return mapping.get(declared, "")


# -----------------------------------------------------------------------------
# Requirements semánticos derivados de una instancia de patrón (§6, §14)
# -----------------------------------------------------------------------------


def pattern_semantic_requirements(value: str) -> tuple[str, ...]:
    """Requisitos semánticos que exige un patrón concreto.

    El patrón NO es un requirement documental; sus SEMÁNTICAS sí:
    definición de cada símbolo, matching posicional, literalidad, longitud,
    sufijo/prefijo y alcance del campo.
    """
    symbols = tuple(dict.fromkeys(char for char in (value or "") if char in _PATTERN_SYMBOLS))
    requirements: list[str] = []
    for symbol in symbols:
        requirements.append(f"symbol:{symbol}")
        requirements.append(f"definition:symbol:{symbol}")
    requirements.append("matching_policy")
    requirements.append("positional_semantics")
    requirements.append("literal_semantics")
    requirements.append("length_semantics")
    return tuple(dict.fromkeys(requirements))


# -----------------------------------------------------------------------------
# Parámetros numéricos del escenario (§27)
# -----------------------------------------------------------------------------

#: `nombre = valor` o `nombre: valor` explícitos en la pregunta.
_ASSIGNMENT_RE = re.compile(
    r"\b([a-záéíóúñ_][a-z0-9áéíóúñ_]{1,24})\s*(?:=|:)\s*(\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
#: «mi edad es 20», «el precio es 100».
_HAVE_VALUE_RE = re.compile(
    r"\b(?:tengo\s+el|tengo\s+la|mi|mis|el|la|nuestro|nuestra)\s+"
    r"([a-záéíóúñ_][a-z0-9áéíóúñ_]{1,24})\s+"
    r"(?:es|=|:)?\s*(\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
#: «tengo 20» sin nombre de parámetro: el número es el escenario.
_HAVE_BARE_NUMBER_RE = re.compile(
    r"\b(?:tengo|traigo|aporto|i\s+have)\s+(\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
#: «age 20», «status ACTIVE», «tax_rate=0.18», «precio 100».
_KEYWORD_VALUE_RE = re.compile(
    r"\b(age|edad|status|estado|precio|price|base|monto|amount|total|"
    r"salario|salary|descuento|discount|tax_rate|tasa|rate|value|valor|"
    r"cantidad|quantity|stock)\s*(?:=|:|is|es|de)?\s*"
    r"(\d+(?:[.,]\d+)?[A-Za-z]*|[A-Z][A-Z0-9_]{2,}|[A-Z0-9][A-Z0-9&*?%#@!~^_-]{1,})\b",
    re.IGNORECASE,
)
#: Umbrales/reglas: NO son datos del usuario.
_THRESHOLD_RE = re.compile(
    r"\b(?:m[ií]nim[ao]|m[aá]xim[ao]|umbral|threshold|m[ií]n\.?|m[aá]x\.?|"
    r"requiere|debe\s+ser|deben\s+ser|>=|<=|>\s*\d|<|at\s+least|at\s+most)\b",
    re.IGNORECASE,
)


def _threshold_governs(text: str, match_start: int, *, lookback: int = 40) -> bool:
    """¿El umbral más cercano gobierna ESTE número?

    «la edad mínima es 18, tengo 20»: el umbral gobierna el 18 (no hay otro
    número entre ambos); el 20 es del escenario y no se descarta.
    """
    prefix = str(text or "")[max(0, match_start - lookback) : match_start]
    matches = list(_THRESHOLD_RE.finditer(prefix))
    if not matches:
        return False
    last = matches[-1]
    return not re.search(r"\d", prefix[last.end() :])


#: Nombres estructurales que jamás son parámetros del usuario («el record 2»).
_NON_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "record", "registro", "byte", "position", "posicion", "posición",
        "line", "linea", "línea", "page", "pagina", "página", "field", "campo",
        "tabla", "table", "fila", "row", "columna", "column", "version", "versión",
        "capitulo", "capítulo", "chapter", "seccion", "sección", "section", "item",
        "punto", "paso", "step", "anexo", "apendice", "apéndice", "figura", "figure",
    }
)


#: «active=true», «verified: no»: parámetros booleanos del escenario.
_ASSIGNMENT_BOOL_RE = re.compile(
    r"\b([a-záéíóúñ_][a-z0-9áéíóúñ_]{1,24})\s*(?:=|:)\s*"
    r"(true|false|sí|si|yes|no)\b",
    re.IGNORECASE,
)
#: Fechas explícitas del escenario («2026-10-04», «04/10/2026»).
_DATE_TOKEN_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b")


def _is_parameter_name(name: str) -> bool:
    return str(name or "").strip().lower() not in _NON_PARAM_NAMES


def _source_lookup_window(text: str, match_start: int, match_end: int) -> bool:
    """¿El número está dentro de una pregunta de presencia literal?

    «¿el documento menciona age 20?»: 20 es requirement de fuente, no dato.
    """
    window = str(text or "")[max(0, match_start - 50) : match_end + 30]
    return bool(_SOURCE_LOOKUP_RE.search(window))


def extract_runtime_parameters(question: str) -> tuple[QuerySemanticObject, ...]:
    """Parámetros numéricos aportados por el usuario (nunca source anchors).

    Un `18` tras «mínima es» es un umbral documentado; un `20` tras «tengo» es
    el escenario del usuario. La distinción es contextual, no numérica.
    """
    text = str(question or "")
    found: list[QuerySemanticObject] = []
    seen: set[str] = set()
    for match in _ASSIGNMENT_RE.finditer(text):
        name, raw = match.group(1), match.group(2)
        if not _is_parameter_name(name):
            continue
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        if _threshold_governs(text, match.start()):
            continue
        key = f"{name.lower()}={raw}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw,
                lexical_kind="numero",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="parameter",
                evidence_required=False,
                runtime_value=True,
                confidence=0.85,
                cues=(name, "assignment"),
            )
        )
    for match in _HAVE_VALUE_RE.finditer(text):
        name, raw = match.group(1), match.group(2)
        if not _is_parameter_name(name):
            continue
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        if _threshold_governs(text, match.start(), lookback=34):
            continue
        key = f"{name.lower()}={raw}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw,
                lexical_kind="numero",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="parameter",
                evidence_required=False,
                runtime_value=True,
                confidence=0.8,
                cues=(name, "have"),
            )
        )
    for match in _HAVE_BARE_NUMBER_RE.finditer(text):
        raw = match.group(1)
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        key = f"={raw}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw,
                lexical_kind="numero",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="parameter",
                evidence_required=False,
                runtime_value=True,
                confidence=0.75,
                cues=("tengo", "bare"),
            )
        )
    for match in _KEYWORD_VALUE_RE.finditer(text):
        name, raw = match.group(1), match.group(2)
        if not _is_parameter_name(name):
            continue
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        if not raw[0].isdigit() and not raw.isupper():
            # `[A-Z]` con IGNORECASE captura prosa: un enum real es MAYÚSCULA.
            continue
        if _threshold_governs(text, match.start(), lookback=34):
            continue
        key = f"{name.lower()}={raw}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw,
                lexical_kind="numero" if raw[0].isdigit() else "sigla",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="status" if name.lower() in ("status", "estado") else "parameter",
                evidence_required=False,
                runtime_value=True,
                confidence=0.8,
                cues=(name, "keyword"),
            )
        )
    for match in _ASSIGNMENT_BOOL_RE.finditer(text):
        name, raw = match.group(1), match.group(2)
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        key = f"{name.lower()}={raw.lower()}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw.lower(),
                lexical_kind="booleano",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="boolean",
                evidence_required=False,
                runtime_value=True,
                confidence=0.85,
                cues=(name, "boolean"),
            )
        )
    for match in _DATE_TOKEN_RE.finditer(text):
        raw = match.group(1)
        if _source_lookup_window(text, match.start(), match.end()):
            continue
        key = f"date={raw}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            QuerySemanticObject(
                value=raw,
                lexical_kind="fecha",
                semantic_role=QuerySemanticRole.RUNTIME_PARAMETER.value,
                semantic_type="date",
                evidence_required=False,
                runtime_value=True,
                confidence=0.85,
                cues=("date", "date_token"),
            )
        )
    return tuple(found)


# -----------------------------------------------------------------------------
# Clasificador LLM opcional (§42): una sola llamada estructurada, JSON estricto.
# -----------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT = (
    "You classify query tokens by semantic role. Return ONLY strict JSON with "
    "keys: intent, objects, confidence. Each object: value, role, confidence. "
    "Allowed roles: SOURCE_REQUIREMENT, RULE_REQUIREMENT, FIELD_REQUIREMENT, "
    "DEFINITION_REQUIREMENT, REFERENCE, DOMAIN_ENTITY, USER_INPUT, USER_EXAMPLE, "
    "RUNTIME_VALUE, RUNTIME_PATTERN, RUNTIME_PARAMETER, OPTIONAL_CONTEXT. "
    "User-provided values are runtime data, not source requirements."
)


def build_classifier_prompt(question: str, anchors: Iterable[Anchor] = ()) -> str:
    """Prompt de una sola llamada, sin cadena de pensamiento."""
    values = ", ".join(
        f"{anchor.value} ({anchor.kind})"
        for anchor in anchors
        if str(getattr(anchor, "value", "") or "")
    )
    return f"Question: {question}\nTokens: {values or '(none)'}\nReturn JSON only."


def parse_classifier_response(
    text: str, *, fallback: QuerySemantics | None = None
) -> QuerySemantics | None:
    """Parsea la respuesta JSON estricta; cualquier desvío devuelve el fallback."""
    import json

    if not text:
        return fallback
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return fallback
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    intent = str(payload.get("intent") or "").upper()
    if intent not in {member.value for member in QueryIntent}:
        return fallback
    objects: list[QuerySemanticObject] = []
    for raw in payload.get("objects") or ():
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").upper()
        if role not in {member.value for member in QuerySemanticRole}:
            continue
        value = str(raw.get("value") or "").strip()
        if not value:
            continue
        objects.append(
            QuerySemanticObject(
                value=value,
                lexical_kind=str(raw.get("lexical_kind") or raw.get("kind") or ""),
                semantic_role=role,
                evidence_required=role in DOCUMENTABLE_SEMANTIC_ROLES,
                runtime_value=role in RUNTIME_ROLES,
                requires_semantics=(
                    pattern_semantic_requirements(value)
                    if role == QuerySemanticRole.RUNTIME_PATTERN.value
                    else ()
                ),
                confidence=float(raw.get("confidence") or 0.7),
                decided_by="llm",
            )
        )
    try:
        confidence = float(payload.get("confidence") or 0.7)
    except (TypeError, ValueError):
        confidence = 0.7
    return QuerySemantics(
        question=str(getattr(fallback, "question", "") or ""),
        intent=intent,
        intent_confidence=confidence,
        objects=tuple(objects) if objects else tuple(getattr(fallback, "objects", ()) or ()),
        decided_by="llm",
    )


# -----------------------------------------------------------------------------
# API pública (con cache determinista por pregunta + valores)
# -----------------------------------------------------------------------------


@lru_cache(maxsize=512)
def _classify_cached(
    question: str, anchor_values: tuple[tuple[str, str, str], ...]
) -> QuerySemantics:
    anchors = [
        Anchor(
            kind=kind,
            value=value,
            label=f"{kind} {value}",
            variants=(value,),
            needles=(value,),
            role=role,
        )
        for kind, value, role in anchor_values
    ]
    return ContextualQueryRoleClassifier().classify(question, anchors)


def classify_query_semantics(
    question: str,
    anchors: Sequence[Anchor] = (),
    entities: Sequence[Any] = (),
) -> QuerySemantics:
    """Clasificación semántica determinista de la consulta (fail-soft)."""
    try:
        if not anchors:
            from src.intelligence.response.anchors import extract_anchors

            anchors = extract_anchors(question)
        # La cache sólo se usa cuando no hay entidades (no hashables y el
        # clasificador no las necesita para roles de anchors).
        if not entities:
            key = tuple(
                (str(a.kind), str(a.value), str(getattr(a, "role", "") or ""))
                for a in anchors
            )
            return _classify_cached(str(question or ""), key)
        return ContextualQueryRoleClassifier().classify(question, anchors, entities)
    except Exception:  # noqa: BLE001 — la semántica nunca rompe el run
        return QuerySemantics(
            question=str(question or ""),
            intent=QueryIntent.LOOKUP.value,
            intent_confidence=0.3,
            decided_by="fallback",
        )


__all__ = [
    "CLASSIFIER_SYSTEM_PROMPT",
    "DEFAULT_LLM_THRESHOLD",
    "DOCUMENTABLE_SEMANTIC_ROLES",
    "QUERY_SEMANTICS_VERSION",
    "REASONING_INTENTS",
    "RUNTIME_ROLES",
    "SOURCE_INTENTS",
    "ContextualQueryRoleClassifier",
    "QueryIntent",
    "QuerySemanticObject",
    "QuerySemantics",
    "QuerySemanticRole",
    "build_classifier_prompt",
    "classify_query_semantics",
    "classify_validate_vs_apply",
    "detect_query_intent",
    "extract_runtime_parameters",
    "is_documentable_semantic_role",
    "is_runtime_semantic_role",
    "parse_classifier_response",
    "pattern_semantic_requirements",
]
