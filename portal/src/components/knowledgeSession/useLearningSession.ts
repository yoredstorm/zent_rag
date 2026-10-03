// =============================================================================
// useLearningSession — estado vivo de una Knowledge Session
// =============================================================================
// Regla dura: la UI nunca inventa actividad. Este hook solo:
//   1. carga la verdad durable (detalle, eventos, grafo),
//   2. escucha el SSE de la sesión,
//   3. agrupa eventos entrantes en ventanas de 250 ms (batching en cliente),
//   4. deriva contadores SOLO de eventos reales.
// =============================================================================
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Discovery,
  fetchLearningSession,
  fetchSessionGraph,
  SessionEvent,
  SessionGraph,
  streamLearningSession,
  fetchSessionEvents,
  LearningSessionDetail,
} from "../../lib/knowledgeSessions";

const BATCH_MS = 250;
const DETAIL_POLL_MS = 4000;
const EVENTS_POLL_MS = 3000;
const GRAPH_POLL_MS = 9000;
const MAX_EVENTS = 4000;

// tipo de evento -> contador crudo (espejo de backend _EVENT_METRICS).
const EVENT_METRIC: Record<string, string> = {
  SEMANTIC_UNIT_CREATED: "semantic_units",
  SEMANTIC_RECONSTRUCTED: "reconstruction_sources",
  CONTINUATIONS_MERGED: "merged_continuations",
  FRAGMENTS_REJECTED: "fragments_rejected",
  SCHEMAS_INFERRED: "schemas_inferred",
  ENTITY_DISCOVERED: "entities_new",
  ENTITY_MATCHED: "entities_enriched",
  ENTITY_MERGED: "merges",
  FACT_DISCOVERED: "facts_new",
  FACT_REINFORCED: "facts_reinforced",
  RELATIONSHIP_DISCOVERED: "relationships",
  RULE_DISCOVERED: "rules",
  EVIDENCE_LINKED: "evidence",
  CONFLICT_DETECTED: "conflicts",
  DUPLICATE_DETECTED: "duplicates",
  TABLE_DETECTED: "tables",
  INDEX_UPDATED: "chunks",
  KNOWLEDGE_OBJECT_CREATED: "knowledge_objects",
  TEMPORAL_RANGE_DISCOVERED: "temporal_ranges",
};

export interface LearningSessionState {
  detail: LearningSessionDetail | null;
  events: SessionEvent[];
  graph: SessionGraph | null;
  metrics: Record<string, number>;
  delta: Record<string, number>;
  discoveries: Discovery[];
  stage: string;
  connected: boolean;
  loading: boolean;
  error: string;
  lastEventAt: string | null;
  active: boolean;
  refresh: () => void;
}

export function deriveMetrics(events: SessionEvent[]): Record<string, number> {
  const raw: Record<string, number> = {};
  for (const event of events) {
    const key = EVENT_METRIC[event.event_type];
    if (!key) continue;
    const count = Math.max(1, Number(event.payload?.count ?? 1));
    raw[key] = (raw[key] ?? 0) + count;
  }
  raw.entities = (raw.entities_new ?? 0) + (raw.entities_enriched ?? 0);
  raw.facts = (raw.facts_new ?? 0) + (raw.facts_reinforced ?? 0);
  return raw;
}

export function deriveDelta(events: SessionEvent[]): Record<string, number> {
  const delta: Record<string, number> = {
    new_entities: 0,
    new_facts: 0,
    new_relationships: 0,
    new_rules: 0,
    new_evidence: 0,
    reinforced_facts: 0,
    enriched_entities: 0,
    merged_entities: 0,
    updated: 0,
    related: 0,
    duplicates: 0,
    conflicts: 0,
    ignored: 0,
  };
  for (const event of events) {
    const count = Math.max(1, Number(event.payload?.count ?? 1));
    switch (event.event_type) {
      case "ENTITY_DISCOVERED":
        delta.new_entities += count;
        break;
      case "ENTITY_MATCHED":
        delta.enriched_entities += count;
        break;
      case "ENTITY_MERGED":
        delta.merged_entities += count;
        break;
      case "FACT_DISCOVERED":
        delta.new_facts += count;
        break;
      case "FACT_REINFORCED":
        delta.reinforced_facts += count;
        break;
      case "RELATIONSHIP_DISCOVERED":
        delta.new_relationships += count;
        if (event.payload?.related === true) delta.related += count;
        break;
      case "RULE_DISCOVERED":
        delta.new_rules += count;
        break;
      case "EVIDENCE_LINKED":
        delta.new_evidence += count;
        break;
      case "DUPLICATE_DETECTED":
        delta.duplicates += count;
        delta.ignored += count;
        break;
      case "CONFLICT_DETECTED": {
        const type = String(event.payload?.conflict_type ?? "");
        if (type === "VERSION_CHANGE" || type === "TEMPORAL_CHANGE") {
          delta.updated += count;
        } else {
          delta.conflicts += count;
        }
        break;
      }
      default:
        break;
    }
  }
  return delta;
}

