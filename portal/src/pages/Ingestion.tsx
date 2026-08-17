import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useSyncJob } from "../syncJob";

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

function timeAgo(iso: string): string {
  const s = secondsAgo(iso);
  if (s < 60) return `hace ${s}s`;
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

function sourceStatus(s: Source, hasProgress: boolean): { label: string; badge: string } {
  if (s.synced) return { label: "Sincronizada", badge: "badge-ok" };
  if (s.skipped) return { label: "Omitida", badge: "badge-pending" };
  if (hasProgress) return { label: "Sincronizando…", badge: "badge-pending" };
  if ((s.lazy_rows_indexed ?? 0) > 0) {
    return {
      label: `Parcial · ${s.lazy_rows_indexed} filas por demanda`,
      badge: "badge-pending",
    };
  }
  return { label: "Pendiente", badge: "badge-pending" };
}

function ProgressBar({ progress }: { progress: TableProgress }) {
  if (!progress) return null;
  const pct = progress.status === "completed" ? 100 : progress.pct || 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", minWidth: 120 }}>
      <div className="sync-progress-track" style={{ flex: 1, height: 6, borderRadius: 3 }}>
        <div
          className="sync-progress-fill"
          style={{
            width: `${pct}%`,
            background: progress.status === "completed" ? "var(--accent)" : "#f0a030",
          }}
        />
      </div>
      <span className="muted" style={{ fontSize: "0.7rem", whiteSpace: "nowrap" }}>
        {progress.status === "completed"
          ? "100%"
          : `${(progress.rows_indexed ?? 0).toLocaleString()}/${(progress.row_count ?? 0).toLocaleString()}`}
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
        tenantId: session.tenantId,
      }),
      api<{ recent: LazyEvent[] }>("/api/v1/ingestion/lazy-activity?days=30&limit=20", {
        token: session.token,
        tenantId: session.tenantId,
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
        tenantId: session.tenantId,
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
  }, [session]);

  useEffect(() => {
    if (sync.status === "completed" && sync.jobId && lastCompleted.current !== sync.jobId) {
      lastCompleted.current = sync.jobId;
      loadSources().catch(() => undefined);
    }
  }, [sync.status, sync.jobId]);

  const pendingCount = sources.filter((s) => s.row_count > 0 && !s.synced && !s.skipped).length;
  const hasPending = pendingCount > 0;

  useEffect(() => {
    if (!hasPending && !sync.active) return;
    const interval = setInterval(() => {
      loadSources().catch(() => undefined);
    }, 5000);
    return () => clearInterval(interval);
  }, [hasPending, sync.active, session]);

  const ago = secondsAgo(sync.updatedAt);
  const showProgress = Boolean(sync.jobId);

  return (
    <div>
      <h1>Ingestión</h1>
      <p className="muted">
        Descubre tablas y sincroniza tu información para poder hacer preguntas.
        No es obligatorio sincronizar todo antes de empezar: las tablas grandes se
        indexan solas a medida que las preguntas las necesitan. Las tablas con{" "}
        <code>updated_at</code> se sincronizan incrementalmente (solo lo nuevo).
      </p>
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ marginBottom: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <button
          className="btn"
          type="button"
          onClick={() => void sync.startSyncAll(false)}
          disabled={sync.active}
        >
          {sync.active ? "Sincronizando…" : `Sincronizar todos mis datos${hasPending ? ` (${pendingCount} pendientes)` : ""}`}
        </button>
        <button
          type="button"
          className="help-icon"
          title="No es obligatorio sincronizar todo antes de empezar. Las tablas grandes se indexan automáticamente a medida que las preguntas las necesitan."
          aria-label="No es obligatorio sincronizar todo antes de empezar. Las tablas grandes se indexan automáticamente a medida que las preguntas las necesitan."
        >
          ⓘ
        </button>
        <button
          className="btn secondary"
          type="button"
          onClick={() => {
            setError("");
            loadSources().catch((err) =>
              setError(err instanceof Error ? err.message : "Error")
            );
          }}
        >
          Refrescar
        </button>
        {sync.jobId && !sync.active && (
          <button className="btn secondary" type="button" onClick={sync.clearJob}>
            Limpiar estado
          </button>
        )}
      </div>

      {showProgress && (
        <div className={`panel sync-panel${sync.stale ? " sync-banner-stale" : ""}`}>
          <h2>
            {sync.active
              ? "Progreso en vivo"
              : sync.status === "completed"
                ? "Última sincronización — completada"
                : sync.status === "failed"
                  ? "Última sincronización — falló"
                  : "Estado del job"}
          </h2>
          <div className="sync-progress-track">
            <div
              className="sync-progress-fill"
              style={{ width: `${Math.min(sync.progress, 100)}%` }}
            />
          </div>
          <div className="sync-meta">
            <div>
              <strong>{sync.progress}%</strong>
              {sync.tablesTotal > 0 && (
                <>
                  {" "}
                  · tablas {sync.tablesDone}/{sync.tablesTotal}
                </>
              )}
              {ago > 0 && <> · actualizado hace {ago}s</>}
            </div>
            <div>{sync.message || "—"}</div>
            {sync.currentTable && sync.active && (
              <div className="mono">Tabla actual: {sync.currentTable}</div>
            )}
            {sync.stale && (
              <div className="error">
                Sin heartbeat reciente (&gt;3 min). Si la tabla es grande, el proceso
                puede seguir en el servidor.
              </div>
            )}
            {sync.error && <div className="error">{sync.error}</div>}
            {sync.resultSummary && sync.status === "completed" && (
              <div className="success">
                Vectores: {String(sync.resultSummary.vectors_upserted ?? "—")} · Filas:{" "}
                {String(sync.resultSummary.rows_indexed ?? "—")} · Duración:{" "}
                {String(sync.resultSummary.duration_ms ?? "—")} ms
              </div>
            )}
            <div className="muted mono">job {sync.jobId}</div>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Fuentes de datos</h2>
        {loading && (
          <p className="muted">
            <span className="loading" aria-label="Cargando" /> Cargando…
          </p>
        )}
        {!loading && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Schema</th>
                  <th>Tabla</th>
                  <th>Filas</th>
                  <th>Progreso</th>
                  <th>Estado</th>
                  <th style={{ width: 200 }}>Acción</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => {
                  const key = `${s.schema}.${s.table}`;
                  const isSyncing = syncingTables.has(key);
                  const hasProgress = Boolean(s.progress && s.progress.status === "running");
                  const status = sourceStatus(s, hasProgress);
                  const isPartial = !s.synced && !s.skipped && !hasProgress && (s.lazy_rows_indexed ?? 0) > 0;
                  return (
                    <tr key={key}>
                      <td>{s.schema}</td>
                      <td className="mono">{s.table}</td>
                      <td>{(s.row_count ?? 0).toLocaleString()}</td>
                      <td>
                        <ProgressBar progress={s.progress ?? null} />
                      </td>
                      <td>
                        <span className={`badge ${status.badge}`}>{status.label}</span>
                      </td>
                      <td>
                        {!s.synced && s.row_count > 0 && !s.skipped && (
                          <button
                            className="btn secondary"
                            style={{ padding: "0.25rem 0.6rem", fontSize: "0.8rem", minHeight: 44 }}
                            type="button"
                            disabled={isSyncing || hasProgress}
                            onClick={() => void syncTable(s.schema, s.table)}
                          >
                            {isSyncing
                              ? "..."
                              : hasProgress
                                ? "En curso"
                                : isPartial
                                  ? "Completar sincronización"
                                  : "Sincronizar"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {sources.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">
                      No hay fuentes descubiertas aún. Pulsa «Sincronizar mis datos».
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="panel">
        <h2>Actividad de indexado por demanda</h2>
        <p className="muted">Consultas recientes que dispararon indexado automático.</p>
        {lazyEvents.length === 0 ? (
          <p className="muted">Todavía no hay indexados al vuelo en los últimos 30 días.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Tablas</th>
                  <th>Filas</th>
                  <th>Consulta</th>
                  <th>Cuándo</th>
                </tr>
              </thead>
              <tbody>
                {lazyEvents.map((ev, i) => (
                  <tr key={`${ev.at}-${i}`}>
                    <td>{(ev.tables || []).join(", ") || "—"}</td>
                    <td>{ev.rows_indexed}</td>
                    <td className="muted">{ev.query_preview || "—"}</td>
                    <td className="muted">{timeAgo(ev.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}