import { ArrowsClockwise, Lightning, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
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
import { LearningActivityFeed } from "../../components/knowledgeLearning/LearningActivityFeed";
import { LearningProgress } from "../../components/knowledgeLearning/LearningProgress";
import { LearningStageTimeline } from "../../components/knowledgeLearning/LearningStageTimeline";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import {
  cancelLearning,
  fetchLearningRun,
  fetchLearningRuns,
  stageLabel,
  streamRunEvents,
  type LearningEvent,
  type LearningRun,
} from "../../lib/knowledgeLearning";
import { learnSource } from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";

type SourceRow = { id: string; name: string; type: string };

const ACTIVE_STATUSES = new Set(["queued", "running", "awaiting_validation"]);

function runTone(status: string): "ok" | "danger" | "warn" | "info" | "neutral" {
  if (status === "completed") return "ok";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "neutral";
  if (status === "awaiting_validation") return "warn";
  return "info";
}

export default function KnowledgeActivityPage() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");

  const [runs, setRuns] = useState<LearningRun[]>([]);
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [selectedSource, setSelectedSource] = useState("");
  const [run, setRun] = useState<LearningRun | null>(null);
  const [liveEvents, setLiveEvents] = useState<LearningEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [runsData, sourcesData] = await Promise.all([
        fetchLearningRuns({ limit: 30 }),
        api<{ sources: SourceRow[] }>("/api/v1/sources", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setRuns(runsData.runs);
      setSources(sourcesData.sources ?? []);
      if (!selectedSource && sourcesData.sources?.length) {
        setSelectedSource(sourcesData.sources[0].id);
      }
    } catch (err) {
      setRuns([]);
      setError(
        err instanceof Error
          ? err.message
          : "No pudimos cargar la actividad de aprendizaje."
      );
    } finally {
      setLoading(false);
    }
  }, [session, selectedSource]);

  useEffect(() => {
    void load();
    // Solo al montar / cambiar de sesión.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const activeRunId = useMemo(() => {
    if (runId) return runId;
    const active = runs.find((item) => ACTIVE_STATUSES.has(item.status));
    return active?.id ?? runs[0]?.id ?? null;
  }, [runId, runs]);

  const loadRun = useCallback(async (id: string) => {
    try {
      const data = await fetchLearningRun(id);
      setRun(data);
    } catch (err) {
      setRun(null);
      setError(err instanceof Error ? err.message : "No pudimos cargar el run.");
    }
  }, []);

  useEffect(() => {
    if (activeRunId) void loadRun(activeRunId);
    else setRun(null);
  }, [activeRunId, loadRun]);

  const streamRunId = run && ACTIVE_STATUSES.has(run.status) ? run.id : null;

  useEffect(() => {
    setLiveEvents([]);
    if (!streamRunId) return;
    const handle = streamRunEvents({
      runId: streamRunId,
      sinceSeq: 0,
      onEvent: (event) => setLiveEvents((prev) => [...prev, event]),
      onError: () => setError("Se perdió la conexión en vivo; reintenta recargando."),
    });
    const poll = window.setInterval(() => {
      void loadRun(streamRunId);
    }, 5000);
    return () => {
      handle.close();
      window.clearInterval(poll);
    };
  }, [streamRunId, loadRun]);

  const startLearning = async () => {
    if (!selectedSource) return;
    setBusy(true);
    setError("");
    setActionMessage("");
    try {
      const result = await learnSource(selectedSource);
      const newRunId = String((result.run as { id?: string })?.id ?? "");
      setActionMessage("Aprendizaje iniciado.");
      await load();
      if (newRunId) {
        const updated = new URLSearchParams(params);
        updated.set("run", newRunId);
        setParams(updated, { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar el aprendizaje.");
    } finally {
      setBusy(false);
    }
  };

  const cancelRun = async () => {
    if (!run) return;
    setBusy(true);
    try {
      await cancelLearning(run.id);
      setActionMessage("Aprendizaje cancelado.");
      await loadRun(run.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar el run.");
    } finally {
      setBusy(false);
    }
  };

  const selectedRunSource = sources.find((source) => source.id === run?.catalog_source_id);

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.activity}
        subtitle="Observabilidad del pipeline: runs reales, etapas, eventos y artefactos. El conocimiento vive en el modelo, no aquí."
        actions={
          <>
            <ButtonLink to="/knowledge/sources" variant="secondary">
              Ver fuentes
            </ButtonLink>
            <ButtonLink to="/knowledge/model" variant="primary">
              Ir al modelo
            </ButtonLink>
          </>
        }
      />

      <div className="flex flex-col gap-4">
        <Panel flat className="p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Select
              aria-label="Fuente para aprender"
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="sm:max-w-[320px]"
            >
              <option value="">Selecciona una fuente…</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </Select>
            <Button
              variant="primary"
              leadingIcon={ArrowsClockwise}
              disabled={!selectedSource || busy}
              onClick={() => void startLearning()}
            >
              Aprender / actualizar
            </Button>
            <span className="text-xs text-muted">
              El aprendizaje corre en background y produce artefactos persistentes.
            </span>
          </div>
        </Panel>

        {actionMessage && <p className="text-sm text-ok">{actionMessage}</p>}
        <ErrorInline message={error} className="mb-0" />

        {loading && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-[120px] rounded-lg" />
            <Skeleton className="h-[240px] rounded-lg" />
          </div>
        )}

        {!loading && runs.length === 0 && !error && (
          <Panel>
            <EmptyState
              icon={Lightning}
              title="Sin aprendizajes ejecutados"
              body="Ejecuta aprendizaje sobre una fuente para descubrir schema, entidades, relaciones y reglas. Mientras tanto, el modelo se construye con el discovery existente."
              action={
                <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
                  Añadir fuente
                </ButtonLink>
              }
            />
          </Panel>
        )}

        {!loading && runs.length > 0 && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[380px_1fr]">
            <Panel className="overflow-hidden">
              <PanelHeader title="Runs" description="Más recientes primero." />
              <ul className="flex flex-col">
                {runs.map((item) => {
                  const active = item.id === activeRunId;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={cn(
                          "flex w-full flex-col gap-1 border-b border-border px-4 py-3 text-left last:border-0",
                          active ? "bg-soft/70" : "hover:bg-soft/40"
                        )}
                        onClick={() => {
                          const updated = new URLSearchParams(params);
                          updated.set("run", item.id);
                          setParams(updated, { replace: true });
                        }}
                      >
                        <span className="flex items-center justify-between gap-2">
                          <Badge tone={runTone(item.status)}>{item.status}</Badge>
                          <span className="text-xs text-muted">
                            {fmtDateTime(item.created_at)}
                          </span>
                        </span>
                        <span className="text-xs text-muted">
                          {stageLabel(item.current_stage)} · {item.overall_progress}%
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Panel>

            <div className="flex flex-col gap-4">
              {run ? (
                <>
                  <Panel>
                    <div className="flex flex-col gap-3 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-sm text-text">
                            {selectedRunSource?.name || "Fuente"} ·{" "}
                            <span className="text-muted">{run.id.slice(0, 8)}</span>
                          </p>
                          <p className="text-xs text-muted">
                            {run.started_at ? `Inicio ${fmtDateTime(run.started_at)}` : "En cola"}
                            {run.finished_at ? ` · Fin ${fmtDateTime(run.finished_at)}` : ""}
                          </p>
                        </div>
                        {ACTIVE_STATUSES.has(run.status) && (
                          <Button variant="danger" disabled={busy} onClick={() => void cancelRun()}>
                            Cancelar
                          </Button>
                        )}
                      </div>
                      <LearningProgress
                        overallProgress={run.overall_progress}
                        currentStage={run.current_stage}
                        stageProgress={run.stage_progress}
                        status={run.status}
                      />
                      {run.status === "failed" && (
                        <p className="text-sm text-danger">
                          El run falló.{" "}
                          {Object.keys(run.error_summary ?? {}).length > 0
                            ? "Revisa los eventos para el diagnóstico."
                            : "Sin detalle de error registrado."}
                        </p>
                      )}
                      <div className="grid grid-cols-2 gap-2 text-xs text-muted sm:grid-cols-4">
                        <span>{run.tables_analyzed} tablas</span>
                        <span>{run.entities_detected} entidades</span>
                        <span>{run.fields_detected} campos</span>
                        <span>{run.relationships_detected} relaciones</span>
                      </div>
                    </div>
                  </Panel>

                  <Panel>
                    <PanelHeader
                      title="Etapas"
                      description="Estado real de cada stage del pipeline."
                    />
                    <div className="panel-body">
                      {run.steps && run.steps.length > 0 ? (
                        <LearningStageTimeline steps={run.steps} />
                      ) : (
                        <p className="text-sm text-muted">Sin etapas registradas todavía.</p>
                      )}
                    </div>
                  </Panel>

                  <Panel>
                    <PanelHeader
                      title="Actividad"
                      description="Eventos durables + live del run seleccionado."
                    />
                    <div className="panel-body">
                      <LearningActivityFeed
                        runId={run.id}
                        sourceId={run.catalog_source_id}
                        liveEvents={liveEvents}
                        refreshKey={run.overall_progress}
                      />
                    </div>
                  </Panel>
                </>
              ) : (
                <Panel>
                  <p className="panel-body text-sm text-muted">
                    Selecciona un run para ver sus etapas y eventos.
                  </p>
                </Panel>
              )}
            </div>
          </div>
        )}
      </div>
    </KnowledgeLayout>
  );
}
