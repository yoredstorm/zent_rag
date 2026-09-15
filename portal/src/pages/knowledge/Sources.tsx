import { ArrowsClockwise, Database, Plus, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtDateTime, fmtNum } from "../../lib/format";
import {
  COPY,
  isFileUploadType,
  sourceStatusBadgeClass,
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

const PENDING_KEY = "zent_gdrive_pending";

export default function KnowledgeSourcesPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [profile, setProfile] = useState<{ sourceId: string; tables: { name: string; columns: ProfileCol[] }[] } | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<SourceType>("file");
  const [folderId, setFolderId] = useState("");
  const [creating, setCreating] = useState(false);
  const [syncingId, setSyncingId] = useState("");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SourceRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
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
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
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
    try {
      const kbId = await ensureKbId();
      if (isFileUploadType(type) && file) {
        const params = new URLSearchParams();
        if (kbId) params.set("knowledge_base_id", kbId);
        if (name.trim()) params.set("name", name.trim());
        const qs = params.toString() ? `?${params.toString()}` : "";
        const body = new FormData();
        body.append("file", file);
        await api(`/api/v1/sources/files/upload${qs}`, {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body,
        });
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
      setError(err instanceof Error ? err.message : "Error al crear");
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

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.sources}
        actions={
          <button
            className="btn btn-primary min-h-11"
            type="button"
            onClick={() => setShowCreate((s) => !s)}
          >
            <Plus size={15} aria-hidden />
            Nueva fuente
          </button>
        }
      />
      <p className="mb-4 text-sm text-muted">
        Los agentes eligen estas fuentes en{" "}
        <Link to="/agents" className="text-accent hover:underline">
          Agent Studio
        </Link>
        . Prueba en{" "}
        <Link to="/chat?target=knowledge" className="text-accent hover:underline">
          Playground
        </Link>{" "}
        cuando estén indexadas.
      </p>
      <div className="mt-4">
        <ErrorInline message={error} />
        <SuccessInline message={msg} />
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Alta de fuente</h2>
          </div>
          <form
            className="flex flex-col gap-3 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <label className="block text-sm text-text">
              Nombre
              <input
                className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
                required={!isFileUploadType(type)}
              />
            </label>
            <label className="block text-sm text-text">
              Tipo
              <select
                className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                value={type}
                onChange={(e) => setType(e.target.value as SourceType)}
              >
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {sourceTypeLabel(t)}
                  </option>
                ))}
              </select>
            </label>
            {isFileUploadType(type) && (
              <label className="block text-sm text-text">
                {COPY.uploadFile}
                <input
                  className="mt-1 w-full min-h-11 text-sm text-text"
                  type="file"
                  data-testid="source-file"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
            )}
            {type === "gdrive" && (
              <label className="block text-sm text-text">
                ID de carpeta de Google Drive
                <input
                  className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                  value={folderId}
                  onChange={(e) => setFolderId(e.target.value)}
                  autoComplete="off"
                  placeholder="1abc… (ID de la carpeta, no la URL)"
                />
              </label>
            )}
            <p className="text-[13px] leading-relaxed text-muted">
              {type === "gdrive"
                ? "Se abre Google para autorizar solo lectura. El refresh token vive en el almacén de secretos, nunca en la fuente."
                : isFileUploadType(type)
                  ? COPY.collectionHint
                  : "Las credenciales de conectores viven en Vault, no en esta ficha."}
            </p>
            <button
              className="btn btn-primary min-h-11 w-full sm:w-auto"
              type="submit"
              disabled={
                creating ||
                (isFileUploadType(type) ? !file : type === "gdrive" ? !name.trim() : !name.trim())
              }
            >
              {creating ? <Spinner size={14} /> : <Plus size={15} aria-hidden />}
              {type === "gdrive" ? "Conectar Google Drive" : "Crear fuente"}
            </button>
          </form>
        </div>
      )}

      <div className="panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text">Fuentes de conocimiento</h2>
          <span className="mono text-[11px] text-faint">{sources.length}</span>
        </div>
        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={5} />
          </div>
        ) : sources.length === 0 ? (
          <EmptyState
            icon={Database}
            title="Todavía no hay fuentes"
            body="Crea una fuente (incluido Google Drive) o sube archivos para alimentar tus colecciones."
            action={
              <button
                type="button"
                className="btn btn-secondary min-h-11"
                onClick={() => setShowCreate(true)}
              >
                <Plus size={14} aria-hidden /> Nueva fuente
              </button>
            }
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {sources.map((s) => {
              const canProfile = s.type === "sql" || Boolean(s.config?.managed);
              return (
              <article key={s.id} className="panel p-4" data-testid={`source-card-${s.id}`}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <Link to={`/knowledge/sources/${s.id}`} className="font-medium text-text hover:underline">
                      {s.name}
                    </Link>
                    <p className="text-xs text-muted">{sourceTypeLabel(s.type, s.config?.managed)}</p>
                  </div>
                  <span className={`badge ${sourceStatusBadgeClass(s.status)}`}>
                    {sourceStatusLabel(s.status)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-muted">{sourceTypeBlurb(s.type, s.config?.managed)}</p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted">
                  <div>
                    {COPY.lastSync}: {s.last_sync ? fmtDateTime(s.last_sync) : "—"}
                  </div>
                  <div>
                    {COPY.documents}: {fmtNum(s.document_count || s.last_processed_count || 0)}
                  </div>
                  {s.error_count > 0 ? (
                    <div className="col-span-2 text-danger">
                      {COPY.issues}: {fmtNum(s.error_count)}
                    </div>
                  ) : null}
                </dl>
                {s.last_error ? <p className="mt-2 text-xs text-danger">{s.last_error}</p> : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link to={`/knowledge/sources/${s.id}`} className="btn btn-secondary min-h-11 px-3 text-xs">
                    {COPY.open}
                  </Link>
                  {canProfile ? (
                    <button
                      type="button"
                      className="btn btn-ghost min-h-11 px-3 text-xs"
                      aria-label={`Perfilizar ${s.name}`}
                      onClick={() => void profileSource(s.id)}
                    >
                      Perfilizar
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-3 text-xs"
                    aria-label={`Sincronizar ${s.name}`}
                    disabled={syncingId === s.id}
                    onClick={() => void syncSource(s.id)}
                  >
                    {syncingId === s.id ? <Spinner size={14} /> : <ArrowsClockwise size={14} aria-hidden />}
                    {COPY.sync}
                  </button>
                  {kbs.length > 0 ? (
                    <label className="flex min-h-11 items-center gap-1 text-xs text-muted">
                      {COPY.collection}
                      <select
                        className="min-h-9 rounded-md border border-border bg-soft px-2 text-xs text-text"
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
                      </select>
                    </label>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-3 text-xs text-danger"
                    aria-label={`Eliminar ${s.name}`}
                    data-testid={`source-delete-${s.id}`}
                    onClick={() => setPendingDelete(s)}
                  >
                    <Trash size={14} aria-hidden />
                    {COPY.deleteSource}
                  </button>
                </div>
              </article>
              );
            })}
          </div>
        )}
      </div>

      {profile && (
        <div className="panel mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">Perfil de datos</h3>
            <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => setProfile(null)}>
              Cerrar
            </button>
          </div>
          {profile.tables.map((table) => (
            <div key={table.name} className="mb-4 overflow-x-auto">
              <p className="mb-1 font-mono text-xs text-muted">{table.name}</p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Columna</th>
                    <th>Tipo</th>
                    <th>Null %</th>
                    <th>Cardinalidad</th>
                    <th>PK/FK</th>
                    <th>PII</th>
                  </tr>
                </thead>
                <tbody>
                  {table.columns.map((col) => (
                    <tr key={col.name}>
                      <td className="font-mono text-xs text-text">{col.name}</td>
                      <td className="text-xs text-muted">{col.data_type}</td>
                      <td className="text-xs text-muted">{col.null_rate ?? "—"}</td>
                      <td className="text-xs text-muted">{col.cardinality ?? "—"}</td>
                      <td className="text-xs text-muted">
                        {col.is_pk ? "PK" : col.is_fk ? "FK" : ""}
                      </td>
                      <td className="text-xs">
                        {col.pii_flags.length > 0 ? (
                          <span className="badge badge-danger">{col.pii_flags.join(", ")}</span>
                        ) : col.sensitive ? (
                          <span className="badge badge-pending">sensible</span>
                        ) : (
                          <span className="text-faint">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
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
