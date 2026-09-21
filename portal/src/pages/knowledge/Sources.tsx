import { ArrowsClockwise, Database, MagnifyingGlass, Plus, Trash, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { isApiError } from "../../lib/errors";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileDropzone } from "../../components/FileDropzone";
import { SourceUsageWarning, useSourceUsage } from "../../components/SourceUsageWarning";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
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
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtNum } from "../../lib/format";
import {
  COPY,
  sourceStatusLabel,
  sourceTypeLabel,
} from "./knowledgeCopy";

const SOURCE_TYPES = ["sql", "web", "s3", "api", "gdrive"] as const;

type SourceType = (typeof SOURCE_TYPES)[number];

type UploadItem = {
  filename: string;
  status: "created" | "duplicate" | "rejected" | "error";
  source_id?: string | null;
  job_id?: string | null;
  name?: string | null;
  error?: string | null;
  existing_source_id?: string | null;
  existing_name?: string | null;
};

const UPLOAD_STATUS_LABEL: Record<UploadItem["status"], string> = {
  created: "En cola de indexado",
  duplicate: "Ya existe",
  rejected: "Rechazado",
  error: "Error",
};

const MAX_UPLOAD_MB = 25;
const PAGE_SIZE = 25;

function uploadErrorMessage(err: unknown): string {
  if (isApiError(err) && err.status === 413) {
    return `Supera el máximo por archivo (${MAX_UPLOAD_MB} MB). Probá con uno más chico.`;
  }
  return err instanceof Error ? err.message : "Error al subir";
}

