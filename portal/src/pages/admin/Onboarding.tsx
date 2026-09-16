import { RocketLaunch } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Skeleton,
  type Column,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";
import { fmtDateTime } from "../../lib/format";

type Metrics = { total_orgs: number; completed: number; activation_rate: number; avg_time_to_first_value_seconds: number | null; funnel: { step: string; orgs: number }[] };
type OrgRow = { organization_id: string; done_steps: string[]; current_step: string; started_at: string; completed_at: string | null; time_to_first_value_seconds: number | null };

const STEPS = ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"];
const LABELS: Record<string, string> = { create_kb: "KB", add_documents: "Docs", create_agent: "Agente", deploy_agent: "Deploy", first_query: "Query" };

function minutes(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  return `${Math.round(seconds / 60)}m`;
}

export default function AdminOnboardingPage() {
  const { session } = usePlatformAuth();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, o] = await Promise.all([
        platformApi<Metrics>("/api/v1/platform/onboarding/metrics", { token: session.token }),
        platformApi<{ organizations: OrgRow[] }>("/api/v1/platform/onboarding/status", { token: session.token }),
      ]);
      setMetrics(m);
      setOrgs(o.organizations || []);
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

  const maxFunnel = Math.max(...(metrics?.funnel ?? []).map((f) => f.orgs), 1);

  const columns: Column<OrgRow>[] = [
    {
      key: "org",
      header: "Org",
      render: (o) => <span className="mono text-xs text-muted">{o.organization_id.slice(0, 8)}…</span>,
    },
    {
      key: "steps",
      header: "Pasos",
      render: (o) => (
        <span className="flex flex-wrap gap-1">
          {STEPS.map((s) => (
            <Badge key={s} tone={o.done_steps.includes(s) ? "ok" : "neutral"} title={s}>
              {LABELS[s]}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (o) =>
        o.completed_at ? (
          <Badge tone="ok">completado</Badge>
        ) : (
          <Badge tone="warn">{LABELS[o.current_step] ?? o.current_step}</Badge>
        ),
    },
    {
      key: "ttfv",
      header: "TTFV",
      align: "right",
      render: (o) => <span className="mono text-xs">{minutes(o.time_to_first_value_seconds)}</span>,
    },
    {
      key: "started",
      header: "Inicio",
      hideBelow: "md",
      render: (o) => <span className="text-muted">{fmtDateTime(o.started_at)}</span>,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Onboarding & Activación"
        subtitle="TTFV, tasa de completación y funnel por paso."
      />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <Skeleton className="h-[320px] rounded-lg" />
      ) : (
        <>
          {/* Foco: la tasa de activación; el resto es volumen de contexto */}
          <Panel className="p-4">
            <p className="eyebrow">Activación de organizaciones</p>
            <p className="mt-1.5 text-display tabular-nums">
              {((metrics?.activation_rate ?? 0) * 100).toFixed(1)}%
            </p>
            <p className="mt-2 text-[13px] text-muted">
              {metrics?.completed ?? 0} de {metrics?.total_orgs ?? 0} organizaciones completaron el
              flujo de activación
            </p>
          </Panel>

          <MetricGrid cols={3}>
            <Metric size="md" label="Orgs" value={metrics?.total_orgs ?? 0} icon={RocketLaunch} />
            <Metric size="md" label="Completaron" value={metrics?.completed ?? 0} />
            <Metric
              size="md"
              label="TTFV promedio"
              value={minutes(metrics?.avg_time_to_first_value_seconds)}
              hint="tiempo a primer valor"
            />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title="Funnel de pasos"
              description="Organizaciones que alcanzaron cada paso del flujo."
            />
            {(metrics?.funnel ?? []).length === 0 ? (
              <EmptyState
                compact
                title="Sin funnel"
                body="No hay organizaciones que hayan iniciado el flujo de activación."
              />
            ) : (
              <ul className="flex flex-col gap-3 p-4">
                {(metrics?.funnel ?? []).map((f) => (
                  <li key={f.step} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-xs text-text">
                      {LABELS[f.step] ?? f.step}
                    </span>
                    <span className="progress-track flex-1">
                      <span
                        className="progress-fill block"
                        style={{ width: `${(f.orgs / maxFunnel) * 100}%` }}
                      />
                    </span>
                    <span className="mono w-20 shrink-0 text-right text-xs text-faint">
                      {f.orgs} orgs
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <section>
            <SectionHeader
              title="Progreso por organización"
              description="Paso actual y tiempo a primer valor de cada tenant."
              className="mb-3"
            />
            <DataTable
              columns={columns}
              rows={orgs}
              rowKey={(o) => o.organization_id}
              caption="Onboarding por organización"
              stickyHeader
              empty={
                <EmptyState
                  icon={RocketLaunch}
                  title="Sin organizaciones en onboarding"
                  body="Todavía ninguna organización inició el flujo de activación."
                />
              }
            />
          </section>
        </>
      )}
    </div>
  );
}
