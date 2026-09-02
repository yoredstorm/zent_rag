import { Cards } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, StatusBadge } from "../../components/ui";

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

export default function Subscriptions() {
  const { session } = usePlatformAuth();
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    platformApi<{ subscriptions: Subscription[] }>("/api/v1/platform/subscriptions", {
      token: session.token,
    })
      .then((d) => setSubs(d.subscriptions || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Subscriptions"
        subtitle="Todas las suscripciones de la plataforma, con plan, estado y período."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : subs.length === 0 ? (
        <div className="panel">
          <EmptyState icon={Cards} title="Sin suscripciones" body="Aún no hay suscripciones." />
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Plan</th>
                <th>Estado</th>
                <th>Intervalo</th>
                <th>Período</th>
                <th>Provider</th>
              </tr>
            </thead>
            <tbody>
              {subs.map((s) => (
                <tr key={s.id}>
                  <td>
                    <Link className="text-accent hover:underline" to={`/control-center/tenants/${s.organization_id}`}>
                      {s.organization_name}
                    </Link>
                  </td>
                  <td className="text-sm">{s.plan}</td>
                  <td>
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="text-sm text-muted">{s.interval}</td>
                  <td className="text-sm text-muted">
                    {s.period_start
                      ? `${new Date(s.period_start).toLocaleDateString("es-PE")} → ${s.period_end ? new Date(s.period_end).toLocaleDateString("es-PE") : "…"}`
                      : "—"}
                  </td>
                  <td className="text-sm text-muted">{s.provider || "manual"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}