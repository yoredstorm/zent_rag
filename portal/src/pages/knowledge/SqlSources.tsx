import {
  ArrowsClockwise,
  Database,
  Info,
  Lightning,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, Spinner } from "../../components/ui";
import { fmtNum, timeAgo } from "../../lib/format";
import { useSyncJob } from "../../syncJob";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";

type TableProgress = {
  rows_indexed: number;
  row_count: number;
  pct: number;
  status: string;
  page?: number;
} | null;

type Source = {
  schema: string;
  table: string;
  row_count: number;
  synced?: boolean;
  skipped?: boolean;
  columns?: number;
  progress?: TableProgress;
  lazy_rows_indexed?: number;
};

type LazyEvent = {
  tables: string[];
  rows_indexed: number;
  query_preview: string;
  at: string;
};

function secondsAgo(iso: string): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

function sourceStatus(
  s: Source,
  hasProgress: boolean
): { label: string; badge: string } {
  if (s.synced) return { label: "Sincronizada", badge: "badge-ok" };
  if (s.skipped) return { label: "Omitida", badge: "badge-muted" };
  if (hasProgress) return { label: "Sincronizando…", badge: "badge-pending" };
  if ((s.lazy_rows_indexed ?? 0) > 0) {
    return {
      label: `Parcial · ${fmtNum(s.lazy_rows_indexed)} filas por demanda`,
      badge: "badge-pending",
    };
  }
  return { label: "Pendiente", badge: "badge-pending" };
}

