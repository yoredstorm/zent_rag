import { CreditCard, FileArrowDown, Receipt, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  Input,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  type Column,
} from "../components/ui";
import { fmtCurrency, fmtCurrencyCents, fmtDate, fmtNum } from "../lib/format";

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
  managed_db: "Base de datos Zent",
  managed_db_backups: "Backups managed DB",
  managed_db_max_mb: "Tamaño managed DB (MB)",
};

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

const PAYMENT_METHODS = [
  { value: "card", label: "Tarjeta" },
  { value: "sepa", label: "SEPA" },
  { value: "wire", label: "Transferencia" },
  { value: "manual", label: "Manual" },
];

function invoiceTone(status: string): "ok" | "neutral" | "warn" {
  if (status === "paid") return "ok";
  if (status === "void") return "neutral";
  return "warn";
}

function usageTone(pct: number): "accent" | "warn" | "danger" {
  if (pct >= 100) return "danger";
  if (pct >= 80) return "warn";
  return "accent";
}

function EntitlementValue({ value }: { value: boolean | number | null | undefined }) {
  if (value === true) return <Badge tone="ok">Incluido</Badge>;
  if (value === false) return <Badge tone="neutral">No incluido</Badge>;
  if (value == null) return <span className="text-[13px] text-muted">Ilimitado</span>;
  return <span className="mono text-xs text-text">{fmtNum(value)}</span>;
}

