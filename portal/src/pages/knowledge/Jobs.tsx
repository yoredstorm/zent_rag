import { ArrowsClockwise } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { fmtDateTime, fmtNum } from "../../lib/format";

type Job = {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  records_processed: number;
  records_failed: number;
  error_summary: string | null;
  created_at: string;
};

export default function KnowledgeJobsPage() {
  const { session } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<{ jobs: Job[] }>("/api/v1/jobs?limit=50", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setJobs(data.jobs || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Trabajos de sync"
        subtitle="Jobs de ingestión de tu organización. La API legacy de ingestión sigue disponible."
      />
      <ErrorInline message={error} />
      <div className="panel">
        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={5} />
          </div>
        ) : jobs.length === 0 ? (
          <EmptyState
            icon={ArrowsClockwise}
            title="Sin trabajos todavía"
            body="Cuando sincronices una fuente, el progreso se listará aquí."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>Tipo</th>
                  <th>Estado</th>
                  <th className="text-right">Progreso</th>
                  <th className="text-right">Procesados</th>
                  <th className="text-right">Fallidos</th>
                  <th>Creado</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td className="mono text-xs">{j.job_type}</td>
                    <td>
                      <span className="badge badge-ok">{j.status}</span>
                    </td>
                    <td className="mono text-right">{fmtNum(j.progress)}</td>
                    <td className="mono text-right">{fmtNum(j.records_processed)}</td>
                    <td className="mono text-right">{fmtNum(j.records_failed)}</td>
                    <td className="text-muted">{fmtDateTime(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
