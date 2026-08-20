import {
  CloudArrowDown,
  File,
  Link,
  Plus,
  Trash,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Connector = {
  id: string;
  name: string;
  type: "sql" | "api" | "files";
  config: Record<string, unknown>;
  status: string;
  created_at: string;
};

const TYPE_ICONS: Record<Connector["type"], Icon> = {
  sql: CloudArrowDown,
  api: Link,
  files: File,
};

const TYPES: Connector["type"][] = ["sql", "api", "files"];

export default function ConnectorsPage() {
  const { session } = useAuth();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState<Connector["type"]>("sql");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    api<{ connectors: Connector[] }>("/api/v1/connectors", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setConnectors(data.connectors))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

  async function create() {
    if (!session) return;
    setError("");
    setMsg("");
    setCreating(true);
    try {
      await api("/api/v1/connectors", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), type, config: {} }),
      });
      setMsg("Conector creado. Configura sus credenciales en Vault.");
      setName("");
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  async function remove(connectorId: string, connectorName: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/connectors/${connectorId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Conector "${connectorName}" eliminado.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Conectores"
        subtitle="Fuentes de datos registradas (sql / api / files). Las credenciales viven en Vault, nunca en la base de datos."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="mb-4 flex justify-end">
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => setShowCreate((s) => !s)}
        >
          <Plus size={15} aria-hidden />
          Nuevo conector
        </button>
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Crear conector</h2>
          </div>
          <div className="flex flex-col gap-3 p-5">
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              placeholder="Nombre"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <select
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              value={type}
              onChange={(e) => setType(e.target.value as Connector["type"])}
              aria-label="Tipo de conector"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <div>
              <button
                className="btn btn-primary"
                type="button"
                disabled={creating || !name.trim()}
                onClick={() => void create()}
              >
                {creating ? <Spinner size={14} /> : <Plus size={15} aria-hidden />}
                Crear
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="panel p-5">
          <SkeletonBlock rows={4} />
        </div>
      ) : connectors.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={Link}
            title="Sin conectores"
            body="Registra tus fuentes de datos para sincronizarlas con RAG."
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {connectors.map((c) => {
            const IconEl = TYPE_ICONS[c.type] ?? Link;
            return (
              <div key={c.id} className="panel p-5">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h3 className="flex items-center gap-2 font-semibold text-text">
                    <IconEl size={16} className="text-accent" aria-hidden />
                    {c.name}
                  </h3>
                  <button
                    type="button"
                    className="btn btn-ghost px-2 py-1.5 text-xs text-danger"
                    aria-label={`Eliminar ${c.name}`}
                    onClick={() => void remove(c.id, c.name)}
                  >
                    <Trash size={14} aria-hidden />
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
                  <span className="badge badge-ok">{c.type}</span>
                  <span className={`badge ${c.status === "active" ? "badge-ok" : "badge-muted"}`}>
                    {c.status}
                  </span>
                  <span>Creado {fmtDateTime(c.created_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
