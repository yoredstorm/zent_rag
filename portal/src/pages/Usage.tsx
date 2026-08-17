import { ChartLineUp, Lightning, Timer, ListBullets } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
} from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type Usage = {
  totals: { requests: number; tokens: number; avg_latency_ms: number };
  daily: { day: string; requests: number; tokens: number; avg_latency_ms: number }[];
  recent: {
    id: number;
    total_tokens: number;
    latency_ms: number;
    model: string | null;
    created_at: string;
  }[];
};

export default function UsagePage() {
  const { session } = useAuth();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<Usage>("/api/v1/billing/usage?days=30", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then(setUsage)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Uso"
        subtitle="Actividad de consultas en los últimos 30 días."
      />
      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="stat">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : (
        usage && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatCard
                label="Consultas"
                value={fmtNum(usage.totals.requests)}
                icon={ChartLineUp}
              />
              <StatCard
                label="Tokens"
                value={fmtNum(usage.totals.tokens)}
                icon={Lightning}
              />
              <StatCard
                label="Latencia media"
                value={fmtLatency(usage.totals.avg_latency_ms)}
                icon={Timer}
              />
            </div>

            <div className="panel mt-4">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Por día</h2>
              </div>
              {usage.daily.length === 0 ? (
                <EmptyState
                  icon={ChartLineUp}
                  title="Sin actividad aún"
                  body="Todavía no hay consultas registradas en los últimos 30 días."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table min-w-[560px]">
                    <thead>
                      <tr>
                        <th>Día</th>
                        <th className="text-right">Consultas</th>
                        <th className="text-right">Tokens</th>
                        <th className="text-right">Latencia media</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.daily.map((d) => (
                        <tr key={d.day}>
                          <td className="mono">{d.day}</td>
                          <td className="mono text-right">{fmtNum(d.requests)}</td>
                          <td className="mono text-right">{fmtNum(d.tokens)}</td>
                          <td className="mono text-right">{fmtLatency(d.avg_latency_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel mt-4">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Recientes</h2>
              </div>
              {usage.recent.length === 0 ? (
                <EmptyState
                  icon={ListBullets}
                  title="Sin consultas recientes"
                  body="Las últimas consultas y su rendimiento aparecerán aquí."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table min-w-[560px]">
                    <thead>
                      <tr>
                        <th>Fecha</th>
                        <th className="text-right">Tokens</th>
                        <th className="text-right">Latencia</th>
                        <th>Modelo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.recent.map((r) => (
                        <tr key={r.id}>
                          <td className="text-muted">{fmtDateTime(r.created_at)}</td>
                          <td className="mono text-right">{fmtNum(r.total_tokens)}</td>
                          <td className="mono text-right">{fmtLatency(r.latency_ms)}</td>
                          <td className="mono text-faint">{r.model || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )
      )}
    </div>
  );
}
