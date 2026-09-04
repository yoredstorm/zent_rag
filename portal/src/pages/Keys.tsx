import {
  ArrowClockwise,
  BookOpenText,
  Copy,
  Eye,
  EyeSlash,
  Key as KeyIcon,
  Plus,
  ShieldCheck,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import { PageTabs } from "../components/PageTabs";
import WebhooksPage from "./Webhooks";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

const SCOPE_OPTIONS: { id: string; hint: string }[] = [
  { id: "rag:read", hint: "Chat y consultas RAG" },
  { id: "rag:write", hint: "Ingestión, fuentes y knowledge bases" },
  { id: "knowledge:read", hint: "Listar fuentes y knowledge bases" },
  { id: "agents:read", hint: "Listar agentes" },
  { id: "agents:execute", hint: "Ejecutar agentes" },
  { id: "connectors:read", hint: "Listar conectores" },
  { id: "connectors:write", hint: "Crear y editar conectores" },
  { id: "usage:read", hint: "Métricas de uso" },
  { id: "analytics:read", hint: "Alias de usage:read" },
];

type ApiKeyInfo = {
  id: string;
  name: string;
  prefix: string;
  environment?: "live" | "test";
  scopes: string[];
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
};

function keyEnvironment(key: ApiKeyInfo): "live" | "test" {
  if (key.environment === "test" || key.prefix.startsWith("zent_sk_test")) {
    return "test";
  }
  return "live";
}

export default function KeysPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [tab, setTab] = useState<"keys" | "webhooks" | "docs">("keys");
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newToken, setNewToken] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [selectedScopes, setSelectedScopes] = useState<string[]>([
    "rag:read",
    "rag:write",
  ]);
  const [environment, setEnvironment] = useState<"live" | "test">("live");

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
          scopes: selectedScopes,
          environment,
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

  async function rotateKey(keyId: string, name: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      const data = await api<{ token: string }>(
        `/api/v1/organizations/api-keys/${keyId}/rotate`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: "{}",
        }
      );
      setNewToken(data.token);
      setRevealed(true);
      setMsg(`Clave "${name}" rotada. La anterior quedó revocada.`);
      const refreshed = await api<{ keys: ApiKeyInfo[] }>(
        "/api/v1/organizations/api-keys",
        { token: session.token, organizationId: session.organizationId }
      );
      setKeys(refreshed.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al rotar");
    }
  }

  return (
    <div>
      <PageHeader
        title="API y Claves"
        subtitle="Administra las credenciales para acceder a Zent programáticamente desde tus sistemas."
      />
      <PageTabs
        tabs={[
          { id: "keys", label: "API Keys", icon: KeyIcon },
          { id: "webhooks", label: "Webhooks" },
          { id: "docs", label: "Documentación", icon: BookOpenText },
        ]}
        active={tab}
        onChange={(id) => setTab(id as "keys" | "webhooks" | "docs")}
        idPrefix="api"
      />
      <div className="mt-4">
        <ErrorInline message={error} />
        <SuccessInline message={msg} />
      </div>

      {tab === "webhooks" && <WebhooksPage />}

      {tab === "docs" && (
        <div className="panel mt-4">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Documentación de API</h2>
          </div>
          <div className="flex flex-col gap-2 p-5">
            <p className="text-[13px] leading-relaxed text-muted">
              Referencia interactiva y ejemplos de código para integrar Zent en tus aplicaciones.
            </p>
            <pre className="overflow-x-auto rounded-md bg-soft p-3 font-mono text-xs leading-relaxed text-text">
{`curl -X POST https://api.zent.example/api/v1/rag/query \\
  -H "Authorization: Bearer zent_sk_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"query": "¿Cuánto stock queda del producto ABC?"}'`}
            </pre>
            <div className="flex flex-wrap gap-2">
              <a
                href="/docs"
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary"
              >
                Swagger UI
              </a>
              <Link to="/developers" className="btn btn-secondary">
                Centro de desarrolladores
              </Link>
              <a
                href="/redoc"
                target="_blank"
                rel="noreferrer"
                className="btn btn-ghost"
              >
                Redoc
              </a>
            </div>
          </div>
        </div>
      )}

      {tab === "keys" && (
      <>
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
          <div className="flex flex-col gap-3 p-5">
            <label className="block text-sm text-text">
              Nombre
              <input
                className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                placeholder="Nombre (ej. backend-prod)"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                autoComplete="off"
              />
            </label>
            <fieldset>
              <legend className="mb-2 text-xs font-medium text-muted">Entorno</legend>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
                  <input
                    type="radio"
                    name="key-environment"
                    checked={environment === "live"}
                    onChange={() => setEnvironment("live")}
                  />
                  Production (zent_sk_live_)
                </label>
                <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
                  <input
                    type="radio"
                    name="key-environment"
                    checked={environment === "test"}
                    onChange={() => setEnvironment("test")}
                  />
                  Development (zent_sk_test_)
                </label>
              </div>
              <p className="mt-2 text-[13px] text-muted">
                Live: 100 req/min y 10.000/día. Test: 30 req/min y 1.000/día. Misma organización.
              </p>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-xs font-medium text-muted">Scopes</legend>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {SCOPE_OPTIONS.map((scope) => {
                  const checked = selectedScopes.includes(scope.id);
                  return (
                    <label
                      key={scope.id}
                      className="flex min-h-11 cursor-pointer items-start gap-2 rounded-md border border-border px-3 py-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checked}
                        onChange={() => {
                          setSelectedScopes((current) =>
                            checked
                              ? current.filter((s) => s !== scope.id)
                              : [...current, scope.id]
                          );
                        }}
                      />
                      <span>
                        <span className="mono font-medium text-text">{scope.id}</span>
                        <span className="block text-xs text-muted">{scope.hint}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <button
              className="btn btn-primary shrink-0 self-start"
              type="button"
              disabled={creating || selectedScopes.length === 0}
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
          <span className="text-[11px] text-faint">
            Production y Development comparten los mismos datos; test tiene cuota más baja.
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
            body="Crea una clave de Production o Development para integrar tus sistemas."
          />
        ) : (
          <div className="flex flex-col gap-6 p-5">
            {(["live", "test"] as const).map((env) => {
              const rows = keys.filter((k) => keyEnvironment(k) === env);
              return (
                <section key={env}>
                  <h3 className="mb-2 text-sm font-semibold text-text">
                    {env === "live" ? "Production" : "Development"}
                    <span className="ml-2 font-normal text-muted">
                      {env === "live"
                        ? "zent_sk_live_ · 100/min · 10k/día"
                        : "zent_sk_test_ · 30/min · 1k/día"}
                    </span>
                  </h3>
                  {rows.length === 0 ? (
                    <p className="text-sm text-muted">
                      No hay claves de {env === "live" ? "Production" : "Development"}.
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="table min-w-[640px]">
                        <thead>
                          <tr>
                            <th>Nombre</th>
                            <th>Prefijo</th>
                            <th>Scopes</th>
                            <th>Límites</th>
                            <th>Último uso</th>
                            <th>Estado</th>
                            <th className="text-right">Acciones</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((key) => (
                            <tr key={key.id}>
                              <td className="font-medium text-text">{key.name}</td>
                              <td className="mono">{key.prefix}</td>
                              <td className="mono text-xs">{key.scopes.join(", ")}</td>
                              <td className="text-xs text-muted">
                                {env === "live" ? "100/min · 10k/día" : "30/min · 1k/día"}
                              </td>
                              <td>
                                {key.last_used_at ? fmtDateTime(key.last_used_at) : "—"}
                              </td>
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
                                  <div className="flex justify-end gap-1">
                                    <button
                                      type="button"
                                      className="btn btn-ghost min-h-11 px-2 py-1.5 text-xs"
                                      onClick={() => void rotateKey(key.id, key.name)}
                                      aria-label={`Rotar ${key.name}`}
                                      title="Rotar: revoca y emite una nueva"
                                    >
                                      <ArrowClockwise size={14} aria-hidden />
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-ghost min-h-11 px-2 py-1.5 text-xs"
                                      onClick={() => void revokeKey(key.id, key.name)}
                                      aria-label={`Revocar ${key.name}`}
                                    >
                                      <Trash size={14} aria-hidden />
                                    </button>
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
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
      </>
      )}
    </div>
  );
}
