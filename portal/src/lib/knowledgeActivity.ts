// =============================================================================
// Activity feed del Knowledge OS — una sola historia, tres fuentes reales
// =============================================================================
// knowledge_events (aprendizaje), knowledge/activity (objetos + eventos de
// dominio) y knowledge_compilations (qué produjo cada documento). Todo se
// agrupa para no mostrar miles de filas idénticas.
// =============================================================================
import {
  fetchKnowledgeActivity,
  fetchKnowledgeCompilations,
  type KnowledgeActivityItem,
  type KnowledgeCompilation,
} from "./knowledgeModel";
import { fetchEvents, type LearningEvent } from "./knowledgeLearning";
import { humanStageLabel, learningEventHeadline } from "./knowledgeLanguage";
import { loadSession } from "../api";
import { emitAuthExpired } from "./errors";

export type KnowledgeFeedKind = "learning" | "knowledge" | "compilation" | "object";

export type KnowledgeFeedItem = {
  id: string;
  kind: KnowledgeFeedKind;
  at: string | null;
  title: string;
  detail?: string;
  href?: string;
  category: string;
  severity: "info" | "success" | "warning" | "error";
  sourceId?: string | null;
  /** Veces que se repitió el mismo evento en la ventana de agrupación. */
  repeat: number;
};

const OBJECT_HREF = "/knowledge/objects/";

function activityTitle(item: KnowledgeActivityItem): string {
  if (item.kind === "object") return `ZENT aprendió ${item.title}`;
  if (item.kind === "assertion") return `ZENT verificó un hecho: ${item.title}`;
  return item.title;
}

export function learningEventToFeedItem(event: LearningEvent): KnowledgeFeedItem {
  const stage = humanStageLabel(event.stage);
  return {
    id: `learning-${event.id}`,
    kind: "learning",
    at: event.created_at,
    title: learningEventHeadline(event),
    detail: stage || undefined,
    href: event.run_id ? `/knowledge/activity?view=runs&run=${event.run_id}` : undefined,
    category: event.category,
    severity: event.severity,
    sourceId: event.source_id,
    repeat: 1,
  };
}

export function compilationToFeedItem(
  compilation: KnowledgeCompilation
): KnowledgeFeedItem {
  const counts = compilation.counts;
  const parts = [
    counts.entities > 0 ? `${counts.entities} conceptos` : "",
    counts.facts > 0 ? `${counts.facts} hechos` : "",
    counts.relationships > 0 ? `${counts.relationships} relaciones` : "",
    counts.rules > 0 ? `${counts.rules} reglas` : "",
  ].filter(Boolean);
  const title = compilation.document_title
    ? `ZENT comprendió ${compilation.document_title}`
    : "ZENT comprendió un documento";
  return {
    id: `compilation-${compilation.id}`,
    kind: "compilation",
    at: compilation.finished_at || compilation.started_at,
    title,
    detail: parts.length > 0 ? parts.join(" · ") : undefined,
    href: compilation.document_id
      ? `/knowledge/documents?document=${compilation.document_id}`
      : undefined,
    category: "discovery",
    severity: compilation.status === "failed" ? "error" : "success",
    sourceId: compilation.source_id,
    repeat: 1,
  };
}

export function knowledgeActivityToFeedItem(
  item: KnowledgeActivityItem
): KnowledgeFeedItem {
  return {
    id: `activity-${item.kind}-${item.id}`,
    kind: item.kind === "event" ? "knowledge" : "object",
    at: item.at,
    title: activityTitle(item),
    detail: item.category || undefined,
    href: item.kind === "object" ? `${OBJECT_HREF}${item.id}` : undefined,
    category: item.category || "knowledge",
    severity:
      item.severity === "error"
        ? "error"
        : item.severity === "warning"
          ? "warning"
          : item.kind === "object"
            ? "success"
            : "info",
    repeat: 1,
  };
}

/** Une las tres fuentes y ordena por fecha real descendente. */
export function mergeKnowledgeFeed(input: {
  events: LearningEvent[];
  activity: KnowledgeActivityItem[];
  compilations: KnowledgeCompilation[];
}): KnowledgeFeedItem[] {
  const items = [
    ...input.events.map(learningEventToFeedItem),
    ...input.compilations.map(compilationToFeedItem),
    ...input.activity.map(knowledgeActivityToFeedItem),
  ];
  return items.sort((a, b) => {
    const ta = a.at ? Date.parse(a.at) : 0;
    const tb = b.at ? Date.parse(b.at) : 0;
    return tb - ta;
  });
}

/**
 * Agrupa eventos repetidos: mismo título en una ventana de 15 minutos cuenta
 * como uno con `repeat`. No oculta información: el detalle queda visible.
 */
export function groupKnowledgeFeed(
  items: KnowledgeFeedItem[],
  windowMs = 15 * 60 * 1000
): KnowledgeFeedItem[] {
  const grouped: KnowledgeFeedItem[] = [];
  for (const item of items) {
    const previous = grouped[grouped.length - 1];
    if (previous) {
      const sameTitle = previous.title === item.title;
      const ta = previous.at ? Date.parse(previous.at) : 0;
      const tb = item.at ? Date.parse(item.at) : 0;
      const close = Math.abs(ta - tb) <= windowMs;
      if (sameTitle && close) {
        previous.repeat += 1;
        continue;
      }
    }
    grouped.push({ ...item });
  }
  return grouped;
}

export async function fetchKnowledgeFeed(limit = 60): Promise<KnowledgeFeedItem[]> {
  const [eventsResult, activityResult, compilationsResult] = await Promise.allSettled([
    fetchEvents({ limit }),
    fetchKnowledgeActivity(limit),
    fetchKnowledgeCompilations(Math.min(limit, 25)),
  ]);
  const events = eventsResult.status === "fulfilled" ? eventsResult.value.events : [];
  const activity =
    activityResult.status === "fulfilled" ? activityResult.value.items : [];
  const compilations =
    compilationsResult.status === "fulfilled" ? compilationsResult.value.items : [];
  return groupKnowledgeFeed(
    mergeKnowledgeFeed({ events, activity, compilations })
  );
}

// ---------------------------------------------------------------------------
// SSE: eventos de conocimiento en vivo (replay durable + bus)
// ---------------------------------------------------------------------------

export type KnowledgeStreamHandle = { close: () => void };

/**
 * Suscribe al stream real del Knowledge OS. El backend reenvía el historial
 * durable y luego los eventos live; el caller decide qué refrescar.
 */
export function streamKnowledgeEvents(options: {
  sinceSeq?: number;
  onEvent: (event: LearningEvent) => void;
  onOpen?: () => void;
  onError?: (message: string) => void;
}): KnowledgeStreamHandle {
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
        `/api/v1/knowledge/stream?since_seq=${options.sinceSeq ?? 0}`,
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
