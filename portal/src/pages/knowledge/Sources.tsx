import { ArrowsClockwise, Database, MagnifyingGlass, Plus, Trash, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
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
import { isApiError } from "../../lib/errors";
import { fmtDateTime, fmtNum } from "../../lib/format";
import {
  COPY,
  isFileUploadType,
  sourceStatusLabel,
  sourceTypeBlurb,
  sourceTypeLabel,
} from "./knowledgeCopy";

const SOURCE_TYPES = [
  "sql",
  "file",
  "csv",
  "excel",
  "web",
  "s3",
  "api",
  "gdrive",
] as const;

type SourceType = (typeof SOURCE_TYPES)[number];

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
  const [name, setName] = useState("");
  const [type, setType] = useState<SourceType>("file");
  const [folderId, setFolderId] = useState("");
  const [creating, setCreating] = useState(false);
  const [duplicate, setDuplicate] = useState<{
    id: string;
    name: string;
    file: File;
    kbId?: string;
  } | null>(null);
  const [syncingId, setSyncingId] = useState("");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SourceRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");

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
    if (isFileUploadType(type) && !file) {
      setError(COPY.pickFile);
      return;
    }
    setCreating(true);
    let kbId: string | undefined;
    try {
      kbId = await ensureKbId();
      if (isFileUploadType(type) && file) {
        await uploadFileSource(file, kbId, false);
        setMsg("Archivo subido. Indexado en cola.");
      } else {
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
      }
      setName("");
      setFile(null);
      setShowCreate(false);
      load();
    } catch (err) {
      if (isApiError(err) && err.status === 409 && err.details?.existing_source_id && file) {
        setError("");
        setDuplicate({
          id: err.details.existing_source_id,
          name: err.details.existing_name || name.trim() || file.name,
          file,
          kbId,
        });
      } else {
        setError(err instanceof Error ? err.message : "Error al crear");
      }
    } finally {
      setCreating(false);
    }
  }

  async function uploadFileSource(file: File, kbId: string | undefined, force: boolean) {
    if (!session) return;
    const params = new URLSearchParams();
    if (kbId) params.set("knowledge_base_id", kbId);
    if (name.trim()) params.set("name", name.trim());
    if (force) params.set("force", "true");
    const qs = params.toString() ? `?${params.toString()}` : "";
    const body = new FormData();
    body.append("file", file);
    await api(`/api/v1/sources/files/upload${qs}`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body,
    });
  }

  async function forceDuplicateCopy() {
    if (!duplicate) return;
    setCreating(true);
    setError("");
    try {
      await uploadFileSource(duplicate.file, duplicate.kbId, true);
      setDuplicate(null);
      setMsg("Copia creada. Indexado en cola.");
      setName("");
      setFile(null);
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear la copia");
    } finally {
      setCreating(false);
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

        {duplicate && (
          <Panel className="border-warn/40">
            <div className="panel-body flex flex-wrap items-center gap-3 text-sm">
              <span className="text-text">
                Ya existe una fuente con el mismo nombre:{" "}
                <span className="mono">{duplicate.name}</span>
              </span>
              <div className="flex gap-2">
                <ButtonLink to={`/knowledge/sources/${duplicate.id}`} variant="secondary">
                  Abrir existente
                </ButtonLink>
                <Button
                  variant="secondary"
                  disabled={creating}
                  onClick={() => void forceDuplicateCopy()}
                >
                  Crear copia
                </Button>
                <Button variant="ghost" onClick={() => setDuplicate(null)}>
                  Cancelar
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {showCreate && (
          <Panel>
            <PanelHeader
              title="Alta de fuente"
              description="El origen queda conectado a una colección para que los agentes puedan citarlo."
              actions={
                <IconButton
                  label="Cerrar alta de fuente"
                  icon={X}
                  onClick={() => setShowCreate(false)}
                />
              }
            />
            <form
              className="panel-body flex flex-col gap-3"
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
                    required={!isFileUploadType(type)}
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

              {isFileUploadType(type) && (
                <Field label={COPY.uploadFile} hint="PDF, CSV o Excel. Se indexa en la colección elegida.">
                  <Input
                    type="file"
                    data-testid="source-file"
                    className="py-1.5 file:mr-3 file:rounded-sm file:border-0 file:bg-soft file:px-2.5 file:py-1.5 file:text-[13px] file:font-medium file:text-text"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </Field>
              )}

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
                  : isFileUploadType(type)
                    ? COPY.collectionHint
                    : "Las credenciales de conectores viven en Vault, no en esta ficha."}
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="submit"
                  variant="primary"
                  loading={creating}
                  leadingIcon={Plus}
                  disabled={
                    creating ||
                    (isFileUploadType(type) ? !file : type === "gdrive" ? !name.trim() : !name.trim())
                  }
                >
                  {type === "gdrive" ? "Conectar Google Drive" : "Crear fuente"}
                </Button>
                <Button variant="ghost" onClick={() => setShowCreate(false)}>
                  Cancelar
                </Button>
              </div>
            </form>
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
            <ul>
              {visible.map((s) => {
                const canProfile = s.type === "sql" || Boolean(s.config?.managed);
                const docs = s.document_count || s.last_processed_count || 0;
                return (
                  <li
                    key={s.id}
                    data-testid={`source-card-${s.id}`}
                    data-state={RAIL_STATE[s.status]}
                    className="state-rail border-b border-border-soft py-3.5 pr-3 pl-4 last:border-b-0"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
                          <Link
                            to={`/knowledge/sources/${s.id}`}
                            className="truncate text-[13.5px] font-medium text-text transition-colors duration-150 hover:text-accent"
                          >
                            {s.name}
                          </Link>
                          <StatusBadge status={s.status} label={sourceStatusLabel(s.status)} />
                        </div>
                        <p className="prose-measure mt-1 text-xs leading-relaxed text-muted">
                          <span className="text-faint">{sourceTypeLabel(s.type, s.config?.managed)}</span>
                          {" · "}
                          {sourceTypeBlurb(s.type, s.config?.managed)}
                        </p>
                        <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
                          <span>
                            {COPY.lastSync}:{" "}
                            <span className="text-muted">
                              {s.last_sync ? fmtDateTime(s.last_sync) : "—"}
                            </span>
                          </span>
                          <span>
                            {COPY.documents}:{" "}
                            <span className="mono text-muted">{fmtNum(docs)}</span>
                          </span>
                          {s.error_count > 0 ? (
                            <span className="text-danger">
                              {COPY.issues}: <span className="mono">{fmtNum(s.error_count)}</span>
                            </span>
                          ) : null}
                        </p>
                        {s.last_error ? (
                          <p className="mt-1.5 max-w-[68ch] text-xs leading-relaxed text-danger">
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
        body={COPY.deleteSourceBody}
        confirmLabel={COPY.deleteSource}
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </KnowledgeLayout>
  );
}
