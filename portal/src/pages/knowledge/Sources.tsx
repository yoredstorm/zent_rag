import {
  ArrowsClockwise,
  Database,
  MagnifyingGlass,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SourceUsageWarning, useSourceUsage } from "../../components/SourceUsageWarning";
import {
  fetchLearningSessions,
  type LearningSessionDetail,
} from "../../lib/knowledgeSessions";
import { useLearningJob } from "../../learningJob";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  IconButton,
  Input,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  Skeleton,
  SuccessInline,
  type Column,
} from "../../components/ui";
import { StatusBadge } from "../../components/ui/Badge";
import { MarketplaceSurfaceDialog } from "../../components/marketplace/MarketplaceSurfaceDialog";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeImportWizard } from "../../components/knowledgeImport/KnowledgeImportWizard";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtNum } from "../../lib/format";
import {
  COPY,
  sourceStatusLabel,
  sourceTypeLabel,
} from "./knowledgeCopy";
import { sourceReadiness } from "./sourceState";

const PAGE_SIZE = 25;

/** Mismo vocabulario que la vista de sesión (LearningSessionView). */
const SESSION_STATUS_LABEL: Record<string, string> = {
  preparing: "preparando",
  learning: "aprendiendo ahora",
  available: "disponible",
  optimizing: "optimizando",
  completed: "completado",
  partial: "parcial",
  failed: "no se pudo completar",
  canceled: "cancelado",
};

type SourceRow = {
  id: string;
  name: string;
  type: string;
  status: string;
  last_sync: string | null;
  last_error: string | null;
  document_count: number;
  error_count: number;
  last_processed_count?: number;
  knowledge_base_id?: string | null;
  config?: { managed?: boolean };
};

type KnowledgeBase = { id: string; name: string };

type ProfileCol = {
  name: string;
  data_type: string;
  nullable: boolean;
  is_pk: boolean;
  is_fk: boolean;
  null_rate: number | null;
  cardinality: number | null;
  pii_flags: string[];
  sensitive: boolean;
};

const PENDING_KEY = "zent_gdrive_pending";

type RailState = "queued" | "running" | "ready" | "failed";

/** Estado real de la fuente → rail de actividad. Sin estado conocido, rail neutro. */
const RAIL_STATE: Record<string, RailState> = {
  created: "queued",
  discovering: "running",
  ingesting: "running",
  ready: "ready",
  indexed: "ready",
  error: "failed",
};

const PROFILE_COLUMNS: Column<ProfileCol>[] = [
  {
    key: "name",
    header: "Columna",
    render: (col) => <span className="mono text-xs text-text">{col.name}</span>,
  },
  {
    key: "data_type",
    header: "Tipo",
    render: (col) => <span className="text-xs text-muted">{col.data_type}</span>,
  },
  {
    key: "null_rate",
    header: "Null %",
    align: "right",
    hideBelow: "md",
    render: (col) => (
      <span className="mono text-xs text-muted">{col.null_rate ?? "—"}</span>
    ),
  },
  {
    key: "cardinality",
    header: "Cardinalidad",
    align: "right",
    hideBelow: "lg",
    render: (col) => <span className="mono text-xs text-muted">{col.cardinality ?? "—"}</span>,
  },
  {
    key: "keys",
    header: "PK/FK",
    hideBelow: "md",
    render: (col) =>
      col.is_pk || col.is_fk ? (
        <Badge tone="neutral">{col.is_pk ? "PK" : "FK"}</Badge>
      ) : (
        <span className="text-xs text-faint">—</span>
      ),
  },
  {
    key: "pii",
    header: "PII",
    render: (col) =>
      col.pii_flags.length > 0 ? (
        <Badge tone="danger">{col.pii_flags.join(", ")}</Badge>
      ) : col.sensitive ? (
        <Badge tone="warn">sensible</Badge>
      ) : (
        <span className="text-xs text-faint">—</span>
      ),
  },
];

