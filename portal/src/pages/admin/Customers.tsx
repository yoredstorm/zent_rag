import { Buildings } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
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

export default function AdminCustomersPage() {
  const { session } = usePlatformAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

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

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return orgs.filter((o) => {
      if (!matchesFilter(o, filter)) return false;
      if (!q) return true;
      const hay = `${o.company_name || ""} ${o.name} ${o.email || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [orgs, query, filter]);

  return (
    <div>
      <PageHeader title="Clientes" subtitle="Organizaciones de la plataforma." />
      <ErrorInline message={error} />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="sr-only" htmlFor="customer-search">
          Buscar empresa o email
        </label>
        <input
          id="customer-search"
          type="search"
          className="min-h-11 w-full max-w-sm rounded-md border border-border bg-surface px-3 text-sm"
          placeholder="Buscar empresa o email"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por suscripción">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className={`btn min-h-11 px-3 text-sm ${
                filter === f.id ? "btn-primary" : "btn-secondary"
              }`}
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {loading && <SkeletonBlock />}
      {!loading && visible.length === 0 && (
        <EmptyState icon={Buildings} title="Sin organizaciones" />
      )}
      {visible.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="px-4 py-3">Empresa</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Plan</th>
                <th className="px-4 py-3">Suscripción</th>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Por pagar</th>
                <th className="px-4 py-3">Próxima renovación</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className="px-4 py-3">
                    <Link className="text-accent hover:underline" to={`/control-center/tenants/${o.id}`}>
                      {o.company_name || o.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted">{o.email || "—"}</td>
                  <td className="px-4 py-3">{o.plan || "—"}</td>
                  <td className="px-4 py-3">{o.subscription_status || o.status}</td>
                  <td className="px-4 py-3">{o.payment_provider || "—"}</td>
                  <td className="px-4 py-3">{usdCents(o.amount_due_cents || 0)}</td>
                  <td className="px-4 py-3 text-muted">
                    {o.next_renewal_at
                      ? new Date(o.next_renewal_at).toLocaleDateString("es-CL")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
