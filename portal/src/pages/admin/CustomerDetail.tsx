import { CaretDown, UserSwitch, WarningOctagon } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { platformApi, saveSession } from "../../api";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Timeline, type TimelineItem } from "../../components/Timeline";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  RecentActivity,
  RoleBadge,
  SkeletonBlock,
  StatCard,
  StatusBadge,
  TenantHealthBadge,
} from "../../components/ui";
import { IMPERSONATING_KEY, usePlatformAuth } from "../../platformAuth";
import { fmtCurrency, fmtCurrencyCents, fmtDate, fmtDateTime } from "../../lib/format";

type FinopsOrg = {
  revenue_cents: number;
  costs: { llm: number; embedding: number; storage: number; infra: number };
  gross_profit: number;
  gross_margin_pct: number | null;
};

type Detail = {
  id: string;
  name: string;
  company_name: string | null;
  email: string | null;
  status: string;
  plan: string | null;
  subscription_status: string | null;
  started: string | null;
  mrr_cents: number;
  users: number;
  agents: number;
  requests_30d: number;
  ai_cost_30d: number;
  margin: number | null;
  payment_provider: string | null;
  amount_due_cents: number;
  next_renewal_at: string | null;
};

type Health = {
  score: number;
  label: string;
  requests_30d: number;
  tokens_30d: number;
  cost_30d: number;
  errors_7d: number;
  subscription_status: string | null;
  organization_status: string;
};

type TenantUser = { id: string; email: string | null; roles: string[]; last_active_at: string | null };
type TenantAgent = { id: string; name: string; model: string | null; is_active: boolean; deployments: number; created_at: string | null };
type TenantSource = { id: string; name: string; type: string; status: string | null; last_success_at: string | null; created_at: string | null };
type TenantBilling = {
  subscription: { id: string; plan: string; status: string; interval: string; period_start: string | null; period_end: string | null; auto_renew: boolean } | null;
  invoices: { id: string; status: string; total_cents: number; paid_at: string | null; created_at: string | null }[];
};
type TenantKey = { id: string; name: string; prefix: string; scopes: string[]; is_active: boolean; last_used_at: string | null; expires_at: string | null; created_at: string | null };
type AuditEntry = { actor_user_id: string | null; action: string; resource_type: string; resource_id: string | null; created_at: string | null; metadata: Record<string, unknown> };

const TABS = ["Overview", "Timeline", "Users", "Agents", "Data Sources", "Costs", "Billing", "Security", "Audit"] as const;
type Tab = (typeof TABS)[number];

