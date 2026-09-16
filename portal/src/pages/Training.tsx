import { CheckCircle, Circle, CircleNotch, Play, WarningCircle } from "@phosphor-icons/react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Select,
  StatusBadge,
  type Column,
} from "../components/ui";
import { fmtDateTime, fmtNum, formatErrorSummary } from "../lib/format";

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
  error_summary: string | { error?: unknown; message?: unknown } | null;
  created_at: string | null;
  finished_at: string | null;
};

const STEPS = ["preparation", "chunking", "embedding", "indexing", "validation", "evaluation"];

const STEP_LABELS: Record<string, string> = {
  preparation: "Preparación",
  chunking: "Fragmentación",
  embedding: "Vectorización",
  indexing: "Indexación",
  validation: "Validación",
  evaluation: "Evaluación",
};

export default function Training() {
  const { session } = useAuth();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [kbId, setKbId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Run | null>(null);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function kbName(run: Run): string {
    return kbs.find((k) => k.id === run.knowledge_base_id)?.name ?? run.knowledge_base_id.slice(0, 8);
  }

  const columns: Column<Run>[] = [
    {
      key: "status",
      header: "Estado",
      render: (run) => (
        <div className="min-w-0">
          <StatusBadge status={run.status} />
          <p className="mono mt-1 text-[11px] text-faint">{run.id.slice(0, 8)}</p>
        </div>
      ),
    },
    {
      key: "kb",
      header: "Colección",
      hideBelow: "md",
      render: (run) => <span className="text-[13px] text-text">{kbName(run)}</span>,
    },
    {
      key: "progress",
      header: "Progreso",
      width: "190px",
      render: (run) => (
        <Progress
          value={run.progress}
          tone={run.status === "failed" ? "danger" : run.status === "completed" ? "ok" : "accent"}
          showValue
          className="max-w-[170px]"
        />
      ),
    },
    {
      key: "counts",
      header: "Filas / vectores / errores",
      align: "right",
      hideBelow: "lg",
      render: (run) => (
        <span className="mono text-xs text-muted">
          {fmtNum(run.rows_processed)} / {fmtNum(run.vectors_upserted)} /{" "}
          <span className={run.errors > 0 ? "text-danger" : undefined}>{fmtNum(run.errors)}</span>
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Creado",
      hideBelow: "lg",
      render: (run) => (
        <span className="text-xs text-muted">
          {run.created_at ? fmtDateTime(run.created_at) : "—"}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Training"
        subtitle="Pipeline de preparación, fragmentación, vectorización e indexación con progreso en vivo."
      />
      <ErrorInline message={error} />
      <Panel className="mb-4">
        <PanelHeader
          title="Nuevo run"
          description="El run recorre el pipeline completo sobre la colección elegida."
        />
        <form className="panel-body" onSubmit={(e) => void start(e)}>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Knowledge base" className="min-w-56 flex-1">
              <Select
                value={kbId}
                onChange={(e) => setKbId(e.target.value)}
                disabled={kbs.length === 0}
              >
                {kbs.length === 0 && <option value="">Sin colecciones</option>}
                {kbs.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Button
              type="submit"
              variant="primary"
              leadingIcon={Play}
              loading={busy}
              disabled={!kbId}
            >
              Iniciar training
            </Button>
          </div>
          {kbs.length === 0 && (
            <p className="mt-3 text-xs text-muted">
              Necesitás al menos una colección con documentos para iniciar un run.
            </p>
          )}
        </form>
      </Panel>

      <DataTable
        columns={columns}
        rows={runs}
        rowKey={(run) => run.id}
        caption="Runs de training"
        loading={loading}
        empty={
          <EmptyState
            icon={Play}
            title="Sin training runs"
            body="Iniciá un run para ver el progreso del pipeline."
          />
        }
        onRowClick={(run) => setSelected(run)}
        isRowSelected={(run) => selected?.id === run.id}
        rowActions={(run) => (
          <Button variant="ghost" size="sm" onClick={() => setSelected(run)}>
            Detalle
          </Button>
        )}
      />

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected ? `Run ${selected.id.slice(0, 8)}` : "Run"}
        description={selected ? kbName(selected) : undefined}
        width={460}
      >
        {selected && <RunDetail run={selected} stepStatus={stepStatus} />}
      </Drawer>
    </div>
  );
}

function RunDetail({
  run,
  stepStatus,
}: {
  run: Run;
  stepStatus: (run: Run, step: string) => "done" | "active" | "todo";
}) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={run.status} />
        <Badge tone={run.status === "failed" ? "danger" : "neutral"}>
          {run.progress}%
        </Badge>
      </div>
      <Progress
        value={run.progress}
        tone={run.status === "failed" ? "danger" : run.status === "completed" ? "ok" : "accent"}
        showValue
        label="Avance del pipeline"
      />

      <section>
        <p className="eyebrow mb-2">Etapas</p>
        <ol className="space-y-2">
          {STEPS.map((step) => {
            const st = stepStatus(run, step);
            return (
              <li key={step} className="flex items-center gap-2.5 text-[13px]">
                {st === "done" ? (
                  <CheckCircle size={15} weight="fill" className="shrink-0 text-ok" aria-hidden />
                ) : st === "active" ? (
                  <CircleNotch size={15} className="shrink-0 animate-spin text-accent" aria-hidden />
                ) : (
                  <Circle size={15} className="shrink-0 text-ghost" aria-hidden />
                )}
                <span className={st === "todo" ? "text-faint" : "text-text"}>
                  {STEP_LABELS[step] ?? step}
                </span>
                <span className="ml-auto text-xs text-faint tabular-nums">
                  {st === "done" ? "Completada" : st === "active" ? "En curso" : "Pendiente"}
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      <section>
        <p className="eyebrow mb-2">Métricas</p>
        <KeyValue
          columns={2}
          items={[
            { key: "Filas", value: fmtNum(run.rows_processed), mono: true },
            { key: "Vectores", value: fmtNum(run.vectors_upserted), mono: true },
            { key: "Errores", value: fmtNum(run.errors), mono: true },
            { key: "Paso actual", value: STEP_LABELS[run.current_step] ?? run.current_step },
            { key: "Creado", value: run.created_at ? fmtDateTime(run.created_at) : "—" },
            { key: "Finalizado", value: run.finished_at ? fmtDateTime(run.finished_at) : "—" },
          ]}
        />
      </section>

      {run.error_summary && (
        <section>
          <p className="eyebrow mb-2">Error</p>
          <ErrorInline className="mb-0">
            <span className="flex items-start gap-2">
              <WarningCircle size={15} className="mt-0.5 shrink-0" aria-hidden />
              {formatErrorSummary(run.error_summary)}
            </span>
          </ErrorInline>
        </section>
      )}
    </div>
  );
}
