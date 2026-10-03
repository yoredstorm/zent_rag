// =============================================================================
// Knowledge Delta — qué cambió, con ventana real
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowsClockwise, TrendUp } from "@phosphor-icons/react";
import { Button, ErrorInline, Panel, Skeleton, cn } from "../ui";
import {
  fetchKnowledgeDelta,
  objectTypeLabel,
  type KnowledgeDelta,
  type KnowledgeDeltaWindow,
} from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";
import { AnimatedNumber } from "./AnimatedNumber";

const WINDOWS: { id: KnowledgeDeltaWindow; label: string }[] = [
  { id: "24h", label: "24 h" },
  { id: "7d", label: "7 días" },
  { id: "30d", label: "30 días" },
  { id: "custom", label: "Personalizado" },
];

const TILES: { key: keyof KnowledgeDelta["totals"]; label: string }[] = [
  { key: "objects", label: "Objetos de conocimiento" },
  { key: "facts", label: "Hechos" },
  { key: "relationships", label: "Relaciones" },
  { key: "evidence", label: "Evidencias" },
  { key: "rules", label: "Reglas" },
  { key: "conflicts_resolved", label: "Conflictos resueltos" },
];

function toIso(value: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
}

export function KnowledgeDelta({
  initialWindow = "24h",
  onSelectObject,
  refreshKey = 0,
}: {
  initialWindow?: KnowledgeDeltaWindow;
  onSelectObject?: (id: string) => void;
  refreshKey?: number;
}) {
  const [windowId, setWindowId] = useState<KnowledgeDeltaWindow>(initialWindow);
  const [customSince, setCustomSince] = useState("");
  const [customUntil, setCustomUntil] = useState("");
  const [applied, setApplied] = useState<{ since?: string; until?: string }>({});
  const [data, setData] = useState<KnowledgeDelta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await fetchKnowledgeDelta({
        window: windowId,
        since: windowId === "custom" ? applied.since : undefined,
        until: windowId === "custom" ? applied.until : undefined,
      });
      setData(next);
    } catch (err) {
      setData(null);
      setError(
        err instanceof Error ? err.message : "No pudimos leer los cambios del conocimiento."
      );
    } finally {
      setLoading(false);
    }
  }, [windowId, applied.since, applied.until]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const timelineMax = useMemo(() => {
    if (!data) return 0;
    return Math.max(
      1,
      ...data.timeline.map((point) => point.objects + point.facts + point.relationships)
    );
  }, [data]);

  const hasChanges =
    data != null &&
    (data.totals.objects > 0 ||
      data.totals.facts > 0 ||
      data.totals.relationships > 0 ||
      data.totals.evidence > 0 ||
      data.totals.conflicts_resolved > 0);

  return (
    <Panel className="overflow-hidden" data-testid="knowledge-delta">
      <div className="panel-header flex-col items-start gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0">
          <h2 className="text-h3 flex items-center gap-2">
            <TrendUp size={15} className="text-accent" aria-hidden />
            Knowledge Delta
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            Qué cambió en el conocimiento, con datos reales del modelo.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {WINDOWS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={cn("kh-window-tab", windowId === option.id && "is-active")}
              aria-pressed={windowId === option.id}
              onClick={() => setWindowId(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {windowId === "custom" && (
        <div className="flex flex-wrap items-end gap-2 border-b border-border px-4 py-3">
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Desde
            <input
              type="datetime-local"
              className="input min-h-8 py-1 text-xs"
              value={customSince}
              onChange={(event) => setCustomSince(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            Hasta
            <input
              type="datetime-local"
              className="input min-h-8 py-1 text-xs"
              value={customUntil}
              onChange={(event) => setCustomUntil(event.target.value)}
            />
          </label>
          <Button
            size="sm"
            variant="secondary"
            disabled={!customSince || !customUntil}
            onClick={() =>
              setApplied({ since: toIso(customSince), until: toIso(customUntil) })
            }
          >
            Aplicar
          </Button>
        </div>
      )}

      <div className="panel-body">
        {loading && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-busy="true">
            {TILES.map((tile) => (
              <Skeleton key={tile.key} className="h-[74px] rounded-md" />
            ))}
          </div>
        )}

        {!loading && error && (
          <div>
            <ErrorInline message={error} className="mb-0" />
            <Button className="mt-3" variant="secondary" onClick={() => void load()}>
              Reintentar
            </Button>
          </div>
        )}

        {!loading && !error && data && (
          <div className="flex flex-col gap-5">
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {TILES.map((tile) => {
                const value = data.totals[tile.key];
                return (
                  <div
                    key={tile.key}
                    className={cn("kh-delta-tile", value > 0 && "has-value")}
                  >
                    <dt>{tile.label}</dt>
                    <dd>
                      {value > 0 ? "+" : ""}
                      <AnimatedNumber value={value} />
                    </dd>
                  </div>
                );
              })}
            </dl>

            {hasChanges && data.timeline.length > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="eyebrow">Ritmo de aprendizaje</p>
                  <p className="text-[11px] text-faint">
                    {fmtDateTime(data.since)} — {fmtDateTime(data.until)}
                  </p>
                </div>
                <svg
                  viewBox={`0 0 ${Math.max(data.timeline.length * 10, 100)} 40`}
                  className="h-[72px] w-full"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label="Cambios de conocimiento por intervalo"
                >
                  {data.timeline.map((point, index) => {
                    const total = point.objects + point.facts + point.relationships;
                    const height = (total / timelineMax) * 34;
                    return (
                      <g key={point.bucket ?? index}>
                        <rect
                          x={index * 10 + 1}
                          y={36 - height}
                          width={8}
                          height={Math.max(1, height)}
                          rx={1.5}
                          className="kh-timeline-bar"
                        >
                          <title>
                            {`${point.bucket ? fmtDateTime(point.bucket) : ""}: ${
                              point.objects
                            } objetos · ${point.facts} hechos · ${
                              point.relationships
                            } relaciones`}
                          </title>
                        </rect>
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}

            {data.enriched.length > 0 && (
              <div>
                <p className="eyebrow mb-2">
                  Conocimiento enriquecido
                  <span className="ml-2 normal-case tracking-normal text-faint">
                    {data.enriched_total} en esta ventana
                  </span>
                </p>
                <ul className="flex flex-col gap-1.5">
                  {data.enriched.slice(0, 5).map((item) => (
                    <li key={item.id} className="flex items-center gap-2">
                      <span className="badge badge-muted shrink-0">
                        {objectTypeLabel(item.type)}
                      </span>
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate text-left text-sm text-text hover:underline"
                        onClick={() => onSelectObject?.(item.id)}
                      >
                        {item.name}
                      </button>
                      <span className="shrink-0 text-[11px] text-faint">
                        {fmtDateTime(item.updated_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!hasChanges && (
              <div className="flex items-center gap-2 text-sm text-muted">
                <ArrowsClockwise size={14} className="text-faint" aria-hidden />
                Sin cambios de conocimiento en esta ventana.
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
