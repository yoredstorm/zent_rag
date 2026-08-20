import {
  Copy,
  Eye,
  EyeSlash,
  Key as KeyIcon,
  Plus,
  ShieldCheck,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type ApiKeyInfo = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
};

export default function KeysPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newToken, setNewToken] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<{ keys: ApiKeyInfo[] }>("/api/v1/organizations/api-keys", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setKeys(data.keys))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      pushToast("success", `${label} copiada`, "Ya está en tu portapapeles.");
    } catch {
      pushToast("error", "No se pudo copiar", "Copia el texto manualmente.");
    }
  }

  async function createKey() {
    if (!session) return;
    setError("");
    setMsg("");
    setCreating(true);
    try {
      const data = await api<{ token: string }>("/api/v1/organizations/api-keys", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: newKeyName.trim() || "Default",
          scopes: ["rag:query", "rag:ingest"],
        }),
      });
      setNewToken(data.token);
      setRevealed(true);
      setMsg("Clave creada. Guárdala ahora — no se vuelve a mostrar.");
      setShowCreate(false);
      setNewKeyName("");
      const refreshed = await api<{ keys: ApiKeyInfo[] }>(
        "/api/v1/organizations/api-keys",
        { token: session.token, organizationId: session.organizationId }
      );
      setKeys(refreshed.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  async function revokeKey(keyId: string, name: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/organizations/api-keys/${keyId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Clave "${name}" revocada.`);
      const refreshed = await api<{ keys: ApiKeyInfo[] }>(
        "/api/v1/organizations/api-keys",
        { token: session.token, organizationId: session.organizationId }
      );
      setKeys(refreshed.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al revocar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Claves de integración"
        subtitle="API keys de tu organización. Cada una tiene scopes propios y puede revocarse sin afectar a las demás."
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
          Nueva clave
        </button>
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Crear API key</h2>
          </div>
          <div className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              placeholder="Nombre (ej. backend-prod)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
            />
            <button
              className="btn btn-primary shrink-0"
              type="button"
              disabled={creating}
              onClick={() => void createKey()}
            >
              {creating ? <Spinner size={14} /> : <Plus size={15} aria-hidden />}
              Crear
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
            <KeyIcon size={16} className="text-accent" aria-hidden />
            Claves ({keys.length})
          </h2>
          <span className="mono text-xs text-faint">
            {session?.organizationId}
          </span>
        </div>

        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={4} />
          </div>
        ) : keys.length === 0 ? (
          <EmptyState
            icon={KeyIcon}
            title="No hay claves"
            body="Crea una clave para integrar tus sistemas externos."
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Prefijo</th>
                <th>Scopes</th>
                <th>Último uso</th>
                <th>Estado</th>
                <th className="text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id}>
                  <td className="font-medium text-text">{key.name}</td>
                  <td className="mono">{key.prefix}</td>
                  <td className="mono text-xs">{key.scopes.join(", ")}</td>
                  <td>{key.last_used_at ? fmtDateTime(key.last_used_at) : "—"}</td>
                  <td>
                    {key.is_active ? (
                      <span className="badge badge-ok">
                        <ShieldCheck size={13} aria-hidden /> Activa
                      </span>
                    ) : (
                      <span className="badge badge-muted">Revocada</span>
                    )}
                  </td>
                  <td className="text-right">
                    {key.is_active && (
                      <button
                        type="button"
                        className="btn btn-ghost px-2 py-1.5 text-xs"
                        onClick={() => void revokeKey(key.id, key.name)}
                        aria-label={`Revocar ${key.name}`}
                      >
                        <Trash size={14} aria-hidden />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {newToken && (
        <div className="panel mt-4 border-accent/30">
          <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Nueva clave</h2>
            <span className="badge badge-pending">Cópiala ahora</span>
          </div>
          <div className="flex flex-col gap-2 p-5 sm:flex-row sm:items-center">
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 font-mono text-sm text-text outline-none focus:border-accent"
              readOnly
              value={revealed ? newToken : "•".repeat(48)}
              aria-label="Nueva clave"
            />
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                aria-label={revealed ? "Ocultar clave" : "Mostrar clave"}
                onClick={() => setRevealed((r) => !r)}
              >
                {revealed ? <EyeSlash size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void copy(newToken, "Clave")}
              >
                <Copy size={15} aria-hidden />
                Copiar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
