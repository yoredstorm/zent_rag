import { ArrowClockwise, Plus, Trash, WebhooksLogo } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
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

export default function WebhooksPage() {
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
  const [deleting, setDeleting] = useState<string | null>(null);

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
    setDeleting(hook.id);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/webhooks/${hook.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Webhook "${hook.event_type}" eliminado.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Webhooks"
        subtitle="Recibe eventos de tu workspace en tus propios sistemas. Enviamos un POST firmado por cada evento suscrito."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate((v) => !v)}>
            <Plus size={15} aria-hidden />
            Suscribir webhook
          </button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {showCreate && (
        <form onSubmit={create} className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Nuevo webhook</h2>
          </div>
          <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2">
            <div className="field">
              <label htmlFor="wh-event">Evento</label>
              <select
                id="wh-event"
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
              >
                {WEBHOOK_EVENTS.map((ev) => (
                  <option key={ev} value={ev}>
                    {ev}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="wh-url">URL de destino</label>
              <input
                id="wh-url"
                type="url"
                required
                placeholder="https://tu-sistema.example/hook"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </div>
            <div className="field sm:col-span-2">
              <label htmlFor="wh-secret">
                Secreto <span className="text-faint">(opcional)</span>
              </label>
              <input
                id="wh-secret"
                type="password"
                autoComplete="off"
                placeholder="Si lo dejas vacío generamos uno automáticamente"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowCreate(false)}
            >
              Cancelar
            </button>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? <Spinner size={14} /> : <Plus size={15} aria-hidden />}
              Suscribir
            </button>
          </div>
        </form>
      )}

      <div className="panel">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <WebhooksLogo size={16} className="text-accent" aria-hidden />
          <h2 className="text-sm font-semibold text-text">Suscripciones ({hooks.length})</h2>
        </div>
        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={4} />
          </div>
        ) : hooks.length === 0 ? (
          <EmptyState
            icon={WebhooksLogo}
            title="Sin webhooks configurados"
            body="Suscribe un evento para recibir notificaciones en tu infraestructura cuando ocurra."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>Evento</th>
                  <th>URL</th>
                  <th>Estado</th>
                  <th>Entregas</th>
                  <th>Fallos</th>
                  <th>Última entrega</th>
                  <th>Creado</th>
                  <th className="text-right">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {hooks.map((hook) => (
                  <tr key={hook.id}>
                    <td className="mono text-xs text-text">{hook.event_type}</td>
                    <td className="max-w-[220px] truncate font-mono text-xs text-muted" title={hook.url}>
                      {hook.url}
                    </td>
                    <td>
                      {hook.enabled ? (
                        <span className="badge badge-ok">Activo</span>
                      ) : (
                        <span className="badge badge-muted">Desactivado</span>
                      )}
                    </td>
                    <td className="mono text-xs">{hook.delivery_count}</td>
                    <td className="mono text-xs text-danger">{hook.fail_count}</td>
                    <td className="text-xs text-muted">
                      {hook.last_delivered_at ? fmtDateTime(hook.last_delivered_at) : "—"}
                    </td>
                    <td className="text-xs text-faint">{fmtDateTime(hook.created_at)}</td>
                    <td className="text-right">
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          className="btn btn-ghost min-h-10 px-2 py-1 text-xs"
                          onClick={() => void testHook(hook)}
                          disabled={testing === hook.id}
                          title="Enviar ping de prueba"
                        >
                          {testing === hook.id ? <Spinner size={13} /> : <ArrowClockwise size={14} aria-hidden />}
                          Probar
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost min-h-10 px-2 py-1 text-xs"
                          onClick={() => void deleteHook(hook)}
                          disabled={deleting === hook.id}
                          aria-label={`Eliminar webhook ${hook.event_type}`}
                        >
                          {deleting === hook.id ? <Spinner size={13} /> : <Trash size={14} aria-hidden />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}