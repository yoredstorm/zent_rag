// =============================================================================
// Knowledge Sessions API — "ZENT está aprendiendo"
// =============================================================================
// Cada número y cada texto viene de eventos reales del Knowledge Compiler o de
// tablas del Knowledge OS. El frontend NO inventa progreso: acumula lo que ya
// ocurrió (replay durable) y lo que sigue ocurriendo (SSE).
//
// Los eventos de alta frecuencia llegan agregados por ventana
// (payload.count + muestras acotadas): la UI nunca procesa 5.000 updates/s.
// =============================================================================
import { api, loadSession } from "../api";
import { emitAuthExpired } from "./errors";

function withSession<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = loadSession();
  return api<T>(path, {
    ...options,
    token: session?.token,
    organizationId: session?.organizationId,
  });
}

export type SessionStatus =
  | "preparing"
  | "learning"
  | "available"
  | "optimizing"
  | "completed"
  | "partial"
  | "failed"
  | "canceled";

export type SourceStatus =
  | "pending"
  | "learning"
  | "available"
  | "completed"
  | "failed";

export type SessionStageKey =
  | "reading"
  | "understanding"
  | "organizing"
  | "connecting"
  | "verifying"
  | "learned";

export interface SessionStage {
  key: SessionStageKey | string;
  label: string;
  technical?: string | null;
}

export interface KnowledgeDelta {
  new_concepts: number;
  new_entities: number;
  new_facts: number;
  new_relationships: number;
  new_rules: number;
  new_evidence: number;
  reinforced_facts: number;
  enriched_entities: number;
  merged_entities: number;
  updated: number;
  related: number;
  duplicates: number;
  conflicts: number;
  ignored: number;
  totals_before: Record<string, number>;
  totals_after: Record<string, number>;
}

export interface SessionSource {
  id: string;
  session_id: string;
  source_id: string | null;
  job_id: string | null;
  name: string;
  source_type: string;
  status: SourceStatus | string;
  stage: SessionStageKey | string;
  stage_label: string;
  stats: Record<string, number>;
  error: string | null;
  available_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LearningSessionDetail {
  session_id: string;
  organization_id: string;
  workspace_id: string | null;
  title: string;
  origin: string;
  status: SessionStatus | string;
  stage: SessionStageKey | string;
  stage_label: string;
  stage_technical: string | null;
  stages: SessionStage[];
  source_count: number;
  available_sources: number;
  completed_sources: number;
  failed_sources: number;
  metrics: Record<string, number>;
  knowledge_delta: Partial<KnowledgeDelta>;
  delta_totals: Record<string, number>;
  totals_before: Record<string, number>;
  totals_after: Record<string, number>;
  warnings: number;
  errors: number;
  started_at: string | null;
  available_at: string | null;
  completed_at: string | null;
  sealed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  is_available: boolean;
  sources: SessionSource[];
}

export interface SessionEventPayload {
  count?: number;
  items?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface SessionEvent {
  seq: number;
  id?: string;
  session_id: string;
  source_id: string | null;
  event_type: string;
  stage: string | null;
  severity: "info" | "warning" | "error" | string;
  message: string;
  payload: SessionEventPayload;
  aggregate: boolean;
  created_at: string;
}

export interface Discovery {
  event_type: string;
  severity: string;
  stage: string | null;
  source_id: string | null;
  message: string;
  count: number;
  items: Array<Record<string, unknown>>;
  seq: number;
  at: string | null;
}

export interface SessionGraphNode {
  id: string;
  name: string;
  kind: string;
  known: boolean;
}

export interface SessionGraphEdge {
  id: string;
  subject: string;
  object: string;
  predicate: string;
}

export interface SessionGraph {
  session_id: string;
  nodes: SessionGraphNode[];
  edges: SessionGraphEdge[];
}

// ---------------------------------------------------------------------------
// REST
// ---------------------------------------------------------------------------

export function startLearningSession(payload: {
  title?: string;
  source_ids?: string[];
  origin?: string;
}): Promise<LearningSessionDetail> {
  return withSession<LearningSessionDetail>("/api/v1/knowledge/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchLearningSessions(
  limit = 20
): Promise<{ sessions: LearningSessionDetail[]; count: number }> {
  return withSession(`/api/v1/knowledge/sessions?limit=${limit}`);
}

export function sealLearningSession(
  sessionId: string
): Promise<LearningSessionDetail> {
  return withSession<LearningSessionDetail>(
    `/api/v1/knowledge/sessions/${sessionId}/seal`,
    { method: "POST" }
  );
}

export function fetchLearningSession(
  sessionId: string
): Promise<LearningSessionDetail> {
  return withSession(`/api/v1/knowledge/sessions/${sessionId}`);
}

export function fetchSessionEvents(
  sessionId: string,
  sinceSeq = 0,
  limit = 800
): Promise<{ events: SessionEvent[]; count: number }> {
  return withSession(
    `/api/v1/knowledge/sessions/${sessionId}/events?since_seq=${sinceSeq}&limit=${limit}`
  );
}

export function fetchSessionFeed(
  sessionId: string,
  limit = 60
): Promise<{ discoveries: Discovery[] }> {
  return withSession(
    `/api/v1/knowledge/sessions/${sessionId}/feed?limit=${limit}`
  );
}

export function fetchSessionGraph(sessionId: string): Promise<SessionGraph> {
  return withSession(`/api/v1/knowledge/sessions/${sessionId}/graph`);
}

// ---------------------------------------------------------------------------
// SSE: fetch reader (EventSource no soporta headers Authorization)
// ---------------------------------------------------------------------------

export type StreamHandle = { close: () => void };

export function streamLearningSession(options: {
  sessionId: string;
  sinceSeq?: number;
  onEvent: (event: SessionEvent) => void;
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
        `/api/v1/knowledge/sessions/${options.sessionId}/stream?since_seq=${
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
          const dataLine = frame
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const eventType = eventLine ? eventLine.slice(7).trim() : "message";
          if (eventType === "heartbeat") continue;
          try {
            const payload = JSON.parse(dataLine.slice(6)) as SessionEvent;
            options.onEvent({
              ...payload,
              event_type: payload.event_type || eventType,
              seq: Number(payload.seq ?? 0),
            });
          } catch {
            // Frame parcial o malformado: se ignora, el siguiente lo completa.
          }
        }
      }
      options.onError?.("stream_closed");
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      options.onError?.("stream_failed");
    }
  })();

  return { close: () => controller.abort() };
}
