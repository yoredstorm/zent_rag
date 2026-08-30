import { Play, Stack } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../../components/ui";

type Dataset = { id: string; name: string };
type Run = {
  id: string;
  dataset_name?: string;
  target_type?: string;
  status?: string;
  created_at?: string;
  composite_score?: number | null;
  quality?: { composite_score?: number | null };
};

export default function EvaluationRunsPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [datasetId, setDatasetId] = useState(params.get("dataset") || "");
  const [judge, setJudge] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function reload() {
    if (!session) return;
    setLoading(true);
    try {
      const [ds, rs] = await Promise.all([
        api<{ datasets: Dataset[] }>("/api/v1/eval/datasets", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ runs: Run[] }>("/api/v1/eval/runs", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setDatasets(ds.datasets || []);
      setRuns(rs.runs || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando runs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [session]);

  async function onRun(e: FormEvent) {
    e.preventDefault();
    if (!session || !datasetId) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const out = await api<{ run_id: string }>("/api/v1/eval/runs", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          dataset_id: datasetId,
          target_type: "rag",
          judge_enabled: judge,
        }),
      });
      setMsg("Run completado.");
      await reload();
      if (out.run_id) {
        window.location.assign(`/evaluation/runs/${out.run_id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "El run falló");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Runs de evaluación"
        subtitle="El juez LLM no es determinista. Los costes del judge se registran en usage."
        actions={
          <Link to="/evaluation/compare" className="btn btn-secondary min-h-11">
            Comparar
          </Link>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />
      <form className="panel mb-6 flex flex-col gap-3 p-5 sm:flex-row sm:items-end" onSubmit={onRun}>
        <div className="min-w-0 flex-1">
          <label className="mb-1 block text-sm text-text" htmlFor="run-ds">
            Dataset
          </label>
          <select
            id="run-ds"
            className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
            value={datasetId}
            onChange={(ev) => setDatasetId(ev.target.value)}
            required
          >
            <option value="">Selecciona…</option>
            {datasets.map((ds) => (
              <option key={ds.id} value={ds.id}>
                {ds.name}
              </option>
            ))}
          </select>
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={judge}
            onChange={(ev) => setJudge(ev.target.checked)}
          />
          Juez LLM
        </label>
        <button type="submit" className="btn btn-primary min-h-11" disabled={busy || !datasetId}>
          {busy ? <Spinner size={14} /> : <Play size={16} aria-hidden />}
          Lanzar
        </button>
      </form>
      {loading && <SkeletonBlock />}
      {!loading && runs.length === 0 && (
        <EmptyState
          icon={Stack}
          title="Sin runs"
          body="Importa un dataset y lanza una evaluación."
          action={
            <Link to="/evaluation/datasets" className="btn btn-secondary min-h-11">
              Ir a datasets
            </Link>
          }
        />
      )}
      {runs.length > 0 && (
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-faint">
                <th className="py-2 pr-3 font-medium">Dataset</th>
                <th className="py-2 pr-3 font-medium">Score</th>
                <th className="py-2 pr-3 font-medium">Estado</th>
                <th className="py-2 font-medium">Fecha</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-border/70">
                  <td className="py-3 pr-3">
                    <Link to={`/evaluation/runs/${run.id}`} className="text-accent hover:underline">
                      {run.dataset_name || run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="py-3 pr-3">
                    {(run.composite_score ?? run.quality?.composite_score) == null
                      ? "—"
                      : Number(run.composite_score ?? run.quality?.composite_score).toFixed(3)}
                  </td>
                  <td className="py-3 pr-3">{run.status || "—"}</td>
                  <td className="py-3 text-muted">
                    {run.created_at
                      ? new Date(run.created_at).toLocaleString("es-CL")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
