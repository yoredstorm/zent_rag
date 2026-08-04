import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./Toast";

export type SyncJobState = {
  jobId: string | null;
  status: string;
  progress: number;
  message: string;
  currentTable: string;
  tablesDone: number;
  tablesTotal: number;
  updatedAt: string;
  error: string;
  resultSummary: Record<string, unknown> | null;
  stale: boolean;
  active: boolean;
};

type SyncJobContextValue = SyncJobState & {
  startSyncAll: (fullRefresh?: boolean) => Promise<void>;
  clearJob: () => void;
};

const emptyState: SyncJobState = {
  jobId: null,
  status: "",
  progress: 0,
  message: "",
  currentTable: "",
  tablesDone: 0,
  tablesTotal: 0,
  updatedAt: "",
  error: "",
  resultSummary: null,
  stale: false,
  active: false,
};

const SyncJobContext = createContext<SyncJobContextValue | null>(null);

const STALE_MS = 180_000;
const POLL_MS = 1500;
const TABLE_TOAST_THROTTLE_MS = 3000;

function storageKey(tenantId: string) {
  return `rag_sync_job_${tenantId}`;
}

type JobApi = {
  status: string;
  progress?: number;
  message?: string;
  current_table?: string;
  tables_done?: number;
  tables_total?: number;
  updated_at?: string;
  error?: string;
  result_summary?: Record<string, unknown> | null;
};

function secondsAgo(iso: string): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