export default function AdminCustomerDetailPage() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<Tab>("Overview");
  const [data, setData] = useState<Detail | null>(null);
  const [finops, setFinops] = useState<FinopsOrg | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [agents, setAgents] = useState<TenantAgent[]>([]);
  const [sources, setSources] = useState<TenantSource[]>([]);
  const [billing, setBilling] = useState<TenantBilling | null>(null);
  const [keys, setKeys] = useState<TenantKey[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmAction, setConfirmAction] = useState<"" | "pause" | "suspend" | "cancel" | "reset">("");
  const [impersonateConfirm, setImpersonateConfirm] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    if (!moreOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMoreOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  async function loadBase() {
    if (!session || !orgId) return;
    const d = await platformApi<Detail>(`/api/v1/platform/organizations/${orgId}`, {
      token: session.token,
    });
    setData(d);
    const f = await platformApi<FinopsOrg>(`/api/v1/platform/finops/organizations/${orgId}`, {
      token: session.token,
    });
    setFinops(f);
    const h = await platformApi<Health>(`/api/v1/platform/tenants/${orgId}/health`, {
      token: session.token,
    });
    setHealth(h);
  }

  async function loadTab(next: Tab) {
    if (!session || !orgId) return;
    if (next === "Users") {
      setUsers((await platformApi<{ users: TenantUser[] }>(`/api/v1/platform/organizations/${orgId}/users`, { token: session.token })).users || []);
    } else if (next === "Agents") {
      setAgents((await platformApi<{ agents: TenantAgent[] }>(`/api/v1/platform/organizations/${orgId}/agents`, { token: session.token })).agents || []);
    } else if (next === "Data Sources") {
      const d = await platformApi<{ sources: TenantSource[] }>(`/api/v1/platform/organizations/${orgId}/sources`, { token: session.token });
      setSources(d.sources || []);
    } else if (next === "Billing") {
      setBilling(await platformApi<TenantBilling>(`/api/v1/platform/organizations/${orgId}/billing`, { token: session.token }));
    } else if (next === "Security") {
      setKeys((await platformApi<{ api_keys: TenantKey[] }>(`/api/v1/platform/organizations/${orgId}/security`, { token: session.token })).api_keys || []);
    } else if (next === "Audit") {
      setAudit((await platformApi<{ entries: AuditEntry[] }>(`/api/v1/platform/organizations/${orgId}/audit`, { token: session.token })).entries || []);
    } else if (next === "Timeline") {
      await loadTimeline();
    }
  }

  async function loadTimeline() {
    if (!session || !orgId) return;
    setTimelineLoading(true);
    try {
      const [aud, bil, ops, sec, us, not] = await Promise.all([
        platformApi<{ entries: AuditEntry[] }>(`/api/v1/platform/organizations/${orgId}/audit`, { token: session.token }).catch(() => ({ entries: [] })),
        platformApi<TenantBilling>(`/api/v1/platform/organizations/${orgId}/billing`, { token: session.token }).catch(() => null),
        platformApi<{ jobs: { id: string; job_type: string; status: string; organization_id: string; created_at: string; error_summary: string | null }[] }>("/api/v1/platform/operations", { token: session.token }).catch(() => ({ jobs: [] })),
        platformApi<{ api_keys: TenantKey[] }>(`/api/v1/platform/organizations/${orgId}/security`, { token: session.token }).catch(() => ({ api_keys: [] })),
        platformApi<{ users: TenantUser[] }>(`/api/v1/platform/organizations/${orgId}/users`, { token: session.token }).catch(() => ({ users: [] })),
        platformApi<{ notifications: { id: string; title: string; organization_id: string | null; created_at: string | null }[] }>("/api/v1/platform/notifications", { token: session.token }).catch(() => ({ notifications: [] })),
      ]);
      const items: TimelineItem[] = [];
      (aud.entries || []).forEach((e, i) => {
        if (!e.created_at) return;
        items.push({
          id: `audit-${i}`,
          at: e.created_at,
          title: e.action,
          detail: e.resource_type ? `${e.resource_type}${e.resource_id ? ` · ${e.resource_id.slice(0, 8)}` : ""}` : undefined,
          kind: "audit",
          tone: e.action.includes("delete") || e.action.includes("cancel") || e.action.includes("suspend") ? "danger" : "default",
        });
      });
      (bil?.invoices || []).forEach((inv, i) => {
        if (!inv.created_at) return;
        items.push({
          id: `invoice-${i}`,
          at: inv.created_at,
          title: `Factura ${inv.status}`,
          detail: `$${fmtCurrencyCents(inv.total_cents)}`,
          kind: "billing",
          tone: inv.status === "paid" ? "ok" : inv.status === "open" || inv.status === "draft" ? "warn" : "default",
        });
      });
      (ops.jobs || [])
        .filter((j) => j.organization_id === orgId)
        .forEach((j, i) => {
          if (!j.created_at) return;
          items.push({
            id: `job-${i}`,
            at: j.created_at,
            title: `Sync ${j.job_type} ${j.status}`,
            detail: j.error_summary ? j.error_summary.slice(0, 140) : undefined,
            kind: "job",
            tone: j.status === "failed" || j.status === "dead" ? "danger" : j.status === "completed" ? "ok" : "default",
          });
        });
      (sec.api_keys || []).forEach((k, i) => {
        if (!k.created_at) return;
        items.push({
          id: `key-${i}`,
          at: k.created_at,
          title: `API key creada: ${k.name}`,
          detail: k.scopes.join(", ") || undefined,
          kind: "key",
        });
      });
      (us.users || []).forEach((u, i) => {
        if (!u.last_active_at) return;
        items.push({
          id: `user-${i}`,
          at: u.last_active_at,
          title: `Actividad de ${u.email || u.id.slice(0, 8)}`,
          kind: "user",
        });
      });
      (not.notifications || [])
        .filter((n) => n.organization_id === orgId)
        .forEach((n, i) => {
          if (!n.created_at) return;
          items.push({
            id: `notif-${i}`,
            at: n.created_at,
            title: n.title,
            kind: "notification",
            tone: "warn",
          });
        });
      setTimeline(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando timeline");
    } finally {
      setTimelineLoading(false);
    }
  }

  useEffect(() => {
    if (!session || !orgId) return;
    (async () => {
      try {
        await loadBase();
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando ficha");
      }
    })();
  }, [session, orgId]);

  useEffect(() => {
    if (!session || !orgId || tab === "Overview" || tab === "Costs") return;
    loadTab(tab).catch((e) => setError(e instanceof Error ? e.message : "Error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, tab]);

  async function run(path: string, action: string) {
    if (!session || !orgId) return;
    setBusy(action);
    setError("");
    try {
      await platformApi(`/api/v1/platform/organizations/${orgId}/${path}`, {
        method: "POST",
        token: session.token,
        body: path === "plan" ? undefined : "{}",
      });
      await loadBase();
      setConfirmAction("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "La acción falló");
    } finally {
      setBusy("");
    }
  }

  async function impersonate() {
    if (!session || !orgId || !data) return;
    setBusy("impersonate");
    setError("");
    try {
      const out = await platformApi<{ access_token: string }>(
        `/api/v1/platform/organizations/${orgId}/impersonate`,
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ expires_seconds: 3600 }),
        }
      );
      saveSession({
        token: out.access_token,
        organizationId: orgId,
        companyName: data.company_name || data.name,
        email: data.email || undefined,
      });
      localStorage.setItem(IMPERSONATING_KEY, data.company_name || data.name);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo impersonar");
    } finally {
      setBusy("");
    }
  }

  if (!data && !error) return <SkeletonBlock />;

  return (
    <div>
      <PageHeader
        title={data?.company_name || data?.name || "Tenant"}
        subtitle={data?.email || undefined}
        actions={
          <Link to="/control-center/tenants" className="btn btn-secondary min-h-11">
            Volver
          </Link>
        }
      />
      <ErrorInline message={error} />
      {data && health && (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border bg-surface px-4 py-3">
          <span className="badge badge-muted">Plan: {data.plan || "—"}</span>
          <StatusBadge status={data.subscription_status || data.status || "unknown"} />
          <TenantHealthBadge label={health.label} score={health.score} />
          <span className="mx-1 hidden h-4 w-px bg-border sm:inline-block" aria-hidden />
          <span className="text-xs text-muted">
            MRR <span className="mono font-medium text-text">{fmtCurrencyCents(data.mrr_cents, 0)}</span>
          </span>
          <span className="text-xs text-muted">
            {data.requests_30d} requests 30d
          </span>
          <span className="text-xs text-muted">
            AI cost <span className="mono font-medium text-text">{fmtCurrency(finops?.costs.llm ?? data.ai_cost_30d)}</span>
          </span>
          <span className="text-xs text-muted">
            margin{" "}
            <span className="mono font-medium text-text">
              {finops?.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"}
            </span>
          </span>
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-1" role="tablist" aria-label="Tenant 360">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`btn min-h-9 text-xs ${tab === t ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && data && (
        <>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Plan" value={data.plan || "—"} hint={data.subscription_status || ""} />
            <StatCard label="Pago" value={data.payment_provider || "manual"} />
            <StatCard label="Por pagar" value={fmtCurrencyCents(data.amount_due_cents, 0)} hint="Facturas draft u open" />
            <StatCard label="Próxima renovación" value={data.next_renewal_at ? fmtDate(data.next_renewal_at) : "—"} />
            <StatCard label="MRR" value={fmtCurrencyCents(data.mrr_cents, 0)} />
            <StatCard label="Usuarios" value={data.users} />
            <StatCard label="Agentes" value={data.agents} />
            <StatCard label="Requests 30d" value={data.requests_30d} />
            <StatCard label="AI cost 30d" value={fmtCurrency(finops?.costs.llm ?? data.ai_cost_30d)} />
            <StatCard label="Embeddings" value={fmtCurrency(finops?.costs.embedding ?? 0)} />
            <StatCard label="Revenue (cash)" value={finops ? fmtCurrencyCents(finops.revenue_cents, 0) : "—"} />
            <StatCard label="Gross margin" value={finops?.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"} />
          </div>
          <div className="panel">
            <h3 className="mb-2 text-sm font-semibold text-text">Acciones</h3>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-ghost min-h-9 text-xs"
                disabled={busy !== ""}
                onClick={() => setImpersonateConfirm(true)}
              >
                <UserSwitch size={14} aria-hidden />
                Impersonar
                <span className="badge badge-pending">privilegiada</span>
              </button>
              <div className="relative">
                <button
                  type="button"
                  className="btn btn-secondary min-h-9 text-xs"
                  disabled={busy !== ""}
                  aria-haspopup="menu"
                  aria-expanded={moreOpen}
                  onClick={() => setMoreOpen((v) => !v)}
                >
                  <CaretDown size={12} aria-hidden />
                  More actions
                </button>
                {moreOpen && (
                  <div
                    role="menu"
                    className="absolute left-0 z-30 mt-1.5 w-48 overflow-hidden rounded-md border border-border bg-raised shadow-pop"
                    aria-label="Acciones peligrosas"
                  >
                    {(["pause", "suspend", "cancel", "reset"] as const).map((a) => (
                      <button
                        key={a}
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted transition-colors hover:bg-soft hover:text-text"
                        onClick={() => {
                          setMoreOpen(false);
                          setConfirmAction(a);
                        }}
                      >
                        <WarningOctagon size={14} className="text-warn" aria-hidden />
                        {a === "reset" ? "Reset usage" : a[0].toUpperCase() + a.slice(1)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {tab === "Timeline" && (
        <div className="panel">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Timeline del tenant</h2>
          </div>
          {timelineLoading ? (
            <div className="p-5">
              <SkeletonBlock rows={5} />
            </div>
          ) : (
            <Timeline items={timeline} />
          )}
        </div>
      )}

      {tab === "Users" && (
        <div className="panel overflow-x-auto">
          {users.length === 0 ? (
            <EmptyState title="Sin usuarios" body="Este tenant no tiene miembros." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Roles</th>
                  <th>Última actividad</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="text-sm">{u.email || u.id}</td>
                    <td>
                      <span className="inline-flex flex-wrap gap-1">
                        {u.roles.map((r) => (
                          <RoleBadge key={r} role={r} />
                        ))}
                      </span>
                    </td>
                    <td className="text-sm text-muted">
                      {u.last_active_at ? fmtDateTime(u.last_active_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Agents" && (
        <div className="panel overflow-x-auto">
          {agents.length === 0 ? (
            <EmptyState title="Sin agentes" body="Este tenant no tiene agentes." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Modelo</th>
                  <th>Activo</th>
                  <th>Deployments healthy</th>
                  <th>Creado</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.id}>
                    <td className="text-sm">{a.name}</td>
                    <td className="font-mono text-xs text-muted">{a.model || "—"}</td>
                    <td className="text-sm">{a.is_active ? "sí" : "no"}</td>
                    <td className="text-sm">{a.deployments}</td>
                    <td className="text-sm text-muted">{a.created_at ? fmtDateTime(a.created_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Data Sources" && (
        <div className="panel overflow-x-auto">
          {sources.length === 0 ? (
            <EmptyState title="Sin fuentes" body="Este tenant no tiene fuentes de datos." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Fuente</th>
                  <th>Tipo</th>
                  <th>Estado</th>
                  <th>Última sync</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id}>
                    <td className="text-sm">{s.name}</td>
                    <td className="font-mono text-xs text-muted">{s.type}</td>
                    <td className="text-sm">{s.status || "—"}</td>
                    <td className="text-sm text-muted">{s.last_success_at ? fmtDateTime(s.last_success_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Costs" && finops && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Revenue (cash)" value={fmtCurrencyCents(finops.revenue_cents, 0)} />
          <StatCard label="LLM" value={fmtCurrency(finops.costs.llm)} />
          <StatCard label="Embeddings" value={fmtCurrency(finops.costs.embedding)} />
          <StatCard label="Storage" value={fmtCurrency(finops.costs.storage)} />
          <StatCard label="Infra" value={fmtCurrency(finops.costs.infra)} />
          <StatCard label="Gross profit" value={fmtCurrency(finops.gross_profit)} />
          <StatCard label="Gross margin" value={finops.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"} />
        </div>
      )}

      {tab === "Billing" && billing && (
        <div className="panel overflow-x-auto">
          {billing.subscription ? (
            <p className="mb-4 text-sm text-text">
              Plan <span className="font-semibold">{billing.subscription.plan}</span> · {billing.subscription.status} ·{" "}
              {billing.subscription.period_start ? fmtDate(billing.subscription.period_start) : "—"} →{" "}
              {billing.subscription.period_end ? fmtDate(billing.subscription.period_end) : "—"}
            </p>
          ) : (
            <p className="mb-4 text-sm text-muted">Sin suscripción activa.</p>
          )}
          {billing.invoices.length === 0 ? (
            <EmptyState title="Sin facturas" body="Este tenant no tiene facturas." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Factura</th>
                  <th>Estado</th>
                  <th>Total</th>
                  <th>Pagada</th>
                </tr>
              </thead>
              <tbody>
                {billing.invoices.map((inv) => (
                  <tr key={inv.id}>
                    <td className="font-mono text-xs">{inv.id.slice(0, 8)}</td>
                    <td className="text-sm">{inv.status}</td>
                    <td className="text-sm">${fmtCurrencyCents(inv.total_cents)}</td>
                    <td className="text-sm text-muted">{inv.paid_at ? fmtDateTime(inv.paid_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Security" && (
        <div className="panel overflow-x-auto">
          {keys.length === 0 ? (
            <EmptyState title="Sin API keys" body="Este tenant no tiene API keys." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Scopes</th>
                  <th>Activa</th>
                  <th>Último uso</th>
                  <th>Expira</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id}>
                    <td className="text-sm">{k.name} <span className="font-mono text-xs text-faint">({k.prefix}…)</span></td>
                    <td className="font-mono text-xs text-muted">{k.scopes.join(", ") || "—"}</td>
                    <td className="text-sm">{k.is_active ? "sí" : "no"}</td>
                    <td className="text-sm text-muted">{k.last_used_at ? fmtDateTime(k.last_used_at) : "—"}</td>
                    <td className="text-sm text-muted">{k.expires_at ? fmtDateTime(k.expires_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Audit" && (
        <div className="panel">
          {audit.length === 0 ? (
            <EmptyState title="Sin eventos" body="No hay eventos de auditoría para este tenant." />
          ) : (
            <RecentActivity items={audit} />
          )}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmAction}
        title={`Confirmar: ${confirmAction || ""}`}
        body={
          <p>
            Esta acción afecta al tenant{" "}
            <strong className="text-text">{data?.company_name || data?.name || ""}</strong>.{" "}
            {confirmAction === "cancel"
              ? "Cancelar detiene la suscripción. Se puede revertir manualmente."
              : confirmAction === "reset"
                ? "Reset de uso reinicia los contadores del período."
                : "Esta operación es reversible desde la ficha."}
          </p>
        }
        confirmLabel={confirmAction || "Confirmar"}
        busy={busy === confirmAction}
        onConfirm={() => {
          if (confirmAction) {
            void run(confirmAction === "reset" ? "usage/reset" : confirmAction, confirmAction);
          }
        }}
        onCancel={() => setConfirmAction("")}
      />

      <ConfirmDialog
        open={impersonateConfirm}
        title="Impersonar tenant"
        body={
          <p>
            Vas a entrar como <strong className="text-text">{data?.company_name || data?.name || ""}</strong>{" "}
            usando tu sesión de plataforma. Es una <strong className="text-text">operación privilegiada</strong> que
            queda registrada en auditoría. Cierra sesión del portal al terminar.
          </p>
        }
        confirmLabel="Impersonar"
        busy={busy === "impersonate"}
        onConfirm={() => void impersonate()}
        onCancel={() => setImpersonateConfirm(false)}
      />
    </div>
  );
}