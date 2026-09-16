import {
  CloudArrowDown,
  File,
  Link,
  MagnifyingGlass,
  Plus,
  Trash,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button,
  CodeBlock,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  KeyValue,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Toolbar,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Connector = {
  id: string;
  name: string;
  type: string;
  config: Record<string, unknown>;
  status: string;
  created_at: string;
};

type ConnectorDetail = Connector & { project_id?: string | null; has_secrets?: boolean };

const TYPE_ICONS: Record<string, Icon> = {
  sql: CloudArrowDown,
  api: Link,
  files: File,
  gdrive: CloudArrowDown,
};

const TYPES = ["sql", "api", "files", "gdrive"] as const;

function typeLabel(type: string): string {
  return type === "gdrive" ? "Google Drive" : type;
}

export default function ConnectorsPage() {
  const { session } = useAuth();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState<(typeof TYPES)[number]>("sql");
  const [folderId, setFolderId] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Connector | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [detail, setDetail] = useState<ConnectorDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

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
      if (type === "gdrive") {
        if (!folderId.trim()) {
          setError("Indica el ID de la carpeta de Google Drive.");
          setCreating(false);
          return;
        }
        const started = await api<{ authorization_url: string }>(
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
        return;
      }
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

  async function openDetail(connector: Connector) {
    setDetail(connector);
    setDetailError("");
    if (!session) return;
    setDetailLoading(true);
    try {
      const full = await api<ConnectorDetail>(`/api/v1/connectors/${connector.id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setDetail(full);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Error");
    } finally {
      setDetailLoading(false);
    }
  }

  async function remove(connectorId: string) {
    if (!session) return;
    setError("");
    setMsg("");
    setDeleting(true);
    try {
      await api(`/api/v1/connectors/${connectorId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Conector eliminado.");
      setPendingDelete(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setDeleting(false);
    }
  }

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return connectors.filter((c) => {
      if (typeFilter && c.type !== typeFilter) return false;
      if (!term) return true;
      return c.name.toLowerCase().includes(term) || c.type.toLowerCase().includes(term);
    });
  }, [connectors, search, typeFilter]);

  return (
    <div>
      <PageHeader
        title="Conectores"
        subtitle="Fuentes de datos (sql / api / files / Google Drive). Las credenciales viven en Vault, nunca en la base de datos."
        actions={
          <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
            Nuevo conector
          </Button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {loading ? (
        <Panel className="p-4">
          <SkeletonBlock rows={4} />
        </Panel>
      ) : connectors.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Link}
            title="Sin conectores"
            body="Registra tus fuentes de datos para sincronizarlas con RAG."
            action={
              <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
                Nuevo conector
              </Button>
            }
          />
        </Panel>
      ) : (
        <>
          <Toolbar className="mb-3">
            <Input
              icon={MagnifyingGlass}
              className="w-full sm:max-w-64"
              placeholder="Buscar por nombre o tipo…"
              aria-label="Buscar conector"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Select
              className="w-full sm:max-w-44"
              aria-label="Filtrar por tipo"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              placeholder="Todos los tipos"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {typeLabel(t)}
                </option>
              ))}
            </Select>
            <ResultCount shown={filtered.length} total={connectors.length} noun="conectores" />
          </Toolbar>

          <Panel>
            <PanelHeader
              title={`Catálogo (${connectors.length})`}
              description="El estado viene del backend; las credenciales se guardan en Vault."
            />
            {filtered.length === 0 ? (
              <EmptyState
                compact
                icon={MagnifyingGlass}
                title="Sin resultados"
                body="Ningún conector coincide con la búsqueda o el tipo elegido."
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSearch("");
                      setTypeFilter("");
                    }}
                  >
                    Limpiar filtros
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-border-soft">
                {filtered.map((c) => {
                  const IconEl = TYPE_ICONS[c.type] ?? Link;
                  return (
                    <li key={c.id} className="flex items-center gap-3 px-4 py-3">
                      <span
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-soft text-accent"
                        aria-hidden
                      >
                        <IconEl size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium text-text">{c.name}</p>
                        <p className="truncate text-xs text-faint">
                          {typeLabel(c.type)} · Creado {fmtDateTime(c.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={c.status} />
                      <Button variant="ghost" size="sm" onClick={() => void openDetail(c)}>
                        Detalle
                      </Button>
                      <IconButton
                        label={`Eliminar ${c.name}`}
                        icon={Trash}
                        variant="ghost"
                        onClick={() => setPendingDelete(c)}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </>
      )}

      <Modal
        open={showCreate}
        onOpenChange={setShowCreate}
        title="Crear conector"
        description="Los datos de conexión se configuran aparte: acá registramos el conector y su tipo."
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={creating}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={creating}
              leadingIcon={Plus}
              disabled={!name.trim()}
              onClick={() => void create()}
            >
              {type === "gdrive" ? "Conectar Google Drive" : "Crear"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Nombre" required>
            <Input
              placeholder="ej. ERP producción"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field label="Tipo" hint="El tipo define cómo se sincroniza la fuente.">
            <Select value={type} onChange={(e) => setType(e.target.value as (typeof TYPES)[number])}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {typeLabel(t)}
                </option>
              ))}
            </Select>
          </Field>
          {type === "gdrive" && (
            <Field label="ID de carpeta" required hint="Solo se sincroniza esa carpeta de Drive.">
              <Input
                placeholder="ID de la carpeta de Google Drive"
                value={folderId}
                onChange={(e) => setFolderId(e.target.value)}
                autoComplete="off"
              />
            </Field>
          )}
        </div>
      </Modal>

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.name ?? "Conector"}
        description={detail ? `Conector de tipo ${typeLabel(detail.type)}` : undefined}
        width={480}
      >
        {detail && (
          <div className="flex flex-col gap-4">
            <ErrorInline message={detailError} className="mb-0" />
            <KeyValue
              columns={2}
              items={[
                { key: "Estado", value: <StatusBadge status={detail.status} /> },
                { key: "Tipo", value: typeLabel(detail.type), mono: true },
                { key: "Creado", value: fmtDateTime(detail.created_at) },
                {
                  key: "Credenciales",
                  value:
                    detail.has_secrets === undefined
                      ? detailLoading
                        ? "Consultando…"
                        : "—"
                      : detail.has_secrets
                        ? "Guardadas en Vault"
                        : "Sin configurar",
                },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Configuración</p>
              {Object.keys(detail.config ?? {}).length > 0 ? (
                <CodeBlock
                  code={JSON.stringify(detail.config, null, 2)}
                  language="json"
                  filename="config.json"
                  maxHeight={240}
                />
              ) : (
                <p className="text-xs leading-relaxed text-faint">
                  Sin configuración adicional registrada.
                </p>
              )}
            </div>
            <p className="text-xs leading-relaxed text-faint">
              Los secretos se guardan en Vault y la API nunca los devuelve.
            </p>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={pendingDelete ? `Eliminar el conector "${pendingDelete.name}"` : "Eliminar conector"}
        body="Se elimina el conector y sus sincronizaciones dejan de ejecutarse. Esta acción no se puede deshacer."
        confirmLabel="Eliminar"
        loading={deleting}
        onConfirm={() => {
          if (pendingDelete) void remove(pendingDelete.id);
        }}
      />
    </div>
  );
}
