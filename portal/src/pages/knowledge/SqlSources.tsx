import {
  ArrowsClockwise,
  CheckCircle,
  Database,
  Info,
  Lightning,
  Prohibit,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  Progress,
  ResultCount,
  SectionHeader,
  StatusBadge,
  StatusRow,
  Toolbar,
  Tooltip,
  type Column,
} from "../../components/ui";
import { fmtNum, timeAgo } from "../../lib/format";
import { useSyncJob } from "../../syncJob";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

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

function SourceStatusBadge({ source, running }: { source: Source; running: boolean }) {
  if (source.synced) {
    return (
      <Badge tone="ok" icon={CheckCircle}>
        Sincronizada
      </Badge>
    );
  }
  if (source.skipped) {
    return (
      <Badge tone="neutral" icon={Prohibit}>
        Omitida
      </Badge>
    );
  }
  if (running) return <StatusBadge status="syncing" />;
  const lazyRows = source.lazy_rows_indexed ?? 0;
  if (lazyRows > 0) {
    return (
      <Badge tone="warn" icon={Lightning}>
        Parcial · {fmtNum(lazyRows)} filas por demanda
      </Badge>
    );
  }
  return <StatusBadge status="pending" />;
}

function ProgressCell({ progress }: { progress: TableProgress }) {
  if (!progress) return <span className="text-xs text-ghost">—</span>;
  const pct = progress.status === "completed" ? 100 : progress.pct || 0;
  return (
    <div className="flex min-w-[150px] items-center gap-2">
      <Progress
        value={pct}
        tone={progress.status === "completed" ? "accent" : "warn"}
        className="w-24 flex-1"
      />
      <span className="mono shrink-0 text-[11px] text-faint tabular-nums">
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

  const jobState: "queued" | "running" | "warning" | "ready" | "failed" = sync.active
    ? sync.stale
      ? "warning"
      : "running"
    : sync.status === "failed"
      ? "failed"
      : sync.status === "completed"
        ? "ready"
        : "queued";

  const jobTitle = sync.active
    ? "Progreso en vivo"
    : sync.status === "completed"
      ? "Última sincronización — completada"
      : sync.status === "failed"
        ? "Última sincronización — falló"
        : "Estado del job";

  const jobStatus =
    jobState === "running"
      ? "running"
      : jobState === "warning"
        ? "warning"
        : jobState === "ready"
          ? "completed"
          : jobState === "failed"
            ? "failed"
            : "queued";

  const sourceColumns: Column<Source>[] = [
    {
      key: "schema",
      header: "Esquema",
      hideBelow: "md",
      render: (s) => <span className="text-muted">{s.schema}</span>,
    },
    {
      key: "table",
      header: "Tabla",
      render: (s) => <span className="mono text-[13px]">{s.table}</span>,
    },
    {
      key: "rows",
      header: "Filas",
      align: "right",
      render: (s) => <span className="mono">{fmtNum(s.row_count ?? 0)}</span>,
    },
    {
      key: "progress",
      header: "Progreso",
      hideBelow: "lg",
      render: (s) => <ProgressCell progress={s.progress ?? null} />,
    },
    {
      key: "status",
      header: "Estado",
      render: (s) => {
        const isSyncing = syncingTables.has(`${s.schema}.${s.table}`);
        const hasProgress = Boolean(s.progress && s.progress.status === "running");
        return <SourceStatusBadge source={s} running={isSyncing || hasProgress} />;
      },
    },
  ];

  const lazyRows = lazyEvents.map((ev, index) => ({ ...ev, _key: `${ev.at}-${index}` }));
  const lazyColumns: Column<LazyEvent & { _key: string }>[] = [
    {
      key: "tables",
      header: "Tablas",
      render: (ev) => <span className="mono text-xs">{(ev.tables || []).join(", ") || "—"}</span>,
    },
    {
      key: "rows",
      header: "Filas",
      align: "right",
      render: (ev) => <span className="mono">{fmtNum(ev.rows_indexed)}</span>,
    },
    {
      key: "query",
      header: "Consulta",
      hideBelow: "md",
      className: "max-w-[320px] text-muted",
      render: (ev) => (
        <span className="block truncate" title={ev.query_preview}>
          {ev.query_preview || "—"}
        </span>
      ),
    },
    {
      key: "at",
      header: "Cuándo",
      render: (ev) => <span className="text-faint">{timeAgo(ev.at)}</span>,
    },
  ];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.sql}
        subtitle="Descubrí tablas y sincronizá tu información para poder hacer preguntas. Las tablas grandes se indexan solas a medida que las preguntas las necesitan."
        actions={
          <Button
            variant="secondary"
            leadingIcon={ArrowsClockwise}
            onClick={() => {
              setError("");
              loadSources().catch((err) =>
                setError(err instanceof Error ? err.message : "Error")
              );
            }}
          >
            Refrescar
          </Button>
        }
      />
      <ErrorInline message={error} />

      <Toolbar className="mb-4">
        <Button
          variant="primary"
          leadingIcon={Database}
          loading={sync.active}
          disabled={sync.active}
          onClick={() => void sync.startSyncAll(false)}
        >
          {sync.active
            ? "Sincronizando…"
            : `Sincronizar todos mis datos${hasPending ? ` (${pendingCount} pendientes)` : ""}`}
        </Button>
        <Tooltip label="No es obligatorio sincronizar todo antes de empezar. Las tablas grandes se indexan automáticamente a medida que las preguntas las necesitan.">
          <span
            tabIndex={0}
            className="inline-flex items-center gap-1.5 text-xs text-faint transition-colors duration-150 hover:text-muted"
          >
            <Info size={14} aria-hidden />
            La sincronización completa es opcional
          </span>
        </Tooltip>
        {sync.jobId && !sync.active && (
          <Button variant="ghost" leadingIcon={Trash} onClick={sync.clearJob}>
            Limpiar estado
          </Button>
        )}
      </Toolbar>

      {showProgress && (
        <Panel className="mb-6">
          <div className="p-4">
            <StatusRow
              state={jobState}
              progress={sync.progress}
              title={
                <>
                  <span className="text-h3">{jobTitle}</span>
                  <StatusBadge status={jobStatus} />
                </>
              }
              meta={
                <>
                  <span className="block">{sync.message || "—"}</span>
                  {sync.currentTable && sync.active && (
                    <span className="mono block">Tabla actual: {sync.currentTable}</span>
                  )}
                  {sync.stale && (
                    <span className="block text-warn">
                      Sin heartbeat reciente (&gt;3 min). Si la tabla es grande, el proceso
                      puede seguir en el servidor.
                    </span>
                  )}
                  {sync.error && <span className="block text-danger">{sync.error}</span>}
                  {sync.resultSummary && sync.status === "completed" && (
                    <span className="block text-ok">
                      Vectores: {String(sync.resultSummary.vectors_upserted ?? "—")} · Filas:{" "}
                      {String(sync.resultSummary.rows_indexed ?? "—")} · Duración:{" "}
                      {String(sync.resultSummary.duration_ms ?? "—")} ms
                    </span>
                  )}
                  <span className="mono block text-[11px]">
                    {Math.round(sync.progress)}%
                    {sync.tablesTotal > 0 && (
                      <>
                        {" "}
                        · tablas {sync.tablesDone}/{sync.tablesTotal}
                      </>
                    )}
                    {ago > 0 && <> · actualizado hace {ago}s</>} · job {sync.jobId}
                  </span>
                </>
              }
            />
          </div>
        </Panel>
      )}

      <SectionHeader
        title="Fuentes de datos"
        description="Tablas descubiertas y su estado de indexado."
        className="mb-3"
        actions={
          sources.length > 0 ? (
            <ResultCount shown={sources.length} total={sources.length} noun="tablas" />
          ) : undefined
        }
      />
      <DataTable
        columns={sourceColumns}
        rows={sources}
        rowKey={(s) => `${s.schema}.${s.table}`}
        caption="Tablas descubiertas en las fuentes SQL"
        loading={loading}
        empty={
          <EmptyState
            icon={Database}
            title="No hay fuentes descubiertas aún"
            body="Usá «Sincronizar todos mis datos» para descubrir tablas e indexarlas."
            hint="De paso quedan registradas en Conocimiento para poder preguntarles."
          />
        }
        rowActions={(s) => {
          const key = `${s.schema}.${s.table}`;
          const isSyncing = syncingTables.has(key);
          const hasProgress = Boolean(s.progress && s.progress.status === "running");
          const isPartial =
            !s.synced && !s.skipped && !hasProgress && (s.lazy_rows_indexed ?? 0) > 0;
          if (s.synced || s.row_count <= 0 || s.skipped) return null;
          return (
            <Button
              size="sm"
              variant="secondary"
              loading={isSyncing || hasProgress}
              disabled={isSyncing || hasProgress}
              onClick={() => void syncTable(s.schema, s.table)}
            >
              {isSyncing || hasProgress
                ? "En curso"
                : isPartial
                  ? "Completar sincronización"
                  : "Sincronizar"}
            </Button>
          );
        }}
      />

      <SectionHeader
        title="Actividad de indexado por demanda"
        description="Tablas que se indexaron al vuelo porque una pregunta las necesitó."
        className="mt-8 mb-3"
        actions={<span className="text-xs text-faint">Últimos 30 días</span>}
      />
      <DataTable
        columns={lazyColumns}
        rows={lazyRows}
        rowKey={(ev) => ev._key}
        caption="Indexados por demanda de los últimos 30 días"
        empty={
          <EmptyState
            icon={Lightning}
            title="Todavía no hay indexados al vuelo"
            body="Cuando una pregunta necesite datos no sincronizados, se indexarán automáticamente y quedarán registrados aquí."
          />
        }
      />

      <p className="mt-6 flex items-start gap-2 text-xs leading-relaxed text-faint">
        <Lightning size={14} className="mt-px shrink-0 text-accent" aria-hidden />
        Las tablas con columna de actualización se sincronizan incrementalmente: solo se
        indexa lo nuevo.
      </p>
    </KnowledgeLayout>
  );
}
