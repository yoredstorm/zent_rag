// =============================================================================
// LearningActivityFeed — eventos reales (durables + SSE) con filtros
// =============================================================================
import { CheckCircle, Circle, WarningCircle, XCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CATEGORY_LABELS,
  fetchEvents,
  fetchRunEvents,
  type LearningEvent,
} from "../../lib/knowledgeLearning";

const FILTERS = ["all", "discovery", "ai", "validation", "indexing"] as const;

function SeverityIcon({ severity }: { severity: LearningEvent["severity"] }) {
  if (severity === "success") {
    return <CheckCircle size={13} weight="fill" className="text-ok" aria-hidden />;
  }
  if (severity === "warning") {
    return <WarningCircle size={13} weight="fill" className="text-warn" aria-hidden />;
  }
  if (severity === "error") {
    return <XCircle size={13} weight="fill" className="text-danger" aria-hidden />;
  }
  return <Circle size={11} weight="fill" className="text-faint" aria-hidden />;
}

function eventTime(event: LearningEvent): string {
  if (!event.created_at) return "";
  const date = new Date(event.created_at);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("es-PE", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function LearningActivityFeed({
  runId,
  sourceId,
  liveEvents,
  refreshKey = 0,
}: {
  runId?: string | null;
  sourceId?: string | null;
  liveEvents: LearningEvent[];
  refreshKey?: number;
}) {
  const [stored, setStored] = useState<LearningEvent[]>([]);
  const [category, setCategory] = useState<(typeof FILTERS)[number]>("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = runId
        ? await fetchRunEvents(runId)
        : await fetchEvents({ source_id: sourceId ?? undefined });
      setStored(data.events || []);
    } catch {
      setStored([]);
    } finally {
      setLoading(false);
    }
  }, [runId, sourceId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const merged = useMemo(() => {
    const byId = new Map<string, LearningEvent>();
    for (const event of [...liveEvents, ...stored]) {
      if (!byId.has(event.id)) byId.set(event.id, event);
    }
    return [...byId.values()]
      .sort((a, b) => {
        const seqA = a.seq || 0;
        const seqB = b.seq || 0;
        if (seqA && seqB && seqA !== seqB) return seqB - seqA;
        return (b.created_at ?? "").localeCompare(a.created_at ?? "");
      })
      .slice(0, 200);
  }, [liveEvents, stored]);

  const filtered =
    category === "all" ? merged : merged.filter((event) => event.category === category);

  return (
    <section className="panel" data-testid="activity-feed">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text">Actividad en vivo</h2>
        <div className="flex flex-wrap items-center gap-1">
          {FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              className={`btn btn-ghost min-h-7 px-2 py-0.5 text-[11px] ${
                category === filter ? "text-accent" : "text-muted"
              }`}
              aria-pressed={category === filter}
              onClick={() => setCategory(filter)}
            >
              {filter === "all" ? "Todo" : CATEGORY_LABELS[filter] ?? filter}
            </button>
          ))}
        </div>
      </div>
      {loading && merged.length === 0 ? (
        <p className="text-[13px] text-faint">Cargando actividad…</p>
      ) : filtered.length === 0 ? (
        <p className="text-[13px] text-faint">
          Sin actividad todavía. Inicia un aprendizaje para ver el progreso real.
        </p>
      ) : (
        <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
          {filtered.map((event) => (
            <li key={event.id} className="flex items-start gap-2 text-[13px]">
              <span className="mt-0.5 w-16 shrink-0 font-mono text-[11px] tabular-nums text-faint">
                {eventTime(event)}
              </span>
              <span className="mt-0.5">
                <SeverityIcon severity={event.severity} />
              </span>
              <span className="min-w-0 flex-1 break-words text-text">
                {event.message || event.event_type}
              </span>
              <span className="hidden shrink-0 text-[10px] uppercase tracking-wide text-faint sm:inline">
                {CATEGORY_LABELS[event.category] ?? event.category}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