export function SyncJobProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [state, setState] = useState<SyncJobState>(emptyState);
  const lastTableToastAt = useRef(0);
  const lastTableToasted = useRef("");
  const staleToastSent = useRef(false);
  const terminalToastSent = useRef<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const clearJob = useCallback(() => {
    if (session) {
      sessionStorage.removeItem(storageKey(session.tenantId));
    }
    setState(emptyState);
    terminalToastSent.current = null;
    staleToastSent.current = false;
  }, [session]);

  const applyJob = useCallback(
    (jobId: string, job: JobApi) => {
      const status = job.status || "unknown";
      const updatedAt = job.updated_at || "";
      const stale =
        ["pending", "running"].includes(status) &&
        updatedAt !== "" &&
        Date.now() - Date.parse(updatedAt) > STALE_MS;

      const next: SyncJobState = {
        jobId,
        status,
        progress: job.progress ?? 0,
        message: job.message || "",
        currentTable: job.current_table || "",
        tablesDone: job.tables_done ?? 0,
        tablesTotal: job.tables_total ?? 0,
        updatedAt,
        error: job.error || "",
        resultSummary: job.result_summary ?? null,
        stale,
        active: ["pending", "running"].includes(status),
      };
      setState(next);

      const table = job.current_table || "";
      if (
        next.active &&
        table &&
        table !== lastTableToasted.current &&
        Date.now() - lastTableToastAt.current >= TABLE_TOAST_THROTTLE_MS
      ) {
        lastTableToasted.current = table;
        lastTableToastAt.current = Date.now();
        const done = job.tables_done ?? 0;
        const total = job.tables_total ?? 0;
        pushToast(
          "info",
          "Sincronizando tabla",
          total > 0 ? `${table} (${done}/${total})` : table
        );
      }

      if (stale && !staleToastSent.current) {
        staleToastSent.current = true;
        pushToast(
          "warn",
          "Tabla grande en curso…",
          "Sin actualización reciente (>3 min). El job puede seguir embebiendo en el servidor."
        );
      }
      if (!stale) staleToastSent.current = false;

      if (
        (status === "completed" || status === "failed") &&
        terminalToastSent.current !== jobId
      ) {
        terminalToastSent.current = jobId;
        if (status === "completed") {
          pushToast("success", "Ingestión completada", job.message || undefined);
        } else {
          pushToast(
            "error",
            "Ingestión falló",
            job.error || job.message || "Error desconocido"
          );
        }
        if (session) {
          window.setTimeout(() => {
            sessionStorage.removeItem(storageKey(session.tenantId));
          }, 4000);
        }
      }
    },
    [pushToast, session]
  );

  const pollOnce = useCallback(
    async (jobId: string) => {
      if (!session) return;
      try {
        const job = await api<JobApi>(`/api/v1/ingestion/jobs/${jobId}`, {
          token: session.token,
          tenantId: session.tenantId,
        });
        applyJob(jobId, job);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Error al consultar job";
        setState((prev) => ({
          ...prev,
          jobId,
          error: msg,
          message: msg,
          active: false,
          status: "failed",
        }));
      }
    },
    [session, applyJob]
  );

  // Resume from sessionStorage + poll loop
  useEffect(() => {
    if (!session) {
      setState(emptyState);
      return;
    }
    const saved = sessionStorage.getItem(storageKey(session.tenantId));
    if (saved && !state.jobId) {
      setState((prev) => ({
        ...prev,
        jobId: saved,
        status: "running",
        active: true,
        message: "Reanudando seguimiento…",
      }));
    }
  }, [session]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!session || !state.jobId) return;

    const jobId = state.jobId;
    void pollOnce(jobId);

    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(() => {
      void pollOnce(jobId);
    }, POLL_MS);

    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [session, state.jobId, pollOnce]);

  // Stop interval when terminal (keep state for UI)
  useEffect(() => {
    if (!state.active && pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [state.active]);

  const startSyncAll = useCallback(
    async (fullRefresh = false) => {
      if (!session) return;
      if (state.active) {
        pushToast("warn", "Ya hay una sincronización en curso");
        return;
      }
      terminalToastSent.current = null;
      staleToastSent.current = false;
      lastTableToasted.current = "";
      try {
        const job = await api<{ job_id: string }>(
          `/api/v1/ingestion/sync?full_refresh=${fullRefresh ? "true" : "false"}`,
          {
            method: "POST",
            token: session.token,
            tenantId: session.tenantId,
          }
        );
        sessionStorage.setItem(storageKey(session.tenantId), job.job_id);
        setState({
          ...emptyState,
          jobId: job.job_id,
          status: "running",
          active: true,
          message: "Iniciando sincronización…",
          progress: 0,
        });
        pushToast("info", "Ingestión iniciada", "Puedes navegar; el progreso continúa.");
      } catch (err) {
        pushToast(
          "error",
          "No se pudo iniciar Sync All",
          err instanceof Error ? err.message : "Error"
        );
      }
    },
    [session, state.active, pushToast]
  );

  const value = useMemo(
    () => ({ ...state, startSyncAll, clearJob }),
    [state, startSyncAll, clearJob]
  );

  return (
    <SyncJobContext.Provider value={value}>{children}</SyncJobContext.Provider>
  );
}

export function SyncBanner() {
  const state = useSyncJob();
  if (!state.jobId || !state.active) return null;

  const ago = secondsAgo(state.updatedAt);

  return (
    <div className={`sync-banner${state.stale ? " sync-banner-stale" : ""}`}>
      <div className="sync-banner-top">
        <strong>Sincronizando datos</strong>
        <span className="muted">
          {state.progress}%
          {state.tablesTotal > 0
            ? ` · ${state.tablesDone}/${state.tablesTotal} tablas`
            : ""}
          {ago > 0 ? ` · hace ${ago}s` : ""}
        </span>
      </div>
      <div className="sync-progress-track">
        <div
          className="sync-progress-fill"
          style={{ width: `${Math.min(state.progress, 100)}%` }}
        />
      </div>
      <div className="sync-banner-msg">
        {state.message ||
          (state.currentTable
            ? `Trabajando en ${state.currentTable}`
            : "Procesando…")}
        {state.stale && (
          <span className="sync-stale-hint"> — sin heartbeat reciente</span>
        )}
      </div>
    </div>
  );
}

export function useSyncJob() {
  const ctx = useContext(SyncJobContext);
  if (!ctx) throw new Error("useSyncJob outside SyncJobProvider");
  return ctx;
}
