import { CheckCircle, Flask, Play, Plus, XCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  Checkbox,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  SectionHeader,
  Select,
  Skeleton,
  StatusBadge,
  SuccessInline,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtDate, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Dataset = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  version: number;
  status: string;
  items: number;
  created_at: string;
};

type Run = {
  id: string;
  dataset_id: string;
  dataset_version: number;
  agent_id: string;
  model: string | null;
  status: string;
  score_overall: number | null;
  faithfulness: number | null;
  hallucination_rate: number | null;
  latency_p95: number | null;
  cost_total: number | null;
  passed_gate: boolean | null;
  regression: boolean;
  started_at: string;
};

const PAGE_SIZE = 20;

function sortRows<T>(rows: T[], sort: SortState, get: (row: T, key: string) => string | number) {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const left = get(a, sort.key);
    const right = get(b, sort.key);
    if (typeof left === "string" && typeof right === "string") {
      return sort.dir === "asc" ? left.localeCompare(right) : right.localeCompare(left);
    }
    return sort.dir === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
  });
}

export default function AdminEvalsLabPage() {
  const { session } = usePlatformAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [agents, setAgents] = useState<Record<string, { id: string; name: string }[]>>({});
  const [dsForm, setDsForm] = useState({ organization_id: "", name: "", description: "" });
  const [itemForm, setItemForm] = useState({ dataset_id: "", question: "", expected_answer: "" });
  const [runForm, setRunForm] = useState({ organization_id: "", dataset_id: "", agent_id: "", auto_promote: false, auto_rollback: false });
  const [detail, setDetail] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sortDatasets, setSortDatasets] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [sortRuns, setSortRuns] = useState<SortState>({ key: "started_at", dir: "desc" });
  const [page, setPage] = useState(1);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [d, r, o] = await Promise.all([
        platformApi<{ datasets: Dataset[] }>("/api/v1/platform/evals/datasets", { token: session.token }),
        platformApi<{ runs: Run[] }>("/api/v1/platform/evals/runs", { token: session.token }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token }),
      ]);
      setDatasets(d.datasets || []);
      setRuns(r.runs || []);
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

  async function loadAgents(oid: string) {
    if (!session) return;
    try {
      const a = await platformApi<{ agents: { id: string; name: string }[] }>(
        `/api/v1/platform/organizations/${oid}/agents`,
        { token: session.token }
      );
      setAgents((prev) => ({ ...prev, [oid]: a.agents || [] }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function createDataset() {
    if (!session) return;
    setBusy("ds");
    setError("");
    setNotice("");
    try {
      await platformApi("/api/v1/platform/evals/datasets", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(dsForm),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addItems() {
    if (!session) return;
    setBusy("items");
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ version: number; items_added: number }>(
        `/api/v1/platform/evals/datasets/${itemForm.dataset_id}/items`,
        { method: "POST", token: session.token, body: JSON.stringify({ items: [{ question: itemForm.question, expected_answer: itemForm.expected_answer }] }) }
      );
      setNotice(`Items añadidos: ${out.items_added} (v${out.version})`);
      setItemForm({ dataset_id: "", question: "", expected_answer: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function triggerRun() {
    if (!session) return;
    setBusy("run");
    setError("");
    setNotice("");
    setDetail("");
    try {
      const out = await platformApi<{ status: string; run_id: string }>("/api/v1/platform/evals/runs", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(runForm),
      });
      setNotice(`Run iniciado: ${out.run_id.slice(0, 8)}…`);
      setTimeout(() => void load(), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(runId: string) {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Record<string, unknown>>(`/api/v1/platform/evals/runs/${runId}`, {
        token: session.token,
      });
      setDetail(JSON.stringify(d, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const datasetRows = useMemo(
    () =>
      sortRows(datasets, sortDatasets, (row, key) => {
        if (key === "name") return row.name;
        if (key === "version") return row.version;
        if (key === "items") return row.items;
        if (key === "status") return row.status;
        if (key === "created_at") return row.created_at;
        return row.name;
      }),
    [datasets, sortDatasets]
  );

  const runRows = useMemo(
    () =>
      sortRows(runs, sortRuns, (row, key) => {
        if (key === "status") return row.status;
        if (key === "model") return row.model ?? "";
        if (key === "score_overall") return row.score_overall ?? -1;
        if (key === "faithfulness") return row.faithfulness ?? -1;
        if (key === "hallucination_rate") return row.hallucination_rate ?? -1;
        if (key === "latency_p95") return row.latency_p95 ?? -1;
        if (key === "passed_gate") return row.passed_gate ? 1 : 0;
        if (key === "regression") return row.regression ? 1 : 0;
        return row.started_at;
      }),
    [runs, sortRuns]
  );

  const completed = runs.filter((r) => r.status === "completed");
  const passedGate = completed.filter((r) => r.passed_gate).length;
  const regressions = runs.filter((r) => r.regression).length;
  const totalItems = datasets.reduce((n, d) => n + d.items, 0);
  const maxPage = Math.max(1, Math.ceil(runRows.length / PAGE_SIZE));
  const safePage = Math.min(page, maxPage);
  const pageRuns = runRows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const datasetColumns: Column<Dataset>[] = [
    {
      key: "name",
      header: "Dataset",
      sortable: true,
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-[13px] text-text" title={row.name}>
            {row.name}
          </p>
          {row.description && (
            <p className="max-w-[360px] truncate text-xs text-faint" title={row.description}>
              {row.description}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "version",
      header: "Versión",
      sortable: true,
      width: "100px",
      render: (row) => <Badge tone="neutral">v{row.version}</Badge>,
    },
    {
      key: "items",
      header: "Items",
      align: "right",
      sortable: true,
      width: "90px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.items)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "created_at",
      header: "Creado",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "130px",
      render: (row) => <span className="text-xs text-faint">{fmtDate(row.created_at)}</span>,
    },
  ];

  const runColumns: Column<Run>[] = [
    {
      key: "id",
      header: "Run",
      width: "120px",
      render: (row) => <span className="mono text-xs text-faint">{row.id.slice(0, 8)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      hideBelow: "md",
      render: (row) => <span className="mono text-xs text-muted">{row.model ?? "—"}</span>,
    },
    {
      key: "score_overall",
      header: "Score",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.score_overall ?? "—"}</span>,
    },
    {
      key: "faithfulness",
      header: "Faith.",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.faithfulness ?? "—"}</span>,
    },
    {
      key: "hallucination_rate",
      header: "Halluc.",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.hallucination_rate ?? "—"}</span>,
    },
    {
      key: "latency_p95",
      header: "p95",
      align: "right",
      sortable: true,
      hideBelow: "xl",
      width: "100px",
      render: (row) => (
        <span className="mono text-xs text-muted">{row.latency_p95 != null ? `${row.latency_p95.toFixed(0)}ms` : "—"}</span>
      ),
    },
    {
      key: "passed_gate",
      header: "Gate",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) =>
        row.status !== "completed" ? (
          <span className="text-xs text-faint">—</span>
        ) : row.passed_gate == null ? (
          <Badge tone="neutral">sin gate</Badge>
        ) : row.passed_gate ? (
          <Badge tone="ok" icon={CheckCircle}>
            PASS
          </Badge>
        ) : (
          <Badge tone="danger" icon={XCircle}>
            FAIL
          </Badge>
        ),
    },
    {
      key: "regression",
      header: "Regresión",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) =>
        row.regression ? <Badge tone="danger">Regresión</Badge> : <span className="text-xs text-faint">—</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evals Lab"
        subtitle="Datasets versionados, runs con gate de promo y detección de regresión."
      />
      <ErrorInline message={error} />
      <SuccessInline message={notice} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[320px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Runs ejecutados"
              value={fmtNum(runs.length)}
              hint={completed.length > 0 ? `${passedGate} de ${completed.length} completados pasaron el gate` : "Sin runs completados"}
              icon={Flask}
              tone={regressions > 0 ? "warn" : "default"}
            />
            <MetricGrid cols={3} className="lg:grid-cols-3">
              <Metric label="Datasets" value={fmtNum(datasets.length)} size="md" />
              <Metric label="Items versionados" value={fmtNum(totalItems)} size="md" hint="Suma de datasets" />
              <Metric
                label="Regresiones"
                value={fmtNum(regressions)}
                size="md"
                tone={regressions > 0 ? "danger" : "default"}
              />
            </MetricGrid>
          </div>

          <Tabs defaultValue="datasets">
            <TabsList>
              <TabsTrigger value="datasets">Datasets</TabsTrigger>
              <TabsTrigger value="runs">Runs</TabsTrigger>
            </TabsList>

            <TabsContent value="datasets">
              <section className="min-w-0">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <Plus size={15} aria-hidden /> Dataset + items
                    </span>
                  }
                  description="Cada lote de items incrementa la versión del dataset."
                  className="mb-3"
                />
                <Panel className="mb-4">
                  <PanelHeader title="Crear dataset" description="Pertenece a una organización." />
                  <div className="panel-body">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field label="Organización">
                        <Select
                          value={dsForm.organization_id}
                          onChange={(e) => setDsForm((f) => ({ ...f, organization_id: e.target.value }))}
                          placeholder="Seleccionar…"
                        >
                          {orgs.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.id.slice(0, 8)}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Nombre">
                        <Input
                          value={dsForm.name}
                          onChange={(e) => setDsForm((f) => ({ ...f, name: e.target.value }))}
                          placeholder="ej. soporte-v1"
                        />
                      </Field>
                      <Field label="Descripción" hint="Opcional">
                        <Input
                          value={dsForm.description}
                          onChange={(e) => setDsForm((f) => ({ ...f, description: e.target.value }))}
                        />
                      </Field>
                    </div>
                    <div className="mt-3">
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={busy === "ds"}
                        disabled={!dsForm.organization_id || !dsForm.name.trim()}
                        onClick={() => void createDataset()}
                      >
                        Crear dataset
                      </Button>
                    </div>
                  </div>
                </Panel>

                <Panel className="mb-4">
                  <PanelHeader title="Añadir item" description="Pregunta y respuesta esperada; incrementa la versión." />
                  <div className="panel-body">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field label="Dataset">
                        <Select
                          value={itemForm.dataset_id}
                          onChange={(e) => setItemForm((f) => ({ ...f, dataset_id: e.target.value }))}
                          placeholder="Seleccionar…"
                        >
                          {datasets.map((d) => (
                            <option key={d.id} value={d.id}>
                              {d.name} (v{d.version})
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Pregunta">
                        <Input
                          value={itemForm.question}
                          onChange={(e) => setItemForm((f) => ({ ...f, question: e.target.value }))}
                        />
                      </Field>
                      <Field label="Respuesta esperada">
                        <Input
                          value={itemForm.expected_answer}
                          onChange={(e) => setItemForm((f) => ({ ...f, expected_answer: e.target.value }))}
                        />
                      </Field>
                    </div>
                    <div className="mt-3">
                      <Button
                        variant="primary"
                        size="sm"
                        leadingIcon={Plus}
                        loading={busy === "items"}
                        disabled={!itemForm.dataset_id || !itemForm.question.trim()}
                        onClick={() => void addItems()}
                      >
                        Añadir item
                      </Button>
                    </div>
                  </div>
                </Panel>

                <DataTable
                  stickyHeader
                  columns={datasetColumns}
                  rows={datasetRows}
                  rowKey={(row) => row.id}
                  sort={sortDatasets}
                  onSortChange={setSortDatasets}
                  empty={
                    <EmptyState
                      icon={Flask}
                      title="Sin datasets"
                      body="Creá el primero para versionar preguntas y respuestas esperadas."
                    />
                  }
                />
              </section>
            </TabsContent>

            <TabsContent value="runs">
              <section className="min-w-0">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <Play size={15} aria-hidden /> Ejecutar run
                    </span>
                  }
                  description="El run evalúa el agente contra el dataset elegido."
                  className="mb-3"
                />
                <Panel className="mb-4">
                  <PanelHeader title="Configuración del run" description="Org, dataset y agente a evaluar." />
                  <div className="panel-body">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field label="Organización">
                        <Select
                          value={runForm.organization_id}
                          onChange={(e) => {
                            setRunForm((f) => ({ ...f, organization_id: e.target.value }));
                            void loadAgents(e.target.value);
                          }}
                          placeholder="Seleccionar…"
                        >
                          {orgs.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.id.slice(0, 8)}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Dataset">
                        <Select
                          value={runForm.dataset_id}
                          onChange={(e) => setRunForm((f) => ({ ...f, dataset_id: e.target.value }))}
                          placeholder="Seleccionar…"
                        >
                          {datasets
                            .filter((d) => !runForm.organization_id || d.organization_id === runForm.organization_id)
                            .map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.name} (v{d.version}, {d.items} items)
                              </option>
                            ))}
                        </Select>
                      </Field>
                      <Field label="Agente">
                        <Select
                          value={runForm.agent_id}
                          onChange={(e) => setRunForm((f) => ({ ...f, agent_id: e.target.value }))}
                          placeholder="Seleccionar…"
                        >
                          {(agents[runForm.organization_id] ?? []).map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    </div>
                    <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-6">
                      <Checkbox
                        checked={runForm.auto_promote}
                        onCheckedChange={(checked) => setRunForm((f) => ({ ...f, auto_promote: checked }))}
                        label="Auto-promote si pasa gate"
                      />
                      <Checkbox
                        checked={runForm.auto_rollback}
                        onCheckedChange={(checked) => setRunForm((f) => ({ ...f, auto_rollback: checked }))}
                        label="Auto-rollback si regresión"
                      />
                    </div>
                    <div className="mt-3">
                      <Button
                        variant="primary"
                        size="sm"
                        leadingIcon={Play}
                        loading={busy === "run"}
                        disabled={!runForm.organization_id || !runForm.dataset_id || !runForm.agent_id}
                        onClick={() => void triggerRun()}
                      >
                        Ejecutar
                      </Button>
                    </div>
                  </div>
                </Panel>

                <DataTable
                  stickyHeader
                  columns={runColumns}
                  rows={pageRuns}
                  rowKey={(row) => row.id}
                  sort={sortRuns}
                  onSortChange={(next) => {
                    setSortRuns(next);
                    setPage(1);
                  }}
                  onRowClick={(row) => void showDetail(row.id)}
                  rowActions={(row) => (
                    <Button variant="ghost" size="sm" onClick={() => void showDetail(row.id)}>
                      Ver
                    </Button>
                  )}
                  empty={
                    <EmptyState
                      icon={Flask}
                      title="Sin runs"
                      body="Creá un dataset con items y ejecutá una evaluación."
                    />
                  }
                  footer={
                    runRows.length > PAGE_SIZE ? (
                      <>
                        <ResultCount shown={pageRuns.length} total={runRows.length} noun="runs" />
                        <Pagination page={safePage} pageSize={PAGE_SIZE} total={runRows.length} onPageChange={setPage} />
                      </>
                    ) : (
                      <ResultCount shown={runRows.length} total={runRows.length} noun="runs" />
                    )
                  }
                />
              </section>
            </TabsContent>
          </Tabs>

          <Drawer
            open={Boolean(detail)}
            onOpenChange={(open) => {
              if (!open) setDetail("");
            }}
            title="Detalle del run"
            description="Respuesta cruda de la API de evaluación."
            width={620}
          >
            <CodeBlock code={detail} language="json" maxHeight={560} showLineNumbers />
          </Drawer>
        </>
      )}
    </div>
  );
}
