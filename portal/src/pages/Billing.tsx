import { CreditCard } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
} from "../components/ui";
import { fmtDateTime, fmtNum } from "../lib/format";

type Subscription = {
  plan_name: string | null;
  status: string;
  requests_used: number;
  requests_limit: number | null;
  trial_end: string | null;
  checkout_available?: boolean;
  self_service_upgrade_enabled?: boolean;
};

type Entitlements = Record<string, boolean | number | null>;

const ENTITLEMENT_LABELS: Record<string, string> = {
  monthly_requests: "Consultas mensuales",
  max_users: "Usuarios",
  max_agents: "Agentes",
  max_knowledge_bases: "Colecciones",
  max_connectors: "Conectores",
  api_access: "Acceso API",
  custom_models: "Modelos personalizados",
  embed_widget: "Widget embebido",
  eval_ui: "Evaluación RAG",
  sso: "SSO",
};

function formatEntitlement(value: boolean | number | null | undefined): string {
  if (value === true) return "Incluido";
  if (value === false) return "No incluido";
  if (value == null) return "Ilimitado";
  return String(value);
}

type Plan = {
  name: string;
  display_name: string;
  price_monthly_usd: number;
};

type Invoice = {
  id: string;
  status: string;
  total_cents?: number;
  currency?: string;
  period_start?: string;
  period_end?: string;
  created_at?: string;
};

export default function BillingPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [entitlements, setEntitlements] = useState<Entitlements>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [subData, planData, invoiceData, entData] = await Promise.all([
          api<Subscription>("/api/v1/billing/subscription", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ plans: Plan[] }>("/api/v1/billing/plans", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ invoices: Invoice[] }>("/api/v1/billing/invoices", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ invoices: [] as Invoice[] })),
          api<{ entitlements: Entitlements }>("/api/v1/billing/entitlements", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ entitlements: {} as Entitlements })),
        ]);
        setSub(subData);
        setPlans(planData.plans || []);
        setInvoices(invoiceData.invoices || []);
        setEntitlements(entData.entitlements || {});
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando facturación");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? null;
  const used = sub?.requests_used ?? 0;
  const canCheckout = Boolean(sub?.checkout_available);
  const canCancel = Boolean(sub?.self_service_upgrade_enabled);

  async function startCheckout(planName: string) {
    if (!session || !canCheckout) return;
    setBusy(planName);
    setError("");
    try {
      const out = await api<{ checkout_url: string }>("/api/v1/billing/checkout", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ plan_name: planName, interval: "monthly" }),
      });
      window.location.assign(out.checkout_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar el pago");
      setBusy("");
    }
  }

  async function cancelPlan() {
    if (!session || !canCancel) return;
    setBusy("cancel");
    setError("");
    try {
      await api("/api/v1/billing/subscription/cancel", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setConfirmCancel(false);
      const subData = await api<Subscription>("/api/v1/billing/subscription", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setSub(subData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar");
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <PageHeader
        title="Facturación"
        subtitle={
          canCheckout
            ? "Plan, cuota y facturas. El upgrade abre Stripe Checkout."
            : "Plan, cuota y facturas. Para cambiar de plan, contacta a Zent."
        }
      />
      <ErrorInline message={error} />
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="stat">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard label="Plan" value={sub?.plan_name || "—"} icon={CreditCard} />
            <StatCard label="Estado" value={sub?.status || "—"} />
            <StatCard
              label="Cuota"
              value={limit ? `${fmtNum(used)} / ${fmtNum(limit)}` : fmtNum(used)}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {canCheckout ? (
              <p className="self-center text-xs text-faint">
                Elige un plan de pago abajo para continuar en Stripe.
              </p>
            ) : (
              <p className="self-center text-sm text-muted">Contactar a Zent</p>
            )}
            {canCancel &&
              (confirmCancel ? (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn btn-danger min-h-11"
                    disabled={!!busy}
                    onClick={() => void cancelPlan()}
                  >
                    Confirmar cancelación
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary min-h-11"
                    onClick={() => setConfirmCancel(false)}
                  >
                    Volver
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary min-h-11"
                  disabled={!!busy}
                  onClick={() => setConfirmCancel(true)}
                >
                  Cancelar plan
                </button>
              ))}
          </div>
          <div className="panel mt-4">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Planes disponibles</h2>
            </div>
            <ul className="divide-y divide-border/60">
              {plans.map((p) => (
                <li key={p.name} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <span className="text-text">{p.display_name || p.name}</span>
                  <span className="flex items-center gap-3">
                    <span className="mono text-muted">${p.price_monthly_usd}/mes</span>
                    {canCheckout && p.name !== "trial" && p.name !== "enterprise" && (
                      <button
                        type="button"
                        className="btn btn-primary min-h-11"
                        disabled={!!busy}
                        onClick={() => void startCheckout(p.name)}
                      >
                        {busy === p.name ? "Abriendo…" : "Contratar"}
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="panel mt-4">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Límites y funciones</h2>
            </div>
            {Object.keys(ENTITLEMENT_LABELS).every((k) => entitlements[k] === undefined) ? (
              <EmptyState
                icon={CreditCard}
                title="Sin entitlements"
                body="Cuando tu plan tenga límites configurados, aparecerán aquí."
              />
            ) : (
              <ul className="divide-y divide-border/60">
                {Object.entries(ENTITLEMENT_LABELS).map(([key, label]) =>
                  key in entitlements ? (
                    <li
                      key={key}
                      className="flex items-center justify-between px-5 py-3 text-sm"
                    >
                      <span className="text-text">{label}</span>
                      <span className="text-muted">{formatEntitlement(entitlements[key])}</span>
                    </li>
                  ) : null
                )}
              </ul>
            )}
          </div>
          <div className="panel mt-4">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Facturas</h2>
            </div>
            {invoices.length === 0 ? (
              <EmptyState
                icon={CreditCard}
                title="Sin facturas"
                body="Cuando se emitan facturas (manual o Stripe), aparecerán aquí."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="table min-w-[560px]">
                  <thead>
                    <tr>
                      <th>Estado</th>
                      <th className="text-right">Total</th>
                      <th>Periodo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map((inv) => (
                      <tr key={inv.id}>
                        <td>{inv.status}</td>
                        <td className="mono text-right">
                          {inv.total_cents != null
                            ? `${(inv.total_cents / 100).toFixed(2)} ${inv.currency || "USD"}`
                            : "—"}
                        </td>
                        <td className="text-muted">
                          {inv.period_start ? fmtDateTime(inv.period_start) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