/** Agrupa eventos consecutivos del mismo tipo/fuente: "ZENT reconoció 84 carriers". */
export function groupDiscoveries(
  events: SessionEvent[],
  limit = 60
): Discovery[] {
  const hidden = new Set([
    "SESSION_STARTED",
    "SOURCE_RECEIVED",
    "PARSING_STARTED",
    "INDEX_UPDATED",
    "SOURCE_AVAILABLE",
  ]);
  const grouped: Discovery[] = [];
  let current: Discovery | null = null;
  for (const event of events) {
    if (hidden.has(event.event_type)) continue;
    const count = Math.max(1, Number(event.payload?.count ?? 1));
    const sameAsCurrent =
      current !== null &&
      current.event_type === event.event_type &&
      current.source_id === (event.source_id ?? null) &&
      current.items.length < 5;
    if (sameAsCurrent && current) {
      current.count += count;
      current.items.push(event.payload ?? {});
      current.at = event.created_at ?? current.at;
      current.message = event.message || current.message;
      continue;
    }
    current = {
      event_type: event.event_type,
      severity: event.severity,
      stage: event.stage,
      source_id: event.source_id ?? null,
      message: event.message,
      count,
      items: [event.payload ?? {}],
      seq: event.seq,
      at: event.created_at ?? null,
    };
    grouped.push(current);
  }
  return grouped.slice(-limit).reverse();
}

function mergeEvents(previous: SessionEvent[], incoming: SessionEvent[]): SessionEvent[] {
  if (incoming.length === 0) return previous;
  const bySeq = new Map<number, SessionEvent>();
  for (const event of previous) bySeq.set(event.seq, event);
  for (const event of incoming) {
    if (!Number.isFinite(event.seq) || event.seq <= 0) continue;
    bySeq.set(event.seq, event);
  }
  const merged = Array.from(bySeq.values()).sort((a, b) => a.seq - b.seq);
  return merged.length > MAX_EVENTS ? merged.slice(merged.length - MAX_EVENTS) : merged;
}

