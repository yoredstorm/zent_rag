import { FlowArrow, TrendUp, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  SectionHeader,
  Skeleton,
  StatusBadge,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type TriggerRow = { trigger_type: string; runs: number; ok: number };
type FailedStep = { step_type: string; count: number };
type RecentRun = { workflow: string; status: string; duration_ms: number | null; started_at: string };
type Dash = { total_runs: number; success_rate: number; failed_runs: number; avg_duration_ms: number; active_workflows: number; by_trigger: TriggerRow[]; recent_runs: RecentRun[]; failed_steps: FailedStep[] };

export default function AdminWorkflowsPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/workflows/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const triggers = useMemo(() => {
    const rows = [...(dash?.by_trigger ?? [])];
    if (!sort) return rows;
    return rows.sort((a, b) => {
      const value = (row: TriggerRow) =>
        sort.key === "runs" ? row.runs : sort.key === "ok" ? row.ok : row.trigger_type;
      const left = value(a);
      const right = value(b);
      if (typeof left === "string" && typeof right === "string") {
        return sort.dir === "asc" ? left.localeCompare(right) : right.localeCompare(left);
      }
      return sort.dir === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
    });
  }, [dash?.by_trigger, sort]);

  const failedSteps = dash?.failed_steps ?? [];
  const recentRuns = dash?.recent_runs ?? [];
  const maxStepCount = Math.max(1, ...failedSteps.map((s) => s.count));
  const failed = dash?.failed_runs ?? 0;
  const total = dash?.total_runs ?? 0;

  const triggerColumns: Column<TriggerRow>[] = [
    {
      key: "trigger_type",
      header: "Disparador",
      sortable: true,
      render: (row) => <span className="text-[13px] text-text">{row.trigger_type}</span>,
    },
    {
      key: "runs",
      header: "Runs",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.runs}</span>,
    },
    {
      key: "ok",
      header: "Éxito",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.ok}</span>,
    },
    {
      key: "rate",
      header: "% éxito",
      align: "right",
      width: "100px",
      render: (row) =>
        row.runs > 0 ? (
          <span className="mono text-xs text-muted">{((row.ok / row.runs) * 100).toFixed(0)}%</span>
        ) : (
          <span className="text-xs text-ghost">—</span>
        ),
    },
  ];

  const runColumns: Column<RecentRun>[] = [
    {
      key: "status",
      header: "Estado",
      width: "120px",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "workflow",
      header: "Workflow",
      render: (row) => (
        <span className="block max-w-[420px] truncate text-[13px] text-text" title={row.workflow}>
          {row.workflow}
        </span>
      ),
    },
    {
      key: "duration_ms",
      header: "Duración",
      align: "right",
      hideBelow: "md",
      width: "110px",
      render: (row) => (
        <span className="mono text-xs text-muted">
          {row.duration_ms != null ? `${row.duration_ms}ms` : "—"}
        </span>
      ),
    },
    {
      key: "started_at",
      header: "Inicio",
      align: "right",
      hideBelow: "lg",
      width: "160px",
      render: (row) => <span className="text-xs text-faint">{fmtDateTime(row.started_at)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Workflow Automation" subtitle="Automatizaciones en todas las organizaciones: éxito, duración y fallos por paso." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[240px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Tasa de éxito"
              value={`${dash?.success_rate ?? 0}%`}
              hint={total > 0 ? `${(total - failed).toLocaleString()} de ${total.toLocaleString()} runs` : "Sin runs registrados"}
              icon={FlowArrow}
              tone={failed > 0 ? "warn" : "default"}
            />
            <MetricGrid cols={4} className="lg:grid-cols-4">
              <Metric label="Runs totales" value={total.toLocaleString()} size="md" />
              <Metric label="Fallidos" value={failed.toLocaleString()} size="md" tone={failed > 0 ? "danger" : "default"} />
              <Metric label="Duración media" value={`${dash?.avg_duration_ms ?? 0}ms`} size="md" />
              <Metric label="Workflows activos" value={(dash?.active_workflows ?? 0).toLocaleString()} size="md" />
            </MetricGrid>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section className="min-w-0">
              <SectionHeader title="Runs por disparador" className="mb-3" />
              <DataTable
                stickyHeader
                columns={triggerColumns}
                rows={triggers}
                rowKey={(row) => row.trigger_type}
                sort={sort}
                onSortChange={setSort}
                empty={
                  <EmptyState compact icon={FlowArrow} title="Sin runs" body="Los workflows ejecutados en el periodo se agruparán acá." />
                }
              />
              <div className="mt-6">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <WarningCircle size={15} aria-hidden /> Fallos por paso
                    </span>
                  }
                  className="mb-3"
                />
                <Panel>
                  {failedSteps.length === 0 ? (
                    <EmptyState compact icon={WarningCircle} title="Sin fallos" body="Ningún paso falló en la ventana reportada." />
                  ) : (
                    <ul className="divide-y divide-border-soft">
                      {failedSteps.map((s) => (
                        <li key={s.step_type} className="flex items-center gap-3 px-4 py-2.5">
                          <span className="min-w-0 flex-1 truncate text-[13px] text-text">{s.step_type}</span>
                          <span className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-track" aria-hidden>
                            <span
                              className="block h-full rounded-full bg-danger"
                              style={{ width: `${(s.count / maxStepCount) * 100}%` }}
                            />
                          </span>
                          <span className="mono w-8 shrink-0 text-right text-xs text-danger">{s.count}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </div>
            </section>

            <section className="min-w-0 lg:col-span-2">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <TrendUp size={15} aria-hidden /> Runs recientes
                  </span>
                }
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={runColumns}
                rows={recentRuns}
                rowKey={(row) => `${row.workflow}-${row.started_at}`}
                empty={
                  <EmptyState compact icon={FlowArrow} title="Sin runs" body="Cuando se ejecute un workflow verás su estado acá." />
                }
              />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
