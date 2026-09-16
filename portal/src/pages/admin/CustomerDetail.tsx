import {
  ArrowLeft,
  CaretDown,
  ClockCounterClockwise,
  Database,
  Key,
  Receipt,
  Robot,
  UserSwitch,
  UsersThree,
  WarningOctagon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { platformApi } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Timeline, type TimelineItem } from "../../components/Timeline";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  Menu,
  MenuItem,
  PageHeader,
  Panel,
  PanelHeader,
  RecentActivity,
  RoleBadge,
  SkeletonBlock,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TenantHealthBadge,
  menuItemClass,
  type Column,
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
  factors: { key: string; label: string; score: number; weight: number; status: string; detail: string }[];
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

const ACTIONS = ["pause", "suspend", "cancel", "reset"] as const;

export default function AdminCustomerDetailPage() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const { session } = usePlatformAuth();
  const { applySession } = useAuth();
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
  const [impersonateReason, setImpersonateReason] = useState("");
  const [impersonateTicket, setImpersonateTicket] = useState("");

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
      // FASE 03 (S12): timeline server-side con deployments/feedback/spikes.
      const server = await platformApi<{
        items: { id: string; at: string; kind: string; title: string; detail?: string; tone?: string }[];
        spikes: { kind: string; at: string; detail: string; tone: string }[];
      }>(`/api/v1/platform/organizations/${orgId}/timeline`, { token: session.token }).catch(() => ({ items: [], spikes: [] }));

      const items: TimelineItem[] = (server.items || []).map((e) => ({
        id: e.id,
        at: e.at,
        title: e.title,
        detail: e.detail || undefined,
        kind: (e.kind as TimelineItem["kind"]) || "audit",
        tone: (e.tone as TimelineItem["tone"]) || "default",
      }));
      (server.spikes || []).forEach((s, i) => {
        items.push({
          id: `spike-${i}`,
          at: s.at,
          title: s.kind === "error_spike" ? "Spike de errores" : "Spike de costo",
          detail: s.detail,
          kind: "spike",
          tone: (s.tone as TimelineItem["tone"]) || "warn",
        });
      });

      // Extras que el endpoint no cubre: keys, users, notifications.
      const [sec, us, not] = await Promise.all([
        platformApi<{ api_keys: TenantKey[] }>(`/api/v1/platform/organizations/${orgId}/security`, { token: session.token }).catch(() => ({ api_keys: [] })),
        platformApi<{ users: TenantUser[] }>(`/api/v1/platform/organizations/${orgId}/users`, { token: session.token }).catch(() => ({ users: [] })),
        platformApi<{ notifications: { id: string; title: string; organization_id: string | null; created_at: string | null }[] }>("/api/v1/platform/notifications", { token: session.token }).catch(() => ({ notifications: [] })),
      ]);
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
      items.sort((a, b) => (a.at < b.at ? 1 : -1));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    if (!impersonateReason.trim()) {
      setError("El motivo es obligatorio para impersonar.");
      return;
    }
    setBusy("impersonate");
    setError("");
    try {
      const out = await platformApi<{ access_token: string; expires_seconds?: number }>(
        `/api/v1/platform/organizations/${orgId}/impersonate`,
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({
            expires_seconds: 3600,
            reason: impersonateReason.trim(),
            ticket: impersonateTicket.trim() || null,
          }),
        }
      );
      applySession({
        token: out.access_token,
        organizationId: orgId,
        companyName: data.company_name || data.name,
        email: data.email || undefined,
      });
      // Metadatos de la impersonación (no sensibles) para el banner.
      sessionStorage.setItem(IMPERSONATING_KEY, data.company_name || data.name);
      sessionStorage.setItem(
        "zent_impersonation_meta",
        JSON.stringify({
          tenant: data.company_name || data.name,
          reason: impersonateReason.trim(),
          expiresAt: Math.floor(Date.now() / 1000) + (out.expires_seconds || 3600),
        })
      );
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo impersonar");
    } finally {
      setBusy("");
    }
  }

  const userColumns: Column<TenantUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => <span className="text-text">{u.email || u.id}</span>,
    },
    {
      key: "roles",
      header: "Roles",
      render: (u) => (
        <span className="inline-flex flex-wrap gap-1">
          {u.roles.map((r) => (
            <RoleBadge key={r} role={r} />
          ))}
        </span>
      ),
    },
    {
      key: "last",
      header: "Última actividad",
      hideBelow: "md",
      render: (u) => (
        <span className="text-muted">{u.last_active_at ? fmtDateTime(u.last_active_at) : "—"}</span>
      ),
    },
  ];

  const agentColumns: Column<TenantAgent>[] = [
    { key: "name", header: "Nombre", render: (a) => a.name },
    {
      key: "model",
      header: "Modelo",
      hideBelow: "md",
      render: (a) => <span className="mono text-xs text-muted">{a.model || "—"}</span>,
    },
    {
      key: "state",
      header: "Estado",
      render: (a) => (
        <Badge tone={a.is_active ? "ok" : "neutral"}>{a.is_active ? "Activo" : "Inactivo"}</Badge>
      ),
    },
    {
      key: "deployments",
      header: "Deployments healthy",
      align: "right",
      render: (a) => <span className="mono">{a.deployments}</span>,
    },
    {
      key: "created",
      header: "Creado",
      hideBelow: "lg",
      render: (a) => <span className="text-muted">{a.created_at ? fmtDateTime(a.created_at) : "—"}</span>,
    },
  ];

  const sourceColumns: Column<TenantSource>[] = [
    { key: "name", header: "Fuente", render: (s) => s.name },
    {
      key: "type",
      header: "Tipo",
      render: (s) => <span className="mono text-xs text-muted">{s.type}</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (s) => (s.status ? <StatusBadge status={s.status} /> : <span className="text-muted">—</span>),
    },
    {
      key: "last",
      header: "Última sync",
      hideBelow: "md",
      render: (s) => (
        <span className="text-muted">{s.last_success_at ? fmtDateTime(s.last_success_at) : "—"}</span>
      ),
    },
  ];

  const keyColumns: Column<TenantKey>[] = [
    {
      key: "name",
      header: "Key",
      render: (k) => (
        <span>
          {k.name} <span className="mono text-xs text-faint">({k.prefix}…)</span>
        </span>
      ),
    },
    {
      key: "scopes",
      header: "Scopes",
      hideBelow: "lg",
      render: (k) => <span className="mono text-xs text-muted">{k.scopes.join(", ") || "—"}</span>,
    },
    {
      key: "active",
      header: "Estado",
      render: (k) => (
        <Badge tone={k.is_active ? "ok" : "neutral"}>{k.is_active ? "Activa" : "Inactiva"}</Badge>
      ),
    },
    {
      key: "last",
      header: "Último uso",
      hideBelow: "md",
      render: (k) => (
        <span className="text-muted">{k.last_used_at ? fmtDateTime(k.last_used_at) : "—"}</span>
      ),
    },
    {
      key: "expires",
      header: "Expira",
      hideBelow: "xl",
      render: (k) => (
        <span className="text-muted">{k.expires_at ? fmtDateTime(k.expires_at) : "—"}</span>
      ),
    },
  ];

  const invoiceColumns: Column<TenantBilling["invoices"][number]>[] = [
    {
      key: "id",
      header: "Factura",
      render: (inv) => <span className="mono text-xs">{inv.id.slice(0, 8)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      render: (inv) => <StatusBadge status={inv.status} />,
    },
    {
      key: "total",
      header: "Total",
      align: "right",
      render: (inv) => <span className="mono">{fmtCurrencyCents(inv.total_cents)}</span>,
    },
    {
      key: "paid",
      header: "Pagada",
      hideBelow: "md",
      render: (inv) => (
        <span className="text-muted">{inv.paid_at ? fmtDateTime(inv.paid_at) : "—"}</span>
      ),
    },
  ];

  if (!data && !error) return <SkeletonBlock />;

  const riskyFactors = (health?.factors ?? []).filter((f) => f.status !== "ok");
  const company = data?.company_name || data?.name || "Tenant";

  return (
    <div>
      <PageHeader
        title={company}
        subtitle={data?.email || undefined}
        actions={
          <ButtonLink variant="secondary" to="/control-center/tenants" leadingIcon={ArrowLeft}>
            Volver
          </ButtonLink>
        }
      />
      <ErrorInline message={error} />

      {data && health && (
        <Panel className="mb-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Badge tone="neutral">Plan: {data.plan || "—"}</Badge>
            <StatusBadge status={data.subscription_status || data.status || "unknown"} />
            <TenantHealthBadge label={health.label} score={health.score} />
            {health.factors && health.factors.length > 0 && (
              <span
                className="cursor-help rounded-xs border border-border bg-soft px-2 py-1 text-[11px] text-muted"
                title={health.factors
                  .map((f) => `${f.label}: ${f.detail}${f.status !== "ok" ? " ✗" : " ✓"}`)
                  .join("\n")}
              >
                {riskyFactors.length} factor(es) a revisar
              </span>
            )}
            <span className="mx-1 hidden h-4 w-px bg-border sm:inline-block" aria-hidden />
            <span className="text-xs text-muted">
              MRR <span className="mono font-medium text-text">{fmtCurrencyCents(data.mrr_cents, 0)}</span>
            </span>
            <span className="text-xs text-muted">{data.requests_30d} requests 30d</span>
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
        </Panel>
      )}

      {riskyFactors.length > 0 && (
        <Panel className="mb-3">
          <PanelHeader
            title={`Health ${health?.score}/100 · Factores`}
            description="Factores que restan puntaje, ordenados por peso."
          />
          <ul className="grid grid-cols-1 gap-1.5 p-4 sm:grid-cols-2">
            {riskyFactors.map((f) => (
              <li
                key={f.key}
                className="flex items-center justify-between gap-2 rounded-sm bg-soft px-2.5 py-1.5 text-[12px]"
              >
                <span className="text-text">{f.label}</span>
                <span className="flex items-center gap-2">
                  <Badge tone={f.status === "bad" ? "danger" : "warn"}>−{f.weight}</Badge>
                  <span className="mono text-muted">{f.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="mb-4">
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="Overview">
          {data && (
            <div className="flex flex-col gap-3">
              <MetricGrid cols={4}>
                <Metric size="md" label="Plan" value={data.plan || "—"} hint={data.subscription_status || undefined} />
                <Metric size="md" label="Pago" value={data.payment_provider || "manual"} />
                <Metric
                  size="md"
                  label="Por pagar"
                  value={fmtCurrencyCents(data.amount_due_cents, 0)}
                  hint="Facturas draft u open"
                />
                <Metric
                  size="md"
                  label="Próxima renovación"
                  value={data.next_renewal_at ? fmtDate(data.next_renewal_at) : "—"}
                />
                <Metric size="md" label="MRR" value={fmtCurrencyCents(data.mrr_cents, 0)} />
                <Metric size="md" label="Usuarios" value={data.users} />
                <Metric size="md" label="Agentes" value={data.agents} />
                <Metric size="md" label="Requests 30d" value={data.requests_30d} />
                <Metric size="md" label="AI cost 30d" value={fmtCurrency(finops?.costs.llm ?? data.ai_cost_30d)} />
                <Metric size="md" label="Embeddings" value={fmtCurrency(finops?.costs.embedding ?? 0)} />
                <Metric
                  size="md"
                  label="Revenue (cash)"
                  value={finops ? fmtCurrencyCents(finops.revenue_cents, 0) : "—"}
                />
                <Metric
                  size="md"
                  label="Gross margin"
                  value={finops?.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"}
                />
              </MetricGrid>

              <Panel>
                <PanelHeader
                  title="Acciones"
                  description="Operaciones sobre el tenant. Quedan registradas en auditoría."
                />
                <div className="flex flex-wrap items-center gap-2 p-4">
                  <Button
                    variant="ghost"
                    className="border border-border"
                    disabled={busy !== ""}
                    onClick={() => setImpersonateConfirm(true)}
                  >
                    <UserSwitch size={15} aria-hidden />
                    Impersonar
                    <Badge tone="warn">privilegiada</Badge>
                  </Button>
                  <Menu
                    label="Acciones del tenant"
                    trigger={
                      <Button variant="secondary" trailingIcon={CaretDown} disabled={busy !== ""}>
                        More actions
                      </Button>
                    }
                  >
                    {ACTIONS.map((a) => (
                      <MenuItem
                        key={a}
                        className={menuItemClass}
                        onSelect={() => setConfirmAction(a)}
                      >
                        <WarningOctagon size={14} className="text-warn" aria-hidden />
                        {a === "reset" ? "Reset usage" : a[0].toUpperCase() + a.slice(1)}
                      </MenuItem>
                    ))}
                  </Menu>
                </div>
              </Panel>
            </div>
          )}
        </TabsContent>

        <TabsContent value="Timeline">
          <Panel>
            <PanelHeader title="Timeline del tenant" description="Eventos reales del tenant en orden cronológico inverso." />
            {timelineLoading ? (
              <div className="p-4">
                <SkeletonBlock rows={5} />
              </div>
            ) : (
              <Timeline items={timeline} />
            )}
          </Panel>
        </TabsContent>

        <TabsContent value="Users">
          <DataTable
            columns={userColumns}
            rows={users}
            rowKey={(u) => u.id}
            caption="Usuarios del tenant"
            stickyHeader
            empty={
              <EmptyState
                icon={UsersThree}
                title="Sin usuarios"
                body="Este tenant no tiene miembros con acceso."
              />
            }
          />
        </TabsContent>

        <TabsContent value="Agents">
          <DataTable
            columns={agentColumns}
            rows={agents}
            rowKey={(a) => a.id}
            caption="Agentes del tenant"
            stickyHeader
            empty={
              <EmptyState
                icon={Robot}
                title="Sin agentes"
                body="Este tenant todavía no creó agentes."
              />
            }
          />
        </TabsContent>

        <TabsContent value="Data Sources">
          <DataTable
            columns={sourceColumns}
            rows={sources}
            rowKey={(s) => s.id}
            caption="Fuentes de datos del tenant"
            stickyHeader
            empty={
              <EmptyState
                icon={Database}
                title="Sin fuentes"
                body="Este tenant todavía no conectó fuentes de datos."
              />
            }
          />
        </TabsContent>

        <TabsContent value="Costs">
          {finops ? (
            <MetricGrid cols={4}>
              <Metric size="md" label="Revenue (cash)" value={fmtCurrencyCents(finops.revenue_cents, 0)} />
              <Metric size="md" label="LLM" value={fmtCurrency(finops.costs.llm)} />
              <Metric size="md" label="Embeddings" value={fmtCurrency(finops.costs.embedding)} />
              <Metric size="md" label="Storage" value={fmtCurrency(finops.costs.storage)} />
              <Metric size="md" label="Infra" value={fmtCurrency(finops.costs.infra)} />
              <Metric size="md" label="Gross profit" value={fmtCurrency(finops.gross_profit)} />
              <Metric
                size="md"
                label="Gross margin"
                value={finops.gross_margin_pct != null ? `${finops.gross_margin_pct.toFixed(1)}%` : "—"}
              />
            </MetricGrid>
          ) : (
            <Panel>
              <EmptyState
                title="Sin datos de costos"
                body="La API de FinOps no devolvió datos para este tenant."
              />
            </Panel>
          )}
        </TabsContent>

        <TabsContent value="Billing">
          <div className="flex flex-col gap-3">
            {billing?.subscription ? (
              <Panel className="flex flex-wrap items-center gap-x-3 gap-y-1 p-4 text-[13px]">
                <span className="text-muted">
                  Plan <span className="font-medium text-text">{billing.subscription.plan}</span>
                </span>
                <StatusBadge status={billing.subscription.status} />
                <span className="text-muted">
                  {billing.subscription.period_start ? fmtDate(billing.subscription.period_start) : "—"}
                  <span className="mx-1.5 text-ghost">–</span>
                  {billing.subscription.period_end ? fmtDate(billing.subscription.period_end) : "—"}
                </span>
              </Panel>
            ) : (
              billing && (
                <Panel className="p-4 text-[13px] text-muted">Sin suscripción activa.</Panel>
              )
            )}
            <DataTable
              columns={invoiceColumns}
              rows={billing?.invoices ?? []}
              rowKey={(inv) => inv.id}
              caption="Facturas del tenant"
              stickyHeader
              empty={
                <EmptyState
                  icon={Receipt}
                  title="Sin facturas"
                  body="Este tenant no tiene facturas emitidas."
                />
              }
            />
          </div>
        </TabsContent>

        <TabsContent value="Security">
          <DataTable
            columns={keyColumns}
            rows={keys}
            rowKey={(k) => k.id}
            caption="API keys del tenant"
            stickyHeader
            empty={
              <EmptyState
                icon={Key}
                title="Sin API keys"
                body="Este tenant no tiene API keys emitidas."
              />
            }
          />
        </TabsContent>

        <TabsContent value="Audit">
          <Panel>
            <PanelHeader
              title="Auditoría"
              description="Eventos registrados para este tenant, más recientes primero."
            />
            {audit.length === 0 ? (
              <EmptyState
                icon={ClockCounterClockwise}
                title="Sin eventos"
                body="No hay eventos de auditoría para este tenant."
              />
            ) : (
              <div className="px-4 py-1">
                <RecentActivity items={audit} />
              </div>
            )}
          </Panel>
        </TabsContent>
      </Tabs>

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
                : confirmAction === "suspend"
                  ? "Suspend bloqueará requests, logins y deployments del tenant."
                  : "Esta operación es reversible desde la ficha."}
          </p>
        }
        confirmLabel={confirmAction || "Confirmar"}
        confirmText={confirmAction === "suspend" ? "SUSPEND" : confirmAction === "cancel" ? "CANCEL" : undefined}
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
          <div className="space-y-3">
            <p>
              Vas a entrar como <strong className="text-text">{data?.company_name || data?.name || ""}</strong>{" "}
              usando tu sesión de plataforma. Es una <strong className="text-text">operación privilegiada</strong> que
              queda registrada en auditoría con el motivo. La sesión del admin real nunca se pierde.
            </p>
            <Field label="Motivo (obligatorio)" required>
              <Input
                value={impersonateReason}
                onChange={(e) => setImpersonateReason(e.target.value)}
                placeholder="Ej. Soporte: usuario reportó acceso caído"
              />
            </Field>
            <Field label="Ticket de soporte (opcional)">
              <Input
                value={impersonateTicket}
                onChange={(e) => setImpersonateTicket(e.target.value)}
                placeholder="SUP-1234"
              />
            </Field>
            <p className="text-xs text-faint">Duración máxima: 1 hora. Expira automáticamente.</p>
          </div>
        }
        confirmLabel="Impersonar"
        busy={busy === "impersonate"}
        onConfirm={() => void impersonate()}
        onCancel={() => setImpersonateConfirm(false)}
      />
    </div>
  );
}
