import {
  ArrowsClockwise,
  Database,
  Files,
  FolderSimple,
  List,
  MagnifyingGlass,
  Plus,
  type Icon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
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
import { fmtDateTime, fmtNum } from "../../lib/format";

const KNOWLEDGE_TABS: { to: string; label: string; icon: Icon }[] = [
  { to: "/knowledge/sources", label: "Fuentes", icon: Database },
  { to: "/knowledge/collections", label: "Colecciones", icon: FolderSimple },
  { to: "/knowledge/documents", label: "Documentos", icon: Files },
  { to: "/knowledge/sql", label: "SQL", icon: Database },
  { to: "/knowledge/jobs", label: "Sincronización", icon: List },
  { to: "/knowledge/playground", label: "Búsqueda", icon: MagnifyingGlass },
];

function KnowledgeTabs() {
  return (
    <nav className="tabs" aria-label="Secciones de conocimiento">
      {KNOWLEDGE_TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.to === "/knowledge/sources"}
          className={({ isActive }) =>
            `tab ${isActive ? "" : "opacity-70 hover:opacity-100"}`
          }
        >
          <tab.icon size={15} aria-hidden />
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

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
    <div>
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
      <KnowledgeTabs />
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
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Tipo</th>
                  <th>Estado</th>
                  <th>Último sync</th>
                  <th className="text-right">Filas / chunks</th>
                  <th className="text-right">Errores</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id}>
                    <td className="font-medium text-text">{s.name}</td>
                    <td className="mono text-xs">
                      {s.type === "gdrive" ? "Google Drive" : s.type}
                    </td>
                    <td>
                      <span
                        className={`badge ${s.status === "error" ? "badge-danger" : s.status === "ready" || s.status === "indexed" ? "badge-ok" : s.status === "ingesting" || s.status === "discovering" ? "badge-pending" : "badge-muted"}`}
                      >
                        {s.status || "—"}
                      </span>
                    </td>
                    <td className="text-muted">
                      {s.last_sync ? fmtDateTime(s.last_sync) : "—"}
                      {s.last_error ? (
                        <p className="mt-1 max-w-xs text-xs text-danger">{s.last_error}</p>
                      ) : null}
                    </td>
                    <td className="mono text-right">
                      {fmtNum(s.document_count || s.last_processed_count || 0)}
                    </td>
                    <td className="mono text-right">
                      {s.error_count > 0 ? (
                        <span className="text-danger">{fmtNum(s.error_count)}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost min-h-11 px-3 text-xs"
                        aria-label={`Perfilizar ${s.name}`} onClick={() => void profileSource(s.id)}
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
                        {syncingId === s.id ? (
                          <Spinner size={14} />
                        ) : (
                          <ArrowsClockwise size={14} aria-hidden />
                        )}
                        Sync
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
    </div>
  );
}
