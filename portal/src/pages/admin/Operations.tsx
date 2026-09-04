import { Gauge } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, StatusBadge } from "../../components/ui";

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

export default function Operations() {
  const { session } = usePlatformAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    platformApi<{ jobs: Job[] }>("/api/v1/platform/operations", { token: session.token })
      .then((d) => setJobs(d.jobs || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Operations"
        subtitle="Jobs de ingestión y errores de toda la plataforma."
      />
      <ErrorInline message={error} />
      {loading ? (
        <SkeletonBlock />
      ) : jobs.length === 0 ? (
        <div className="panel">
          <EmptyState icon={Gauge} title="Sin jobs" body="No hay jobs de ingestión recientes." />
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th>Progreso</th>
                <th>Intentos</th>
                <th>Error</th>
                <th>Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const errText = formatErrorSummary(j.error_summary);
                return (
                <tr key={j.id}>
                  <td>
                    <Link className="text-accent hover:underline" to={`/control-center/tenants/${j.organization_id}`}>
                      {j.organization_name}
                    </Link>
                  </td>
                  <td className="font-mono text-xs">{j.job_type}</td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="text-sm text-muted">{j.progress ?? 0}%</td>
                  <td className="text-sm text-muted">{j.attempts}</td>
                  <td className="max-w-52 truncate text-xs text-muted" title={errText}>
                    {errText || "—"}
                  </td>
                  <td className="text-sm text-muted">
                    {j.updated_at ? new Date(j.updated_at).toLocaleString("es-PE") : "—"}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}