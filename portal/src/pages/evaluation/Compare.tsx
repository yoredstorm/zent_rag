import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";

type Run = { id: string; dataset_name?: string; created_at?: string };
type Dimension = {
  dimension: string;
  metric: string;
  baseline: number | null;
  current: number | null;
  delta: number | null;
  status: string;
};
type Report = {
  overall: string;
  classification: string;
  dimensions: Dimension[];
};

export default function EvaluationComparePage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [currentId, setCurrentId] = useState(params.get("current") || "");
  const [baselineId, setBaselineId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const out = await api<{ runs: Run[] }>("/api/v1/eval/runs", {
          token: session.token,
          organizationId: session.organizationId,
        });
        setRuns(out.runs || []);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando runs");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  async function onCompare(e: FormEvent) {
    e.preventDefault();
    if (!session || !currentId || !baselineId) return;
    setBusy(true);
    setError("");
    try {
      setReport(
        await api<Report>(`/api/v1/eval/runs/${currentId}/compare`, {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ baseline_run_id: baselineId }),
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare falló");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Comparar runs"
        subtitle="Regresión contra un baseline. Veredictos del compare existente: pass / warn / fail."
      />
      <ErrorInline message={error} />
      {loading && <SkeletonBlock />}
      <form className="panel mb-6 grid gap-3 p-5 sm:grid-cols-2" onSubmit={onCompare}>
        <div>
          <label className="mb-1 block text-sm" htmlFor="cmp-current">
            Run actual
          </label>
          <select
            id="cmp-current"
            className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
            value={currentId}
            onChange={(ev) => setCurrentId(ev.target.value)}
            required
          >
            <option value="">Selecciona…</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {(run.dataset_name || run.id.slice(0, 8)) +
                  (run.created_at ? ` · ${new Date(run.created_at).toLocaleString("es-CL")}` : "")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm" htmlFor="cmp-base">
            Baseline
          </label>
          <select
            id="cmp-base"
            className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
            value={baselineId}
            onChange={(ev) => setBaselineId(ev.target.value)}
            required
          >
            <option value="">Selecciona…</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {(run.dataset_name || run.id.slice(0, 8)) +
                  (run.created_at ? ` · ${new Date(run.created_at).toLocaleString("es-CL")}` : "")}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn btn-primary min-h-11 sm:col-span-2" disabled={busy}>
          Comparar
        </button>
      </form>
      {report && (
        <>
          <div className="mb-4">
            <StatCard label="Overall" value={report.overall} />
            <StatCard
              label="Clasificación"
              value={
                report.classification === "regression" ? (
                  <span className="badge badge-danger">Regression</span>
                ) : report.classification === "improvement" ? (
                  <span className="badge badge-ok">Improvement</span>
                ) : (
                  <span className="badge badge-muted">No material change</span>
                )
              }
            />
          </div>
          <ul className="divide-y divide-border rounded-md border border-border">
            {report.dimensions.map((dim) => (
              <li key={dim.dimension} className="flex flex-wrap justify-between gap-2 px-4 py-3 text-sm">
                <span className="font-medium">{dim.dimension}</span>
                <span className="text-muted">
                  {dim.baseline ?? "—"} → {dim.current ?? "—"} (Δ {dim.delta ?? "—"}) · {dim.status}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
