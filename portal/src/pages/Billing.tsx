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
import { fmtNum } from "../lib/format";

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
  invoice_number?: string;
  created_at?: string;
};

type BillingProfile = {
  legal_name?: string | null;
  tax_id?: string | null;
  address_line1?: string | null;
  city?: string | null;
  default_payment_method?: string | null;
  card_last4?: string | null;
};

export default function BillingPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [profile, setProfile] = useState<BillingProfile>({ default_payment_method: "card" });
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
        const [subData, planData, invoiceData, entData, profileData] = await Promise.all([
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
          api<{ profile: BillingProfile | null }>("/api/v1/billing/billing-profile", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ profile: null })),
        ]);
        setSub(subData);
        setPlans(planData.plans || []);
        setInvoices(invoiceData.invoices || []);
        setEntitlements(entData.entitlements || {});
        if (profileData.profile) setProfile(profileData.profile);
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

  async function upgradePlan(planName: string) {
    if (!session) return;
    setBusy(planName);
    setError("");
    try {
      const out = await api<{ status: string }>("/api/v1/billing/subscription/upgrade", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        headers: { "X-New-Plan": planName },
      });
      setBusy("");
      const [subData] = await Promise.all([
        api<Subscription>("/api/v1/billing/subscription", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setSub(subData);
      setError(`Plan actualizado: ${out.status}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar el plan");
      setBusy("");
    }
  }

  async function generateInvoice() {
    if (!session) return;
    setBusy("gen");
    setError("");
    try {
      await api("/api/v1/billing/invoices/generate", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      const invoiceData = await api<{ invoices: Invoice[] }>("/api/v1/billing/invoices", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setInvoices(invoiceData.invoices || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar la factura");
    } finally {
      setBusy("");
    }
  }

  async function payInvoice(invoiceId: string) {
    if (!session) return;
    setBusy(`pay-${invoiceId.slice(0, 6)}`);
    setError("");
    try {
      await api(`/api/v1/billing/invoices/${invoiceId}/pay`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      const invoiceData = await api<{ invoices: Invoice[] }>("/api/v1/billing/invoices", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setInvoices(invoiceData.invoices || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo procesar el pago");
    } finally {
      setBusy("");
    }
  }

  async function saveProfile() {
    if (!session) return;
    setBusy("profile");
    setError("");
    try {
      const out = await api<{ profile: BillingProfile }>("/api/v1/billing/billing-profile", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(profile),
      });
      setProfile(out.profile);
      setError("Perfil de facturación guardado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el perfil");
    } finally {
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
        subtitle="Plan, uso del período y límites de tu workspace. Administra tus facturas y perfil de pago."
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
            <StatCard label="Plan actual" value={sub?.plan_name || "—"} icon={CreditCard} />
            <StatCard label="Estado" value={sub?.status || "—"} />
            <StatCard
              label="Uso del período"
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
                    {!canCheckout && sub?.self_service_upgrade_enabled && (
                      <button
                        type="button"
                        className="btn btn-secondary min-h-11"
                        disabled={!!busy}
                        onClick={() => void upgradePlan(p.name)}
                      >
                        {busy === p.name ? "Actualizando…" : "Upgrade"}
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
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Facturas</h2>
              <button
                type="button"
                className="btn btn-secondary min-h-8 px-3 text-xs"
                onClick={() => void generateInvoice()}
                disabled={!!busy}
              >
                Generar del mes anterior
              </button>
            </div>
            {invoices.length === 0 ? (
              <EmptyState
                icon={CreditCard}
                title="Sin facturas"
                body="Genera la factura del mes anterior o espera la emisión automática."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="table min-w-[640px]">
                  <thead>
                    <tr>
                      <th>Nº</th>
                      <th>Estado</th>
                      <th className="text-right">Total</th>
                      <th>Periodo</th>
                      <th className="text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map((inv) => (
                      <tr key={inv.id}>
                        <td className="mono text-xs">{inv.invoice_number}</td>
                        <td><span className={`badge ${inv.status === "paid" ? "badge-ok" : inv.status === "void" ? "badge-muted" : "badge-pending"}`}>{inv.status}</span></td>
                        <td className="mono text-right">
                          {inv.total_cents != null
                            ? `${(inv.total_cents / 100).toFixed(2)} ${inv.currency || "USD"}`
                            : "—"}
                        </td>
                        <td className="text-muted">
                          {inv.period_start ? `${inv.period_start} → ${inv.period_end}` : "—"}
                        </td>
                        <td className="text-right">
                          {inv.status !== "paid" && inv.status !== "void" && (
                            <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void payInvoice(inv.id)}>
                              Pagar
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 px-2 text-xs"
                            onClick={() => session && window.open(`/api/v1/billing/invoices/${inv.id}/csv?token=${encodeURIComponent(session.token)}&organizationId=${encodeURIComponent(session.organizationId)}`, "_blank")}
                          >
                            CSV
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 px-2 text-xs"
                            onClick={() => session && window.open(`/api/v1/billing/invoices/${inv.id}/pdf?token=${encodeURIComponent(session.token)}&organizationId=${encodeURIComponent(session.organizationId)}`, "_blank")}
                          >
                            PDF
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="panel mt-4">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Créditos de IA</h2>
              <span className="badge badge-pending">Próximamente</span>
            </div>
            <p className="px-5 py-4 text-[13px] leading-relaxed text-muted">
              Compra y consumo de créditos para modelos personalizados. Esta funcionalidad
              estará disponible en una próxima fase.
            </p>
          </div>
          <div className="panel mt-4">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-text">Perfil de facturación</h2>
            </div>
            <div className="grid grid-cols-1 gap-2 p-5 md:grid-cols-2">
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Razón social" value={profile.legal_name ?? ""} onChange={(e) => setProfile((p) => ({ ...p, legal_name: e.target.value }))} />
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="RUT/Tax ID" value={profile.tax_id ?? ""} onChange={(e) => setProfile((p) => ({ ...p, tax_id: e.target.value }))} />
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Dirección" value={profile.address_line1 ?? ""} onChange={(e) => setProfile((p) => ({ ...p, address_line1: e.target.value }))} />
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Ciudad" value={profile.city ?? ""} onChange={(e) => setProfile((p) => ({ ...p, city: e.target.value }))} />
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={profile.default_payment_method ?? "card"} onChange={(e) => setProfile((p) => ({ ...p, default_payment_method: e.target.value }))}>
                {["card", "sepa", "wire", "manual"].map((m) => (<option key={m} value={m}>{m}</option>))}
              </select>
              <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Últimos 4 dígitos" maxLength={4} value={profile.card_last4 ?? ""} onChange={(e) => setProfile((p) => ({ ...p, card_last4: e.target.value }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs md:col-span-2" disabled={!!busy} onClick={() => void saveProfile()}>
                Guardar perfil
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
