import {
  ArrowClockwise,
  BookOpenText,
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
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageTabs } from "../components/PageTabs";
import {
  Badge,
  Button,
  Checkbox,
  CodeBlock,
  CopyButton,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  StatusBadge,
  SuccessInline,
  Toolbar,
  type Column,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";
import WebhooksPage from "./Webhooks";

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

const LIMITS: Record<"live" | "test", string> = {
  live: "100/min · 10k/día",
  test: "30/min · 1k/día",
};

const DOCS_EXAMPLE = `curl -X POST https://api.zent.example/api/v1/rag/query \\
  -H "Authorization: Bearer zent_sk_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"query": "¿Cuánto stock queda del producto ABC?"}'`;

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

type PendingAction = { kind: "rotate" | "revoke"; id: string; name: string };

function keyEnvironment(key: ApiKeyInfo): "live" | "test" {
  if (key.environment === "test" || key.prefix.startsWith("zent_sk_test")) {
    return "test";
  }
  return "live";
}

export default function KeysPage() {
  const { session } = useAuth();
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
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["rag:read", "rag:write"]);
  const [environment, setEnvironment] = useState<"live" | "test">("live");
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

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

  async function refreshKeys() {
    if (!session) return;
    const refreshed = await api<{ keys: ApiKeyInfo[] }>("/api/v1/organizations/api-keys", {
      token: session.token,
      organizationId: session.organizationId,
    });
    setKeys(refreshed.keys);
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
      await refreshKeys();
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
    setActionBusy(true);
    try {
      await api(`/api/v1/organizations/api-keys/${keyId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Clave "${name}" revocada.`);
      await refreshKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al revocar");
    } finally {
      setActionBusy(false);
      setPendingAction(null);
    }
  }

  async function rotateKey(keyId: string, name: string) {
    if (!session) return;
    setError("");
    setMsg("");
    setActionBusy(true);
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
      await refreshKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al rotar");
    } finally {
      setActionBusy(false);
      setPendingAction(null);
    }
  }

  const activeCount = keys.filter((k) => k.is_active).length;
  const revokedCount = keys.length - activeCount;

  const columns: Column<ApiKeyInfo>[] = [
    {
      key: "name",
      header: "Nombre",
      render: (key) => (
        <span className="block min-w-0">
          <span className="block truncate text-[13px] font-medium text-text">{key.name}</span>
          <span className="block text-xs text-faint">Creada {fmtDateTime(key.created_at)}</span>
        </span>
      ),
    },
    {
      key: "environment",
      header: "Entorno",
      width: "1%",
      render: (key) => (
        <Badge tone="neutral">{keyEnvironment(key) === "live" ? "Production" : "Development"}</Badge>
      ),
    },
    {
      key: "prefix",
      header: "Prefijo",
      render: (key) => (
        <span className="flex items-center gap-1">
          <span className="mono text-xs text-muted">{key.prefix}</span>
          <CopyButton value={key.prefix} label={`Copiar prefijo de ${key.name}`} copiedLabel="Prefijo copiado" />
        </span>
      ),
    },
    {
      key: "scopes",
      header: "Scopes",
      hideBelow: "lg",
      render: (key) => (
        <span className="flex flex-wrap gap-1">
          {key.scopes.map((scope) => (
            <span key={scope} className="chip mono text-[11px]">
              {scope}
            </span>
          ))}
          {key.scopes.length === 0 && <span className="text-xs text-faint">Sin scopes</span>}
        </span>
      ),
    },
    {
      key: "limits",
      header: "Límites",
      hideBelow: "md",
      render: (key) => <span className="mono text-xs text-faint">{LIMITS[keyEnvironment(key)]}</span>,
    },
    {
      key: "last_used",
      header: "Último uso",
      render: (key) =>
        key.last_used_at ? (
          <span className="text-xs text-muted">{fmtDateTime(key.last_used_at)}</span>
        ) : (
          <span className="text-xs text-faint">Sin uso todavía</span>
        ),
    },
    {
      key: "status",
      header: "Estado",
      width: "1%",
      render: (key) => <StatusBadge status={key.is_active ? "active" : "revoked"} />,
    },
  ];

  const docsTab = (
    <Panel className="mt-4">
      <PanelHeader
        title="Documentación de API"
        description="Referencia interactiva y ejemplos de código para integrar Zent en tus aplicaciones."
      />
      <div className="panel-body flex flex-col gap-3">
        <CodeBlock code={DOCS_EXAMPLE} language="bash" filename="request.sh" maxHeight={220} />
        <div className="flex flex-wrap gap-2">
          <a href="/docs" target="_blank" rel="noreferrer" className="btn btn-secondary">
            Swagger UI
          </a>
          <Link to="/developers" className="btn btn-secondary">
            Centro de desarrolladores
          </Link>
          <a href="/redoc" target="_blank" rel="noreferrer" className="btn btn-ghost">
            Redoc
          </a>
        </div>
      </div>
    </Panel>
  );

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

      {tab === "webhooks" && <WebhooksPage embedded />}

      {tab === "docs" && docsTab}

      {tab === "keys" && (
        <>
          {newToken && (
            <Panel className="mb-4 border-accent/30">
              <PanelHeader
                title="Nueva clave"
                description="Esta es la única vez que se muestra completa."
                actions={
                  <>
                    <Badge tone="warn">Cópiala ahora</Badge>
                    <CopyButton value={newToken} label="Copiar clave" copiedLabel="Clave copiada" variant="secondary" />
                  </>
                }
              />
              <div className="panel-body flex flex-col gap-2 sm:flex-row sm:items-center">
                <Input
                  className="font-mono"
                  readOnly
                  aria-label="Nueva clave"
                  value={revealed ? newToken : "•".repeat(48)}
                />
                <div className="flex shrink-0 gap-2">
                  <IconButton
                    label={revealed ? "Ocultar clave" : "Mostrar clave"}
                    icon={revealed ? EyeSlash : Eye}
                    variant="secondary"
                    aria-pressed={revealed}
                    onClick={() => setRevealed((r) => !r)}
                  />
                  <Button variant="ghost" onClick={() => setNewToken("")}>
                    Ocultar del todo
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          <Toolbar className="mb-3">
            <p className="text-xs text-muted tabular-nums">
              {keys.length === 1 ? "1 clave" : `${keys.length} claves`} · {activeCount} activas ·{" "}
              {revokedCount} revocadas
            </p>
            <span className="flex-1" aria-hidden />
            <span className="text-xs text-faint">
              Production y Development comparten los mismos datos; test tiene cuota más baja.
            </span>
            <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
              Nueva clave
            </Button>
          </Toolbar>

          <DataTable
            columns={columns}
            rows={keys}
            rowKey={(key) => key.id}
            loading={loading}
            caption="API keys de la organización"
            empty={
              <EmptyState
                icon={KeyIcon}
                title="No hay claves"
                body="Crea una clave de Production o Development para integrar tus sistemas."
                action={
                  <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
                    Añadir la primera clave
                  </Button>
                }
              />
            }
            footer={
              keys.length > 0 ? (
                <p className="flex items-center gap-1.5 text-xs text-faint">
                  <ShieldCheck size={13} aria-hidden />
                  Las claves inactivas quedan visibles para auditoría; no vuelven a emitirse.
                </p>
              ) : undefined
            }
            rowActions={(key) =>
              key.is_active ? (
                <>
                  <IconButton
                    label={`Rotar ${key.name}`}
                    icon={ArrowClockwise}
                    title="Rotar: revoca y emite una nueva"
                    onClick={() => setPendingAction({ kind: "rotate", id: key.id, name: key.name })}
                  />
                  <IconButton
                    label={`Revocar ${key.name}`}
                    icon={Trash}
                    onClick={() => setPendingAction({ kind: "revoke", id: key.id, name: key.name })}
                  />
                </>
              ) : null
            }
          />
        </>
      )}

      <Modal
        open={showCreate}
        onOpenChange={setShowCreate}
        title="Crear API key"
        description="Elige el entorno y los scopes mínimos que necesita tu integración."
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={creating}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={creating}
              leadingIcon={Plus}
              disabled={selectedScopes.length === 0}
              onClick={() => void createKey()}
            >
              Crear
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Field label="Nombre" hint="Te ayuda a identificar la integración que usa la clave.">
            <Input
              placeholder="Nombre (ej. backend-prod)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              autoComplete="off"
            />
          </Field>

          <Field label="Entorno" hint="Live: 100 req/min y 10.000/día. Test: 30 req/min y 1.000/día.">
            <Select value={environment} onChange={(e) => setEnvironment(e.target.value as "live" | "test")}>
              <option value="live">Production (zent_sk_live_)</option>
              <option value="test">Development (zent_sk_test_)</option>
            </Select>
          </Field>

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="eyebrow">Scopes ({selectedScopes.length})</p>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedScopes(SCOPE_OPTIONS.map((s) => s.id))}
                >
                  Seleccionar todos
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setSelectedScopes([])}>
                  Limpiar
                </Button>
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border border-border p-2">
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {SCOPE_OPTIONS.map((scope) => (
                  <Checkbox
                    key={scope.id}
                    checked={selectedScopes.includes(scope.id)}
                    onCheckedChange={(checked) =>
                      setSelectedScopes((current) =>
                        checked ? [...current, scope.id] : current.filter((s) => s !== scope.id)
                      )
                    }
                    className="rounded-sm p-2 hover:bg-soft"
                    label={
                      <span>
                        <span className="mono text-xs font-medium text-text">{scope.id}</span>
                        <span className="block text-xs text-muted">{scope.hint}</span>
                      </span>
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={pendingAction?.kind === "revoke"}
        title="Revocar API key"
        body={
          <p>
            La clave <strong className="text-text">{pendingAction?.name}</strong> dejará de funcionar
            de inmediato. Los clientes que la usan recibirán 401.
          </p>
        }
        confirmLabel="Revocar"
        confirmText="REVOKE"
        busy={actionBusy}
        onConfirm={() => {
          if (pendingAction) void revokeKey(pendingAction.id, pendingAction.name);
        }}
        onCancel={() => setPendingAction(null)}
      />

      <ConfirmDialog
        open={pendingAction?.kind === "rotate"}
        title="Rotar API key"
        body={
          <p>
            Se revoca <strong className="text-text">{pendingAction?.name}</strong> y se emite una clave
            nueva que se muestra una sola vez. Actualiza tus clientes después de rotar.
          </p>
        }
        confirmLabel="Rotar"
        confirmText="ROTATE"
        busy={actionBusy}
        onConfirm={() => {
          if (pendingAction) void rotateKey(pendingAction.id, pendingAction.name);
        }}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}
