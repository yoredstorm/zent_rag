import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  SkeletonBlock,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  type Column,
} from "../../components/ui";
import { fmtCurrency, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Dash = {
  decisions: {
    decisions_today: number;
    rules_pct: number;
    jev_pct: number;
    small_llm_pct: number;
    reasoning_llm_pct: number;
    average_confidence: number;
    fallback_rate: number;
    average_latency_ms: number;
  };
  usage: {
    requests: number;
    tokens: number;
    cost: number;
    average_cost: number;
    weighted_average_cost: number;
    by_event_type: { event_type: string; requests: number; cost: number }[];
    by_provider: { provider: string; requests: number; cost: number }[];
  };
  efficiency: {
    score: number;
    components: { quality: number; cost: number; latency: number; fallback: number };
    weights: { quality: number; cost: number; latency: number; fallback: number };
    formula: string;
  };
  llm_calls_avoided_estimate: number;
  flags: Record<string, string | number>;
};

type Price = {
  provider: string;
  model: string;
  input_cost_per_1k: number;
  output_cost_per_1k: number;
  embedding_cost_per_1k: number;
  request_cost: number;
  cost_kind: string;
  currency: string;
  updated_at: string;
};

type Cap = {
  id: string;
  name: string;
  handler: string;
  risk: string;
  cost_class: string;
  availability: string;
};

export default function AdminRuntimePage() {
  const { session } = usePlatformAuth();
  const token = session?.token;
  const [dash, setDash] = useState<Dash | null>(null);
  const [prices, setPrices] = useState<Price[]>([]);
  const [caps, setCaps] = useState<Cap[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [labInput, setLabInput] = useState(
    '[{"request":"hola","expected_capability":"respond_directly"}]',
  );
  const [labOut, setLabOut] = useState<string>("");
  const [edit, setEdit] = useState<Partial<Price>>({
    provider: "jev",
    model: "jev-latest",
    input_cost_per_1k: 0,
    output_cost_per_1k: 0,
    embedding_cost_per_1k: 0,
    request_cost: 0,
    cost_kind: "provider",
    currency: "USD",
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [board, providers, capabilities] = await Promise.all([
          platformApi<Dash>("/api/v1/platform/runtime/dashboard", { token }),
          platformApi<{ prices: Price[] }>("/api/v1/platform/runtime/providers", { token }),
          platformApi<{ items: Cap[] }>("/api/v1/platform/runtime/capabilities", { token }),
        ]);
        if (cancelled) return;
        setDash(board);
        setPrices(providers.prices || []);
        setCaps(capabilities.items || []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load runtime");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function savePrice() {
    if (!token) return;
    try {
      await platformApi("/api/v1/platform/runtime/providers", {
        token,
        method: "PUT",
        body: JSON.stringify(edit),
      });
      const providers = await platformApi<{ prices: Price[] }>("/api/v1/platform/runtime/providers", {
        token,
      });
      setPrices(providers.prices || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el precio");
    }
  }

  async function runLab() {
    if (!token) return;
    try {
      const cases = JSON.parse(labInput);
      const out = await platformApi("/api/v1/platform/runtime/experiments", {
        token,
        method: "POST",
        body: JSON.stringify({ cases }),
      });
      setLabOut(JSON.stringify(out, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Experiment failed");
    }
  }

  const priceCols: Column<Price>[] = [
    { key: "provider", header: "Provider", render: (row) => row.provider },
    { key: "model", header: "Model", render: (row) => row.model },
    { key: "kind", header: "Kind", render: (row) => row.cost_kind },
    {
      key: "in",
      header: "Input / 1k",
      align: "right",
      render: (row) => fmtCurrency(row.input_cost_per_1k),
    },
    {
      key: "out",
      header: "Output / 1k",
      align: "right",
      render: (row) => fmtCurrency(row.output_cost_per_1k),
    },
    {
      key: "req",
      header: "Per request",
      align: "right",
      render: (row) => fmtCurrency(row.request_cost || 0),
    },
  ];

  const capCols: Column<Cap>[] = [
    { key: "id", header: "Capability", render: (row) => row.id },
    { key: "handler", header: "Handler", render: (row) => row.handler || "—" },
    { key: "risk", header: "Risk", render: (row) => row.risk },
    { key: "cost", header: "Cost", render: (row) => row.cost_class },
    { key: "availability", header: "Availability", render: (row) => row.availability },
  ];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="AI Runtime"
        subtitle="Knowledge, Agents, Tools y Workflows son capabilities del mismo runtime. JEV decide; el Orchestrator ejecuta."
      />
      {error ? <ErrorInline message={error} /> : null}
      {loading ? <SkeletonBlock rows={5} /> : null}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="providers">Providers</TabsTrigger>
          <TabsTrigger value="capabilities">Capabilities</TabsTrigger>
          <TabsTrigger value="lab">Experiment Lab</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          {dash ? (
            <div className="flex flex-col gap-4">
              <MetricGrid>
                <Metric label="Requests today" value={fmtNum(dash.usage.requests)} />
                <Metric label="Decisions" value={fmtNum(dash.decisions.decisions_today)} />
                <Metric label="JEV %" value={`${dash.decisions.jev_pct}%`} />
                <Metric label="Rules %" value={`${dash.decisions.rules_pct}%`} />
                <Metric label="Small LLM %" value={`${dash.decisions.small_llm_pct}%`} />
                <Metric label="Large LLM %" value={`${dash.decisions.reasoning_llm_pct}%`} />
                <Metric label="Avg cost / request" value={fmtCurrency(dash.usage.average_cost)} />
                <Metric
                  label="Weighted cost / request"
                  value={fmtCurrency(dash.usage.weighted_average_cost)}
                />
                <Metric label="Tokens" value={fmtNum(dash.usage.tokens)} />
                <Metric label="Provider cost" value={fmtCurrency(dash.usage.cost)} />
                <Metric
                  label="LLM calls avoided (est.)"
                  value={fmtNum(dash.llm_calls_avoided_estimate)}
                />
                <Metric label="AI Efficiency Score" value={dash.efficiency.score.toFixed(3)} />
              </MetricGrid>
              <Panel>
                <PanelHeader title="Efficiency components" />
                <p className="mb-3 text-[12px] text-muted">{dash.efficiency.formula}</p>
                <div className="grid gap-3 sm:grid-cols-4">
                  {(["quality", "cost", "latency", "fallback"] as const).map((key) => (
                    <div key={key}>
                      <div className="text-xs text-muted">{key}</div>
                      <div>{dash.efficiency.components[key].toFixed(3)}</div>
                      <div className="text-xs text-faint">
                        weight {dash.efficiency.weights[key].toFixed(2)}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel>
                <PanelHeader title="Flags" />
                <div className="flex flex-wrap gap-2">
                  {Object.entries(dash.flags).map(([key, value]) => (
                    <Badge key={key} tone="neutral">
                      {key}: {String(value)}
                    </Badge>
                  ))}
                </div>
              </Panel>
              <Panel>
                <PanelHeader title="Trace shape" />
                <p className="text-[13px] leading-relaxed text-muted">
                  User → JEV Decision → Knowledge Search → Evidence Gate → Response. El chat ejecuta
                  knowledge y SQL; agentes, workflows y tools corren con target explícito
                  (agent_id / workflow_id / tool) vía CapabilityDispatcher. Cada paso registra
                  duration, tokens, cost, confidence y status en decision_traces y rag_trace.
                </p>
              </Panel>
            </div>
          ) : null}
        </TabsContent>
        <TabsContent value="providers">
          <Panel>
            <PanelHeader title="Provider costs" />
              <DataTable
                columns={priceCols}
                rows={prices}
                rowKey={(row) => `${row.provider}:${row.model}`}
                empty={<EmptyState title="Sin precios" body="El registry de pricing_models está vacío." />}
              />
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Field label="Provider">
                <Input
                  value={String(edit.provider || "")}
                  onChange={(e) => setEdit({ ...edit, provider: e.target.value })}
                />
              </Field>
              <Field label="Model">
                <Input
                  value={String(edit.model || "")}
                  onChange={(e) => setEdit({ ...edit, model: e.target.value })}
                />
              </Field>
              <Field label="Kind">
                <Select
                  value={String(edit.cost_kind || "provider")}
                  onChange={(e) => setEdit({ ...edit, cost_kind: e.target.value })}
                >
                  <option value="provider">provider</option>
                  <option value="internal">internal</option>
                  <option value="customer">customer</option>
                </Select>
              </Field>
              <Field label="Input / 1k">
                <Input
                  type="number"
                  value={String(edit.input_cost_per_1k ?? 0)}
                  onChange={(e) => setEdit({ ...edit, input_cost_per_1k: Number(e.target.value) })}
                />
              </Field>
              <Field label="Output / 1k">
                <Input
                  type="number"
                  value={String(edit.output_cost_per_1k ?? 0)}
                  onChange={(e) => setEdit({ ...edit, output_cost_per_1k: Number(e.target.value) })}
                />
              </Field>
              <Field label="Per request">
                <Input
                  type="number"
                  value={String(edit.request_cost ?? 0)}
                  onChange={(e) => setEdit({ ...edit, request_cost: Number(e.target.value) })}
                />
              </Field>
            </div>
            <Button className="mt-3" onClick={() => void savePrice()}>
              Guardar precio
            </Button>
          </Panel>
        </TabsContent>
        <TabsContent value="capabilities">
          <Panel>
            <PanelHeader title="Capability registry" />
              <DataTable
                columns={capCols}
                rows={caps}
                rowKey={(row) => row.id}
                empty={<EmptyState title="Sin capabilities" body="El catálogo no devolvió specs." />}
              />
          </Panel>
        </TabsContent>
        <TabsContent value="lab">
          <Panel>
            <PanelHeader title="Experiment Lab" />
            <p className="mb-3 text-[13px] text-muted">
              Compara Rules, JEV, Novita small y reasoning LLM sobre un dataset. No es tráfico de
              producción.
            </p>
            <Textarea rows={8} value={labInput} onChange={(e) => setLabInput(e.target.value)} />
            <Button className="mt-3" onClick={() => void runLab()}>
              Ejecutar comparación
            </Button>
            {labOut ? (
              <pre className="mt-4 overflow-auto rounded-md bg-soft p-3 text-[12px]">{labOut}</pre>
            ) : null}
          </Panel>
        </TabsContent>
      </Tabs>
    </div>
  );
}
