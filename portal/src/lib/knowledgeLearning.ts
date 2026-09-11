// =============================================================================
// Knowledge Learning API — tipos reales y streaming SSE (FASE 33E)
// =============================================================================
// Todo lo que muestra la UI proviene de estados reales del backend:
// /status, /sources, /runs/{id}, /runs/{id}/events (SSE), /questions,
// /entities y /score. Nunca se inventa progreso ni confianza.
// =============================================================================
import { api, loadSession } from "../api";
import { emitAuthExpired } from "./errors";

function withSession<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const session = loadSession();
  return api<T>(path, {
    ...options,
    token: session?.token,
    organizationId: session?.organizationId,
  });
}

export type KnowledgeGate =
  | "NOT_READY"
  | "LEARNING"
  | "NEEDS_INPUT"
  | "READY"
  | "DEGRADED";

export type ScoreDimension = {
  key: string;
  label: string;
  score: number;
  weight: number;
  detail: string;
  measured: boolean;
};

export type KnowledgeScore = {
  overall: number;
  gate: KnowledgeGate;
  dimensions: ScoreDimension[];
  reasons: string[];
  weights: Record<string, number>;
  computed_at: string | null;
  source_id?: string | null;
};

export type LearningStatusCounts = {
  sources_connected: number;
  tables_total: number;
  columns_total: number;
  entities_total: number;
  entities_understood: number;
  fields_total: number;
  relationships_total: number;
  relationships_confirmed: number;
  pending_questions: number;
  verified_knowledge: number;
  open_gaps: number;
};

export type LearningStatus = {
  enabled: boolean;
  headline: string;
  counts: LearningStatusCounts;
  readiness: { overall: number | null; gate: KnowledgeGate; computed_at: string | null };
  active_runs: LearningRun[];
  sources: SourceLearning[];
};

export type SourceLearning = {
  source_id: string;
  connector_id: string;
  engine: string | null;
  connectivity: "healthy" | "degraded" | "unknown";
  phase: string | null;
  last_learning_at: string | null;
  scan_error: string | null;
  knowledge: { overall: number | null; gate: KnowledgeGate };
  tables: { analyzed: number; total: number };
  fields: { understood: number; total: number; documented: number };
  relationships: { discovered: number; confirmed: number };
  pending_questions: number;
  active_run: {
    id: string;
    status: string;
    current_stage: string;
    overall_progress: number;
  } | null;
};

export type LearningRun = {
  id: string;
  organization_id: string;
  catalog_source_id: string | null;
  status: "queued" | "running" | "awaiting_validation" | "completed" | "failed" | "cancelled";
  current_stage: string;
  overall_progress: number;
  stage_progress: number;
  gate: KnowledgeGate | null;
  tables_analyzed: number;
  entities_detected: number;
  fields_detected: number;
  relationships_detected: number;
  metrics: Record<string, unknown>;
  error_summary: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  steps?: LearningStep[];
};

export type LearningStep = {
  id: string;
  stage: string;
  sequence: number;
  status: "pending" | "running" | "completed" | "skipped" | "failed";
  progress: number;
  metrics: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
};

export type LearningEvent = {
  id: string;
  seq: number;
  run_id: string | null;
  source_id: string | null;
  event_type: string;
  stage: string | null;
  category: "discovery" | "ai" | "validation" | "indexing" | "system";
  severity: "info" | "success" | "warning" | "error";
  message: string;
  payload: Record<string, unknown>;
  created_at: string | null;
};

export type KnowledgeQuestionOption = {
  value: string;
  label: string;
  occurrence_count?: number;
};

export type KnowledgeQuestion = {
  id: string;
  source_id: string | null;
  run_id: string | null;
  entity_id: string | null;
  field_id: string | null;
  column_id: string | null;
  question_type: string;
  title: string;
  body: string;
  evidence: string[];
  options: KnowledgeQuestionOption[];
  answer_schema: Record<string, unknown>;
  priority: "critical" | "high" | "medium" | "low";
  priority_score: number;
  impact: Record<string, unknown>;
  status: "pending" | "answered" | "skipped" | "deferred" | "expired";
  answer: Record<string, unknown>;
  structured_answer: Record<string, unknown>;
  confidence_before: number | null;
  confidence_after: number | null;
  created_at: string | null;
  answered_at: string | null;
};

