import { Flask, Play, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  cn,
  EmptyState,
  ErrorInline,
  Panel,
  PanelHeader,
  PageHeader,
  Select,
  Skeleton,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fetchKnowledgeHealth, type KnowledgeHealth } from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";

type SourceRow = { id: string; name: string };

type EvaluationPayload = {
  enabled: boolean;
  judge_enabled: boolean;
  max_questions: number;
  latest: {
    id: string;
    dataset_name: string;
    status: string;
    created_at: string | null;
    overall: number;
    composite_score: number | null;
    quality: Record<string, number>;
    performance: Record<string, number>;
    total_cases: number;
    failed_cases: number;
  } | null;
};

const METRIC_LABELS: Record<string, string> = {
  retrieval_precision: "Precisión de recuperación",
  retrieval_recall: "Recall de recuperación",
  context_relevance: "Relevancia del contexto",
  answer_relevance: "Relevancia de la respuesta",
  faithfulness: "Fidelidad (groundedness)",
  citation_accuracy: "Precisión de citas",
  anti_hallucination: "Anti-alucinación",
};

function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-muted";
  if (score >= 0.75) return "text-ok";
  if (score >= 0.5) return "text-warn";
  return "text-danger";
}

export default function KnowledgeEvaluationPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [payload, setPayload] = useState<EvaluationPayload | null>(null);
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [sourcesData, evaluation, healthData] = await Promise.all([
        api<{ sources: SourceRow[] }>("/api/v1/sources", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<EvaluationPayload>(
          `/api/v1/knowledge/learning/evaluation${sourceId ? `?source_id=${sourceId}` : ""}`,
          { token: session.token, organizationId: session.organizationId }
        ),
        fetchKnowledgeHealth(),
      ]);
      setSources(sourcesData.sources ?? []);
      setPayload(evaluation);
      setHealth(healthData);
    } catch (err) {
      setPayload(null);
      setError(
        err instanceof Error
          ? err.message
          : "No pudimos obtener la evaluación. No significa que el conocimiento sea 0."
      );
    } finally {
      setLoading(false);
    }
  }, [session, sourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const runEvaluation = async () => {
    if (!session || !sourceId) return;
    setRunning(true);
    setError("");
    setMessage("");
    try {
      const result = await api<{ status?: string; reason?: string; candidates?: number }>(
        "/api/v1/knowledge/learning/evaluation/run",
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ source_id: sourceId }),
        }
      );
      if (result.status === "skipped") {
        setMessage(
          `No se pudo evaluar: ${result.reason ?? "sin candidatos justificados por el catálogo"}.`
        );
      } else {
        setMessage("Evaluación ejecutada.");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo ejecutar la evaluación.");
    } finally {
      setRunning(false);
    }
  };

  const retrieval = health?.dimensions.find((d) => d.key === "retrieval_quality");
  const latest = payload?.latest ?? null;

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.evaluation}
        subtitle="¿Zent responde bien con el conocimiento que tiene? Métricas reales de recuperación y respuesta, sin maquillaje."
        actions={
          <Link to="/evaluation" className="btn btn-secondary min-h-9 px-3 text-xs">
            Centro de evaluación completo
          </Link>
        }
      />

      <div className="flex flex-col gap-4">
        <Panel flat className="p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Select
              aria-label="Fuente a evaluar"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              className="sm:max-w-[320px]"
            >
              <option value="">Todas las fuentes</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </Select>
            <Button
              variant="primary"
              leadingIcon={Play}
              disabled={!sourceId || running || payload?.enabled === false}
              onClick={() => void runEvaluation()}
            >
              {running ? "Evaluando…" : "Zent se examina"}
            </Button>
            {payload && (
              <span className="text-xs text-muted">
                {payload.enabled ? "Auto-evaluación activa" : "Auto-evaluación deshabilitada"}
                {payload.judge_enabled ? " · juez LLM" : " · sin juez LLM"} · máximo{" "}
                {payload.max_questions} preguntas
              </span>
            )}
          </div>
        </Panel>

        {message && <p className="text-sm text-ok">{message}</p>}
        <ErrorInline message={error} className="mb-0" />

        {loading && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-[140px] rounded-lg" />
            <Skeleton className="h-[200px] rounded-lg" />
          </div>
        )}

        {!loading && !error && retrieval && (
          <Panel>
            <PanelHeader
              title="Calidad de recuperación (Knowledge Health)"
              description="Dimensión explicable del knowledge model."
            />
            <div className="panel-body">
              {retrieval.measured && retrieval.score != null ? (
                <div className="flex items-end gap-3">
                  <span className={cn("stat-value", scoreTone(retrieval.score / 100))}>
                    {Math.round(retrieval.score)}
                  </span>
                  <span className="pb-1 text-xs text-muted">{retrieval.reason}</span>
                </div>
              ) : (
                <div className="flex items-start gap-2">
                  <WarningCircle size={16} className="mt-0.5 text-warn" aria-hidden />
                  <div>
                    <p className="text-sm text-text">No medido</p>
                    <p className="text-xs text-muted">{retrieval.reason}</p>
                  </div>
                </div>
              )}
              {retrieval.issues.length > 0 && (
                <ul className="mt-2 list-disc pl-4 text-xs text-muted">
                  {retrieval.issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>
        )}

        {!loading && !error && !latest && (
          <Panel>
            <EmptyState
              icon={Flask}
              title="Sin evaluaciones todavía"
              body="Ejecuta «Zent se examina» sobre una fuente con entidades y campos mapeados para medir recuperación, groundedness y citas."
            />
          </Panel>
        )}

        {!loading && !error && latest && (
          <>
            <Panel>
              <PanelHeader
                title="Última auto-evaluación"
                description={`${latest.dataset_name} · ${fmtDateTime(latest.created_at)}`}
                actions={<Badge tone="info">{latest.status}</Badge>}
              />
              <div className="panel-body flex flex-col gap-4">
                <div className="flex items-end gap-3">
                  <span className={cn("stat-value", scoreTone(latest.composite_score))}>
                    {Math.round(latest.overall)}
                  </span>
                  <span className="pb-1 text-xs text-muted">
                    composite · {latest.total_cases} casos
                    {latest.failed_cases > 0 ? ` · ${latest.failed_cases} fallidos` : ""}
                  </span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(latest.quality ?? {}).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                    >
                      <span className="text-xs text-muted">
                        {METRIC_LABELS[key] || key}
                      </span>
                      <span className={cn("mono text-sm", scoreTone(Number(value)))}>
                        {typeof value === "number" ? Math.round(value * 100) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </Panel>
            {Object.keys(latest.performance ?? {}).length > 0 && (
              <Panel>
                <PanelHeader title="Rendimiento" description="Latencia y tokens reales del run." />
                <div className="panel-body grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {Object.entries(latest.performance).map(([key, value]) => (
                    <div key={key} className="rounded-md border border-border px-3 py-2">
                      <p className="text-xs text-muted">{key}</p>
                      <p className="mono text-sm text-text">
                        {typeof value === "number" ? Math.round(value) : String(value)}
                      </p>
                    </div>
                  ))}
                </div>
              </Panel>
            )}
          </>
        )}
      </div>
    </KnowledgeLayout>
  );
}