/** Sube UN archivo por request: evita el 413 por suma de tamaños del lote. */
async function uploadSingleFile(
  file: File,
  auth: { token: string; organizationId: string },
  opts: { kbId?: string; force: boolean },
): Promise<UploadItem> {
  const form = new FormData();
  form.append("files", file);
  const params = new URLSearchParams();
  if (opts.kbId) params.set("knowledge_base_id", opts.kbId);
  if (opts.force) params.set("force", "true");
  const out = await api<{ items: UploadItem[] }>(
    `/api/v1/sources/files/upload-batch?${params.toString()}`,
    {
      method: "POST",
      token: auth.token,
      organizationId: auth.organizationId,
      body: form,
    },
  );
  return (
    (out.items || [])[0] ?? {
      filename: file.name,
      status: "error",
      error: "El servidor no devolvió resultado para el archivo.",
    }
  );
}

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
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [profile, setProfile] = useState<{ sourceId: string; tables: { name: string; columns: ProfileCol[] }[] } | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState<SourceType>("web");
  const [folderId, setFolderId] = useState("");
  const [creating, setCreating] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState("");
  const [syncingId, setSyncingId] = useState("");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [pendingDelete, setPendingDelete] = useState<SourceRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const { agents: deleteUsage, loading: deleteUsageLoading } = useSourceUsage(
    pendingDelete?.id ?? null,
  );

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
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
    ])
      .then(([data, kbData]) => {
        setSources(data.sources || []);
        setKbs(kbData.knowledge_bases || []);
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => {
    load();
  }, [load]);

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
    setCreating(true);
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
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setCreating(false));
  }, [session, load]);

  async function create() {
    if (!session) return;
    setError("");
    setMsg("");
    if (type === "gdrive") {
      if (!folderId.trim()) {
        setError("Indica el ID de la carpeta de Google Drive.");
        return;
      }
      setCreating(true);
      try {
        sessionStorage.setItem(
          PENDING_KEY,
          JSON.stringify({ name: name.trim(), folder_id: folderId.trim() }),
        );
        const started = await api<{ authorization_url: string; connector_id: string }>(
          "/api/v1/connectors/oauth/drive/start",
          {
            method: "POST",
            token: session.token,
            organizationId: session.organizationId,
            body: JSON.stringify({
              name: name.trim(),
              folder_id: folderId.trim(),
            }),
          },
        );
        window.location.assign(started.authorization_url);
      } catch (err) {
        sessionStorage.removeItem(PENDING_KEY);
        setError(err instanceof Error ? err.message : "Error al conectar Drive");
        setCreating(false);
      }
      return;
    }
    setCreating(true);
    try {
      const kbId = await ensureKbId();
      await api("/api/v1/sources", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: name.trim(),
          type,
          knowledge_base_id: kbId || null,
          config: {},
        }),
      });
      setMsg("Fuente creada.");
      setName("");
      setShowCreate(false);
      setAdvanced(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  function addUploadFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    if (incoming.length === 0) return;
    setUploadItems([]);
    setUploadFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...incoming.filter((f) => !seen.has(`${f.name}:${f.size}`))];
    });
  }

  async function uploadAll(force: boolean) {
    if (!session?.token || uploadFiles.length === 0) return;
    const auth = { token: session.token, organizationId: session.organizationId };
    setUploading(true);
    setError("");
    setMsg("");
    const results: UploadItem[] = [];
    let created = 0;
    let failed = 0;
    try {
      const kbId = await ensureKbId();
      for (const file of uploadFiles) {
        try {
          const item = await uploadSingleFile(file, auth, { kbId, force });
          results.push(item);
          if (item.status === "created") created += 1;
          else if (item.status === "error" || item.status === "rejected") failed += 1;
        } catch (err) {
          failed += 1;
          results.push({
            filename: file.name,
            status: "error",
            error: uploadErrorMessage(err),
          });
        }
        // Progreso por archivo: los que falten siguen aunque uno falle.
        setUploadItems([...results]);
      }
      if (created > 0) {
        setMsg(
          created === 1
            ? "1 archivo en cola de indexado."
            : `${created} archivos en cola de indexado.`,
        );
      }
      if (failed > 0) {
        setError(
          failed === 1
            ? "1 archivo no se pudo subir. Revisá el detalle."
            : `${failed} archivos no se pudieron subir. Revisá el detalle.`,
        );
      }
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir");
    } finally {
      setUploading(false);
    }
  }

  async function retryUpload(item: UploadItem) {
    if (!session?.token) return;
    const file = uploadFiles.find((f) => f.name === item.filename);
    if (!file) return;
    setRetrying(item.filename);
    setError("");
    try {
      const kbId = await ensureKbId();
      const result = await uploadSingleFile(
        file,
        { token: session.token, organizationId: session.organizationId },
        { kbId, force: true },
      );
      setUploadItems((prev) =>
        prev.map((i) => (i.filename === item.filename ? result : i)),
      );
      if (result.status === "created") setMsg("Copia creada. En cola de indexado.");
      load();
    } catch (err) {
      setError(uploadErrorMessage(err));
    } finally {
      setRetrying("");
    }
  }

  async function ensureKbId(): Promise<string | undefined> {
    if (!session) return undefined;
    if (kbs[0]) return kbs[0].id;
    const created = await api<KnowledgeBase>("/api/v1/knowledge-bases", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ name: COPY.principalKb }),
    });
    setKbs((prev) => [...prev, created]);
    return created.id;
  }

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
      await api(`/api/v1/sources/${pendingDelete.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Fuente «${pendingDelete.name}» eliminada.`);
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
          <Button
            variant="primary"
            leadingIcon={Plus}
            aria-expanded={showCreate}
            onClick={() => setShowCreate((s) => !s)}
          >
            Nueva fuente
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {showCreate && (
          <Panel>
            <PanelHeader
              title="Añadir fuentes"
              description="Soltá uno o varios archivos: se suben de a uno, cada uno se indexa solo y hereda el nombre del archivo."
              actions={
                <IconButton
                  label="Cerrar alta de fuente"
                  icon={X}
                  onClick={() => setShowCreate(false)}
                />
              }
            />
            <div className="panel-body flex flex-col gap-3">
              <FileDropzone
                onFiles={addUploadFiles}
                inputTestId="source-files"
                dropzoneTestId="source-dropzone"
              />

              {uploadFiles.length > 0 && (
                <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
                  {uploadFiles.map((item) => (
                    <li
                      key={`${item.name}-${item.size}`}
                      className="flex flex-wrap items-center gap-2 rounded-sm bg-soft px-2.5 py-1.5 text-[12.5px] text-text"
                    >
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                      <span className="text-[11px] text-faint">
                        {Math.max(1, Math.round(item.size / 1024))} KB
                      </span>
                      <IconButton
                        label={`Quitar ${item.name}`}
                        icon={X}
                        onClick={() =>
                          setUploadFiles((prev) => prev.filter((f) => f !== item))
                        }
                      />
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  leadingIcon={Plus}
                  loading={uploading}
                  disabled={uploading || uploadFiles.length === 0}
                  onClick={() => void uploadAll(false)}
                >
                  {uploadFiles.length > 1
                    ? `Subir ${uploadFiles.length} archivos`
                    : "Subir e indexar"}
                </Button>
                {uploadFiles.length > 0 && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setUploadFiles([]);
                      setUploadItems([]);
                    }}
                  >
                    Limpiar
                  </Button>
                )}
              </div>

              <p className="text-[13px] leading-relaxed text-muted">
                {kbs.length > 0
                  ? `Se indexa en la colección ${kbs[0].name}.`
                  : "Se crea la colección Principal y se indexa ahí."}{" "}
                Después podés marcarla en Agent Studio.
              </p>

              {uploadItems.length > 0 && (
                <ul className="flex max-h-48 flex-col gap-1.5 overflow-y-auto" data-testid="upload-results">
                  {uploadItems.map((item) => (
                    <li
                      key={item.filename}
                      className="flex flex-wrap items-center gap-2 rounded-sm border border-border-soft px-2.5 py-2 text-[12.5px]"
                    >
                      <span className="min-w-0 flex-1 truncate text-text">
                        {item.name || item.filename}
                      </span>
                      <span
                        className={
                          item.status === "created"
                            ? "text-ok"
                            : item.status === "duplicate"
                              ? "text-warn"
                              : "text-danger"
                        }
                      >
                        {UPLOAD_STATUS_LABEL[item.status]}
                      </span>
                      {item.status === "duplicate" && item.existing_source_id && (
                        <>
                          <ButtonLink
                            to={`/knowledge/sources/${item.existing_source_id}`}
                            variant="secondary"
                          >
                            Abrir existente
                          </ButtonLink>
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={retrying === item.filename}
                            onClick={() => void retryUpload(item)}
                          >
                            Subir igual
                          </Button>
                        </>
                      )}
                      {(item.status === "rejected" || item.status === "error") &&
                        item.error && (
                          <span className="text-[11px] text-danger">{item.error}</span>
                        )}
                    </li>
                  ))}
                </ul>
              )}

              <div>
                <Button variant="ghost" size="sm" onClick={() => setAdvanced((v) => !v)}>
                  {advanced
                    ? "Ocultar conexión avanzada"
                    : "Conectar otra fuente (base de datos, web, API, Drive)"}
                </Button>
              </div>

              {advanced && (
                <form
                  className="flex flex-col gap-3 border-t border-border-soft pt-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void create();
                  }}
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Nombre" hint="Cómo vas a reconocer esta fuente en los agentes.">
                      <Input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        autoComplete="off"
                        required
                      />
                    </Field>
                    <Field label="Tipo">
                      <Select value={type} onChange={(e) => setType(e.target.value as SourceType)}>
                        {SOURCE_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {sourceTypeLabel(t)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </div>

                  {type === "gdrive" && (
                    <Field
                      label="ID de carpeta de Google Drive"
                      hint="1abc… (ID de la carpeta, no la URL). Se autoriza solo lectura."
                    >
                      <Input
                        value={folderId}
                        onChange={(e) => setFolderId(e.target.value)}
                        autoComplete="off"
                        placeholder="1abc…"
                      />
                    </Field>
                  )}

                  <p className="prose-measure text-[13px] leading-relaxed text-muted">
                    {type === "gdrive"
                      ? "Se abre Google para autorizar solo lectura. El refresh token vive en el almacén de secretos, nunca en la fuente."
                      : "Las credenciales de conectores viven en Vault, no en esta ficha."}
                  </p>

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="submit"
                      variant="primary"
                      loading={creating}
                      leadingIcon={Plus}
                      disabled={creating || !name.trim()}
                    >
                      {type === "gdrive" ? "Conectar Google Drive" : "Crear fuente"}
                    </Button>
                    <Button variant="ghost" onClick={() => setShowCreate(false)}>
                      Cancelar
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </Panel>
        )}

        <Panel>
          <PanelHeader
            title="Fuentes de conocimiento"
            description="Origen de datos indexado en tus colecciones."
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
                          <StatusBadge status={s.status} label={sourceStatusLabel(s.status)} />
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