export function useLearningSession(
  sessionId: string | undefined,
  options: { includeGraph?: boolean } = {}
): LearningSessionState {
  const includeGraph = options.includeGraph !== false;
  const [detail, setDetail] = useState<LearningSessionDetail | null>(null);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [graph, setGraph] = useState<SessionGraph | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const lastSeqRef = useRef(0);
  const pendingRef = useRef<SessionEvent[]>([]);
  const closedRef = useRef(false);

  const active = Boolean(
    detail &&
      !["completed", "partial", "failed", "canceled"].includes(detail.status)
  );

  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  // ------------------------------------------------------------- carga inicial
  useEffect(() => {
    if (!sessionId) return;
    closedRef.current = false;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [loadedDetail, loadedEvents] = await Promise.all([
          fetchLearningSession(sessionId),
          fetchSessionEvents(sessionId, 0, 2000),
        ]);
        if (cancelled) return;
        setDetail(loadedDetail);
        setEvents(mergeEvents([], loadedEvents.events));
        lastSeqRef.current = loadedEvents.events.reduce(
          (max, event) => Math.max(max, event.seq),
          0
        );
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "No se pudo cargar la sesión");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshKey]);

  // -------------------------------------------------------------------- SSE
  useEffect(() => {
    if (!sessionId) return;
    const handle = streamLearningSession({
      sessionId,
      sinceSeq: lastSeqRef.current,
      onOpen: () => setConnected(true),
      onError: () => setConnected(false),
      onEvent: (event) => {
        pendingRef.current.push(event);
      },
    });
    const flush = window.setInterval(() => {
      const batch = pendingRef.current;
      if (batch.length === 0) return;
      pendingRef.current = [];
      for (const event of batch) {
        lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
      }
      setEvents((prev) => mergeEvents(prev, batch));
    }, BATCH_MS);
    return () => {
      handle.close();
      window.clearInterval(flush);
      setConnected(false);
    };
  }, [sessionId]);

  // -------------------------------------------------- polling de respaldo
  useEffect(() => {
    if (!sessionId) return;
    let stopped = false;
    const pollDetail = window.setInterval(async () => {
      if (stopped) return;
      try {
        const fresh = await fetchLearningSession(sessionId);
        if (!stopped) setDetail(fresh);
      } catch {
        // silencio: el SSE sigue siendo la fuente primaria
      }
    }, DETAIL_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(pollDetail);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let stopped = false;
    const pollEvents = window.setInterval(async () => {
      if (stopped) return;
      try {
        const fresh = await fetchSessionEvents(sessionId, lastSeqRef.current, 800);
        if (stopped || fresh.events.length === 0) return;
        for (const event of fresh.events) {
          lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
        }
        setEvents((prev) => mergeEvents(prev, fresh.events));
      } catch {
        // silencio
      }
    }, EVENTS_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(pollEvents);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !includeGraph) return;
    let stopped = false;
    const load = async () => {
      try {
        const fresh = await fetchSessionGraph(sessionId);
        if (!stopped) setGraph(fresh);
      } catch {
        // el grafo es opcional
      }
    };
    load();
    const poll = window.setInterval(load, GRAPH_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(poll);
    };
  }, [sessionId, includeGraph]);

  // ---------------------------------------------------------- derivaciones
  // Los contadores del servidor son la verdad durable; los derivados de
  // eventos son la verdad viva. Se toma el mayor por clave (nunca se infla:
  // ambos cuentan exactamente los mismos eventos y convergen).
  const metrics = useMemo(() => {
    const derived = deriveMetrics(events);
    const server = (detail?.metrics ?? {}) as Record<string, unknown>;
    const merged: Record<string, number> = { ...derived };
    for (const [key, value] of Object.entries(server)) {
      const numeric = Number(value);
      if (Number.isFinite(numeric)) {
        merged[key] = Math.max(merged[key] ?? 0, numeric);
      }
    }
    merged.sources = Math.max(merged.sources ?? 0, detail?.source_count ?? 0);
    merged.sources_available = Math.max(
      merged.sources_available ?? 0,
      detail?.available_sources ?? 0
    );
    return merged;
  }, [events, detail?.metrics, detail?.source_count, detail?.available_sources]);

  const derivedDelta = useMemo(() => deriveDelta(events), [events]);

  const delta = useMemo(() => {
    const server = (detail?.knowledge_delta || {}) as Record<string, unknown>;
    const hasServer = Object.keys(server).length > 0;
    if (!hasServer) return derivedDelta;
    const merged: Record<string, number> = { ...derivedDelta };
    for (const key of Object.keys(derivedDelta)) {
      const value = server[key];
      if (typeof value === "number") merged[key] = value;
    }
    return merged;
  }, [detail?.knowledge_delta, derivedDelta]);

  const discoveries = useMemo(() => groupDiscoveries(events), [events]);

  const stage = useMemo(() => {
    const order = [
      "reading",
      "understanding",
      "organizing",
      "connecting",
      "verifying",
      "learned",
    ];
    const stageOf = (value: string | null | undefined) => {
      const index = order.indexOf(String(value ?? ""));
      return index < 0 ? -1 : index;
    };
    // La etapa del servidor manda; el último evento solo cubre sesiones sin
    // etapa persistida. Un evento de fuente ya terminada no adelanta la sesión.
    const serverStage = stageOf(detail?.stage);
    if (serverStage >= 0) return order[serverStage];
    const lastEventStage = events.length
      ? stageOf(events[events.length - 1].stage)
      : -1;
    return order[Math.max(0, lastEventStage)];
  }, [detail?.stage, events]);

  const lastEventAt = events.length
    ? events[events.length - 1].created_at
    : null;

  return {
    detail,
    events,
    graph,
    metrics,
    delta,
    discoveries,
    stage,
    connected,
    loading,
    error,
    lastEventAt,
    active: active || (detail?.status === "preparing"),
    refresh,
  };
}
