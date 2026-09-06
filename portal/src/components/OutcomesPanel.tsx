import { ChartLineUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api, type Session } from "../api";

type Outcome = { agent_id: string | null; metric_key: string; value: number; period_end: string | null; source: string | null };

/** FASE 03 (S13): métricas de negocio del agente — solo eventos reales. */
export default function OutcomesPanel({ agentId, session }: { agentId: string; session: Session | null }) {
  const [metrics, setMetrics] = useState<Outcome[] | null>(null);

  useEffect(() => {
    if (!session) return;
    api<{ metrics: Outcome[] }>(`/api/v1/organizations/outcomes?agent_id=${agentId}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setMetrics(d.metrics || []))
      .catch(() => setMetrics([]));
  }, [agentId, session]);

  if (metrics === null) return null;
  if (metrics.length === 0) return null; // nunca inventar outcomes

  return (
    <div className="panel mt-4 p-5">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
        <ChartLineUp size={15} aria-hidden /> Outcomes de negocio
      </h2>
      <p className="mb-2 text-xs text-muted">Métricas registradas por sistemas cliente — solo eventos reales.</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {metrics.map((m) => (
          <div key={`${m.metric_key}-${m.period_end}`} className="rounded-md bg-soft px-3 py-2">
            <p className="stat-value">{m.value}</p>
            <p className="mono text-[11px] text-muted">{m.metric_key}</p>
            {m.source && <p className="text-[10px] text-faint">{m.source}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}