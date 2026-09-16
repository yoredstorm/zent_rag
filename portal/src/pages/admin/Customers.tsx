import { Buildings, MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  ResultCount,
  Skeleton,
  StatusBadge,
  cn,
  type Column,
  type SortState,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Org = {
  id: string;
  name: string;
  company_name: string | null;
  email: string | null;
  status: string;
  subscription_status: string | null;
  plan: string | null;
  is_trial: boolean;
  payment_provider: string | null;
  amount_due_cents: number;
  next_renewal_at: string | null;
};

const FILTERS: { id: string; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "trialing", label: "Trial" },
  { id: "active", label: "Active" },
  { id: "past_due", label: "Past due" },
  { id: "paused", label: "Paused/canceled" },
];

const PAGE_SIZE = 25;

type OrgDetail = {
  id: string;
  plan: string | null;
  subscription_status: string | null;
  status: string;
  users: number;
  agents: number;
  requests_30d: number;
  mrr_cents: number;
  amount_due_cents: number;
  next_renewal_at: string | null;
};

function usdCents(cents: number) {
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function matchesFilter(org: Org, filter: string) {
  const status = org.subscription_status || "";
  if (filter === "all") return true;
  if (filter === "trialing") return status === "trialing" || org.is_trial;
  if (filter === "active") return status === "active";
  if (filter === "past_due") return status === "past_due";
  if (filter === "paused") {
    return status === "paused" || status === "canceled" || status === "suspended" || status === "expired";
  }
  return true;
}

function sortValue(org: Org, key: string): string | number {
  switch (key) {
    case "name":
      return (org.company_name || org.name).toLowerCase();
    case "email":
      return (org.email || "").toLowerCase();
    case "plan":
      return (org.plan || "").toLowerCase();
    case "status":
      return (org.subscription_status || org.status || "").toLowerCase();
    case "provider":
      return (org.payment_provider || "").toLowerCase();
    case "due":
      return org.amount_due_cents || 0;
    case "renewal":
      return org.next_renewal_at ? new Date(org.next_renewal_at).getTime() : Number.POSITIVE_INFINITY;
    default:
      return "";
  }
}

export default function AdminCustomersPage() {
  const { session } = usePlatformAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const [page, setPage] = useState(1);
  const [peek, setPeek] = useState<Org | null>(null);
  const [peekData, setPeekData] = useState<OrgDetail | null>(null);
  const [peekLoading, setPeekLoading] = useState(false);
  const [peekError, setPeekError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      try {
        const data = await platformApi<{ organizations: Org[] }>(
          "/api/v1/platform/organizations",
          { token: session.token }
        );
        setOrgs(data.organizations || []);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando clientes");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  useEffect(() => {
    setPage(1);
  }, [query, filter]);

  async function openPeek(org: Org) {
    if (!session) return;
    setPeek(org);
    setPeekData(null);
    setPeekError("");
    setPeekLoading(true);
    try {
      setPeekData(
        await platformApi<OrgDetail>(`/api/v1/platform/organizations/${org.id}`, {
          token: session.token,
        })
      );
    } catch (err) {
      setPeekError(err instanceof Error ? err.message : "Error cargando el resumen");
    } finally {
      setPeekLoading(false);
    }
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = orgs.filter((o) => {
      if (!matchesFilter(o, filter)) return false;
      if (!q) return true;
      const hay = `${o.company_name || ""} ${o.name} ${o.email || ""}`.toLowerCase();
      return hay.includes(q);
    });
    if (!sort) return filtered;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [orgs, query, filter, sort]);

  const paged = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const columns: Column<Org>[] = [
    {
      key: "name",
      header: "Empresa",
      sortable: true,
      render: (o) => (
        <Link
          className="font-medium text-accent hover:underline"
          to={`/control-center/tenants/${o.id}`}
          onClick={(e) => e.stopPropagation()}
        >
          {o.company_name || o.name}
        </Link>
      ),
    },
    {
      key: "email",
      header: "Email",
      sortable: true,
      hideBelow: "lg",
      render: (o) => <span className="text-muted">{o.email || "—"}</span>,
    },
    { key: "plan", header: "Plan", sortable: true, render: (o) => o.plan || "—" },
    {
      key: "status",
      header: "Suscripción",
      sortable: true,
      render: (o) => <StatusBadge status={o.subscription_status || o.status} />,
    },
    {
      key: "provider",
      header: "Provider",
      sortable: true,
      hideBelow: "lg",
      render: (o) => <span className="text-muted">{o.payment_provider || "manual"}</span>,
    },
    {
      key: "due",
      header: "Por pagar",
      align: "right",
      sortable: true,
      render: (o) => <span className="mono">{usdCents(o.amount_due_cents || 0)}</span>,
    },
    {
      key: "renewal",
      header: "Próxima renovación",
      sortable: true,
      hideBelow: "md",
      render: (o) => (
        <span className="text-muted">
          {o.next_renewal_at ? new Date(o.next_renewal_at).toLocaleDateString("es-CL") : "—"}
        </span>
      ),
    },
  ];

  const filtered = query.trim() !== "" || filter !== "all";

  return (
    <div>
      <PageHeader title="Clientes" subtitle="Organizaciones de la plataforma." />
      <DataTable
        columns={columns}
        rows={paged}
        rowKey={(o) => o.id}
        caption="Organizaciones de la plataforma"
        loading={loading}
        error={error || null}
        empty={
          filtered ? (
            <EmptyState
              icon={MagnifyingGlass}
              title="Sin resultados"
              body="Ninguna organización coincide con la búsqueda o el filtro activo."
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                  }}
                >
                  Limpiar filtros
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={Buildings}
              title="Sin organizaciones"
              body="Todavía ninguna organización se registró en la plataforma."
            />
          )
        }
        sort={sort}
        onSortChange={setSort}
        stickyHeader
        onRowClick={(o) => void openPeek(o)}
        toolbar={
          <>
            <Input
              type="search"
              icon={MagnifyingGlass}
              aria-label="Buscar empresa o email"
              placeholder="Buscar empresa o email"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="max-w-sm"
            />
            <div
              role="group"
              aria-label="Filtrar por suscripción"
              className="inline-flex flex-wrap items-center gap-0.5 rounded-md border border-border bg-soft p-0.5"
            >
              {FILTERS.map((f) => {
                const active = filter === f.id;
                return (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setFilter(f.id)}
                    className={cn(
                      "min-h-8 cursor-pointer rounded-sm px-3 text-[13px] font-medium transition-colors duration-150",
                      active ? "bg-surface text-text shadow-panel" : "text-muted hover:text-text"
                    )}
                  >
                    {f.label}
                  </button>
                );
              })}
            </div>
          </>
        }
        footer={
          visible.length > 0 ? (
            <>
              <ResultCount shown={paged.length} total={visible.length} noun="organizaciones" />
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={visible.length}
                onPageChange={setPage}
              />
            </>
          ) : null
        }
      />

      <Drawer
        open={!!peek}
        onOpenChange={(open) => {
          if (!open) setPeek(null);
        }}
        title={peek ? peek.company_name || peek.name : "Tenant"}
        description={peek?.email || undefined}
        width={420}
        footer={
          peek && (
            <ButtonLink
              variant="primary"
              size="sm"
              to={`/control-center/tenants/${peek.id}`}
            >
              Ver ficha 360
            </ButtonLink>
          )
        }
      >
        {peekLoading ? (
          <Skeleton className="h-[180px] rounded-lg" />
        ) : (
          <>
            <ErrorInline message={peekError} />
            {peekData && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">Plan: {peekData.plan || "—"}</Badge>
                  <StatusBadge status={peekData.subscription_status || peekData.status} />
                </div>
                <MetricGrid cols={2}>
                  <Metric size="md" label="MRR" value={usdCents(peekData.mrr_cents)} />
                  <Metric size="md" label="Por pagar" value={usdCents(peekData.amount_due_cents)} />
                  <Metric size="md" label="Usuarios" value={peekData.users} />
                  <Metric size="md" label="Agentes" value={peekData.agents} />
                  <Metric size="md" label="Requests 30d" value={peekData.requests_30d} />
                  <Metric
                    size="md"
                    label="Próxima renovación"
                    value={
                      peekData.next_renewal_at
                        ? new Date(peekData.next_renewal_at).toLocaleDateString("es-CL")
                        : "—"
                    }
                  />
                </MetricGrid>
              </div>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}
