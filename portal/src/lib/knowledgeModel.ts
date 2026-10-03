// =============================================================================
// Knowledge OS API — tipos reales del modelo de conocimiento (FASE 34)
// =============================================================================
// Todo lo que muestra la UI viene del modelo canónico: objetos, assertions,
// evidencia, gaps y conflictos. Nunca se inventan counts ni confianza.
// Los errores se propagan: la UI debe distinguir ERROR de ZERO.
// =============================================================================
import { api, loadSession } from "../api";

function withSession<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = loadSession();
  return api<T>(path, {
    ...options,
    token: session?.token,
    organizationId: session?.organizationId,
  });
}

export type KnowledgeState = "empty" | "partial" | "ready" | "error";

export type KnowledgeObjectType =
  | "domain"
  | "concept"
  | "entity"
  | "attribute"
  | "relationship"
  | "business_rule"
  | "metric"
  | "kpi"
  | "process"
  | "term"
  | "synonym"
  | "event"
  | "constraint"
  | "verified_query"
  | "source"
  | "table"
  | "column"
  | "document"
  | "section"
  | "chunk";

export type KnowledgeObject = {
  id: string;
  type: KnowledgeObjectType | string;
  name: string;
  display_name: string;
  description: string | null;
  domain: string | null;
  status: "draft" | "discovered" | "inferred" | "verified" | "rejected" | "deprecated";
  provenance: string;
  confidence: number | null;
  confidence_label: string;
  source_of_truth: string | null;
  source_id: string | null;
  authority_level: string | null;
  evidence_count: number;
  assertion_count: number;
  verified_at: string | null;
  freshness_at: string | null;
  last_seen_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
};

export type KnowledgeEdge = {
  id: string;
  subject_id: string;
  subject_name?: string;
  subject_type?: string;
  predicate: string;
  object_id: string;
  object_name?: string;
  object_type?: string;
  direction?: "in" | "out";
  relationship_type: "physical" | "logical" | "semantic" | "business";
  confidence: number;
  status: string;
  provenance: string;
  evidence: unknown[];
  metadata: Record<string, unknown>;
};

