import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  DataTable,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  SkeletonBlock,
  type Column,
} from "../../components/ui";
import { fmtDateTime, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Status = {
  primary_provider: string;
  fallback: string;
  mode: string;
  shadow: boolean;
  high_confidence: number;
  low_confidence: number;
  canary_percentage: number;
  jev_status: string;
  rules_loaded?: boolean;
};

type Dashboard = {
  decisions_today: number;
  rules_pct: number;
  jev_pct: number;
  small_llm_pct: number;
  reasoning_llm_pct: number;
  average_confidence: number;
  fallback_rate: number;
  average_latency_ms: number;
  estimated_savings: number;
};

type TraceRow = {
  id: string;
  provider: string;
  selected_capability: string;
  confidence: number;
  routing_mode: string;
  actual_capability: string | null;
  jev_capability: string | null;
  agreement: boolean | null;
  created_at: string | null;
};

type AdaptiveStatus = {
  mode: string;
  canary_percentage: number;
  max_retrieval_attempts: number;
  top_k?: { min: number; max: number };
  jev_evidence: boolean;
  fast_path: boolean;
  rewrite: boolean;
  policy_version: string;
};

type FabricStatus = {
  mode?: string;
  count?: number;
  observations?: Array<{
    kind?: string;
    policy_action?: string;
    confidence?: number;
    reason?: string;
    target_id?: string | null;
  }>;
};

type LearningReport = {
  totals?: { routing_accuracy?: number | null; fallbacks?: number; decisions?: number };
  mismatches?: Array<{
    capability?: string;
    actual_capability?: string | null;
    cases?: number;
  }>;
  fallbacks_by_capability?: Array<{ capability?: string; fallbacks?: number }>;
};

type CalibrationReport = {
  accuracy?: number | null;
  buckets?: Array<{
    bucket?: string;
    decisions?: number;
    accuracy?: number | null;
    calibration_gap?: number | null;
  }>;
};

type ModelReport = {
  production_model?: string;
  candidate_model?: string | null;
  models?: Array<{
    model?: string;
    role?: string;
    decisions?: number;
    routing_accuracy?: number | null;
    cost?: number;
  }>;
};

type CostReport = {
  total_cost?: number;
  jev_cost?: number;
  jev_share?: number | null;
  categories?: Array<{ category?: string; cost?: number; events?: number }>;
  per_result?: {
    cost_per_successful_answer?: number | null;
    cost_per_agent_run?: number | null;
    cost_per_workflow_run?: number | null;
  };
};

type RiskPolicyReport = {
  levels?: Record<
    string,
    {
      choice_threshold?: number;
      warrant_required?: boolean;
      on_low_confidence?: string;
    }
  >;
  max_selectable_risk?: string;
  tenant_override?: boolean;
};

export default function AdminDecisionEnginePage() {
  const { session } = usePlatformAuth();
  const token = session?.token;
  const [status, setStatus] = useState<Status | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [adaptive, setAdaptive] = useState<AdaptiveStatus | null>(null);
  const [fabric, setFabric] = useState<FabricStatus | null>(null);
  const [learning, setLearning] = useState<LearningReport | null>(null);
  const [calibration, setCalibration] = useState<CalibrationReport | null>(null);
  const [models, setModels] = useState<ModelReport | null>(null);
  const [costs, setCosts] = useState<CostReport | null>(null);
  const [riskPolicy, setRiskPolicy] = useState<RiskPolicyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [st, board, recent, adp, sel, learn, calib, mdl, cost, risk] = await Promise.all([
          platformApi<Status>("/api/v1/platform/decision/status", { token }),
          platformApi<Dashboard>("/api/v1/platform/decision/dashboard", { token }),
          platformApi<{ items: TraceRow[] }>("/api/v1/platform/decision/traces?limit=40", {
            token,
          }),
          platformApi<AdaptiveStatus>("/api/v1/platform/adaptive/status", { token }).catch(
            () => null,
          ),
          platformApi<FabricStatus>("/api/v1/platform/decision/selection", { token }).catch(
            () => null,
          ),
          platformApi<LearningReport>("/api/v1/platform/decision/learning", { token }).catch(
            () => null,
          ),
          platformApi<CalibrationReport>("/api/v1/platform/decision/calibration", {
            token,
          }).catch(() => null),
          platformApi<ModelReport>("/api/v1/platform/decision/models", { token }).catch(
            () => null,
          ),
          platformApi<CostReport>("/api/v1/platform/decision/costs", { token }).catch(
            () => null,
          ),
          platformApi<RiskPolicyReport>("/api/v1/platform/decision/risk-policy", {
            token,
          }).catch(() => null),
        ]);
        if (cancelled) return;
        setStatus(st);
        setDash(board);
        setTraces(recent.items || []);
        setAdaptive(adp);
        setFabric(sel);
        setLearning(learn);
        setCalibration(calib);
        setModels(mdl);
        setCosts(cost);
        setRiskPolicy(risk);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load Decision Engine");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const columns: Column<TraceRow>[] = [
    {
      key: "created_at",
      header: "When",
      render: (row) => fmtDateTime(row.created_at),
    },
    { key: "provider", header: "Provider", render: (row) => row.provider },
    {
      key: "selected_capability",
      header: "Capability",
      render: (row) => row.selected_capability,
    },
    {
      key: "confidence",
      header: "Confidence",
      align: "right",
      render: (row) => row.confidence.toFixed(2),
    },
    { key: "routing_mode", header: "Mode", render: (row) => row.routing_mode },
    {
      key: "agreement",
      header: "Agree",
      render: (row) => (row.agreement == null ? "—" : row.agreement ? "yes" : "no"),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Decision Engine"
        subtitle="Rules first, then JEV System One, then a small LLM. The orchestrator still owns execution, auth, and fallbacks."
      />
      {error ? <ErrorInline message={error} /> : null}
      {loading ? <SkeletonBlock rows={4} /> : null}
      {status ? (
        <Panel>
          <PanelHeader title="Runtime" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <div className="text-xs text-muted">Primary</div>
              <div>{status.primary_provider}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Fallback</div>
              <div>{status.fallback || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Mode</div>
              <Badge tone={status.mode === "legacy" ? "neutral" : "info"}>{status.mode}</Badge>
            </div>
            <div>
              <div className="text-xs text-muted">JEV</div>
              <Badge tone={status.jev_status === "connected" ? "ok" : "neutral"}>
                {status.jev_status}
              </Badge>
            </div>
            <div>
              <div className="text-xs text-muted">Shadow</div>
              <div>{status.shadow ? "on" : "off"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">High / low confidence</div>
              <div>
                {status.high_confidence} / {status.low_confidence}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Canary</div>
              <div>{status.canary_percentage}%</div>
            </div>
            <div>
              <div className="text-xs text-muted">Rules</div>
              <div>{status.rules_loaded ? "loaded" : "missing"}</div>
            </div>
          </div>
        </Panel>
      ) : null}
      {dash ? (
        <>
          <SectionHeader title="Today" />
          <MetricGrid>
            <Metric label="Decisions" value={fmtNum(dash.decisions_today)} />
            <Metric label="Rules %" value={`${dash.rules_pct}`} />
            <Metric label="JEV %" value={`${dash.jev_pct}`} />
            <Metric label="Small LLM %" value={`${dash.small_llm_pct}`} />
            <Metric label="Reasoning LLM %" value={`${dash.reasoning_llm_pct}`} />
            <Metric label="Avg confidence" value={`${dash.average_confidence}`} />
            <Metric label="Fallback rate" value={`${dash.fallback_rate}`} />
            <Metric label="Avg latency ms" value={`${dash.average_latency_ms}`} />
            <Metric label="Est. decision cost" value={`${dash.estimated_savings}`} />
          </MetricGrid>
        </>
      ) : null}
      {adaptive ? (
        <Panel>
          <PanelHeader title="Adaptive RAG" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <div className="text-xs text-muted">Mode</div>
              <Badge tone={adaptive.mode === "off" ? "neutral" : "info"}>{adaptive.mode}</Badge>
            </div>
            <div>
              <div className="text-xs text-muted">Canary</div>
              <div>{adaptive.canary_percentage}%</div>
            </div>
            <div>
              <div className="text-xs text-muted">Max retrieval attempts</div>
              <div>{adaptive.max_retrieval_attempts}</div>
            </div>
            <div>
              <div className="text-xs text-muted">top_k min / max</div>
              <div>
                {adaptive.top_k?.min} / {adaptive.top_k?.max}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Fast path</div>
              <div>{adaptive.fast_path ? "on" : "off"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Rewrite</div>
              <div>{adaptive.rewrite ? "on" : "off"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">JEV evidence</div>
              <div>{adaptive.jev_evidence ? "on" : "off"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Policy</div>
              <div>{adaptive.policy_version}</div>
            </div>
          </div>
          <p className="mt-3 text-xs text-muted">
            Default off. Shadow observa el plan. Canary aplica un porcentaje. Cutover 100% solo
            con compare_legacy_vs_adaptive sobre el golden set. El RAG Trace vive en cada
            respuesta (`rag_trace`) y en Chat modo desarrollador.
          </p>
        </Panel>
      ) : null}
      {fabric || learning || calibration || models || costs || riskPolicy ? (
        <SectionHeader title="Judgment Fabric" />
      ) : null}
      {fabric ? (
        <Panel>
          <PanelHeader title="Target selection (agents · workflows · tools)" />
          <MetricGrid>
            <Metric label="Mode" value={fabric.mode ?? "off"} />
            <Metric label="Observations" value={fmtNum(fabric.count ?? 0)} />
          </MetricGrid>
          <div className="mt-3 flex flex-col gap-1 text-xs text-muted">
            {(fabric.observations ?? []).slice(-5).reverse().map((item, index) => (
              <div key={`${item.target_id ?? item.reason ?? "obs"}-${index}`}>
                {item.kind ?? "target"} · {item.policy_action ?? "—"} · conf{" "}
                {(item.confidence ?? 0).toFixed(2)} · {item.reason ?? ""}
                {item.target_id ? ` · ${item.target_id}` : ""}
              </div>
            ))}
            {(fabric.observations ?? []).length === 0 ? (
              <div>
                Shadow/on registra elecciones y política. off mantiene el target explícito.
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}
      {riskPolicy ? (
        <Panel>
          <PanelHeader title="Risk policy" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(riskPolicy.levels ?? {}).map(([level, thresholds]) => (
              <div key={level}>
                <div className="text-xs text-muted">{level}</div>
                <div>
                  choice ≥ {thresholds.choice_threshold ?? "—"}
                  {thresholds.warrant_required ? " + warrant" : ""}
                </div>
                <div className="text-xs text-muted">
                  si duda: {thresholds.on_low_confidence ?? "—"}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            Riesgo máximo auto-seleccionable: {riskPolicy.max_selectable_risk ?? "high"}
            {riskPolicy.tenant_override ? " · override del tenant activo" : ""}. HIGH/CRITICAL
            exigen dos señales (choice + action_warranted), nunca max().
          </p>
        </Panel>
      ) : null}
      {learning ? (
        <Panel>
          <PanelHeader title="Routing accuracy" />
          <MetricGrid>
            <Metric label="Decisions" value={fmtNum(learning.totals?.decisions ?? 0)} />
            <Metric label="Fallbacks" value={fmtNum(learning.totals?.fallbacks ?? 0)} />
            <Metric
              label="Accuracy"
              value={
                learning.totals?.routing_accuracy == null
                  ? "—"
                  : `${(learning.totals.routing_accuracy * 100).toFixed(1)}%`
              }
            />
          </MetricGrid>
          <div className="mt-3 flex flex-col gap-1 text-xs text-muted">
            {(learning.mismatches ?? []).slice(0, 5).map((row, index) => (
              <div key={`${row.capability ?? "cap"}-${index}`}>
                {row.capability ?? "—"} → {row.actual_capability ?? "—"} · {row.cases ?? 0} casos
              </div>
            ))}
            {(learning.mismatches ?? []).length === 0 ? (
              <div>Sin desacuerdos registrados en la ventana.</div>
            ) : null}
          </div>
        </Panel>
      ) : null}
      {calibration ? (
        <Panel>
          <PanelHeader title="Confidence calibration" />
          <DataTable
            columns={[
              { key: "bucket", header: "Bucket", render: (row) => row.bucket ?? "—" },
              {
                key: "decisions",
                header: "Decisions",
                align: "right",
                render: (row) => fmtNum(row.decisions ?? 0),
              },
              {
                key: "accuracy",
                header: "Accuracy",
                align: "right",
                render: (row) =>
                  row.accuracy == null ? "—" : `${(row.accuracy * 100).toFixed(1)}%`,
              },
              {
                key: "gap",
                header: "Gap",
                align: "right",
                render: (row) =>
                  row.calibration_gap == null
                    ? "—"
                    : `${(row.calibration_gap * 100).toFixed(1)} pts`,
              },
            ]}
            rows={calibration.buckets ?? []}
            rowKey={(row) => row.bucket ?? "bucket"}
            empty={<EmptyState title="Sin datos" body="La calibración necesita tráfico real." />}
          />
        </Panel>
      ) : null}
      {models ? (
        <Panel>
          <PanelHeader title="Models (production vs candidate)" />
          <MetricGrid>
            <Metric label="Production" value={models.production_model ?? "—"} />
            <Metric label="Candidate" value={models.candidate_model ?? "sin canary"} />
          </MetricGrid>
          <DataTable
            columns={[
              { key: "model", header: "Model", render: (row) => row.model ?? "—" },
              { key: "role", header: "Role", render: (row) => row.role ?? "—" },
              {
                key: "decisions",
                header: "Decisions",
                align: "right",
                render: (row) => fmtNum(row.decisions ?? 0),
              },
              {
                key: "accuracy",
                header: "Accuracy",
                align: "right",
                render: (row) =>
                  row.routing_accuracy == null
                    ? "—"
                    : `${(row.routing_accuracy * 100).toFixed(1)}%`,
              },
              {
                key: "cost",
                header: "Cost",
                align: "right",
                render: (row) => `$${(row.cost ?? 0).toFixed(4)}`,
              },
            ]}
            rows={models.models ?? []}
            rowKey={(row) => `${row.model ?? "m"}-${row.role ?? "r"}`}
            empty={<EmptyState title="Sin datos" body="Comparación sobre shadow y golden sets." />}
          />
          <p className="mt-3 text-xs text-muted">
            Flujo: candidate → shadow → evaluation → promoción manual. Nada se promueve solo.
          </p>
        </Panel>
      ) : null}
      {costs ? (
        <Panel>
          <PanelHeader title="Cost breakdown" />
          <MetricGrid>
            <Metric label="Total" value={`$${(costs.total_cost ?? 0).toFixed(4)}`} />
            <Metric label="JEV" value={`$${(costs.jev_cost ?? 0).toFixed(4)}`} />
            <Metric
              label="JEV share"
              value={
                costs.jev_share == null ? "—" : `${(costs.jev_share * 100).toFixed(1)}%`
              }
            />
            <Metric
              label="Cost / answer"
              value={
                costs.per_result?.cost_per_successful_answer == null
                  ? "—"
                  : `$${costs.per_result.cost_per_successful_answer.toFixed(4)}`
              }
            />
            <Metric
              label="Cost / agent run"
              value={
                costs.per_result?.cost_per_agent_run == null
                  ? "—"
                  : `$${costs.per_result.cost_per_agent_run.toFixed(4)}`
              }
            />
          </MetricGrid>
          <div className="mt-3 flex flex-col gap-1 text-xs text-muted">
            {(costs.categories ?? []).slice(0, 8).map((row) => (
              <div key={row.category ?? "cat"}>
                {row.category ?? "—"} · ${(row.cost ?? 0).toFixed(4)} · {row.events ?? 0} eventos
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
      <Panel>
        <PanelHeader title="Recent decisions" />
        <DataTable
          columns={columns}
          rows={traces}
          rowKey={(row) => row.id}
          empty={
            <EmptyState
              title="No decisions yet"
              body="Enable shadow mode to compare JEV against live RAG traffic."
            />
          }
        />
      </Panel>
    </div>
  );
}
