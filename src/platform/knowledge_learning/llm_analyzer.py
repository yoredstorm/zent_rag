# =============================================================================
# LLM Analyzer — Comprensión semántica con el LLM (FASE 33B)
# =============================================================================
# Estrategia híbrida: señales deterministas + metadata + profiling + relaciones
# + léxico de la organización + conocimiento aprobado + razonamiento LLM.
#
# El LLM NUNCA es la única fuente de verdad:
#   - salida JSON validada con Pydantic (nunca texto libre como estructura),
#   - jamás se almacena chain-of-thought (solo evidence + reasoning_summary),
#   - INFERRED nunca se promueve a APPROVED automáticamente,
#   - si el LLM falla/no está disponible, el pipeline sigue con heurísticas.
#
# Costo: 1 llamada por TABLA (nunca por columna), temperatura baja, límite de
# tokens, timeout/retry del LLMProvider, cache durable por
# (organization_id, schema_fingerprint, prompt_version, modelo).
#
# Privacidad: sanitize_llm_context() es la única puerta hacia el modelo.
# Nunca se envían passwords, tokens, API keys, secretos ni columnas sensibles;
# los samples solo se incluyen para columnas no sensibles y de baja cardinalidad.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.models import DeepTableProfile
from src.core.config import get_settings
from src.core.domain.pii import is_sensitive_column
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    knowledge_llm_latency_seconds,
    knowledge_llm_requests_total,
    knowledge_llm_tokens_total,
)
from src.platform.knowledge_learning.schema_analyzer import table_fingerprint

logger = get_logger(__name__)

PROMPT_VERSION = "kl-v1"

# Nunca enviar al LLM columnas cuyo nombre (o flags) huela a secreto.
_SECRET_NAME_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|apikey|credential|cvv|"
    r"cvc|pin|ssn|social[_-]?security|iban|swift|routing|account[_-]?number|"
    r"private[_-]?key|salt|hash)",
    re.IGNORECASE,
)
_SAFE_SAMPLE_RE = re.compile(r"^[\w\s\.\-/,:áéíóúÁÉÍÓÚñÑüÜ%$#@()+]{1,80}$")
_JSON_FENCE_RE = re.compile(r"\{.*\}", re.DOTALL)

_MAX_CONTEXT_CHARS = 14_000
_MAX_COLUMNS = 250
_MAX_VALUES_PER_COLUMN = 12

# uuid5 namespace para dedupe de usage events del learning engine.
_USAGE_NAMESPACE = UUID("b9f2d5c8-3f1a-4f6e-9c2d-0a1b2c3d4e5f")


# -----------------------------------------------------------------------------
# Salida estructurada del LLM (validada con Pydantic)
# -----------------------------------------------------------------------------


class LLMEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    business_name: str = ""
    description: str = ""
    business_purpose: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class LLMField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    physical_column: str = ""
    business_name: str = ""
    description: str = ""
    role: str = ""  # IDENTIFIER|DESCRIPTION|MEASURE|DATE|STATUS|CATEGORY|RELATIONSHIP|UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class LLMRelationship(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    business_verb: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class LLMBusinessRule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    definition: str = ""
    applies_to: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class LLMPossibleMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    definition: str = ""
    formula: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class LLMDimension(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    source_column: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class LLMQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    target: str = ""
    options: list[str] = Field(default_factory=list)
    impact: str = "medium"  # critical|high|medium|low
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class LLMAmbiguity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str = ""
    description: str = ""
    options: list[str] = Field(default_factory=list)
    impact: str = "medium"
    evidence: list[str] = Field(default_factory=list)


class LLMTableAnalysis(BaseModel):
    """Contrato JSON del análisis por tabla (nunca texto libre)."""

    model_config = ConfigDict(extra="ignore")

    entity: LLMEntity | None = None
    fields: list[LLMField] = Field(default_factory=list)
    relationships: list[LLMRelationship] = Field(default_factory=list)
    business_rules: list[LLMBusinessRule] = Field(default_factory=list)
    possible_metrics: list[LLMPossibleMetric] = Field(default_factory=list)
    dimensions: list[LLMDimension] = Field(default_factory=list)
    questions: list[LLMQuestion] = Field(default_factory=list)
    ambiguities: list[LLMAmbiguity] = Field(default_factory=list)

    def normalize(self) -> "LLMTableAnalysis":
        """Recorta a límites aptos para usuario (sin chain-of-thought)."""
        if self.entity is not None:
            self.entity.name = self.entity.name[:160]
            self.entity.business_name = self.entity.business_name[:160]
            self.entity.description = self.entity.description[:2000]
            self.entity.business_purpose = self.entity.business_purpose[:1000]
            self.entity.reasoning_summary = self.entity.reasoning_summary[:800]
            self.entity.evidence = [e[:200] for e in self.entity.evidence[:12]]
        for f in self.fields[:400]:
            f.physical_column = f.physical_column[:128]
            f.business_name = f.business_name[:160]
            f.description = f.description[:1500]
            f.reasoning_summary = f.reasoning_summary[:600]
            f.evidence = [e[:200] for e in f.evidence[:10]]
        for r in self.relationships[:100]:
            r.from_table = r.from_table[:160]
            r.from_column = r.from_column[:128]
            r.to_table = r.to_table[:160]
            r.to_column = r.to_column[:128]
            r.business_verb = r.business_verb[:60]
            r.reasoning_summary = r.reasoning_summary[:600]
            r.evidence = [e[:200] for e in r.evidence[:10]]
        for rule in self.business_rules[:40]:
            rule.name = rule.name[:200]
            rule.definition = rule.definition[:2000]
            rule.applies_to = [a[:160] for a in rule.applies_to[:20]]
            rule.evidence = [e[:200] for e in rule.evidence[:10]]
        for m in self.possible_metrics[:40]:
            m.name = m.name[:200]
            m.definition = m.definition[:2000]
            m.formula = m.formula[:1000] if m.formula else None
            m.evidence = [e[:200] for e in m.evidence[:10]]
        for d in self.dimensions[:60]:
            d.name = d.name[:200]
            d.source_column = d.source_column[:128]
            d.evidence = [e[:200] for e in d.evidence[:10]]
        for q in self.questions[:40]:
            q.question = q.question[:1000]
            q.target = q.target[:200]
            q.options = [o[:160] for o in q.options[:12]]
            q.impact = q.impact if q.impact in ("critical", "high", "medium", "low") else "medium"
            q.evidence = [e[:200] for e in q.evidence[:10]]
        for a in self.ambiguities[:40]:
            a.subject = a.subject[:200]
            a.description = a.description[:1500]
            a.options = [o[:160] for o in a.options[:12]]
            a.impact = a.impact if a.impact in ("critical", "high", "medium", "low") else "medium"
            a.evidence = [e[:200] for e in a.evidence[:10]]
        # Cortar listas a límites duros tras normalizar.
        self.fields = self.fields[:400]
        self.relationships = self.relationships[:100]
        self.business_rules = self.business_rules[:40]
        self.possible_metrics = self.possible_metrics[:40]
        self.dimensions = self.dimensions[:60]
        self.questions = self.questions[:40]
        self.ambiguities = self.ambiguities[:40]
        return self


def parse_llm_analysis(content: str) -> LLMTableAnalysis | None:
    """JSON del LLM -> modelo Pydantic. Fences/markdown tolerados; inválido None."""
    if not content or not content.strip():
        return None
    parsed: Any = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = _JSON_FENCE_RE.search(content)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        return None
    try:
        return LLMTableAnalysis.model_validate(parsed).normalize()
    except ValidationError as exc:
        logger.warning(
            "LLM analysis rejected by schema",
            errors=[e.get("loc") for e in exc.errors()[:5]],
        )
        return None


# -----------------------------------------------------------------------------
# Sanitización (única puerta hacia el LLM)
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class SanitizedContext:
    payload: dict
    meta: dict
    digest: str


def _is_secret_like(name: str) -> bool:
    return bool(_SECRET_NAME_RE.search(name or ""))


def sanitize_llm_context(
    *,
    table: dict,
    columns: list[dict],
    relationships: list[dict] | None = None,
    neighbor_tables: list[dict] | None = None,
    lexicon: list[dict] | None = None,
    approved_entities: list[dict] | None = None,
    approved_fields: list[dict] | None = None,
    enum_values: dict[str, list[dict]] | None = None,
    deep_table: DeepTableProfile | None = None,
    max_samples: int = 10,
) -> SanitizedContext:
    """Construye el contexto sanitizado que se envía al LLM.

    Reglas duras:
      - columnas sensibles/PII/secreto-like se OMITEN del payload,
      - samples solo para columnas no sensibles, cardinalidad baja y tipo texto,
      - nunca defaults con pinta de secreto,
      - solo metadata y estadísticas (jamás filas completas).
    """
    deep_cols = {c.name: c for c in (deep_table.columns if deep_table else [])}
    enum_values = enum_values or {}

    safe_columns: list[dict] = []
    omitted_sensitive = 0
    samples_included = 0

    for col in columns[:_MAX_COLUMNS]:
        name = col.get("column_name", "")
        if col.get("is_sensitive") or is_sensitive_column(name) or _is_secret_like(name):
            omitted_sensitive += 1
            continue
        entry: dict[str, Any] = {
            "name": name,
            "datatype": col.get("data_type", ""),
            "nullable": bool(col.get("nullable", True)),
            "primary_key": bool(col.get("is_primary_key")),
            "comment": (col.get("column_comment") or "")[:500],
        }
        if col.get("null_ratio") is not None:
            entry["null_ratio"] = round(float(col["null_ratio"]), 4)
        if col.get("cardinality_approx") is not None:
            entry["cardinality"] = int(col["cardinality_approx"])
        if col.get("column_default") and not _is_secret_like(str(col["column_default"])):
            default = str(col["column_default"])[:120]
            if not _is_secret_like(default):
                entry["default"] = default

        # Samples permitidos: nunca sensibles, nunca sample_disabled, solo texto
        # de baja cardinalidad y valores con forma segura.
        deep_col = deep_cols.get(name)
        if (
            not col.get("sample_disabled")
            and (col.get("cardinality_approx") is None or int(col["cardinality_approx"]) <= 50)
        ):
            raw_values = [
                str(v.get("value", ""))
                for v in enum_values.get(name, [])[:max_samples]
            ] or [
                str(v) for v in (deep_col.distinct_values if deep_col else [])[:max_samples]
            ]
            safe_values = [
                v[:80] for v in raw_values if v and _SAFE_SAMPLE_RE.match(v)
            ][:_MAX_VALUES_PER_COLUMN]
            if safe_values:
                entry["sample_values"] = safe_values
                samples_included += len(safe_values)

        safe_columns.append(entry)

    payload: dict[str, Any] = {
        "database": table.get("database") or table.get("engine") or "",
        "schema": table.get("schema_name", ""),
        "table_name": table.get("table_name", ""),
        "table_comment": (table.get("table_comment") or "")[:1000],
        "is_view": bool(table.get("is_view")),
        "row_count_approx": table.get("row_count_approx"),
        "columns": safe_columns,
    }

    safe_relationships: list[dict] = []
    for rel in (relationships or [])[:100]:
        safe_relationships.append(
            {
                "from_column": str(rel.get("from_column", ""))[:128],
                "to_table": str(rel.get("to_table", ""))[:160],
                "to_column": str(rel.get("to_column", ""))[:128],
                "relation_type": str(rel.get("relation_type", ""))[:30],
                "status": str(rel.get("status", ""))[:20],
            }
        )
    if safe_relationships:
        payload["relationships"] = safe_relationships

    neighbors = [
        {
            "table": str(t.get("qualified_name") or t.get("table_name", ""))[:200],
            "comment": (t.get("table_comment") or "")[:300],
        }
        for t in (neighbor_tables or [])[:20]
    ]
    if neighbors:
        payload["neighbor_tables"] = neighbors

    lexicon_entries = [
        {
            "token": str(entry.get("token", ""))[:80],
            "meaning": str(entry.get("meaning", ""))[:160],
            "role": str(entry.get("role", ""))[:40],
        }
        for entry in (lexicon or [])[:40]
    ]
    if lexicon_entries:
        payload["organization_lexicon"] = lexicon_entries

    approved_refs: list[dict] = []
    for entity in (approved_entities or [])[:50]:
        approved_refs.append(
            {
                "kind": "entity",
                "name": str(entity.get("name", ""))[:160],
                "business_name": str(entity.get("display_name", ""))[:160],
            }
        )
    for fld in (approved_fields or [])[:50]:
        approved_refs.append(
            {
                "kind": "field",
                "name": str(fld.get("name", ""))[:160],
                "role": str(fld.get("role", ""))[:40],
            }
        )
    if approved_refs:
        payload["existing_approved_knowledge"] = approved_refs

    if len(json.dumps(payload, ensure_ascii=False, sort_keys=True)) > _MAX_CONTEXT_CHARS:
        payload["columns"] = safe_columns[: max(1, _MAX_COLUMNS // 2)]

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    meta = {
        "columns_included": len(payload.get("columns", [])),
        "columns_omitted_sensitive": omitted_sensitive,
        "samples_included": samples_included,
        "relationships_included": len(safe_relationships),
        "neighbor_tables": len(neighbors),
        "lexicon_terms": len(lexicon_entries),
        "approved_references": len(approved_refs),
        "context_truncated": len(columns) > _MAX_COLUMNS
        or len(encoded) > _MAX_CONTEXT_CHARS,
        "payload_chars": len(encoded),
    }
    return SanitizedContext(payload=payload, meta=meta, digest=digest)


# -----------------------------------------------------------------------------
# Prompt (versión versionada; solo contexto sanitizado)
# -----------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Eres un analista de datos senior especializado en modelado semántico y "
    "sistemas RAG empresariales. Recibes SOLO metadata de una tabla (nombres, "
    "tipos, comentarios, estadísticas y muestras categóricas seguras; nunca "
    "filas completas ni datos sensibles). Tu tarea es producir una hipótesis "
    "semántica del negocio.\n\n"
    "Responde EXCLUSIVAMENTE con un único objeto JSON válido, sin markdown y "
    "sin texto adicional, con esta forma:\n"
    "{\n"
    '  "entity": {"name": str, "business_name": str, "description": str, '
    '"business_purpose": str, "confidence": 0..1, "reasoning_summary": str, '
    '"evidence": [str]},\n'
    '  "fields": [{"physical_column": str, "business_name": str, '
    '"description": str, "role": "IDENTIFIER|DESCRIPTION|MEASURE|DATE|STATUS|'
    'CATEGORY|RELATIONSHIP|UNKNOWN", "confidence": 0..1, '
    '"reasoning_summary": str, "evidence": [str]}],\n'
    '  "relationships": [{"from_table": str, "from_column": str, '
    '"to_table": str, "to_column": str, "business_verb": str, '
    '"confidence": 0..1, "reasoning_summary": str, "evidence": [str]}],\n'
    '  "business_rules": [{"name": str, "definition": str, '
    '"applies_to": [str], "confidence": 0..1, "evidence": [str]}],\n'
    '  "possible_metrics": [{"name": str, "definition": str, '
    '"formula": str|null, "confidence": 0..1, "evidence": [str]}],\n'
    '  "dimensions": [{"name": str, "source_column": str, '
    '"confidence": 0..1, "evidence": [str]}],\n'
    '  "questions": [{"question": str, "target": str, "options": [str], '
    '"impact": "critical|high|medium|low", "confidence": 0..1, '
    '"evidence": [str]}],\n'
    '  "ambiguities": [{"subject": str, "description": str, '
    '"options": [str], "impact": "critical|high|medium|low", '
    '"evidence": [str]}]\n'
    "}\n\n"
    "Reglas: no inventes columnas; toda afirmación debe citar evidencia "
    "(nombre, tipo, comentario, relación o muestra). Si no hay suficiente "
    "información, usa confidence bajo y agrega la ambigüedad a questions o "
    "ambiguities. No incluyas cadenas de pensamiento internas: reasoning_summary "
    "debe ser corta, en español y apta para el usuario final."
)


def build_user_prompt(context_payload: dict) -> str:
    return (
        "Metadata sanitizada de la tabla (JSON):\n"
        f"{json.dumps(context_payload, ensure_ascii=False)}\n\n"
        "Devuelve solo el JSON del análisis."
    )


# -----------------------------------------------------------------------------
# Analyzer
# -----------------------------------------------------------------------------


@dataclass
class SourceContextIndex:
    """Datos de la fuente cargados una vez por run (sin N+1 por tabla)."""

    tables: list[dict] = field(default_factory=list)
    tables_by_id: dict[str, dict] = field(default_factory=dict)
    relationships: list[dict] = field(default_factory=list)
    lexicon: list[dict] = field(default_factory=list)
    approved_entities: list[dict] = field(default_factory=list)
    approved_fields: list[dict] = field(default_factory=list)
    deep_by_name: dict[str, DeepTableProfile] = field(default_factory=dict)


@dataclass
class TableContext:
    table: dict
    columns: list[dict]
    deep_table: DeepTableProfile | None
    fingerprint: str
    sanitized: SanitizedContext


class LLMAnalyzer:
    """Análisis semántico por tabla con cache durable y fallback heurístico."""

    def __init__(
        self,
        *,
        repository: Any,
        catalog_store: PostgresCatalogStore,
        llm_provider: Any | None = None,
    ) -> None:
        self._repo = repository
        self._store = catalog_store
        self._llm = llm_provider

    @property
    def available(self) -> bool:
        return self._llm is not None

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    # ------------------------------------------------------------- index/context
    async def build_source_index(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        deep: Any | None = None,
    ) -> SourceContextIndex:
        index = SourceContextIndex()
        index.tables = await self._store.list_tables(
            organization_id, source_id, limit=5000
        )
        index.tables_by_id = {t["id"]: t for t in index.tables}
        index.relationships = await self._store.list_relationships(
            organization_id, source_id, limit=5000
        )
        try:
            index.lexicon = await self._store.list_lexicon(organization_id)
        except Exception:  # noqa: BLE001
            index.lexicon = []
        try:
            entities = await self._store.list_entities(organization_id, limit=500)
            index.approved_entities = [
                e for e in entities if e.get("status") == "approved"
            ][:50]
            if index.approved_entities:
                for entity in index.approved_entities:
                    fields = await self._store.list_fields(
                        organization_id, UUID(entity["id"])
                    )
                    index.approved_fields.extend(
                        f for f in fields if f.get("status") == "approved"
                    )
            index.approved_fields = index.approved_fields[:50]
        except Exception:  # noqa: BLE001
            index.approved_entities = []
            index.approved_fields = []
        if deep is not None:
            for table in getattr(deep, "tables", []):
                index.deep_by_name[f"{table.schema}.{table.table_name}"] = table
                index.deep_by_name[table.table_name] = table
        return index

    async def build_table_context(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        table: dict,
        index: SourceContextIndex,
    ) -> TableContext:
        table_id = UUID(table["id"])
        columns = await self._store.list_columns(organization_id, table_id)
        try:
            enum_values = await self._store.list_enum_values_for_table(
                organization_id, table_id
            )
        except Exception:  # noqa: BLE001
            enum_values = {}
        qualified = table.get("qualified_name") or table.get("table_name", "")
        deep_table = index.deep_by_name.get(qualified) or index.deep_by_name.get(
            table.get("table_name", "")
        )

        relationships: list[dict] = []
        neighbor_ids: set[str] = set()
        for rel in index.relationships:
            if rel.get("from_table_id") == table["id"]:
                relationships.append(rel)
                neighbor_ids.add(rel.get("to_table_id"))
            elif rel.get("to_table_id") == table["id"]:
                relationships.append(
                    {
                        "from_column": rel.get("to_column"),
                        "to_table": index.tables_by_id.get(
                            rel.get("from_table_id"), {}
                        ).get("qualified_name", ""),
                        "to_column": rel.get("from_column"),
                        "relation_type": rel.get("relation_type"),
                        "status": rel.get("status"),
                    }
                )
                neighbor_ids.add(rel.get("from_table_id"))
        # FKs físicas del deep profile (aún sin persistir cuando aplica).
        if deep_table is not None:
            for fk in deep_table.foreign_keys:
                relationships.append(
                    {
                        "from_column": fk.from_column,
                        "to_table": fk.to_table,
                        "to_column": fk.to_column,
                        "relation_type": "foreign_key",
                        "status": "observed",
                    }
                )
                neighbor_ids.add(fk.to_table)
        neighbors = [
            index.tables_by_id[nid]
            for nid in neighbor_ids
            if nid in index.tables_by_id
        ]

        sanitized = sanitize_llm_context(
            table=table,
            columns=columns,
            relationships=relationships,
            neighbor_tables=neighbors,
            lexicon=index.lexicon,
            approved_entities=index.approved_entities,
            approved_fields=index.approved_fields,
            enum_values=enum_values,
            deep_table=deep_table,
            max_samples=get_settings().RAG_KNOWLEDGE_LLM_MAX_SAMPLES,
        )
        fingerprint = table.get("schema_fingerprint") or table_fingerprint(
            table, columns
        )
        return TableContext(
            table=table,
            columns=columns,
            deep_table=deep_table,
            fingerprint=fingerprint,
            sanitized=sanitized,
        )

    # ----------------------------------------------------------------- analyze
    async def analyze_table(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        context: TableContext,
        run_id: UUID | None = None,
        model: str | None = None,
    ) -> dict:
        settings = get_settings()
        model_name = (
            model
            or settings.RAG_KNOWLEDGE_LLM_MODEL
            or settings.LITELLM_DEFAULT_MODEL
        )
        table_id = UUID(context.table["id"])
        base = {
            "table_id": str(table_id),
            "table": context.table.get("qualified_name"),
            "model": model_name,
            "prompt_version": PROMPT_VERSION,
            "context_digest": context.sanitized.digest,
            "context_meta": context.sanitized.meta,
            "cached": False,
        }

        # Cache durable: mismo fingerprint + prompt + modelo => sin llamada LLM.
        try:
            cached = await self._repo.get_llm_analysis(
                organization_id,
                table_id=table_id,
                schema_fingerprint=context.fingerprint,
                prompt_version=PROMPT_VERSION,
                model=model_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM analysis cache lookup failed", error=str(exc)[:200])
            cached = None
        if cached is not None:
            knowledge_llm_requests_total.labels(
                organization_id=str(organization_id), status="cached"
            ).inc()
            return {
                **base,
                "status": "cached",
                "analysis": cached.get("result") or {},
                "reasoning_summary": cached.get("reasoning_summary"),
                "confidence": cached.get("confidence"),
                "tokens_input": 0,
                "tokens_output": 0,
                "latency_ms": cached.get("latency_ms") or 0.0,
                "estimated_cost": 0.0,
                "error": None,
            }

        if self._llm is None:
            knowledge_llm_requests_total.labels(
                organization_id=str(organization_id), status="skipped"
            ).inc()
            return {
                **base,
                "status": "skipped",
                "analysis": None,
                "reasoning_summary": None,
                "confidence": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "latency_ms": 0.0,
                "estimated_cost": 0.0,
                "error": "llm_provider_unavailable",
            }

        prompt = build_user_prompt(context.sanitized.payload)
        estimated_input = max(len(prompt) // 4, 64)
        try:
            from src.platform.billing.pricing import estimate_cost
            from src.platform.billing.quota_service import (
                QuotaExceededError,
                check_preflight,
            )

            estimated_cost = await estimate_cost(
                model_name,
                estimated_input,
                settings.RAG_KNOWLEDGE_LLM_MAX_TOKENS // 2,
            )
            await check_preflight(
                organization_id,
                estimated_tokens=estimated_input
                + settings.RAG_KNOWLEDGE_LLM_MAX_TOKENS,
                estimated_cost=estimated_cost,
            )
        except QuotaExceededError as exc:
            await self._persist(
                organization_id,
                source_id=source_id,
                run_id=run_id,
                context=context,
                model=model_name,
                status="skipped",
                error=f"quota_exceeded: {exc}"[:500],
            )
            knowledge_llm_requests_total.labels(
                organization_id=str(organization_id), status="skipped"
            ).inc()
            return {
                **base,
                "status": "skipped",
                "analysis": None,
                "reasoning_summary": None,
                "confidence": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "latency_ms": 0.0,
                "estimated_cost": 0.0,
                "error": "quota_exceeded",
            }
        except Exception:  # noqa: BLE001 — preflight fail-soft
            pass

        started = time.perf_counter()
        try:
            response = await self._llm.generate(
                prompt,
                model=model_name,
                max_tokens=settings.RAG_KNOWLEDGE_LLM_MAX_TOKENS,
                temperature=settings.RAG_KNOWLEDGE_LLM_TEMPERATURE,
                system_prompt=_SYSTEM_PROMPT,
            )
        except Exception as exc:  # noqa: BLE001 — fallback heurístico
            latency_ms = (time.perf_counter() - started) * 1000
            error = f"{type(exc).__name__}: {exc}"[:500]
            await self._persist(
                organization_id,
                source_id=source_id,
                run_id=run_id,
                context=context,
                model=model_name,
                status="failed",
                latency_ms=latency_ms,
                context_digest=context.sanitized.digest,
                error=error,
            )
            knowledge_llm_requests_total.labels(
                organization_id=str(organization_id), status="failed"
            ).inc()
            knowledge_llm_latency_seconds.labels(
                organization_id=str(organization_id)
            ).observe(latency_ms / 1000)
            logger.warning(
                "LLM analysis failed; heuristic fallback continues",
                organization_id=str(organization_id),
                table=context.table.get("qualified_name"),
                error=error,
            )
            return {
                **base,
                "status": "failed",
                "analysis": None,
                "reasoning_summary": None,
                "confidence": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "latency_ms": round(latency_ms, 2),
                "estimated_cost": 0.0,
                "error": error,
            }

        latency_ms = (time.perf_counter() - started) * 1000
        analysis = parse_llm_analysis(response.content)
        if analysis is None:
            await self._persist(
                organization_id,
                source_id=source_id,
                run_id=run_id,
                context=context,
                model=model_name,
                status="failed",
                latency_ms=latency_ms,
                context_digest=context.sanitized.digest,
                error="invalid_json_schema",
                tokens_input=response.prompt_tokens,
                tokens_output=response.completion_tokens,
                model_response=getattr(response, "model", None) or model_name,
            )
            knowledge_llm_requests_total.labels(
                organization_id=str(organization_id), status="failed"
            ).inc()
            await self._record_usage(
                organization_id,
                run_id=run_id,
                table_id=table_id,
                model=model_name,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=latency_ms,
                estimated_cost=0.0,
                status="failed",
            )
            return {
                **base,
                "status": "failed",
                "analysis": None,
                "reasoning_summary": None,
                "confidence": None,
                "tokens_input": response.prompt_tokens,
                "tokens_output": response.completion_tokens,
                "latency_ms": round(latency_ms, 2),
                "estimated_cost": 0.0,
                "error": "invalid_json_schema",
            }

        cost = 0.0
        try:
            from src.platform.billing.pricing import estimate_cost

            cost = await estimate_cost(
                model_name, response.prompt_tokens, response.completion_tokens
            )
        except Exception:  # noqa: BLE001
            cost = 0.0

        summary = ""
        confidence: float | None = None
        if analysis.entity is not None:
            summary = analysis.entity.reasoning_summary
            confidence = analysis.entity.confidence
        if not summary and analysis.fields:
            summary = analysis.fields[0].reasoning_summary
        if confidence is None and analysis.fields:
            confidence = max(f.confidence for f in analysis.fields)

        result_dump = analysis.model_dump(mode="json")
        await self._persist(
            organization_id,
            source_id=source_id,
            run_id=run_id,
            context=context,
            model=model_name,
            status="completed",
            latency_ms=latency_ms,
            context_digest=context.sanitized.digest,
            result=result_dump,
            reasoning_summary=summary[:800] if summary else None,
            confidence=confidence,
            tokens_input=response.prompt_tokens,
            tokens_output=response.completion_tokens,
            estimated_cost=cost,
        )
        await self._record_usage(
            organization_id,
            run_id=run_id,
            table_id=table_id,
            model=model_name,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=latency_ms,
            estimated_cost=cost,
            status="completed",
        )
        knowledge_llm_requests_total.labels(
            organization_id=str(organization_id), status="completed"
        ).inc()
        knowledge_llm_latency_seconds.labels(
            organization_id=str(organization_id)
        ).observe(latency_ms / 1000)
        knowledge_llm_tokens_total.labels(
            organization_id=str(organization_id), token_type="input"
        ).inc(max(0, int(response.prompt_tokens)))
        knowledge_llm_tokens_total.labels(
            organization_id=str(organization_id), token_type="output"
        ).inc(max(0, int(response.completion_tokens)))
        return {
            **base,
            "status": "completed",
            "analysis": result_dump,
            "reasoning_summary": summary[:800] if summary else None,
            "confidence": confidence,
            "tokens_input": int(response.prompt_tokens),
            "tokens_output": int(response.completion_tokens),
            "latency_ms": round(latency_ms, 2),
            "estimated_cost": round(cost, 8),
            "error": None,
        }

    # ------------------------------------------------------------------- helpers
    async def _persist(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        run_id: UUID | None,
        context: TableContext,
        model: str,
        status: str,
        latency_ms: float = 0.0,
        context_digest: str = "",
        result: dict | None = None,
        reasoning_summary: str | None = None,
        confidence: float | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        estimated_cost: float = 0.0,
        error: str | None = None,
        model_response: str | None = None,
    ) -> None:
        try:
            await self._repo.upsert_llm_analysis(
                organization_id,
                source_id=source_id,
                run_id=run_id,
                table_id=UUID(context.table["id"]),
                schema_fingerprint=context.fingerprint,
                prompt_version=PROMPT_VERSION,
                model=(model_response or model),
                status=status,
                context_digest=context_digest or context.sanitized.digest,
                context_meta=context.sanitized.meta,
                result=result or {},
                reasoning_summary=reasoning_summary,
                confidence=confidence,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                latency_ms=latency_ms,
                estimated_cost=estimated_cost,
                error=error,
            )
        except Exception as exc:  # noqa: BLE001 — nunca romper el run
            logger.warning("LLM analysis persist failed", error=str(exc)[:200])

    async def _record_usage(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None,
        table_id: UUID,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        estimated_cost: float,
        status: str,
    ) -> None:
        """Integra el costo con Usage/Metering existente (fail-soft)."""
        try:
            from src.platform.usage.usage_engine import (
                UsageEvent,
                get_usage_counters,
                record_event,
            )

            request_id = uuid5(
                _USAGE_NAMESPACE,
                f"knowledge:{organization_id}:{run_id}:{table_id}:{model}",
            )
            total_tokens = max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
            inserted = await record_event(
                UsageEvent(
                    request_id=request_id,
                    organization_id=organization_id,
                    event_type="knowledge_llm_analysis",
                    model=model,
                    provider="litellm",
                    prompt_tokens=max(0, int(prompt_tokens)),
                    completion_tokens=max(0, int(completion_tokens)),
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    status=status,
                    estimated_cost=estimated_cost,
                    actual_cost=estimated_cost,
                    routing={"feature": "knowledge_learning", "run_id": str(run_id)},
                )
            )
            if inserted:
                await get_usage_counters().record(
                    organization_id, request_id, total_tokens, estimated_cost
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Knowledge LLM usage record failed", error=str(exc)[:200])


# -----------------------------------------------------------------------------
# Selección de tablas a analizar (presupuesto y prioridad)
# -----------------------------------------------------------------------------


def select_tables_for_analysis(
    tables: list[dict],
    *,
    max_tables: int,
    relationships: list[dict] | None = None,
) -> list[dict]:
    """Prioriza tablas con más conexiones y filas; respeta el presupuesto.

    Nunca una llamada por columna: el presupuesto es por tabla.
    """
    rel_count: dict[str, int] = {}
    for rel in relationships or []:
        for key in ("from_table_id", "to_table_id"):
            if rel.get(key):
                rel_count[rel[key]] = rel_count.get(rel[key], 0) + 1
    ranked = sorted(
        tables,
        key=lambda t: (
            rel_count.get(t.get("id"), 0),
            int(t.get("row_count_approx") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(1, max_tables)]
