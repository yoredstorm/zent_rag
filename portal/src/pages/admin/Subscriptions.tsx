import { Cards } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import {
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  ResultCount,
  StatusBadge,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtDate } from "../../lib/format";

type Subscription = {
  id: string;
  organization_id: string;
  organization_name: string;
  plan: string;
  status: string;
  interval: string;
  period_start: string | null;
  period_end: string | null;
  trial_ends_at: string | null;
  auto_renew: boolean;
  provider: string | null;
};

const PAGE_SIZE = 25;

function sortValue(s: Subscription, key: string): string {
  switch (key) {
    case "tenant":
      return (s.organization_name || "").toLowerCase();
    case "plan":
      return (s.plan || "").toLowerCase();
    case "status":
      return (s.status || "").toLowerCase();
    case "interval":
      return (s.interval || "").toLowerCase();
    case "provider":
      return (s.provider || "manual").toLowerCase();
    default:
      return "";
  }
}

export default function Subscriptions() {
  const { session } = usePlatformAuth();
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "tenant", dir: "asc" });
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!session) return;
    platformApi<{ subscriptions: Subscription[] }>("/api/v1/platform/subscriptions", {
      token: session.token,
    })
      .then((d) => setSubs(d.subscriptions || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const sorted = useMemo(() => {
    if (!sort) return subs;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...subs].sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [subs, sort]);

  const paged = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const columns: Column<Subscription>[] = [
    {
      key: "tenant",
      header: "Tenant",
      sortable: true,
      render: (s) => (
        <Link
          className="font-medium text-accent hover:underline"
          to={`/control-center/tenants/${s.organization_id}`}
        >
          {s.organization_name}
        </Link>
      ),
    },
    { key: "plan", header: "Plan", sortable: true, render: (s) => s.plan },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      render: (s) => <StatusBadge status={s.status} />,
    },
    {
      key: "interval",
      header: "Intervalo",
      sortable: true,
      hideBelow: "md",
      render: (s) => <span className="text-muted">{s.interval}</span>,
    },
    {
      key: "period",
      header: "Período",
      hideBelow: "lg",
      render: (s) => (
        <span className="text-muted">
          {s.period_start
            ? `${fmtDate(s.period_start)} – ${s.period_end ? fmtDate(s.period_end) : "…"}`
            : "—"}
        </span>
      ),
    },
    {
      key: "provider",
      header: "Provider",
      sortable: true,
      hideBelow: "xl",
      render: (s) => <span className="text-muted">{s.provider || "manual"}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Subscriptions"
        subtitle="Todas las suscripciones de la plataforma, con plan, estado y período."
      />
      <DataTable
        columns={columns}
        rows={paged}
        rowKey={(s) => s.id}
        caption="Suscripciones de la plataforma"
        loading={loading}
        error={error || null}
        sort={sort}
        onSortChange={setSort}
        stickyHeader
        empty={
          <EmptyState
            icon={Cards}
            title="Sin suscripciones"
            body="Todavía no hay suscripciones registradas en la plataforma."
          />
        }
        footer={
          sorted.length > 0 ? (
            <>
              <ResultCount shown={paged.length} total={sorted.length} noun="suscripciones" />
              <Pagination page={page} pageSize={PAGE_SIZE} total={sorted.length} onPageChange={setPage} />
            </>
          ) : null
        }
      />
    </div>
  );
}
