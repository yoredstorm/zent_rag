import { ArrowsClockwise, Database, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { fmtDateTime, fmtNum } from "../../lib/format";

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
  config?: { managed?: boolean };
};

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

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<{ sources: SourceRow[] }>("/api/v1/sources", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setSources(data.sources || []))
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
    setCreating(true);
    try {
      await api("/api/v1/sources", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), type, config: {} }),
      });
      setMsg("Fuente creada.");
      setName("");
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
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
        title="Conocimiento"
        subtitle="Administra la información que tu IA puede usar para responder: fuentes, colecciones, documentos y sincronización."
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
                required
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
                    {t === "gdrive" ? "Google Drive" : t}
                  </option>
                ))}
              </select>
            </label>
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
                : "Las credenciales de conectores viven en Vault, no en esta ficha."}
            </p>
            <button
              className="btn btn-primary min-h-11 w-full sm:w-auto"
              type="submit"
              disabled={creating || !name.trim()}
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
            {sources.map((s) => (
              <article key={s.id} className="panel p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <Link to={`/knowledge/sources/${s.id}`} className="font-medium text-text hover:underline">
                      {s.name}
                    </Link>
                    <p className="text-xs text-muted">
                      {s.config?.managed ? "Managed Database" : s.type === "gdrive" ? "Google Drive" : s.type}
                    </p>
                  </div>
                  <span
                    className={`badge ${s.status === "error" ? "badge-danger" : s.status === "ready" || s.status === "indexed" ? "badge-ok" : s.status === "ingesting" || s.status === "discovering" ? "badge-pending" : "badge-muted"}`}
                  >
                    {s.status || "—"}
                  </span>
                </div>
                <p className="mt-2 text-sm text-muted">
                  {s.config?.managed || s.type === "sql"
                    ? "Entities, fields, relationships and metrics."
                    : s.type === "file"
                      ? "Topics, sections, entities and policies."
                      : s.type === "csv" || s.type === "excel"
                        ? "Dataset fields, measures and dimensions."
                        : s.type === "web"
                          ? "Pages, topics and products or services."
                          : "Open the source to see what Zent understood."}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted">
                  <div>Last sync: {s.last_sync ? fmtDateTime(s.last_sync) : "—"}</div>
                  <div>Usage: {fmtNum(s.document_count || s.last_processed_count || 0)}</div>
                  <div>Readiness: {s.status === "ready" || s.status === "indexed" ? "Ready" : "In progress"}</div>
                  <div>Issues: {s.error_count > 0 ? fmtNum(s.error_count) : "none"}</div>
                </dl>
                {s.last_error ? <p className="mt-2 text-xs text-danger">{s.last_error}</p> : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link to={`/knowledge/sources/${s.id}`} className="btn btn-secondary min-h-11 px-3 text-xs">
                    Open
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-3 text-xs"
                    aria-label={`Perfilizar ${s.name}`}
                    onClick={() => void profileSource(s.id)}
                  >
                    Perfilizar
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-3 text-xs"
                    aria-label={`Sincronizar ${s.name}`}
                    disabled={syncingId === s.id}
                    onClick={() => void syncSource(s.id)}
                  >
                    {syncingId === s.id ? <Spinner size={14} /> : <ArrowsClockwise size={14} aria-hidden />}
                    Sync
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {profile && (
        <div className="panel mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">Data Profile</h3>
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
                          <span className="badge badge-pending">sensitive</span>
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
    </KnowledgeLayout>
  );
}
