import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { platformApi, saveSession } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  RecentActivity,
  RoleBadge,
  SkeletonBlock,
  StatCard,
  TenantHealthBadge,
} from "../../components/ui";
import { IMPERSONATING_KEY, usePlatformAuth } from "../../platformAuth";

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
type TenantKey = { id: string; name: string; prefix: string; scopes: string[]; is_active: boolean; last_used_at: string | null; expires_at: string | null };
type AuditEntry = { actor_user_id: string | null; action: string; resource_type: string; resource_id: string | null; created_at: string | null; metadata: Record<string, unknown> };

const TABS = ["Overview", "Users", "Agents", "Data Sources", "Costs", "Billing", "Security", "Audit"] as const;
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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<"" | "pause" | "suspend" | "cancel" | "reset">("");

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
      setConfirm("");
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
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <TenantHealthBadge label={health.label} score={health.score} />
          <span className="text-xs text-muted">
            {health.requests_30d} requests · {health.tokens_30d} tokens · {health.errors_7d} errores (7d)
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
            <StatCard label="Por pagar" value={`$${((data.amount_due_cents || 0) / 100).toFixed(0)}`} hint="Facturas draft u open" />
            <StatCard label="Próxima renovación" value={data.next_renewal_at ? new Date(data.next_renewal_at).toLocaleDateString("es-CL") : "—"} />
            <StatCard label="MRR" value={`$${(data.mrr_cents / 100).toFixed(0)}`} />
            <StatCard label="Usuarios" value={data.users} />
            <StatCard label="Agentes" value={data.agents} />
            <StatCard label="Requests 30d" value={data.requests_30d} />
            <StatCard label="AI cost 30d" value={`$${(finops?.costs.llm ?? data.ai_cost_30d).toFixed(2)}`} />
            <StatCard label="Embeddings" value={`$${(finops?.costs.embedding ?? 0).toFixed(2)}`} />
            <StatCard label="Revenue (cash)" value={finops ? `$${(finops.revenue_cents / 100).toFixed(0)}` : "—"} />
            <StatCard label="Gross margin" value={finops?.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"} />
          </div>
          <div className="panel">
            <h3 className="mb-2 text-sm font-semibold text-text">Acciones</h3>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-ghost min-h-9 text-xs" disabled={busy !== ""} onClick={() => void impersonate()}>
                Impersonar
              </button>
              {(["pause", "suspend", "cancel", "reset"] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  className="btn btn-ghost min-h-9 text-xs"
                  disabled={busy !== ""}
                  onClick={() => setConfirm(a)}
                >
                  {a}
                </button>
              ))}
            </div>
            {confirm && (
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-warn-soft bg-warn-soft/40 p-3">
                <p className="text-sm text-text">
                  ¿Confirmar <span className="font-semibold">{confirm}</span> para este tenant?
                </p>
                <button type="button" className="btn btn-danger min-h-8 text-xs" disabled={busy !== ""} onClick={() => void run(confirm === "reset" ? "usage/reset" : confirm, confirm)}>
                  {busy === confirm ? "Procesando…" : "Confirmar"}
                </button>
                <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => setConfirm("")}>
                  Cancelar
                </button>
              </div>
            )}
          </div>
        </>
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
                      {u.last_active_at ? new Date(u.last_active_at).toLocaleString("es-PE") : "—"}
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
                    <td className="text-sm text-muted">{a.created_at ? new Date(a.created_at).toLocaleString("es-PE") : "—"}</td>
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
                    <td className="text-sm text-muted">{s.last_success_at ? new Date(s.last_success_at).toLocaleString("es-PE") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "Costs" && finops && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Revenue (cash)" value={`$${(finops.revenue_cents / 100).toFixed(0)}`} />
          <StatCard label="LLM" value={`$${finops.costs.llm.toFixed(2)}`} />
          <StatCard label="Embeddings" value={`$${finops.costs.embedding.toFixed(2)}`} />
          <StatCard label="Storage" value={`$${finops.costs.storage.toFixed(2)}`} />
          <StatCard label="Infra" value={`$${finops.costs.infra.toFixed(2)}`} />
          <StatCard label="Gross profit" value={`$${finops.gross_profit.toFixed(2)}`} />
          <StatCard label="Gross margin" value={finops.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"} />
        </div>
      )}

      {tab === "Billing" && billing && (
        <div className="panel overflow-x-auto">
          {billing.subscription ? (
            <p className="mb-4 text-sm text-text">
              Plan <span className="font-semibold">{billing.subscription.plan}</span> · {billing.subscription.status} ·{" "}
              {billing.subscription.period_start ? new Date(billing.subscription.period_start).toLocaleDateString("es-PE") : "—"} →{" "}
              {billing.subscription.period_end ? new Date(billing.subscription.period_end).toLocaleDateString("es-PE") : "—"}
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
                    <td className="text-sm">${(inv.total_cents / 100).toFixed(2)}</td>
                    <td className="text-sm text-muted">{inv.paid_at ? new Date(inv.paid_at).toLocaleString("es-PE") : "—"}</td>
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
                    <td className="text-sm text-muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString("es-PE") : "—"}</td>
                    <td className="text-sm text-muted">{k.expires_at ? new Date(k.expires_at).toLocaleString("es-PE") : "—"}</td>
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
    </div>
  );
}