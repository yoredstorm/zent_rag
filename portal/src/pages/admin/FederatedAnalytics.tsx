import { ChartBar, Download, MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
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

export default function AdminFederatedAnalyticsPage() {
  const { session } = usePlatformAuth();
  const [data, setData] = useState<Federated | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const maxRequests = Math.max(1, ...(data?.by_organization ?? []).map((o) => o.requests));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Federated Analytics"
        subtitle="Métricas multi-tenant agregadas (30d) con drill-down por organización."
        actions={
          <button type="button" className="btn btn-secondary min-h-11" onClick={() => void exportCsv()}>
            <Download size={15} aria-hidden /> Export CSV
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">Requests (30d)</p>
              <p className="stat-value">{data?.totals.requests ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Tokens</p>
              <p className="stat-value">{(data?.totals.tokens ?? 0).toLocaleString()}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Costo</p>
              <p className="stat-value">${(data?.totals.cost ?? 0).toFixed(2)}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Error rate</p>
              <p className="stat-value">{data?.totals.error_rate_pct ?? 0}%</p>
            </div>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <MagnifyingGlass size={15} aria-hidden /> Por organización
            </h3>
            <div className="panel overflow-x-auto">
              {(data?.by_organization ?? []).length === 0 ? (
                <EmptyState icon={ChartBar} title="Sin actividad" body="No hay uso en los últimos 30 días." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Organización</th>
                      <th>Requests</th>
                      <th>Error %</th>
                      <th>Tokens</th>
                      <th>Costo</th>
                      <th>Agentes</th>
                      <th>KBs</th>
                      <th>Deploys</th>
                      <th>Última actividad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.by_organization ?? []).map((o) => (
                      <tr key={o.organization_id}>
                        <td className="mono text-xs text-faint">{o.organization_id.slice(0, 13)}…</td>
                        <td className="text-xs">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-16 overflow-hidden rounded bg-soft">
                              <div
                                className="h-full bg-accent/70"
                                style={{ width: `${(o.requests / maxRequests) * 100}%` }}
                              />
                            </div>
                            {o.requests}
                          </div>
                        </td>
                        <td className="text-xs">{o.error_rate_pct}%</td>
                        <td className="text-xs">{o.tokens.toLocaleString()}</td>
                        <td className="text-xs">${o.cost.toFixed(2)}</td>
                        <td className="text-xs">{o.agents}</td>
                        <td className="text-xs">{o.knowledge_bases}</td>
                        <td className="text-xs">{o.deployments}</td>
                        <td className="text-xs text-muted">
                          {o.last_activity ? new Date(o.last_activity).toLocaleString("es-PE") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}