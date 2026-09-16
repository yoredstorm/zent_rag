import { ArrowsClockwise, Play, Stack } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Button,
  ButtonLink,
  Checkbox,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  StatusBadge,
  SuccessInline,
  ToolbarSpacer,
  type Column,
  type SortState,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtDateTime } from "../../lib/format";

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

const PAGE_SIZE = 10;

function runScore(run: Run): number | null {
  const value = run.composite_score ?? run.quality?.composite_score;
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function sortRuns(rows: Run[], sort: SortState): Run[] {
  if (!sort) return rows;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = sort.key === "composite_score" ? runScore(a) : a[sort.key as keyof Run];
    const bv = sort.key === "composite_score" ? runScore(b) : b[sort.key as keyof Run];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "es") * dir;
  });
}

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
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);

  const reload = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    try {
      const [ds, rs] = await Promise.all([
        api<{ datasets: Dataset[] }>("/api/v1/eval/datasets", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ runs: Run[] }>("/api/v1/eval/runs?limit=100", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setDatasets(ds.datasets || []);
      setRuns(rs.runs || []);
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Error cargando runs");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void reload();
  }, [reload]);

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

  const sorted = sortRuns(runs, sort);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const columns: Column<Run>[] = [
    {
      key: "dataset_name",
      header: "Run",
      sortable: true,
      render: (run) => (
        <div className="min-w-0">
          <Link
            to={`/evaluation/runs/${run.id}`}
            className="text-[13.5px] font-medium text-accent transition-colors duration-150 hover:underline"
          >
            {run.dataset_name || run.id.slice(0, 8)}
          </Link>
          <p className="mono mt-0.5 text-xs text-faint">{run.id.slice(0, 8)}</p>
        </div>
      ),
    },
    {
      key: "composite_score",
      header: "Score",
      align: "right",
      sortable: true,
      render: (run) => {
        const score = runScore(run);
        return <span className="mono text-[13px]">{score == null ? "—" : score.toFixed(3)}</span>;
      },
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      render: (run) => <StatusBadge status={run.status || "completed"} />,
    },
    {
      key: "created_at",
      header: "Fecha",
      sortable: true,
      hideBelow: "md",
      render: (run) => (
        <span className="text-xs text-muted tabular-nums">
          {run.created_at ? fmtDateTime(run.created_at) : "—"}
        </span>
      ),
    },
  ];

  return (
    <QualityLayout>
      <PageHeader
        title="Runs de evaluación"
        subtitle="El juez LLM no es determinista. Los costes del judge se registran en usage."
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        <Panel>
          <PanelHeader
            title="Lanzar evaluación"
            description="Elegí un dataset y ejecutá el pipeline completo. Podés activar el juez LLM para métricas semánticas."
          />
          <form
            className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end"
            onSubmit={onRun}
          >
            <Field label="Dataset" required className="min-w-0 flex-1">
              <Select
                id="run-ds"
                value={datasetId}
                onChange={(ev) => setDatasetId(ev.target.value)}
                placeholder="Selecciona…"
                required
              >
                {datasets.map((ds) => (
                  <option key={ds.id} value={ds.id}>
                    {ds.name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex min-h-9 items-center sm:pb-0.5">
              <Checkbox
                checked={judge}
                onCheckedChange={setJudge}
                label="Juez LLM"
                hint="Añade fidelidad, relevancia y alucinación."
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              loading={busy}
              disabled={!datasetId}
              leadingIcon={Play}
            >
              Lanzar
            </Button>
          </form>
        </Panel>

        <DataTable
          columns={columns}
          rows={pageRows}
          rowKey={(run) => run.id}
          caption="Runs de evaluación"
          loading={loading}
          error={loadError}
          stickyHeader
          sort={sort}
          onSortChange={(next) => {
            setSort(next);
            setPage(1);
          }}
          toolbar={
            <>
              <ResultCount shown={pageRows.length} total={runs.length} noun="runs" />
              <ToolbarSpacer />
              <Button
                size="sm"
                variant="ghost"
                leadingIcon={ArrowsClockwise}
                onClick={() => void reload()}
                disabled={loading}
              >
                Actualizar
              </Button>
            </>
          }
          empty={
            <EmptyState
              icon={Stack}
              title="Sin runs"
              body="Importá un dataset y lanzá una evaluación para guardar score, latencia y coste por run."
              action={
                <ButtonLink to="/evaluation/datasets" variant="primary">
                  Ir a datasets
                </ButtonLink>
              }
            />
          }
          footer={
            sorted.length > PAGE_SIZE ? (
              <Pagination
                page={safePage}
                pageSize={PAGE_SIZE}
                total={sorted.length}
                onPageChange={setPage}
              />
            ) : undefined
          }
        />
      </div>
    </QualityLayout>
  );
}
