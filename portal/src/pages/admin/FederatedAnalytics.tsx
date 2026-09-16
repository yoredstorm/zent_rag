import { ChartBar, Download, MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  SectionHeader,
  Skeleton,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtCurrency, fmtDateTime, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Totals = {
  requests: number;
  errors: number;
  error_rate_pct: number;
  tokens: number;
  cost: number;
};

type OrgRow = {
  organization_id: string;
  requests: number;
  errors: number;
  error_rate_pct: number;
  tokens: number;
  cost: number;
  agents: number;
  knowledge_bases: number;
  deployments: number;
  last_activity: string | null;
};

type Federated = { period_days: number; totals: Totals; by_organization: OrgRow[] };

const numeric = (row: OrgRow, key: string): number => {
  switch (key) {
    case "errors":
      return row.errors;
    case "error_rate_pct":
      return row.error_rate_pct;
    case "tokens":
      return row.tokens;
    case "cost":
      return row.cost;
    case "agents":
      return row.agents;
    case "knowledge_bases":
      return row.knowledge_bases;
    case "deployments":
      return row.deployments;
    default:
      return row.requests;
  }
};

export default function AdminFederatedAnalyticsPage() {
  const { session } = usePlatformAuth();
  const [data, setData] = useState<Federated | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "requests", dir: "desc" });

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Federated>("/api/v1/platform/analytics/federated", {
        token: session.token,
      });
      setData(d);
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

  async function exportCsv() {
    if (!session) return;
    setError("");
    try {
      const out = await platformApi<{ payload: string; filename: string; content_type: string }>(
        "/api/v1/platform/analytics/federated?format=csv",
        { token: session.token }
      );
      const blob = new Blob([out.payload], { type: out.content_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = out.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const rows = useMemo(() => {
    const list = [...(data?.by_organization ?? [])];
    if (!sort) return list;
    if (sort.key === "organization_id") {
      return list.sort((a, b) =>
        sort.dir === "asc"
          ? a.organization_id.localeCompare(b.organization_id)
          : b.organization_id.localeCompare(a.organization_id)
      );
    }
    return list.sort((a, b) =>
      sort.dir === "asc"
        ? numeric(a, sort.key) - numeric(b, sort.key)
        : numeric(b, sort.key) - numeric(a, sort.key)
    );
  }, [data?.by_organization, sort]);

  const maxRequests = Math.max(1, ...(data?.by_organization ?? []).map((o) => o.requests));

  const columns: Column<OrgRow>[] = [
    {
      key: "organization_id",
      header: "Organización",
      sortable: true,
      render: (row) => (
        <span className="mono text-xs text-faint" title={row.organization_id}>
          {row.organization_id.slice(0, 13)}…
        </span>
      ),
    },
    {
      key: "requests",
      header: "Requests",
      align: "right",
      sortable: true,
      width: "180px",
      render: (row) => (
        <span className="flex items-center justify-end gap-2">
          <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-track" aria-hidden>
            <span
              className="block h-full rounded-full bg-accent/70"
              style={{ width: `${(row.requests / maxRequests) * 100}%` }}
            />
          </span>
          <span className="mono text-xs text-muted">{fmtNum(row.requests)}</span>
        </span>
      ),
    },
    {
      key: "error_rate_pct",
      header: "Error %",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => (
        <span className={`mono text-xs ${row.error_rate_pct > 0 ? "text-warn" : "text-muted"}`}>
          {row.error_rate_pct}%
        </span>
      ),
    },
    {
      key: "tokens",
      header: "Tokens",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "130px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.tokens)}</span>,
    },
    {
      key: "cost",
      header: "Costo",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost)}</span>,
    },
    {
      key: "agents",
      header: "Agentes",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.agents)}</span>,
    },
    {
      key: "knowledge_bases",
      header: "KBs",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "90px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.knowledge_bases)}</span>,
    },
    {
      key: "deployments",
      header: "Deploys",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.deployments)}</span>,
    },
    {
      key: "last_activity",
      header: "Última actividad",
      align: "right",
      hideBelow: "xl",
      width: "170px",
      render: (row) => <span className="text-xs text-muted">{fmtDateTime(row.last_activity)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Federated Analytics"
        subtitle="Métricas multi-tenant agregadas (30d) con drill-down por organización."
        actions={
          <Button variant="secondary" leadingIcon={Download} onClick={() => void exportCsv()}>
            Export CSV
          </Button>
        }
      />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[280px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
            <Metric
              label="Requests (30d)"
              value={(data?.totals.requests ?? 0).toLocaleString()}
              hint={`${(data?.by_organization ?? []).length} organizaciones con la ventana`}
              icon={ChartBar}
            />
            <MetricGrid cols={3} className="lg:grid-cols-3">
              <Metric label="Tokens" value={(data?.totals.tokens ?? 0).toLocaleString()} size="md" />
              <Metric label="Costo" value={fmtCurrency(data?.totals.cost ?? 0)} size="md" />
              <Metric
                label="Error rate"
                value={`${data?.totals.error_rate_pct ?? 0}%`}
                size="md"
                tone={(data?.totals.errors ?? 0) > 0 ? "warn" : "default"}
              />
            </MetricGrid>
          </div>

          <section className="min-w-0">
            <SectionHeader
              title={
                <span className="flex items-center gap-2">
                  <MagnifyingGlass size={15} aria-hidden /> Por organización
                </span>
              }
              description="Volumen, costo y superficie de cada tenant en el periodo."
              className="mb-3"
            />
            <DataTable
              stickyHeader
              columns={columns}
              rows={rows}
              rowKey={(row) => row.organization_id}
              sort={sort}
              onSortChange={setSort}
              caption="Métricas federadas por organización"
              empty={
                <EmptyState
                  icon={ChartBar}
                  title="Sin actividad"
                  body="No hay uso en los últimos 30 días."
                  hint="Cuando una organización genere requests, aparecerá en esta tabla."
                />
              }
            />
          </section>
        </>
      )}
    </div>
  );
}