export type KnowledgeAssertion = {
  id: string;
  subject_id: string | null;
  subject_label: string;
  predicate: string;
  object_id: string | null;
  object_value: string | null;
  assertion_type: string;
  confidence: number;
  confidence_detail: Record<string, unknown>;
  status:
    | "candidate"
    | "accepted"
    | "verified"
    | "rejected"
    | "conflicted"
    | "stale";
  provenance: string;
  method: string;
  source_id: string | null;
  evidence_count: number;
  version: number;
  verified_at: string | null;
  stale_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type KnowledgeEvidence = {
  id: string;
  source_id: string | null;
  document_id: string | null;
  page: number | null;
  section_path: string[];
  locator: string | null;
  table_reference: string | null;
  database_reference: string | null;
  excerpt: string;
  evidence_type: string;
  strength: number | null;
  authority: string | null;
  retrieval_score: number | null;
  content_hash: string;
  created_at: string | null;
};

export type HealthDimension = {
  key: string;
  label: string;
  score: number | null;
  weight: number;
  measured: boolean;
  reason: string;
  formula: string;
  signals: Record<string, unknown>;
  missing: string[];
  issues: string[];
  updated_at: string | null;
  trend: number | null;
};

export type KnowledgeHealth = {
  overall: number | null;
  measured_dimensions: number;
  total_dimensions: number;
  dimensions: HealthDimension[];
  state: string;
  computed_at: string;
};

export type KnowledgeDomain = {
  name: string;
  objects: number;
  verified: number;
  measured: boolean;
  avg_confidence: number | null;
  sources: number;
  edges?: number;
  conflicts?: number;
  last_updated?: string | null;
  /** Temas (tipos de conocimiento) que ZENT aprendió dentro del dominio. */
  by_type?: { type: string; total: number; verified: number }[];
};

export type KnowledgeDeltaTotals = {
  objects: number;
  entities: number;
  concepts: number;
  relationships: number;
  facts: number;
  rules: number;
  metrics: number;
  terms: number;
  processes: number;
  evidence: number;
  sources: number;
  conflicts_resolved: number;
  conflicts_detected: number;
};

export type KnowledgeDeltaEnriched = {
  id: string;
  type: string;
  name: string;
  updated_at: string | null;
  created_at: string | null;
};

export type KnowledgeDeltaTimelinePoint = {
  bucket: string | null;
  objects: number;
  facts: number;
  relationships: number;
  evidence: number;
};

export type KnowledgeDelta = {
  window: string;
  since: string;
  until: string;
  bucket: "hour" | "day";
  totals: KnowledgeDeltaTotals;
  by_type: { kind: string; total: number; verified: number }[];
  enriched: KnowledgeDeltaEnriched[];
  enriched_total: number;
  by_domain: { domain: string; objects: number }[];
  timeline: KnowledgeDeltaTimelinePoint[];
  computed_at: string;
};

export const KNOWLEDGE_DELTA_WINDOWS = ["24h", "7d", "30d"] as const;
export type KnowledgeDeltaWindow = (typeof KNOWLEDGE_DELTA_WINDOWS)[number] | "custom";

export type KnowledgeAttention = {
  kind: string;
  severity: "high" | "medium" | "low";
  count: number;
  title: string;
  href: string;
};

export type KnowledgeActivityItem = {
  kind: "event" | "object" | "assertion";
  id: string;
  type: string;
  title: string;
  status?: string;
  severity?: string;
  category?: string;
  at: string | null;
};

export type LastLearningRun = {
  id: string;
  source_id: string | null;
  status: string;
  current_stage: string;
  overall_progress: number;
  entities_detected: number;
  fields_detected: number;
  relationships_detected: number;
  metrics: Record<string, unknown>;
  error_summary: Record<string, unknown>;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
};

export type KnowledgeOverview = {
  state: KnowledgeState;
  headline: string;
  generated_at: string;
  health: KnowledgeHealth;
  domains: KnowledgeDomain[];
  attention: KnowledgeAttention[];
  counts: {
    objects: number;
    verified: number;
    inferred: number;
    discovered: number;
    assertions: number;
    evidence: number;
    edges: number;
    sources: number;
    indexed_sources: number;
    indexed_documents: number;
    by_type: Record<string, { total: number; verified: number; inferred: number }>;
  };
  recent: KnowledgeActivityItem[];
  last_learning: LastLearningRun | null;
  conflicts_preview: KnowledgeConflict[];
  gaps_preview: KnowledgeGap[];
  materialized: boolean;
};

export type KnowledgeGap = {
  id: string;
  type: string;
  concept: string;
  title: string;
  description: string | null;
  priority: "critical" | "high" | "medium" | "low";
  priority_score: number;
  status: string;
  occurrences: number;
  question: string | null;
  impact: Record<string, unknown>;
  impact_objects: number;
  object_id: string | null;
  source_id: string | null;
  evidence_hints: unknown[];
  first_seen_at: string | null;
  last_seen_at: string | null;
  origin?: string;
};

export type KnowledgeConflict = {
  id: string;
  object_id: string | null;
  subject_label: string;
  predicate: string;
  assertion_a: string | null;
  assertion_b: string | null;
  value_a: string | null;
  value_b: string | null;
  source_a: string | null;
  source_b: string | null;
  status: "open" | "investigating" | "resolved" | "ignored";
  resolution: string | null;
  resolved_value: string | null;
  reason: string | null;
  detected_at: string | null;
};

export type QualityIssue = {
  kind: string;
  severity: "high" | "medium" | "low";
  title: string;
  count: number;
  action: string;
  items: Record<string, unknown>[];
};

export type QualityReport = {
  issues: QualityIssue[];
  total: number;
  by_severity: Record<string, number>;
  generated_at: string;
};

export type KnowledgeObjectDetail = {
  object: KnowledgeObject;
  edges: KnowledgeEdge[];
  assertions: KnowledgeAssertion[];
  evidence: KnowledgeEvidence[];
  versions: {
    version: number;
    change_kind: string;
    snapshot: Record<string, unknown>;
    changed_by: string | null;
    reason: string | null;
    created_at: string | null;
  }[];
  lineage: {
    physical_refs: { system: string; object_type: string; object_ref: string }[];
    lineage: Record<string, unknown>[];
    count: number;
  };
  impact: {
    object: string | null;
    dependents: {
      kind: string;
      id: string;
      type: string;
      name: string;
      via?: string;
      status?: string;
      confidence?: number;
    }[];
    count: number;
  };
  questions: { id: string; title: string; priority: string }[];
};

export type KnowledgeGraphPayload = {
  nodes: {
    id: string;
    type: string;
    name: string;
    domain: string | null;
    status: string;
    confidence: number | null;
    evidence_count: number;
    degree: number;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    predicate: string;
    relationship_type: string;
    confidence: number;
    status: string;
    provenance: string;
  }[];
  counts: { nodes: number; edges: number };
  truncated: boolean;
  focus_id: string | null;
  depth: number;
};

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

export function fetchKnowledgeOverview(): Promise<KnowledgeOverview> {
  return withSession<KnowledgeOverview>("/api/v1/knowledge/overview");
}

export function fetchKnowledgeDelta(params: {
  window: KnowledgeDeltaWindow;
  since?: string;
  until?: string;
}): Promise<KnowledgeDelta> {
  const query = new URLSearchParams();
  query.set("window", params.window);
  if (params.since) query.set("since", params.since);
  if (params.until) query.set("until", params.until);
  return withSession<KnowledgeDelta>(`/api/v1/knowledge/delta?${query.toString()}`);
}

export function fetchKnowledgeDomains(): Promise<{
  domains: KnowledgeDomain[];
  count: number;
}> {
  return withSession<{ domains: KnowledgeDomain[]; count: number }>(
    "/api/v1/knowledge/domains"
  );
}

export function fetchKnowledgeHealth(): Promise<KnowledgeHealth> {
  return withSession<KnowledgeHealth>("/api/v1/knowledge/health");
}

export type KnowledgeCompilation = {
  id: string;
  source_id: string | null;
  document_id: string | null;
  kind: string;
  status: string;
  counts: {
    units: number;
    entities: number;
    entities_merged: number;
    facts: number;
    relationships: number;
    rules: number;
    conflicts: number;
    evidence: number;
  };
  duration_ms: number;
  error: string | null;
  document_title: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export function fetchKnowledgeCompilations(
  limit = 25,
  sourceId?: string
): Promise<{ items: KnowledgeCompilation[]; total: number }> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (sourceId) query.set("source_id", sourceId);
  return withSession<{ items: KnowledgeCompilation[]; total: number }>(
    `/api/v1/knowledge/compilations?${query.toString()}`
  );
}

export function fetchKnowledgeObjects(
  params: {
    type?: string;
    domain?: string;
    status?: string;
    source_id?: string;
    q?: string;
    min_confidence?: number;
    order_by?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<{ items: KnowledgeObject[]; count: number; total: number }> {
  const query = new URLSearchParams();
  if (params.type) query.set("type", params.type);
  if (params.domain) query.set("domain", params.domain);
  if (params.status) query.set("status", params.status);
  if (params.source_id) query.set("source_id", params.source_id);
  if (params.q) query.set("q", params.q);
  if (params.min_confidence != null) query.set("min_confidence", String(params.min_confidence));
  if (params.order_by) query.set("order_by", params.order_by);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return withSession(`/api/v1/knowledge/objects?${query.toString()}`);
}

export function fetchKnowledgeObject(id: string): Promise<KnowledgeObjectDetail> {
  return withSession<KnowledgeObjectDetail>(`/api/v1/knowledge/objects/${id}`);
}

export function fetchKnowledgeSearch(
  q: string,
  limit = 10
): Promise<{
  groups: { type: string; count: number }[];
  items: KnowledgeObject[];
  count: number;
}> {
  return withSession(
    `/api/v1/knowledge/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
}

export function fetchKnowledgeGraph(
  params: {
    focus_id?: string;
    types?: string;
    domains?: string;
    min_confidence?: number;
    limit_nodes?: number;
    limit_edges?: number;
  } = {}
): Promise<KnowledgeGraphPayload> {
  const query = new URLSearchParams();
  if (params.focus_id) query.set("focus_id", params.focus_id);
  if (params.types) query.set("types", params.types);
  if (params.domains) query.set("domains", params.domains);
  if (params.min_confidence != null) query.set("min_confidence", String(params.min_confidence));
  query.set("limit_nodes", String(params.limit_nodes ?? 120));
  query.set("limit_edges", String(params.limit_edges ?? 300));
  return withSession(`/api/v1/knowledge/graph?${query.toString()}`);
}

export function fetchKnowledgeGaps(
  params: { status?: string; gap_type?: string; priority?: string; limit?: number } = {}
): Promise<{ gaps: KnowledgeGap[]; count: number; open: number; critical: number }> {
  const query = new URLSearchParams();
  query.set("status", params.status ?? "open");
  if (params.gap_type) query.set("gap_type", params.gap_type);
  if (params.priority) query.set("priority", params.priority);
  query.set("limit", String(params.limit ?? 100));
  return withSession(`/api/v1/knowledge/gaps?${query.toString()}`);
}

export function resolveKnowledgeGap(
  gapId: string,
  payload: { status: string; note?: string }
): Promise<{ id: string; status: string }> {
  return withSession(`/api/v1/knowledge/gaps/${gapId}/resolve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchKnowledgeConflicts(
  status = "open"
): Promise<{ conflicts: KnowledgeConflict[]; count: number }> {
  return withSession(
    `/api/v1/knowledge/conflicts?status=${encodeURIComponent(status)}`
  );
}

export function resolveKnowledgeConflict(
  conflictId: string,
  payload: { resolution: string; resolved_value?: string | null; reason?: string | null }
): Promise<KnowledgeConflict> {
  return withSession(`/api/v1/knowledge/conflicts/${conflictId}/resolve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchKnowledgeQuality(limit = 25): Promise<QualityReport> {
  return withSession<QualityReport>(`/api/v1/knowledge/quality?limit=${limit}`);
}

export function fetchKnowledgeActivity(limit = 50): Promise<{
  items: KnowledgeActivityItem[];
  count: number;
}> {
  return withSession(`/api/v1/knowledge/activity?limit=${limit}`);
}

export function verifyKnowledgeObject(id: string): Promise<KnowledgeObject> {
  return withSession(`/api/v1/knowledge/objects/${id}/verify`, { method: "POST" });
}

export function verifyKnowledgeAssertion(id: string): Promise<KnowledgeAssertion> {
  return withSession(`/api/v1/knowledge/assertions/${id}/verify`, { method: "POST" });
}

export function rebuildKnowledgeModel(sourceId?: string): Promise<Record<string, unknown>> {
  return withSession("/api/v1/knowledge/model/rebuild", {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId ?? null }),
  });
}

export function learnSource(
  sourceId: string,
  trigger = "manual"
): Promise<{ run: Record<string, unknown>; job_id: string }> {
  return withSession(`/api/v1/knowledge/sources/${sourceId}/learn`, {
    method: "POST",
    body: JSON.stringify({ trigger }),
  });
}

// ---------------------------------------------------------------------------
// Etiquetas y tonos
// ---------------------------------------------------------------------------

export const OBJECT_TYPE_LABELS: Record<string, string> = {
  domain: "Dominio",
  concept: "Concepto",
  entity: "Entidad",
  attribute: "Atributo",
  relationship: "Relación",
  business_rule: "Regla de negocio",
  metric: "Métrica",
  kpi: "KPI",
  process: "Proceso",
  term: "Término",
  synonym: "Sinónimo",
  event: "Evento",
  constraint: "Restricción",
  verified_query: "Consulta verificada",
  source: "Fuente",
  table: "Tabla",
  column: "Columna",
  document: "Documento",
  section: "Sección",
  chunk: "Fragmento",
};

export const BUSINESS_TYPES = [
  "domain",
  "concept",
  "entity",
  "attribute",
  "relationship",
  "business_rule",
  "metric",
  "kpi",
  "process",
  "term",
  "synonym",
  "event",
  "constraint",
  "verified_query",
];

export const GAP_TYPE_LABELS: Record<string, string> = {
  UNKNOWN_DEFINITION: "Definición desconocida",
  LOW_CONFIDENCE: "Baja confianza",
  MISSING_RELATIONSHIP: "Relación faltante",
  AMBIGUOUS_TERM: "Término ambiguo",
  CONTRADICTION: "Contradicción",
  MISSING_METRIC_DEFINITION: "Métrica sin definición",
  MISSING_BUSINESS_RULE: "Regla de negocio faltante",
  STALE_KNOWLEDGE: "Conocimiento desactualizado",
  UNRESOLVED_QUERY: "Consulta sin resolver",
  UNSUPPORTED_ASSERTION: "Afirmación sin evidencia",
  INCOMPLETE_SOURCE: "Fuente incompleta",
  RETRIEVAL_FAILURE: "Fallo de recuperación",
  MISSING_SOURCE: "Fuente faltante",
  MISSING_TABLE: "Tabla faltante",
  MISSING_FIELD: "Campo faltante",
  MISSING_BUSINESS_TERM: "Término de negocio faltante",
  MISSING_METRIC: "Métrica faltante",
  UNDEFINED_ENUM: "Enum sin documentar",
  STALE_SOURCE: "Fuente desactualizada",
  LOW_DATA_QUALITY: "Calidad de datos baja",
  SOURCE_CONFLICT: "Conflicto entre fuentes",
  CONTEXT_MISSING: "Contexto faltante",
  DATA_MISSING: "Datos faltantes",
  PERMISSION_LIMITATION: "Limitación de permisos",
  UNSUPPORTED_OPERATION: "Operación no soportada",
};

export function objectTypeLabel(type: string): string {
  return OBJECT_TYPE_LABELS[type] || type;
}

export function gapTypeLabel(type: string): string {
  return GAP_TYPE_LABELS[type] || type;
}

export function statusTone(status: string): string {
  if (status === "verified") return "badge-ok";
  if (status === "inferred") return "badge-info";
  if (status === "discovered") return "badge-muted";
  if (status === "rejected") return "badge-danger";
  if (status === "deprecated") return "badge-muted";
  if (status === "conflicted") return "badge-danger";
  if (status === "stale") return "badge-pending";
  return "badge-muted";
}

export function priorityTone(priority: string): string {
  if (priority === "critical") return "badge-danger";
  if (priority === "high") return "badge-pending";
  if (priority === "medium") return "badge-info";
  return "badge-muted";
}

export function confidenceTone(score: number | null | undefined): string {
  if (score == null) return "badge-muted";
  if (score >= 0.85) return "badge-ok";
  if (score >= 0.6) return "badge-info";
  if (score >= 0.35) return "badge-pending";
  return "badge-danger";
}

export function measuredLabel(dimension: HealthDimension): string {
  if (!dimension.measured || dimension.score == null) return "No medido";
  return `${Math.round(dimension.score)}`;
}
