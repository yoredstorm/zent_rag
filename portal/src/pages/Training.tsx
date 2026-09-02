import { FloppyDisk, Play } from "@phosphor-icons/react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatusBadge,
} from "../components/ui";

type KB = { id: string; name: string };
type Run = {
  id: string;
  knowledge_base_id: string;
  status: string;
  current_step: string;
  progress: number;
  rows_processed: number;
  vectors_upserted: number;
  errors: number;
  error_summary: string | null;
  created_at: string | null;
  finished_at: string | null;
};

const STEPS = ["preparation", "chunking", "embedding", "indexing", "validation", "evaluation"];

export default function Training() {
  const { session } = useAuth();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [kbId, setKbId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);
  const activeRun = runs.some((r) => r.status === "pending" || r.status === "running");

  async function loadRuns() {
    if (!session) return;
    try {
      const data = await api<{ runs: Run[] }>("/api/v1/training/runs", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setRuns(data.runs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => {
        setKbs(d.knowledge_bases || []);
        if (d.knowledge_bases?.length) setKbId(d.knowledge_bases[0].id);
      })
      .catch(() => setKbs([]));
    void loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (!activeRun) return;
    pollRef.current = window.setInterval(() => void loadRuns(), 2000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [activeRun]);

  async function start(e: FormEvent) {
    e.preventDefault();
    if (!session || !kbId) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/training/runs", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ knowledge_base_id: kbId }),
      });
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  function stepStatus(run: Run, step: string): "done" | "active" | "todo" {
    const idx = STEPS.indexOf(step);
    const cur = STEPS.indexOf(run.current_step);
    if (run.status === "completed") return "done";
    if (run.status === "failed" && idx <= cur) return "done";
    if (idx < cur) return "done";
    if (idx === cur && (run.status === "running" || run.status === "pending")) return "active";
    return "todo";
  }

  return (
    <div>
      <PageHeader
        title="Training"
        subtitle="Pipeline de preparación → chunking → embedding → indexación con progreso en vivo."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      <form className="panel mb-6" onSubmit={(e) => void start(e)}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
            Knowledge base
            <select className="input" value={kbId} onChange={(e) => setKbId(e.target.value)}>
              {kbs.length === 0 && <option value="">Sin KBs</option>}
              {kbs.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary min-h-10" disabled={busy || !kbId}>
            {busy ? <FloppyDisk size={15} aria-hidden /> : <Play size={15} aria-hidden />}
            Iniciar training
          </button>
        </div>
      </form>
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : runs.length === 0 ? (
        <div className="panel">
          <EmptyState title="Sin training runs" body="Inicia un run para ver el progreso del pipeline." />
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <div key={run.id} className="panel">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <StatusBadge status={run.status} />
                  <span className="text-sm font-semibold text-text">{run.progress}%</span>
                  <span className="font-mono text-xs text-faint">{run.id.slice(0, 8)}</span>
                </div>
                <span className="text-xs text-muted">
                  {run.rows_processed} filas · {run.vectors_upserted} vectores · {run.errors} errores
                </span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-soft">
                <div
                  className={`h-full rounded-full ${
                    run.status === "failed" ? "bg-danger" : "bg-accent"
                  }`}
                  style={{ width: `${run.progress}%` }}
                />
              </div>
              <ol className="mt-3 flex flex-wrap gap-1.5">
                {STEPS.map((step) => {
                  const st = stepStatus(run, step);
                  return (
                    <li
                      key={step}
                      className={`rounded-xs px-2 py-1 text-[11px] font-medium ${
                        st === "done"
                          ? "bg-ok-soft text-ok"
                          : st === "active"
                            ? "bg-warn-soft text-warn"
                            : "bg-soft text-faint"
                      }`}
                    >
                      {step}
                    </li>
                  );
                })}
              </ol>
              {run.error_summary && (
                <p className="mt-2 truncate text-xs text-danger" title={run.error_summary}>
                  {run.error_summary}
                </p>
              )}
              <p className="mt-2 text-xs text-faint">
                Creado {run.created_at ? new Date(run.created_at).toLocaleString("es-PE") : "—"}
                {run.finished_at
                  ? ` · finalizado ${new Date(run.finished_at).toLocaleString("es-PE")}`
                  : ""}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}