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

export default function AdminDecisionEnginePage() {
  const { session } = usePlatformAuth();
  const token = session?.token;
  const [status, setStatus] = useState<Status | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [adaptive, setAdaptive] = useState<AdaptiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [st, board, recent, adp] = await Promise.all([
          platformApi<Status>("/api/v1/platform/decision/status", { token }),
          platformApi<Dashboard>("/api/v1/platform/decision/dashboard", { token }),
          platformApi<{ items: TraceRow[] }>("/api/v1/platform/decision/traces?limit=40", {
            token,
          }),
          platformApi<AdaptiveStatus>("/api/v1/platform/adaptive/status", { token }).catch(
            () => null,
          ),
        ]);
        if (cancelled) return;
        setStatus(st);
        setDash(board);
        setTraces(recent.items || []);
        setAdaptive(adp);
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
