import { Broadcast, Plus } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Delivery = { id: string; subscription_id: string; organization_id: string; event_type: string; status: string; attempts: number; last_status_code: number | null; latency_ms: number | null; error: string | null; delivered_at: string | null; created_at: string };
type SubStatus = { subscription_id: string; url: string; total: number; delivered: number; failed: number; retrying: number; success_rate: number; avg_latency_ms: number | null; last_status_code: number | null };

const ST = { delivered: "badge-ok", failed: "badge-danger", retrying: "badge-warning", pending: "badge-muted" } as Record<string, string>;

export default function AdminNotificationsPage() {
  const { session } = usePlatformAuth();
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [status, setStatus] = useState<SubStatus[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [trigger, setTrigger] = useState({ organization_id: "", event_type: "invoice.paid", title: "Evento de prueba" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [d, s] = await Promise.all([
        platformApi<{ deliveries: Delivery[] }>(`/api/v1/platform/notifications/deliveries${q}`, { token: session.token }),
        platformApi<{ subscriptions: SubStatus[] }>("/api/v1/platform/notifications/deliveries/status?hours=24", { token: session.token }),
      ]);
      setDeliveries(d.deliveries || []);
      setStatus(s.subscriptions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function triggerEvent() {
    if (!session) return;
    setBusy("trigger");
    setError("");
    try {
      const out = await platformApi<{ in_app: boolean; email: boolean; webhook_deliveries: number }>("/api/v1/platform/notifications/trigger", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(trigger),
      });
      setError(`Evento enviado: in_app=${out.in_app} · email=${out.email} · webhook_deliveries=${out.webhook_deliveries}`);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Webhooks & Notifications" subtitle="Entregas con firma HMAC, reintentos con backoff y preferencias multicanal." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {status.map((s) => (
              <div key={s.subscription_id} className="panel p-3">
                <p className="truncate text-[11px] font-medium text-text" title={s.url}>{s.url}</p>
                <p className="stat-value">{(s.success_rate * 100).toFixed(0)}%</p>
                <p className="text-[10px] text-faint">{s.total} entregas · {s.delivered} ok · {s.failed} fail · {s.retrying} retry</p>
                <p className="text-[10px] text-faint">latencia avg {s.avg_latency_ms != null ? `${s.avg_latency_ms.toFixed(0)}ms` : "—"} · último {s.last_status_code ?? "—"}</p>
              </div>
            ))}
            {status.length === 0 && <div className="panel p-4 text-xs text-faint">Sin entregas en 24h.</div>}
          </div>

          <section className="panel p-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Broadcast size={15} aria-hidden /> Enviar evento de prueba
            </h3>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={trigger.organization_id} onChange={(e) => setTrigger((t) => ({ ...t, organization_id: e.target.value }))}>
                <option value="">org…</option>
                {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={trigger.event_type} onChange={(e) => setTrigger((t) => ({ ...t, event_type: e.target.value }))}>
                {["invoice.paid", "quota.exceeded", "agent.deployed", "usage.alert", "test.ping"].map((ev) => (<option key={ev} value={ev}>{ev}</option>))}
              </select>
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={trigger.title} onChange={(e) => setTrigger((t) => ({ ...t, title: e.target.value }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !trigger.organization_id} onClick={() => void triggerEvent()}>
                <Plus size={13} aria-hidden /> Enviar
              </button>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text">Entregas recientes</h3>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">todas</option>
                  {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
                </select>
              </div>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Hora</th>
                      <th>Evento</th>
                      <th>Estado</th>
                      <th>Intentos</th>
                      <th>HTTP</th>
                      <th>Latencia</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deliveries.map((d) => (
                      <tr key={d.id}>
                        <td className="text-[10px] text-faint">{new Date(d.created_at).toLocaleTimeString()}</td>
                        <td className="text-xs">{d.event_type}</td>
                        <td><span className={`badge ${ST[d.status] ?? "badge-muted"}`}>{d.status}</span></td>
                        <td className="text-xs">{d.attempts}</td>
                        <td className="text-xs">{d.last_status_code ?? "—"}</td>
                        <td className="text-xs">{d.latency_ms != null ? `${d.latency_ms.toFixed(0)}ms` : "—"}</td>
                        <td className="max-w-40 truncate text-[10px] text-faint" title={d.error ?? ""}>{d.error ?? ""}</td>
                      </tr>
                    ))}
                    {deliveries.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-xs text-faint">Sin entregas.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Cola de reintentos</h3>
              <p className="text-xs text-faint">Backoff exponencial: 1m → 5m → 30m → 2h → 6h (máx 5 intentos).</p>
              <div className="mt-2 space-y-1">
                {deliveries.filter((d) => d.status === "retrying").slice(0, 8).map((d) => (
                  <div key={d.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="truncate text-text">{d.event_type}</span>
                    <span className="text-faint">intento {d.attempts}/5</span>
                  </div>
                ))}
                {deliveries.filter((d) => d.status === "retrying").length === 0 && <p className="text-xs text-faint">Sin reintentos pendientes.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}