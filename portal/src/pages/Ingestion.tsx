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
  columns?: number;
  progress?: TableProgress;
};

function secondsAgo(iso: string): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
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
  const lastCompleted = useRef<string | null>(null);

  async function loadSources() {
    if (!session) return;
    const data = await api<{ sources: Source[] }>("/api/v1/ingestion/sources", {
      token: session.token,
      tenantId: session.tenantId,
    });
    setSources(data.sources || []);
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

  const pendingCount = sources.filter((s) => s.row_count > 0 && !s.synced).length;
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
        Las tablas con <code>updated_at</code> se sincronizan incrementalmente (solo lo nuevo).
      </p>
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ marginBottom: "1rem" }}>
        <button
          className="btn"
          type="button"
          onClick={() => void sync.startSyncAll(false)}
          disabled={sync.active}
        >
          {sync.active ? "Sincronizando…" : `Sincronizar todos mis datos${hasPending ? ` (${pendingCount} pendientes)` : ""}`}
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
          <table className="table">
            <thead>
              <tr>
                <th>Schema</th>
                <th>Tabla</th>
                <th>Filas</th>
                <th>Progreso</th>
                <th>Estado</th>
                <th style={{ width: 120 }}>Acción</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => {
                const key = `${s.schema}.${s.table}`;
                const isSyncing = syncingTables.has(key);
                const hasProgress = s.progress && s.progress.status === "running";
                return (
                  <tr key={key}>
                    <td>{s.schema}</td>
                    <td className="mono">{s.table}</td>
                    <td>{(s.row_count ?? 0).toLocaleString()}</td>
                    <td>
                      <ProgressBar progress={s.progress} />
                    </td>
                    <td>
                      <span className={`badge ${s.synced ? "badge-ok" : hasProgress ? "badge-pending" : "badge-pending"}`}>
                        {s.synced ? "Sincronizada" : hasProgress ? "Sincronizando…" : "Pendiente"}
                      </span>
                    </td>
                    <td>
                      {!s.synced && s.row_count > 0 && (
                        <button
                          className="btn secondary"
                          style={{ padding: "0.25rem 0.6rem", fontSize: "0.8rem" }}
                          type="button"
                          disabled={isSyncing || hasProgress}
                          onClick={() => void syncTable(s.schema, s.table)}
                        >
                          {isSyncing ? "..." : hasProgress ? "En curso" : "Sincronizar"}
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
        )}
      </div>
    </div>
  );
}