function ProgressBar({ progress }: { progress: TableProgress }) {
  if (!progress) return null;
  const pct = progress.status === "completed" ? 100 : progress.pct || 0;
  return (
    <div className="flex min-w-[130px] items-center gap-2">
      <div className="progress-track h-1.5 flex-1">
        <div
          className={`progress-fill ${progress.status === "completed" ? "" : "bg-warn"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="mono shrink-0 text-[11px] text-faint">
        {progress.status === "completed"
          ? "100%"
          : `${fmtNum(progress.rows_indexed ?? 0)}/${fmtNum(progress.row_count ?? 0)}`}
      </span>
    </div>
  );
}

export default function IngestionPage() {
  const { session } = useAuth();
  const sync = useSyncJob();
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncingTables, setSyncingTables] = useState<Set<string>>(new Set());
  const [lazyEvents, setLazyEvents] = useState<LazyEvent[]>([]);
  const lastCompleted = useRef<string | null>(null);

  async function loadSources() {
    if (!session) return;
    const [data, activity] = await Promise.all([
      api<{ sources: Source[] }>("/api/v1/ingestion/sources", {
        token: session.token,
        organizationId: session.organizationId,
      }),
      api<{ recent: LazyEvent[] }>("/api/v1/ingestion/lazy-activity?days=30&limit=20", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ recent: [] as LazyEvent[] })),
    ]);
    setSources(data.sources || []);
    setLazyEvents(activity.recent || []);
  }

  async function syncTable(schema: string, table: string) {
    if (!session) return;
    const key = `${schema}.${table}`;
    setSyncingTables((prev) => new Set(prev).add(key));
    try {
      await api(`/api/v1/ingestion/sync/${schema}/${table}?background=true`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        headers: { "X-User-Role": "admin" },
      });
      await loadSources();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error sincronizando tabla");
    } finally {
      setSyncingTables((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  }

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    loadSources()
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Error cargando fuentes")
      )
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (sync.status === "completed" && sync.jobId && lastCompleted.current !== sync.jobId) {
      lastCompleted.current = sync.jobId;
      loadSources().catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sync.status, sync.jobId]);

  const pendingCount = sources.filter((s) => s.row_count > 0 && !s.synced && !s.skipped).length;
  const hasPending = pendingCount > 0;

  useEffect(() => {
    if (!hasPending && !sync.active) return;
    const interval = setInterval(() => {
      loadSources().catch(() => undefined);
    }, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPending, sync.active, session]);

  const ago = secondsAgo(sync.updatedAt);
  const showProgress = Boolean(sync.jobId);

  return (
    <KnowledgeLayout>
      <PageHeader
        title="Fuentes SQL"
        subtitle="Descubre tablas y sincroniza tu información para poder hacer preguntas. Las tablas grandes se indexan solas a medida que las preguntas las necesitan."
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setError("");
              loadSources().catch((err) =>
                setError(err instanceof Error ? err.message : "Error")
              );
            }}
          >
            <ArrowsClockwise size={15} aria-hidden />
            Refrescar
          </button>
        }
      />
      <ErrorInline message={error} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => void sync.startSyncAll(false)}
          disabled={sync.active}
        >
          {sync.active ? (
            <>
              <Spinner size={14} /> Sincronizando…
            </>
          ) : (
            <>
              <Database size={16} aria-hidden />
              Sincronizar todos mis datos
              {hasPending ? ` (${pendingCount} pendientes)` : ""}
            </>
          )}
        </button>
        <span
          className="flex items-center gap-1.5 text-xs text-faint"
          title="No es obligatorio sincronizar todo antes de empezar. Las tablas grandes se indexan automáticamente a medida que las preguntas las necesitan."
        >
          <Info size={15} aria-hidden />
          La sincronización completa es opcional
        </span>
        {sync.jobId && !sync.active && (
          <button className="btn btn-secondary" type="button" onClick={sync.clearJob}>
            <Trash size={15} aria-hidden />
            Limpiar estado
          </button>
        )}
      </div>

      {showProgress && (
        <div
          className={`panel mb-4 border p-4 ${
            sync.stale ? "border-warn/40" : "border-accent/25"
          }`}
        >
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-text">
              {sync.active
                ? "Progreso en vivo"
                : sync.status === "completed"
                  ? "Última sincronización — completada"
                  : sync.status === "failed"
                    ? "Última sincronización — falló"
                    : "Estado del job"}
            </h2>
            <span className="mono text-xs text-faint">
              {Math.round(sync.progress)}%
              {sync.tablesTotal > 0 && (
                <> · tablas {sync.tablesDone}/{sync.tablesTotal}</>
              )}
              {ago > 0 && <> · actualizado hace {ago}s</>}
            </span>
          </div>
          <div className="progress-track">
            <div
              className={`progress-fill ${sync.stale ? "bg-warn" : ""}`}
              style={{ width: `${Math.min(sync.progress, 100)}%` }}
            />
          </div>
          <div className="mt-2 space-y-1 text-[13px]">
            <p className="text-muted">{sync.message || "—"}</p>
            {sync.currentTable && sync.active && (
              <p className="mono text-faint">Tabla actual: {sync.currentTable}</p>
            )}
            {sync.stale && (
              <p className="text-warn">
                Sin heartbeat reciente (&gt;3 min). Si la tabla es grande, el proceso
                puede seguir en el servidor.
              </p>
            )}
            {sync.error && <p className="text-danger">{sync.error}</p>}
            {sync.resultSummary && sync.status === "completed" && (
              <p className="text-ok">
                Vectores: {String(sync.resultSummary.vectors_upserted ?? "—")} · Filas:{" "}
                {String(sync.resultSummary.rows_indexed ?? "—")} · Duración:{" "}
                {String(sync.resultSummary.duration_ms ?? "—")} ms
              </p>
            )}
            <p className="mono text-[11px] text-faint">job {sync.jobId}</p>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text">Fuentes de datos</h2>
          <span className="mono text-[11px] text-faint">{sources.length} tablas</span>
        </div>
        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={6} />
          </div>
        ) : sources.length === 0 ? (
          <EmptyState
            icon={Database}
            title="No hay fuentes descubiertas aún"
            body="Pulsa «Sincronizar todos mis datos» para descubrir tablas e indexarlas."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>Schema</th>
                  <th>Tabla</th>
                  <th className="text-right">Filas</th>
                  <th>Progreso</th>
                  <th>Estado</th>
                  <th className="w-[180px]">Acción</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => {
                  const key = `${s.schema}.${s.table}`;
                  const isSyncing = syncingTables.has(key);
                  const hasProgress = Boolean(s.progress && s.progress.status === "running");
                  const status = sourceStatus(s, hasProgress);
                  const isPartial =
                    !s.synced && !s.skipped && !hasProgress && (s.lazy_rows_indexed ?? 0) > 0;
                  return (
                    <tr key={key}>
                      <td className="text-muted">{s.schema}</td>
                      <td className="mono">{s.table}</td>
                      <td className="mono text-right">{fmtNum(s.row_count ?? 0)}</td>
                      <td>
                        <ProgressBar progress={s.progress ?? null} />
                      </td>
                      <td>
                        <span className={`badge ${status.badge}`}>{status.label}</span>
                      </td>
                      <td>
                        {!s.synced && s.row_count > 0 && !s.skipped && (
                          <button
                            className="btn btn-secondary px-3 py-1.5 text-xs"
                            type="button"
                            disabled={isSyncing || hasProgress}
                            onClick={() => void syncTable(s.schema, s.table)}
                          >
                            {isSyncing || hasProgress ? (
                              <>
                                <Spinner size={12} /> En curso
                              </>
                            ) : isPartial ? (
                              "Completar sincronización"
                            ) : (
                              "Sincronizar"
                            )}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel mt-4">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text">Actividad de indexado por demanda</h2>
          <span className="mono text-[11px] text-faint">últimos 30 días</span>
        </div>
        {lazyEvents.length === 0 ? (
          <EmptyState
            icon={Lightning}
            title="Todavía no hay indexados al vuelo"
            body="Cuando una pregunta necesite datos no sincronizados, se indexarán automáticamente y quedarán registrados aquí."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[560px]">
              <thead>
                <tr>
                  <th>Tablas</th>
                  <th className="text-right">Filas</th>
                  <th>Consulta</th>
                  <th>Cuándo</th>
                </tr>
              </thead>
              <tbody>
                {lazyEvents.map((ev, i) => (
                  <tr key={`${ev.at}-${i}`}>
                    <td className="mono text-xs">{(ev.tables || []).join(", ") || "—"}</td>
                    <td className="mono text-right">{fmtNum(ev.rows_indexed)}</td>
                    <td className="max-w-[320px] truncate text-muted" title={ev.query_preview}>
                      {ev.query_preview || "—"}
                    </td>
                    <td className="text-faint">{timeAgo(ev.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-xs text-faint">
        <Lightning size={14} className="text-accent" aria-hidden />
        Las tablas con columna de actualización se sincronizan incrementalmente (solo lo
        nuevo).
      </p>
    </KnowledgeLayout>
  );
}