export type LearnedEntity = {
  entity_id: string;
  name: string;
  display_name: string;
  description: string | null;
  confidence: number;
  confidence_label: string;
  provenance: string;
  status: string;
  table: string | null;
  source_id: string | null;
  fields_total: number;
  fields_understood: number;
  columns_total: number;
  coverage_pct: number | null;
  relationships_total: number;
  relationships_confirmed: number;
  business_rules_total: number;
  business_rules_approved: number;
  open_questions: number;
  last_learned_at: string | null;
};

export const GATE_LABELS: Record<KnowledgeGate, string> = {
  NOT_READY: "Aún no listo",
  LEARNING: "Aprendiendo",
  NEEDS_INPUT: "Necesita tu ayuda",
  READY: "Listo",
  DEGRADED: "Degradado",
};

export const STAGE_LABELS: Record<string, string> = {
  connecting: "Conectando a la fuente",
  discovering_schema: "Descubriendo schema",
  profiling: "Perfilando columnas",
  detecting_entities: "Detectando entidades",
  analyzing_fields: "Analizando campos",
  detecting_relationships: "Entendiendo relaciones",
  llm_reasoning: "Razonando con el LLM",
  generating_questions: "Generando preguntas",
  awaiting_validation: "Esperando tu validación",
  chunking: "Fragmentando conocimiento",
  embedding: "Construyendo embeddings",
  indexing: "Indexando",
  evaluating: "Evaluando conocimiento",
  scoring: "Calculando readiness",
  ready: "Conocimiento listo",
};

export const CATEGORY_LABELS: Record<string, string> = {
  discovery: "Descubrimiento",
  ai: "IA",
  validation: "Validación",
  indexing: "Indexado",
  system: "Sistema",
};

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "";
  return STAGE_LABELS[stage] || stage;
}

export function priorityTone(priority: string): string {
  if (priority === "critical") return "badge-danger";
  if (priority === "high") return "badge-pending";
  if (priority === "medium") return "badge-muted";
  return "badge-muted";
}

