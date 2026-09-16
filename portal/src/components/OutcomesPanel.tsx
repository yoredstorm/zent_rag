import { ChartLineUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api, type Session } from "../api";
import { Panel, PanelHeader, Skeleton } from "./ui";
import { fmtDate, fmtNum } from "../lib/format";

type Outcome = {
  agent_id: string | null;
  metric_key: string;
  value: number;
  period_end: string | null;
  source: string | null;
};

/** FASE 03 (S13): métricas de negocio del agente — solo eventos reales. */
export default function OutcomesPanel({
  agentId,
  session,
}: {
  agentId: string;
  session: Session | null;
}) {
  const [metrics, setMetrics] = useState<Outcome[] | null>(null);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    api<{ metrics: Outcome[] }>(`/api/v1/organizations/outcomes?agent_id=${agentId}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        if (!cancelled) setMetrics(data.metrics || []);
      })
      .catch(() => {
        if (!cancelled) setMetrics([]);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, session]);

  if (metrics === null) {
    return (
      <Panel>
        <PanelHeader title="Outcomes de negocio" />
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-3" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[76px] rounded-lg" />
          ))}
        </div>
      </Panel>
    );
  }

  if (metrics.length === 0) return null; // nunca inventar outcomes

  return (
    <Panel>
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            <ChartLineUp size={15} aria-hidden />
            Outcomes de negocio
          </span>
        }
        description="Métricas registradas por sistemas cliente — solo eventos reales."
      />
      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
        {metrics.map((metric) => (
          <div
            key={`${metric.metric_key}-${metric.period_end}`}
            className="panel-quiet p-3"
          >
            <p className="stat-label mono">{metric.metric_key}</p>
            <p className="mt-1.5 text-[22px] leading-none font-semibold tracking-[-0.02em] text-text tabular-nums">
              {fmtNum(metric.value)}
            </p>
            <p className="mt-1.5 text-xs text-faint">
              {metric.source || "sin fuente"}
              {metric.period_end ? ` · ${fmtDate(metric.period_end)}` : " · sin período"}
            </p>
          </div>
        ))}
      </div>
    </Panel>
  );
}
