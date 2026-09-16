import { Plus, Trash, WebhooksLogo } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  PasswordInput,
  ResultCount,
  Select,
  StatusBadge,
  SuccessInline,
  type Column,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

const WEBHOOK_EVENTS = [
  "agent_run",
  "api_query",
  "deployment_event",
  "incident",
  "workflow_run",
  "invoice.paid",
  "quota.exceeded",
  "usage.alert",
  "agent.deployed",
  "test.ping",
];

type Webhook = {
  id: string;
  event_type: string;
  url: string;
  enabled: boolean;
  delivery_count: number;
  fail_count: number;
  last_delivered_at: string | null;
  created_at: string;
};

/**
 * Suscripciones de webhooks. `embedded` evita un segundo h1 cuando la página
 * se muestra dentro de la pestaña Webhooks de API y Claves.
 */
export default function WebhooksPage({ embedded = false }: { embedded?: boolean }) {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [eventType, setEventType] = useState(WEBHOOK_EVENTS[0]);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Webhook | null>(null);
  const [deleting, setDeleting] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    setError("");
    api<{ webhooks: Webhook[] }>("/api/v1/webhooks", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setHooks(data.webhooks || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    setCreating(true);
    setError("");
    setMsg("");
    try {
      await api<Webhook>("/api/v1/webhooks", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ event_type: eventType, url: url.trim(), secret: secret.trim() || null }),
      });
      setMsg("Webhook creado. Ya recibirá notificaciones del evento seleccionado.");
      setShowCreate(false);
      setUrl("");
      setSecret("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  async function testHook(hook: Webhook) {
    if (!session) return;
    setTesting(hook.id);
    try {
      const res = await api<{ status: string }>(`/api/v1/webhooks/${hook.id}/test`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: "{}",
      });
      pushToast("success", "Ping enviado", `Respuesta del webhook: ${res.status}`);
    } catch (err) {
      pushToast("error", "Fallo en el ping", err instanceof Error ? err.message : "Error");
    } finally {
      setTesting(null);
    }
  }

  async function deleteHook(hook: Webhook) {
    if (!session) return;
    setDeleting(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/webhooks/${hook.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Webhook "${hook.event_type}" eliminado.`);
      setPendingDelete(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setDeleting(false);
    }
  }

  const columns: Column<Webhook>[] = [
    {
      key: "event",
      header: "Evento",
      render: (hook) => <span className="mono text-xs text-text">{hook.event_type}</span>,
    },
    {
      key: "url",
      header: "URL",
      render: (hook) => (
        <span className="mono block max-w-[22rem] truncate text-xs text-muted" title={hook.url}>
          {hook.url}
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      width: "1%",
      render: (hook) => <StatusBadge status={hook.enabled ? "active" : "inactive"} />,
    },
    {
      key: "deliveries",
      header: "Entregas",
      align: "right",
      render: (hook) => <span className="mono text-xs">{hook.delivery_count}</span>,
    },
    {
      key: "failures",
      header: "Fallos",
      align: "right",
      render: (hook) =>
        hook.fail_count > 0 ? (
          <span className="mono text-xs text-danger">{hook.fail_count}</span>
        ) : (
          <span className="mono text-xs text-muted">0</span>
        ),
    },
    {
      key: "last",
      header: "Última entrega",
      hideBelow: "md",
      render: (hook) => (
        <span className="text-xs text-muted">
          {hook.last_delivered_at ? fmtDateTime(hook.last_delivered_at) : "—"}
        </span>
      ),
    },
    {
      key: "created",
      header: "Creado",
      hideBelow: "lg",
      render: (hook) => <span className="text-xs text-faint">{fmtDateTime(hook.created_at)}</span>,
    },
  ];

  const subscribeButton = (
    <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
      Suscribir webhook
    </Button>
  );

  return (
    <div>
      {embedded ? (
        <div className="mb-3 flex justify-end">{subscribeButton}</div>
      ) : (
        <PageHeader
          title="Webhooks"
          subtitle="Recibe eventos de tu workspace en tus propios sistemas. Enviamos un POST firmado por cada evento suscrito."
          actions={subscribeButton}
        />
      )}
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <DataTable
        columns={columns}
        rows={hooks}
        rowKey={(hook) => hook.id}
        loading={loading}
        toolbar={<ResultCount shown={hooks.length} total={hooks.length} noun="suscripciones" />}
        empty={
          <EmptyState
            icon={WebhooksLogo}
            title="Sin webhooks configurados"
            body="Suscribe un evento para recibir notificaciones en tu infraestructura cuando ocurra."
          />
        }
        rowActions={(hook) => (
          <>
            <Button
              variant="ghost"
              size="sm"
              loading={testing === hook.id}
              onClick={() => void testHook(hook)}
            >
              Probar
            </Button>
            <IconButton
              label={`Eliminar webhook ${hook.event_type}`}
              icon={Trash}
              variant="ghost"
              onClick={() => setPendingDelete(hook)}
            />
          </>
        )}
      />

      <Modal
        open={showCreate}
        onOpenChange={setShowCreate}
        title="Nuevo webhook"
        description="Enviamos un POST firmado a la URL cada vez que ocurra el evento suscrito."
        size="md"
      >
        <form onSubmit={create} className="flex flex-col gap-3">
          <Field label="Evento">
            <Select id="wh-event" value={eventType} onChange={(e) => setEventType(e.target.value)}>
              {WEBHOOK_EVENTS.map((ev) => (
                <option key={ev} value={ev}>
                  {ev}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="URL de destino" required>
            <Input
              id="wh-url"
              type="url"
              required
              placeholder="https://tu-sistema.example/hook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field label="Secreto" hint="Si lo dejas vacío generamos uno automáticamente.">
            <PasswordInput
              id="wh-secret"
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
            />
          </Field>
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={creating}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={creating}
              leadingIcon={Plus}
              disabled={!url.trim()}
            >
              Suscribir
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={pendingDelete ? `Eliminar el webhook ${pendingDelete.event_type}` : "Eliminar webhook"}
        body={
          pendingDelete
            ? `Se dejan de enviar los eventos a ${pendingDelete.url}. Esta acción no se puede deshacer.`
            : undefined
        }
        confirmLabel="Eliminar"
        loading={deleting}
        onConfirm={() => {
          if (pendingDelete) void deleteHook(pendingDelete);
        }}
      />
    </div>
  );
}