export default function KnowledgeSourcesPage() {
  const { session } = useAuth();
  const { version: learningVersion, track: trackLearning } = useLearningJob();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");
  const [profile, setProfile] = useState<{ sourceId: string; tables: { name: string; columns: ProfileCol[] }[] } | null>(null);
  const [syncingId, setSyncingId] = useState("");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [pendingDelete, setPendingDelete] = useState<SourceRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [recentSessions, setRecentSessions] = useState<LearningSessionDetail[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  // `?new=1` abre el alta; `session_id` recupera una incorporación tras refresh.
  const [showCreate, setShowCreate] = useState(
    () => searchParams.get("new") === "1" || Boolean(searchParams.get("session_id")),
  );
  const [showMarketplace, setShowMarketplace] = useState(false);

  const closeCreate = useCallback(() => {
    setShowCreate(false);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("new");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const { agents: deleteUsage, loading: deleteUsageLoading } = useSourceUsage(
    pendingDelete?.id ?? null,
  );

  const load = useCallback((silent = false) => {
    if (!session) return;
    if (!silent) setLoading(true);
    setLoadError("");
    Promise.all([
      api<{ sources: SourceRow[] }>("/api/v1/sources", {
        token: session.token,
        organizationId: session.organizationId,
      }),
      api<{ knowledge_bases: KnowledgeBase[] }>("/api/v1/knowledge-bases", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ knowledge_bases: [] as KnowledgeBase[] })),
      fetchLearningSessions(6).catch(() => ({ sessions: [], count: 0 })),
    ])
      .then(([data, kbData, sessionData]) => {
        setSources(data.sources || []);
        setKbs(kbData.knowledge_bases || []);
        setRecentSessions(sessionData.sessions || []);
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Error"))
      .finally(() => {
        if (!silent) setLoading(false);
      });
  }, [session]);

  useEffect(() => {
    load();
  }, [load]);

  // Vivo: mientras haya fuentes en tránsito, la lista se refresca sola.
  const livePending = sources.some((row) =>
    ["created", "discovering", "ingesting"].includes(row.status),
  );
  useEffect(() => {
    if (!livePending) return;
    const interval = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(interval);
  }, [livePending, load]);

  // El aprendizaje terminó en otra pantalla: refresca sin esperar al poll.
  useEffect(() => {
    if (learningVersion === 0) return;
    load(true);
  }, [learningVersion, load]);

  useEffect(() => {
    setPage(1);
  }, [query]);

  useEffect(() => {
    if (!session) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("gdrive") !== "ok") return;
    const connectorId = params.get("connector_id");
    const raw = sessionStorage.getItem(PENDING_KEY);
    window.history.replaceState({}, "", window.location.pathname);
    if (!connectorId || !raw) {
      setMsg("Google Drive conectado. Crea la fuente con el ID de carpeta.");
      return;
    }
    let pending: { name?: string; folder_id?: string };
    try {
      pending = JSON.parse(raw) as { name?: string; folder_id?: string };
    } catch {
      sessionStorage.removeItem(PENDING_KEY);
      return;
    }
    sessionStorage.removeItem(PENDING_KEY);
    const sourceName = (pending.name || "").trim();
    const folder = (pending.folder_id || "").trim();
    if (!sourceName || !folder) return;
    api("/api/v1/sources", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({
        name: sourceName,
        type: "gdrive",
        config: { folder_id: folder, connector_id: connectorId },
      }),
    })
      .then(() => {
        setMsg("Fuente de Google Drive creada. Los tokens no se guardan en la fuente.");
        load();
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
  }, [session, load]);

  async function assignKb(sourceId: string, knowledgeBaseId: string) {
    if (!session || !knowledgeBaseId) return;
    setError("");
    try {
      await api(`/api/v1/sources/${sourceId}`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
      });
      setSources((prev) =>
        prev.map((row) => (row.id === sourceId ? { ...row, knowledge_base_id: knowledgeBaseId } : row)),
      );
      setMsg("Colección actualizada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al agrupar");
    }
  }

  async function confirmDelete() {
    if (!session || !pendingDelete) return;
    setDeleting(true);
    setError("");
    try {
      const result = await api<{ agents_updated?: number }>(`/api/v1/sources/${pendingDelete.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      const updated = result?.agents_updated ?? 0;
      setMsg(
        updated > 0
          ? `Fuente «${pendingDelete.name}» eliminada. Se actualizaron ${updated} agente${updated === 1 ? "" : "s"} que la usaban.`
          : `Fuente «${pendingDelete.name}» eliminada.`,
      );
      setPendingDelete(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setDeleting(false);
    }
  }

  async function profileSource(sourceId: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/sources/${sourceId}/profile`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      const data = await api<{ tables: { name: string; columns: ProfileCol[] }[] }>(
        `/api/v1/sources/${sourceId}/profile`,
        { token: session.token, organizationId: session.organizationId }
      );
      setProfile({ sourceId, tables: data.tables || [] });
      setMsg("Fuente perfilizada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al perfilizar");
    }
  }

  async function syncSource(sourceId: string) {
    if (!session) return;
    setError("");
    setMsg("");
    setSyncingId(sourceId);
    try {
      await api(`/api/v1/sources/${sourceId}/sync`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Sincronización encolada.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al sincronizar");
    } finally {
      setSyncingId("");
    }
  }

  const term = query.trim().toLowerCase();
  const visible = term
    ? sources.filter(
        (s) =>
          s.name.toLowerCase().includes(term) ||
          sourceTypeLabel(s.type, s.config?.managed).toLowerCase().includes(term) ||
          sourceStatusLabel(s.status).toLowerCase().includes(term),
      )
    : sources;
  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = visible.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.sources}
        subtitle={
          <>
            Los agentes eligen estas fuentes en{" "}
            <Link to="/agents" className="text-accent hover:underline">
              Agent Studio
            </Link>
            . Prueba en{" "}
            <Link to="/chat?target=knowledge" className="text-accent hover:underline">
              Playground
            </Link>{" "}
            cuando estén indexadas.
          </>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => setShowMarketplace(true)}>
              Agregar desde Marketplace
            </Button>
            <Button
              variant="primary"
              leadingIcon={Plus}
              aria-expanded={showCreate}
              onClick={() => (showCreate ? closeCreate() : setShowCreate(true))}
            >
              Añadir información
            </Button>
          </div>
        }
      />

      <MarketplaceSurfaceDialog
        open={showMarketplace}
        onOpenChange={setShowMarketplace}
        surface="KNOWLEDGE"
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {showCreate && (
          <KnowledgeImportWizard
            open={showCreate}
            onClose={closeCreate}
            initialSessionId={searchParams.get("session_id")}
            initialCorpusId={searchParams.get("corpus_id")}
            onSession={(sessionId) => {
              setSearchParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  next.set("session_id", sessionId);
                  return next;
                },
                { replace: true },
              );
            }}
            onMinimize={(sessionId) => {
              trackLearning(sessionId);
              setSearchParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  next.set("session_id", sessionId);
                  return next;
                },
                { replace: true },
              );
              closeCreate();
            }}
          />
        )}

        {recentSessions.length > 0 && (
          <Panel>
            <PanelHeader
              title="Aprendizaje de ZENT"
              description="Cada sesión muestra qué aprendió ZENT de tus fuentes, con eventos reales del Knowledge Compiler."
            />
            <div className="panel-body">
              <ul className="flex flex-col gap-1.5" data-testid="recent-sessions">
                {recentSessions.map((learning) => {
                  const activeSession = !["completed", "partial", "failed", "canceled"].includes(
                    learning.status,
                  );
                  return (
                    <li key={learning.session_id}>
                      <Link
                        to={`/knowledge/sessions/${learning.session_id}`}
                        className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-raised"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] text-text">
                            {learning.title || "Aprendizaje de conocimiento"}
                          </span>
                          <span className="text-[11px] text-faint">
                            {learning.source_count} fuente
                            {learning.source_count === 1 ? "" : "s"} ·{" "}
                            {learning.completed_at
                              ? "completado"
                              : SESSION_STATUS_LABEL[learning.status] ?? learning.status}
                          </span>
                        </span>
                        <Badge tone={activeSession ? "accent" : "neutral"}>
                          {activeSession ? "En vivo" : "Ver resumen"}
                        </Badge>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          </Panel>
        )}

        <Panel id="knowledge-source-list">
          <PanelHeader
            title="Fuentes de conocimiento"
            description="Origen de datos disponible para consultar en tus colecciones."
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="search"
                  icon={MagnifyingGlass}
                  aria-label="Buscar fuentes"
                  placeholder="Buscar por nombre o tipo"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="w-full sm:w-64"
                />
                <span className="mono text-[11px] text-faint tabular-nums">
                  {visible.length === sources.length
                    ? fmtNum(sources.length)
                    : `${fmtNum(visible.length)}/${fmtNum(sources.length)}`}
                </span>
              </div>
            }
          />

          {loading ? (
            <div className="flex flex-col gap-4 p-4" aria-busy="true">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-52" />
                  <Skeleton className="h-3.5 w-72" />
                  <Skeleton className="h-8 w-56" />
                </div>
              ))}
            </div>
          ) : loadError ? (
            <div className="p-4">
              <ErrorInline message={loadError} className="mb-0" />
            </div>
          ) : sources.length === 0 ? (
            <EmptyState
              icon={Database}
              title="Todavía no hay fuentes"
              body="Crea una fuente (incluido Google Drive) o sube archivos para alimentar tus colecciones."
              action={
                <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
                  Nueva fuente
                </Button>
              }
            />
          ) : visible.length === 0 ? (
            <EmptyState
              compact
              icon={MagnifyingGlass}
              title="Sin resultados"
              body="Ninguna fuente coincide con la búsqueda."
              action={
                <Button variant="ghost" size="sm" onClick={() => setQuery("")}>
                  Limpiar búsqueda
                </Button>
              }
            />
          ) : (
            <>
            <ul>
              {paged.map((s) => {
                const canProfile = s.type === "sql" || Boolean(s.config?.managed);
                const docs = s.document_count || s.last_processed_count || 0;
                return (
                  <li
                    key={s.id}
                    data-testid={`source-card-${s.id}`}
                    data-state={RAIL_STATE[s.status]}
                    className="state-rail border-b border-border-soft py-2 pr-3 pl-4 last:border-b-0"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
                          <Link
                            to={`/knowledge/sources/${s.id}`}
                            className="truncate text-[13.5px] font-medium text-text transition-colors duration-150 hover:text-accent"
                          >
                            {s.name}
                          </Link>
                          <StatusBadge
                            status={s.status}
                            label={sourceReadiness(s.status).label}
                          />
                          <span className="text-xs text-faint">
                            {sourceTypeLabel(s.type, s.config?.managed)}
                          </span>
                          <span className="text-xs text-faint">
                            {COPY.documents}:{" "}
                            <span className="mono text-muted">{fmtNum(docs)}</span>
                          </span>
                          {s.error_count > 0 ? (
                            <span className="text-xs text-danger">
                              {COPY.issues}: <span className="mono">{fmtNum(s.error_count)}</span>
                            </span>
                          ) : null}
                        </div>
                        {s.last_error ? (
                          <p className="mt-1 max-w-[68ch] truncate text-xs leading-relaxed text-danger">
                            {s.last_error}
                          </p>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap items-center gap-1.5">
                        <ButtonLink
                          to={`/knowledge/sources/${s.id}`}
                          variant="secondary"
                          size="sm"
                        >
                          {COPY.open}
                        </ButtonLink>
                        {canProfile ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Perfilizar ${s.name}`}
                            onClick={() => void profileSource(s.id)}
                          >
                            Perfilizar
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Sincronizar ${s.name}`}
                          loading={syncingId === s.id}
                          leadingIcon={ArrowsClockwise}
                          onClick={() => void syncSource(s.id)}
                        >
                          {COPY.sync}
                        </Button>
                        {kbs.length > 0 ? (
                          <Select
                            className="w-auto py-1 pl-2 text-xs"
                            value={s.knowledge_base_id || kbs[0]?.id || ""}
                            aria-label={`Colección de ${s.name}`}
                            data-testid={`source-kb-${s.id}`}
                            onChange={(e) => void assignKb(s.id, e.target.value)}
                          >
                            {kbs.map((kb) => (
                              <option key={kb.id} value={kb.id}>
                                {kb.name}
                              </option>
                            ))}
                          </Select>
                        ) : null}
                        <IconButton
                          label={`Eliminar ${s.name}`}
                          icon={Trash}
                          className="text-danger"
                          data-testid={`source-delete-${s.id}`}
                          onClick={() => setPendingDelete(s)}
                        />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
            {visible.length > PAGE_SIZE ? (
              <div className="border-t border-border-soft px-4 py-3">
                <Pagination
                  page={safePage}
                  pageSize={PAGE_SIZE}
                  total={visible.length}
                  onPageChange={setPage}
                />
              </div>
            ) : null}
            </>
          )}
        </Panel>

        {profile && (
          <div className="flex flex-col gap-4">
            <SectionHeader
              title="Perfil de datos"
              description="Columnas detectadas por tabla tras la última lectura de la fuente."
              actions={
                <Button variant="ghost" size="sm" onClick={() => setProfile(null)}>
                  Cerrar
                </Button>
              }
            />
            {profile.tables.length === 0 ? (
              <Panel>
                <EmptyState
                  compact
                  title="Sin tablas en el perfil"
                  body="La fuente no expuso tablas al perfilar."
                />
              </Panel>
            ) : (
              profile.tables.map((table) => (
                <div key={table.name} className="min-w-0">
                  <p className="mb-2 font-mono text-xs text-muted">{table.name}</p>
                  <DataTable
                    columns={PROFILE_COLUMNS}
                    rows={table.columns}
                    rowKey={(col) => col.name}
                    caption={`Columnas de ${table.name}`}
                    dense
                  />
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={`Eliminar ${pendingDelete?.name || "fuente"}`}
        body={
          <>
            {COPY.deleteSourceBody}
            <SourceUsageWarning agents={deleteUsage} loading={deleteUsageLoading} />
          </>
        }
        confirmLabel={COPY.deleteSource}
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </KnowledgeLayout>
  );
}