export default function BillingPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [profile, setProfile] = useState<BillingProfile>({ default_payment_method: "card" });
  const [entitlements, setEntitlements] = useState<Entitlements>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelText, setCancelText] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setLoadError("");
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
        setLoadError(err instanceof Error ? err.message : "Error cargando facturación");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? null;
  const used = sub?.requests_used ?? 0;
  const usagePct = limit && limit > 0 ? Math.round((used / limit) * 100) : 0;
  const canCheckout = Boolean(sub?.checkout_available);
  const canCancel = Boolean(sub?.self_service_upgrade_enabled);

  async function startCheckout(planName: string) {
    if (!session || !canCheckout) return;
    setBusy(planName);
    setError("");
    setMsg("");
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
    setMsg("");
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
      setMsg(`Plan actualizado: ${out.status}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar el plan");
      setBusy("");
    }
  }

  async function generateInvoice() {
    if (!session) return;
    setBusy("gen");
    setError("");
    setMsg("");
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
    setMsg("");
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
    setMsg("");
    try {
      const out = await api<{ profile: BillingProfile }>("/api/v1/billing/billing-profile", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(profile),
      });
      setProfile(out.profile);
      setMsg("Perfil de facturación guardado.");
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
    setMsg("");
    try {
      await api("/api/v1/billing/subscription/cancel", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setConfirmCancel(false);
      setCancelText("");
      const subData = await api<Subscription>("/api/v1/billing/subscription", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setSub(subData);
      setMsg("Suscripción cancelada al final del período.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar");
    } finally {
      setBusy("");
    }
  }

  const planColumns: Column<Plan>[] = [
    {
      key: "plan",
      header: "Plan",
      render: (p) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-[13.5px] text-text">{p.display_name || p.name}</span>
          {p.name === sub?.plan_name && <Badge tone="accent">Plan actual</Badge>}
        </span>
      ),
    },
    {
      key: "price",
      header: "Precio",
      align: "right",
      render: (p) => (
        <span className="mono text-[13px] text-muted">{fmtCurrency(p.price_monthly_usd)}/mes</span>
      ),
    },
    {
      key: "action",
      header: "",
      align: "right",
      render: (p) => {
        if (p.name === sub?.plan_name) return null;
        if (canCheckout && p.name !== "trial" && p.name !== "enterprise") {
          return (
            <Button
              variant="primary"
              size="sm"
              loading={busy === p.name}
              disabled={!!busy}
              onClick={() => void startCheckout(p.name)}
            >
              Contratar
            </Button>
          );
        }
        if (!canCheckout && sub?.self_service_upgrade_enabled) {
          return (
            <Button
              variant="secondary"
              size="sm"
              loading={busy === p.name}
              disabled={!!busy}
              onClick={() => void upgradePlan(p.name)}
            >
              Cambiar plan
            </Button>
          );
        }
        return null;
      },
    },
  ];

  const entitlementKeys = Object.keys(ENTITLEMENT_LABELS).filter(
    (key) => entitlements[key] !== undefined,
  );

  const invoiceColumns: Column<Invoice>[] = [
    {
      key: "number",
      header: "Nº",
      render: (inv) => <span className="mono text-xs text-text">{inv.invoice_number || "—"}</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (inv) => <Badge tone={invoiceTone(inv.status)}>{inv.status}</Badge>,
    },
    {
      key: "total",
      header: "Total",
      align: "right",
      render: (inv) => (
        <span className="mono text-xs text-text">
          {inv.total_cents != null ? fmtCurrencyCents(inv.total_cents) : "—"}
        </span>
      ),
    },
    {
      key: "period",
      header: "Período",
      hideBelow: "md",
      render: (inv) => (
        <span className="text-xs text-muted">
          {inv.period_start ? `${fmtDate(inv.period_start)} – ${fmtDate(inv.period_end)}` : "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Acciones",
      align: "right",
      render: (inv) => (
        <span className="inline-flex flex-wrap items-center justify-end gap-1">
          {inv.status !== "paid" && inv.status !== "void" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={!!busy}
              onClick={() => void payInvoice(inv.id)}
            >
              Pagar
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              session &&
              window.open(
                `/api/v1/billing/invoices/${inv.id}/csv?token=${encodeURIComponent(session.token || "")}&organizationId=${encodeURIComponent(session.organizationId)}`,
                "_blank",
              )
            }
          >
            CSV
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              session &&
              window.open(
                `/api/v1/billing/invoices/${inv.id}/pdf?token=${encodeURIComponent(session.token || "")}&organizationId=${encodeURIComponent(session.organizationId)}`,
                "_blank",
              )
            }
          >
            PDF
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Facturación"
        subtitle="Plan, uso del período y límites de tu workspace. Administra tus facturas y perfil de pago."
      />
      <ErrorInline message={loadError} className="mb-0" />
      <ErrorInline message={error} className="mb-0" />
      <SuccessInline message={msg} className="mb-0" />

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Plan actual" />
            <div className="panel-body">
              <SkeletonBlock rows={4} />
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Uso del período" />
            <div className="panel-body">
              <SkeletonBlock rows={4} />
            </div>
          </Panel>
        </div>
      ) : sub ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader
                title="Plan actual"
                description="Estado de la suscripción de tu organización."
                actions={<StatusBadge status={sub.status} />}
              />
              <div className="panel-body">
                <p className="text-h2">{sub.plan_name || "—"}</p>
                {sub.trial_end && (
                  <p className="mt-1 text-[13px] text-muted">
                    Prueba hasta {fmtDate(sub.trial_end)}.
                  </p>
                )}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {canCheckout ? (
                    <p className="text-[13px] text-muted">
                      Elegí un plan de pago para continuar en Stripe.
                    </p>
                  ) : (
                    <p className="text-[13px] text-muted">
                      Los cambios de plan se gestionan con el equipo de Zent.
                    </p>
                  )}
                  {canCancel && (
                    <Button
                      variant="secondary"
                      leadingIcon={WarningCircle}
                      disabled={!!busy}
                      onClick={() => setConfirmCancel(true)}
                    >
                      Cancelar plan
                    </Button>
                  )}
                </div>
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Uso del período"
                description="Consultas consumidas frente al límite de tu plan."
              />
              <div className="panel-body">
                {limit != null ? (
                  <Progress
                    value={used}
                    max={limit}
                    tone={usageTone(usagePct)}
                    label={`${fmtNum(used)} de ${fmtNum(limit)} consultas`}
                    showValue
                  />
                ) : (
                  <>
                    <p className="stat-value text-[22px]">{fmtNum(used)}</p>
                    <p className="stat-hint">Consultas del período. Tu plan no define un límite.</p>
                  </>
                )}
              </div>
            </Panel>
          </div>

          <Panel>
            <PanelHeader
              title="Planes disponibles"
              description="Precios mensuales publicados por Zent."
            />
            <DataTable
              columns={planColumns}
              rows={plans}
              rowKey={(p) => p.name}
              caption="Planes disponibles"
              empty={
                <EmptyState
                  icon={CreditCard}
                  title="Sin planes publicados"
                  body="La lista de planes aparecerá cuando esté disponible."
                />
              }
            />
          </Panel>

          <Panel>
            <PanelHeader
              title="Límites y funciones"
              description="Qué incluye el plan contratado."
            />
            {entitlementKeys.length === 0 ? (
              <EmptyState
                icon={Sparkle}
                title="Sin entitlements"
                body="Cuando tu plan tenga límites configurados, aparecerán aquí."
              />
            ) : (
              <div className="divide-y divide-border-soft">
                {entitlementKeys.map((key) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-3 px-4 py-2.5 text-[13px]"
                  >
                    <span className="text-text">{ENTITLEMENT_LABELS[key]}</span>
                    <EntitlementValue value={entitlements[key]} />
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel>
            <PanelHeader
              title="Facturas"
              actions={
                <Button
                  variant="secondary"
                  size="sm"
                  leadingIcon={Receipt}
                  loading={busy === "gen"}
                  disabled={!!busy}
                  onClick={() => void generateInvoice()}
                >
                  Generar del mes anterior
                </Button>
              }
            />
            <DataTable
              columns={invoiceColumns}
              rows={invoices}
              rowKey={(inv) => inv.id}
              caption="Facturas"
              empty={
                <EmptyState
                  icon={FileArrowDown}
                  title="Sin facturas"
                  body="Generá la factura del mes anterior o esperá la emisión automática."
                />
              }
            />
          </Panel>

          <Panel>
            <PanelHeader
              title="Créditos de IA"
              actions={<Badge tone="warn">Próximamente</Badge>}
            />
            <p className="panel-body text-[13px] leading-relaxed text-muted">
              Compra y consumo de créditos para modelos personalizados. Esta funcionalidad estará
              disponible en una próxima fase.
            </p>
          </Panel>

          <Panel>
            <PanelHeader
              title="Perfil de facturación"
              description="Datos fiscales que Zent usa para emitir facturas."
            />
            <form
              className="panel-body"
              onSubmit={(e) => {
                e.preventDefault();
                void saveProfile();
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Razón social">
                  <Input
                    value={profile.legal_name ?? ""}
                    onChange={(e) => setProfile((p) => ({ ...p, legal_name: e.target.value }))}
                    autoComplete="organization"
                  />
                </Field>
                <Field label="RUT / Tax ID">
                  <Input
                    value={profile.tax_id ?? ""}
                    onChange={(e) => setProfile((p) => ({ ...p, tax_id: e.target.value }))}
                    autoComplete="off"
                  />
                </Field>
                <Field label="Dirección">
                  <Input
                    value={profile.address_line1 ?? ""}
                    onChange={(e) => setProfile((p) => ({ ...p, address_line1: e.target.value }))}
                    autoComplete="street-address"
                  />
                </Field>
                <Field label="Ciudad">
                  <Input
                    value={profile.city ?? ""}
                    onChange={(e) => setProfile((p) => ({ ...p, city: e.target.value }))}
                    autoComplete="address-level2"
                  />
                </Field>
                <Field label="Método de pago">
                  <Select
                    value={profile.default_payment_method ?? "card"}
                    onChange={(e) =>
                      setProfile((p) => ({ ...p, default_payment_method: e.target.value }))
                    }
                  >
                    {PAYMENT_METHODS.map((method) => (
                      <option key={method.value} value={method.value}>
                        {method.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Últimos 4 dígitos" hint="Solo si el pago es con tarjeta.">
                  <Input
                    maxLength={4}
                    inputMode="numeric"
                    value={profile.card_last4 ?? ""}
                    onChange={(e) => setProfile((p) => ({ ...p, card_last4: e.target.value }))}
                    autoComplete="cc-number"
                  />
                </Field>
              </div>
              <FormActions className="mt-6">
                <Button type="submit" variant="primary" loading={busy === "profile"} disabled={!!busy}>
                  Guardar perfil
                </Button>
              </FormActions>
            </form>
          </Panel>
        </>
      ) : null}

      <Modal
        open={confirmCancel}
        onOpenChange={(open) => {
          setConfirmCancel(open);
          if (!open) setCancelText("");
        }}
        title="Cancelar suscripción"
        description="Se cancela el plan actual al final del período. Perderás el acceso a las funciones del plan y los datos se conservan según la política de retención."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              disabled={busy === "cancel"}
              onClick={() => setConfirmCancel(false)}
            >
              Volver
            </Button>
            <Button
              variant="danger"
              loading={busy === "cancel"}
              disabled={cancelText.trim() !== "CANCEL"}
              onClick={() => void cancelPlan()}
            >
              Cancelar plan
            </Button>
          </>
        }
      >
        <Field
          label="Confirmación"
          hint={
            <>
              Escribí <span className="mono text-text">CANCEL</span> para habilitar la acción.
            </>
          }
        >
          <Input
            value={cancelText}
            onChange={(e) => setCancelText(e.target.value)}
            autoComplete="off"
            placeholder="CANCEL"
          />
        </Field>
      </Modal>
    </div>
  );
}
