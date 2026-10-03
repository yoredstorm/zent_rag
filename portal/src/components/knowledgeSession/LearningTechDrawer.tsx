// =============================================================================
// LearningTechDrawer — el modo técnico, sin contaminar la experiencia
// =============================================================================
// Aquí sí: eventos crudos, contadores, jobs, compilaciones, latencia. Todo
// viene de lo ya persistido por el Knowledge OS.
// =============================================================================
import { useEffect, useMemo, useState } from "react";

import { fmtDateTime, fmtLatency } from "../../lib/format";
import {
  fetchKnowledgeCompilations,
  type KnowledgeCompilation,
} from "../../lib/knowledgeModel";
import type { LearningSessionDetail, SessionEvent } from "../../lib/knowledgeSessions";
import { Drawer } from "../ui/overlay";
import {
  eventCountsByType,
  sessionDurationMs,
  sourceTechnicalRows,
} from "./learningInsights";

const METRIC_LABELS: Record<string, string> = {
  entities: "entidades (nuevas + conocidas)",
  entities_new: "entidades nuevas",
  entities_enriched: "entidades conocidas",
  facts: "hechos (nuevos + reforzados)",
  facts_new: "hechos nuevos",
  facts_reinforced: "hechos reforzados",
  relationships: "relaciones",
  relationships_related: "relaciones entre conocimiento existente",
  rules: "reglas",
  evidence: "evidencias",
  merges: "fusiones de entidades",
  conflicts: "conflictos",
  duplicates: "duplicados",
  updated: "actualizaciones",
  ignored: "ignorados",
  semantic_units: "unidades semánticas",
  tables: "tablas",
  sheets: "hojas",
  columns: "columnas",
  rows: "filas",
  candidate_keys: "claves candidatas",
  table_relations: "relaciones entre tablas",
  pages: "páginas",
  sections: "secciones",
  figures: "figuras",
  bytes: "bytes",
  records: "registros",
  chunks: "fragmentos indexados",
  knowledge_objects: "objetos de conocimiento",
  temporal_ranges: "rangos temporales",
  sources: "fuentes",
  sources_available: "fuentes consultables",
};

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

export function LearningTechDrawer({
  open,
  onOpenChange,
  detail,
  events,
  metrics,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  detail: LearningSessionDetail;
  events: SessionEvent[];
  metrics: Record<string, number>;
}) {
  const [compilations, setCompilations] = useState<KnowledgeCompilation[]>([]);
  const [rawLimit, setRawLimit] = useState(60);

  const sourceIds = useMemo(
    () =>
      new Set(
        detail.sources
          .map((source) => source.source_id)
          .filter((value): value is string => Boolean(value))
      ),
    [detail.sources]
  );

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void fetchKnowledgeCompilations(100)
      .then((result) => {
        if (cancelled) return;
        setCompilations(
          result.items.filter(
            (item) => item.source_id && sourceIds.has(item.source_id)
          )
        );
      })
      .catch(() => {
        if (!cancelled) setCompilations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, sourceIds]);

  const duration = sessionDurationMs(detail);
  const typeCounts = useMemo(() => eventCountsByType(events), [events]);
  const metricEntries = useMemo(
    () =>
      Object.entries(metrics)
        .filter(([, value]) => Number(value) > 0)
        .sort((a, b) => Number(b[1]) - Number(a[1])),
    [metrics]
  );
  const rawEvents = useMemo(
    () => [...events].reverse().slice(0, rawLimit),
    [events, rawLimit]
  );

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Detalles técnicos"
      description="Eventos crudos, contadores y jobs de esta sesión. Sin maquillaje."
      width={620}
    >
      <div className="flex flex-col gap-5 p-4" data-testid="learning-tech">
        <section>
          <p className="eyebrow mb-2">Tiempos</p>
          <dl className="ks-tech-kv">
            <div>
              <dt>Inicio</dt>
              <dd>{fmtDateTime(detail.started_at)}</dd>
            </div>
            <div>
              <dt>Fin</dt>
              <dd>{fmtDateTime(detail.completed_at)}</dd>
            </div>
            <div>
              <dt>Duración</dt>
              <dd>{duration != null ? fmtLatency(duration) : "—"}</dd>
            </div>
            <div>
              <dt>Eventos</dt>
              <dd>{events.length.toLocaleString("es-PE")}</dd>
            </div>
          </dl>
        </section>

        <section>
          <p className="eyebrow mb-2">Contadores reales</p>
          <dl className="ks-tech-metrics">
            {metricEntries.map(([key, value]) => (
              <div key={key}>
                <dt>{metricLabel(key)}</dt>
                <dd className="font-mono tabular-nums">
                  {Number(value).toLocaleString("es-PE")}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section>
          <p className="eyebrow mb-2">Eventos por tipo</p>
          <ul className="ks-tech-events">
            {typeCounts.slice(0, 20).map((row) => (
              <li key={row.type}>
                <span className="font-mono text-[11px] text-text">{row.type}</span>
                <span className="font-mono tabular-nums text-muted">
                  {row.count.toLocaleString("es-PE")}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <p className="eyebrow mb-2">Fuentes y jobs</p>
          <ul className="ks-tech-sources">
            {sourceTechnicalRows(detail.sources).map((row) => (
              <li key={row.id}>
                <span className="truncate text-[12px] text-text">{row.name}</span>
                <span className="font-mono text-[10px] text-faint">
                  {row.status}
                  {row.jobId ? ` · job ${row.jobId.slice(0, 8)}` : ""}
                  {row.sourceId ? ` · src ${row.sourceId.slice(0, 8)}` : ""}
                </span>
                {row.error && (
                  <span className="font-mono text-[10px] text-danger break-words">
                    {row.error}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        {compilations.length > 0 && (
          <section>
            <p className="eyebrow mb-2">Compilaciones</p>
            <ul className="ks-tech-compilations">
              {compilations.slice(0, 12).map((item) => (
                <li key={item.id}>
                  <span className="truncate text-[12px] text-text">
                    {item.document_title || item.document_id || "documento"}
                  </span>
                  <span className="font-mono text-[10px] text-faint">
                    {item.status} · {item.counts.entities} entidades ·{" "}
                    {item.counts.facts} hechos · {item.counts.rules} reglas ·{" "}
                    {Math.round(item.duration_ms)} ms
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="eyebrow">Eventos crudos</p>
            {events.length > rawEvents.length && (
              <button
                type="button"
                className="text-[11px] text-accent hover:underline"
                onClick={() => setRawLimit((value) => value + 120)}
              >
                Ver más
              </button>
            )}
          </div>
          <ul className="ks-tech-raw">
            {rawEvents.map((event) => (
              <li key={event.seq}>
                <details>
                  <summary>
                    <span className="font-mono text-[11px] text-text">
                      {event.event_type}
                    </span>
                    <span className="text-[10px] text-faint">
                      {event.stage ?? "—"} ·{" "}
                      {String(
                        (event.payload as Record<string, unknown>)?.count ?? 1
                      )}
                    </span>
                  </summary>
                  <pre>{JSON.stringify(event.payload, null, 1)}</pre>
                </details>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Drawer>
  );
}

export default LearningTechDrawer;
