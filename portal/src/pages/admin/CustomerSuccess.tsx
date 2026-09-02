import { ChartBar, Envelope, Rocket } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Conversion = {
  total_subscriptions: number;
  trials: number;
  paid_active: number;
  conversion_rate_pct: number | null;
  by_plan: { plan: string; total: number; active: number }[];
};

type Onboarding = {
  organization_id: string;
  step: number;
  completed: boolean;
  completed_at: string | null;
  items: { key: string; label: string; done: boolean }[];
};

type ReportSub = {
  id: string;
  organization_id: string;
  email: string;
  frequency: string;
  next_send_at: string;
  last_sent_at: string | null;
};

export default function AdminCustomerSuccessPage() {
  const { session } = usePlatformAuth();
  const [conversion, setConversion] = useState<Conversion | null>(null);
  const [onboarding, setOnboarding] = useState<Onboarding[]>([]);
  const [subs, setSubs] = useState<ReportSub[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [c, o, s] = await Promise.all([
        platformApi<Conversion>("/api/v1/platform/customer-success/conversion", {
          token: session.token,
        }),
        platformApi<{ organizations: Onboarding[] }>(
          "/api/v1/platform/customer-success/onboarding",
          { token: session.token }
        ),
        platformApi<{ subscriptions: ReportSub[] }>(
          "/api/v1/platform/customer-success/reports",
          { token: session.token }
        ),
      ]);
      setConversion(c);
      setOnboarding(o.organizations || []);
      setSubs(s.subscriptions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function sendNow(subId: string) {
    if (!session) return;
    setBusy(subId);
    setError("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/customer-success/reports/${subId}/send-now`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`Reporte: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function removeSub(subId: string) {
    if (!session) return;
    setBusy(subId);
    try {
      await platformApi(`/api/v1/platform/customer-success/reports/${subId}`, {
        method: "DELETE",
        token: session.token,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customer Success"
        subtitle="Conversión trial→paid, onboarding por tenant y reportes de uso por email."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Rocket size={15} aria-hidden /> Conversión trial → paid
            </h3>
            <div className="panel grid grid-cols-2 gap-3 p-4 lg:grid-cols-4">
              <div>
                <p className="stat-label">Trials</p>
                <p className="stat-value">{conversion?.trials ?? 0}</p>
              </div>
              <div>
                <p className="stat-label">Paid activos</p>
                <p className="stat-value">{conversion?.paid_active ?? 0}</p>
              </div>
              <div>
                <p className="stat-label">Conversión</p>
                <p className="stat-value">
                  {conversion?.conversion_rate_pct != null ? `${conversion.conversion_rate_pct}%` : "—"}
                </p>
              </div>
              <div>
                <p className="stat-label">Subs totales</p>
                <p className="stat-value">{conversion?.total_subscriptions ?? 0}</p>
              </div>
            </div>
            <div className="panel mt-2 overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Plan</th>
                    <th>Totales</th>
                    <th>Activas</th>
                  </tr>
                </thead>
                <tbody>
                  {(conversion?.by_plan ?? []).map((p) => (
                    <tr key={p.plan}>
                      <td className="text-sm text-text">{p.plan}</td>
                      <td className="text-xs">{p.total}</td>
                      <td className="text-xs">{p.active}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <ChartBar size={15} aria-hidden /> Onboarding por tenant
            </h3>
            <div className="panel grid grid-cols-1 gap-3 lg:grid-cols-2">
              {onboarding.map((o) => (
                <div key={o.organization_id} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between">
                    <p className="mono text-xs text-faint">{o.organization_id.slice(0, 13)}…</p>
                    <span className={`badge ${o.completed ? "badge-ok" : "badge-pending"}`}>
                      {o.completed ? "completado" : `paso ${o.step}/6`}
                    </span>
                  </div>
                  <ul className="mt-2 space-y-1">
                    {o.items.map((item) => (
                      <li key={item.key} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{item.label}</span>
                        <span className={`badge ${item.done ? "badge-ok" : "badge-muted"}`}>
                          {item.done ? "✓" : "·"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Envelope size={15} aria-hidden /> Reportes de uso por email
            </h3>
            <div className="panel overflow-x-auto">
              {subs.length === 0 ? (
                <EmptyState icon={Envelope} title="Sin suscripciones" body="Nadie se ha suscrito a reportes de uso." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Tenant</th>
                      <th>Email</th>
                      <th>Frecuencia</th>
                      <th>Próximo envío</th>
                      <th>Último envío</th>
                      <th className="text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {subs.map((s) => (
                      <tr key={s.id}>
                        <td className="mono text-xs text-faint">{s.organization_id.slice(0, 8)}</td>
                        <td className="text-sm text-text">{s.email}</td>
                        <td className="text-xs">{s.frequency}</td>
                        <td className="text-xs text-muted">{new Date(s.next_send_at).toLocaleString("es-PE")}</td>
                        <td className="text-xs text-muted">
                          {s.last_sent_at ? new Date(s.last_sent_at).toLocaleString("es-PE") : "—"}
                        </td>
                        <td className="text-right">
                          <div className="flex justify-end gap-1">
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs"
                              disabled={!!busy}
                              onClick={() => void sendNow(s.id)}
                            >
                              Enviar ahora
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs text-danger"
                              disabled={!!busy}
                              onClick={() => void removeSub(s.id)}
                            >
                              Quitar
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}