export function gateTone(gate: KnowledgeGate | null | undefined): string {
  if (!gate) return "badge-muted";
  if (gate === "READY") return "badge-ok";
  if (gate === "NEEDS_INPUT") return "badge-pending";
  if (gate === "DEGRADED") return "badge-danger";
  if (gate === "LEARNING") return "badge-pending";
  return "badge-muted";
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

export function fetchLearningStatus(): Promise<LearningStatus> {
  return withSession<LearningStatus>("/api/v1/knowledge/learning/status");
}

export function fetchLearningSources(): Promise<SourceLearning[]> {
  return withSession<SourceLearning[]>("/api/v1/knowledge/learning/sources");
}

export function fetchLearningRun(runId: string): Promise<LearningRun> {
  return withSession<LearningRun>(`/api/v1/knowledge/learning/runs/${runId}`);
}

export function fetchRunEvents(
  runId: string,
  sinceSeq = 0,
  limit = 500
): Promise<{ events: LearningEvent[]; count: number }> {
  return withSession<{ events: LearningEvent[]; count: number }>(
    `/api/v1/knowledge/learning/runs/${runId}/events?since_seq=${sinceSeq}&limit=${limit}`
  );
}

export function fetchEvents(
  params: { category?: string; source_id?: string; limit?: number } = {}
): Promise<{ events: LearningEvent[]; count: number }> {
  const query = new URLSearchParams();
  if (params.category) query.set("category", params.category);
  if (params.source_id) query.set("source_id", params.source_id);
  query.set("limit", String(params.limit ?? 80));
  return withSession<{ events: LearningEvent[]; count: number }>(
    `/api/v1/knowledge/learning/events?${query.toString()}`
  );
}

export function fetchQuestions(
  params: { source_id?: string; status?: string; entity_id?: string; limit?: number } = {}
): Promise<{
  questions: KnowledgeQuestion[];
  count: number;
  pending: number;
  blocking: number;
}> {
  const query = new URLSearchParams();
  if (params.source_id) query.set("source_id", params.source_id);
  if (params.entity_id) query.set("entity_id", params.entity_id);
  query.set("status", params.status ?? "pending");
  query.set("limit", String(params.limit ?? 100));
  return withSession(`/api/v1/knowledge/learning/questions?${query.toString()}`);
}

export function fetchLearnedEntities(
  sourceId?: string,
  limit = 24
): Promise<{ entities: LearnedEntity[]; count: number }> {
  const query = new URLSearchParams();
  if (sourceId) query.set("source_id", sourceId);
  query.set("limit", String(limit));
  return withSession<{ entities: LearnedEntity[]; count: number }>(
    `/api/v1/knowledge/learning/entities?${query.toString()}`
  );
}

export function fetchKnowledgeScore(sourceId?: string): Promise<KnowledgeScore> {
  const query = sourceId ? `?source_id=${sourceId}` : "";
  return withSession<KnowledgeScore>(`/api/v1/knowledge/learning/score${query}`);
}

export function startLearning(catalogSourceId: string): Promise<{
  run: LearningRun;
  job_id: string;
}> {
  return withSession("/api/v1/knowledge/learning/start", {
    method: "POST",
    body: JSON.stringify({ catalog_source_id: catalogSourceId }),
  });
}

export function cancelLearning(runId: string): Promise<{ cancelled: string }> {
  return withSession(`/api/v1/knowledge/learning/runs/${runId}/cancel`, {
    method: "POST",
  });
}

export function answerQuestion(
  questionId: string,
  payload: { answer?: string; structured_answer?: Record<string, unknown>; choice?: string }
): Promise<{ question: KnowledgeQuestion; applied_to: Array<Record<string, unknown>> }> {
  return withSession(`/api/v1/knowledge/learning/questions/${questionId}/answer`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function skipQuestion(
  questionId: string,
  reason?: string
): Promise<{ question: KnowledgeQuestion }> {
  return withSession(`/api/v1/knowledge/learning/questions/${questionId}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export function deferQuestion(questionId: string): Promise<{ question: KnowledgeQuestion }> {
  return withSession(`/api/v1/knowledge/learning/questions/${questionId}/defer`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ---------------------------------------------------------------------------
// SSE: fetch reader (EventSource no soporta headers Authorization)
// ---------------------------------------------------------------------------

export type StreamHandle = { close: () => void };

export function streamRunEvents(options: {
  runId: string;
  sinceSeq?: number;
  onEvent: (event: LearningEvent) => void;
  onOpen?: () => void;
  onError?: (message: string) => void;
}): StreamHandle {
  const controller = new AbortController();
  const session = loadSession();
  const token = session?.token;
  const organizationId = session?.organizationId;

  (async () => {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (token) headers.Authorization = `Bearer ${token}`;
      if (organizationId) headers["X-Organization-Id"] = organizationId;
      const response = await fetch(
        `/api/v1/knowledge/learning/runs/${options.runId}/stream?since_seq=${
          options.sinceSeq ?? 0
        }`,
        { headers, signal: controller.signal, credentials: "same-origin" }
      );
      if (response.status === 401) {
        emitAuthExpired("tenant");
        options.onError?.("stream_http_401");
        return;
      }
      if (!response.ok || !response.body) {
        options.onError?.(`stream_http_${response.status}`);
        return;
      }
      options.onOpen?.();
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const eventLine = frame
            .split("\n")
            .find((line) => line.startsWith("event: "));
          const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine || !eventLine) continue;
          const eventType = eventLine.slice(7).trim();
          if (eventType === "heartbeat") continue;
          try {
            const payload = JSON.parse(dataLine.slice(6)) as LearningEvent;
            options.onEvent({ ...payload, event_type: payload.event_type || eventType });
          } catch {
            // frame incompleto: ignorar
          }
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        options.onError?.(error instanceof Error ? error.message : "stream_error");
      }
    }
  })();

  return { close: () => controller.abort() };
}
