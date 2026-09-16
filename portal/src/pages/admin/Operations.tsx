import { Gauge, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import {
  Badge,
  ButtonLink,
  Drawer,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  SectionHeader,
  SkeletonTable,
  StatusBadge,
} from "../../components/ui";

type Job = {
  id: string;
  organization_id: string;
  organization_name: string;
  job_type: string;
  status: string;
  progress: number;
  attempts: number;
  error_summary: string | { error?: string; at?: string; attempts?: number } | null;
  created_at: string | null;
  updated_at: string | null;
};

function formatErrorSummary(value: Job["error_summary"]): string {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    if (typeof value.error === "string" && value.error) return value.error;
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

const FAILED_STATES = new Set(["failed", "error"]);
const ACTIVE_STATES = new Set(["running", "processing", "queued", "pending", "indexing", "ingesting", "embedding"]);

export default function Operations() {
  const { session } = usePlatformAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [detail, setDetail] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    platformApi<{ jobs: Job[] }>("/api/v1/platform/operations", { token: session.token })
      .then((d) => setJobs(d.jobs || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const failed = jobs.filter((j) => FAILED_STATES.has(j.status));
  const active = jobs.filter((j) => ACTIVE_STATES.has(j.status));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Operations"
        subtitle="Jobs de ingestión y errores de toda la plataforma."
      />
      <ErrorInline message={error} />
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={5} />
        </Panel>
      ) : jobs.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Gauge}
            compact
            title="Sin jobs"
            body="No hay jobs de ingestión recientes en la plataforma."
            hint="Los jobs aparecen acá cuando un tenant carga o reprocesa conocimiento."
          />
        </Panel>
      ) : (
        <>
          <Panel className="p-4">
            <p className="eyebrow">Jobs en curso</p>
            <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
              {active.length.toLocaleString()}
            </p>
            <p className="mt-2 flex items-center gap-2 text-[13px] leading-relaxed text-muted">
              {failed.length > 0 ? (
                <span className="flex items-center gap-2 text-danger">
                  <WarningCircle size={15} weight="fill" aria-hidden />
                  {failed.length} job(s) fallaron y necesitan revisión.
                </span>
              ) : (
                <span>Sin jobs fallidos en la última lectura.</span>
              )}
            </p>
          </Panel>

          <MetricGrid cols={3}>
            <Metric size="md" label="Jobs totales" value={jobs.length.toLocaleString()} />
            <Metric size="md" label="En curso" value={active.length.toLocaleString()} />
            <Metric
              size="md"
              label="Fallidos"
              value={failed.length.toLocaleString()}
              tone={failed.length > 0 ? "danger" : "default"}
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Jobs de ingestión"
              description="Seleccioná una fila para ver el detalle y el error completo."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              <table className="table min-w-[880px]">
                <thead>
                  <tr>
                    <th>Tenant</th>
                    <th>Tipo</th>
                    <th>Estado</th>
                    <th className="w-40">Progreso</th>
                    <th className="text-right">Intentos</th>
                    <th>Error</th>
                    <th>Actualizado</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => {
                    const errText = formatErrorSummary(j.error_summary);
                    const isFailed = FAILED_STATES.has(j.status);
                    return (
                      <tr
                        key={j.id}
                        className="cursor-pointer"
                        onClick={() => setDetail(j)}
                      >
                        <td>
                          <Link
                            className="text-accent hover:underline"
                            to={`/control-center/tenants/${j.organization_id}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            {j.organization_name}
                          </Link>
                        </td>
                        <td className="font-mono text-xs text-muted">{j.job_type}</td>
                        <td>
                          <StatusBadge status={j.status} />
                        </td>
                        <td>
                          <span className="flex items-center gap-2">
                            <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-track" aria-hidden>
                              <span
                                className={`block h-full rounded-full ${isFailed ? "bg-danger" : "bg-accent"}`}
                                style={{ width: `${Math.min(Math.max(j.progress ?? 0, 0), 100)}%` }}
                              />
                            </span>
                            <span className="text-xs text-muted tabular-nums">{j.progress ?? 0}%</span>
                          </span>
                        </td>
                        <td className="text-right tabular-nums">{j.attempts}</td>
                        <td className="max-w-52 truncate text-xs text-muted" title={errText}>
                          {errText || "—"}
                        </td>
                        <td className="text-xs text-muted tabular-nums">
                          {j.updated_at ? new Date(j.updated_at).toLocaleString("es-PE") : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
          </section>
        </>
      )}

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => !open && setDetail(null)}
        title={detail ? `${detail.job_type} · ${detail.organization_name}` : "Job"}
        description={detail ? `ID ${detail.id}` : undefined}
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={detail.status} />
              {FAILED_STATES.has(detail.status) && <Badge tone="danger">Requiere revisión</Badge>}
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Tenant", value: detail.organization_name },
                { key: "Tipo", value: detail.job_type, mono: true },
                { key: "Progreso", value: `${detail.progress ?? 0}%` },
                { key: "Intentos", value: String(detail.attempts) },
                {
                  key: "Creado",
                  value: detail.created_at ? new Date(detail.created_at).toLocaleString("es-PE") : "—",
                  mono: true,
                },
                {
                  key: "Actualizado",
                  value: detail.updated_at ? new Date(detail.updated_at).toLocaleString("es-PE") : "—",
                  mono: true,
                },
              ]}
            />
            <div>
              <h3 className="eyebrow mb-2">Error</h3>
              {formatErrorSummary(detail.error_summary) ? (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-danger/25 bg-danger-soft p-3 font-mono text-[12.5px] leading-relaxed text-danger">
                  {formatErrorSummary(detail.error_summary)}
                </pre>
              ) : (
                <p className="text-[13px] text-muted">El job no reportó error.</p>
              )}
            </div>
            <ButtonLink variant="secondary" size="sm" to={`/control-center/tenants/${detail.organization_id}`}>
              Ver tenant
            </ButtonLink>
          </div>
        )}
      </Drawer>
    </div>
  );
}
