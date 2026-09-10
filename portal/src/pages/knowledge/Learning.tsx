// =============================================================================
// Knowledge Learning Studio — /knowledge/learning (FASE 33E)
// =============================================================================
// "Zent está aprendiendo cómo funciona tu negocio": readiness real, progreso
// real, actividad real (SSE con replay durable), entidades aprendidas y
// preguntas human-in-the-loop. Nada de animaciones desconectadas del backend.
// =============================================================================
import {
  ArrowClockwise,
  CheckCircle,
  Database,
  Graph,
  Lightning,
  Play,
  Question,
  Sparkle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeEntityCard } from "../../components/knowledgeLearning/KnowledgeEntityCard";
import { KnowledgeLearningOrb } from "../../components/knowledgeLearning/KnowledgeLearningOrb";
import { KnowledgeQuestionCard } from "../../components/knowledgeLearning/KnowledgeQuestionCard";
import {
  KnowledgeReadinessCard,
} from "../../components/knowledgeLearning/KnowledgeReadinessCard";
import { LearningActivityFeed } from "../../components/knowledgeLearning/LearningActivityFeed";
import { LearningProgress } from "../../components/knowledgeLearning/LearningProgress";
import { LearningStageTimeline } from "../../components/knowledgeLearning/LearningStageTimeline";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
} from "../../components/ui";
import { useToast } from "../../Toast";
import { useAuth } from "../../auth";
import { fmtNum, timeAgo } from "../../lib/format";
import {
  answerQuestion,
  cancelLearning,
  deferQuestion,
  fetchKnowledgeScore,
  fetchLearnedEntities,
  fetchLearningRun,
  fetchLearningSources,
  fetchLearningStatus,
  fetchQuestions,
  GATE_LABELS,
  gateTone,
  skipQuestion,
  startLearning,
  streamRunEvents,
  type KnowledgeQuestion,
  type KnowledgeScore,
  type LearnedEntity,
  type LearningEvent,
  type LearningRun,
  type LearningStatus,
  type SourceLearning,
} from "../../lib/knowledgeLearning";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function activityFromEvents(
  events: LearningEvent[],
  run: LearningRun | null
): { message: string; confidence: number | null; evidence: string[] } | null {
  if (!run) return null;
  const sorted = [...events].sort((a, b) => (b.seq || 0) - (a.seq || 0));
  const match = sorted.find(
    (event) =>
      event.stage === run.current_stage &&
      typeof event.payload?.reasoning_summary === "string"
  );
  if (match) {
    return {
      message: String(match.payload.reasoning_summary),
      confidence:
        typeof match.payload.confidence === "number" ? match.payload.confidence : null,
      evidence: Array.isArray(match.payload.evidence)
        ? (match.payload.evidence as unknown[]).map(String).slice(0, 6)
        : [],
    };
  }
  const latest = sorted.find((event) => event.stage === run.current_stage);
  if (latest) {
    return { message: latest.message, confidence: null, evidence: [] };
  }
  return null;
}

export default function KnowledgeLearningPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [sources, setSources] = useState<SourceLearning[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [run, setRun] = useState<LearningRun | null>(null);
  const [steps, setSteps] = useState<LearningRun["steps"]>([]);
  const [score, setScore] = useState<KnowledgeScore | null>(null);
  const [questions, setQuestions] = useState<KnowledgeQuestion[]>([]);
  const [blocking, setBlocking] = useState(0);
  const [entities, setEntities] = useState<LearnedEntity[]>([]);
  const [liveEvents, setLiveEvents] = useState<LearningEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [answerBusyId, setAnswerBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [feedRefresh, setFeedRefresh] = useState(0);
  const streamRef = useRef<{ close: () => void } | null>(null);
  const refreshTimerRef = useRef<number | null>(null);

  const selectedSource = useMemo(
    () => sources.find((source) => source.source_id === selectedSourceId) || null,
    [sources, selectedSourceId]
  );
  const running =
    run !== null && (run.status === "queued" || run.status === "running");

  const loadRun = useCallback(async (runId: string) => {
    try {
      const detail = await fetchLearningRun(runId);
      setRun(detail);
      setSteps(detail.steps || []);
      return detail;
    } catch {
      return null;
    }
  }, []);

  const refreshForSource = useCallback(
    async (sourceId: string) => {
      const [questionsData, entitiesData, scoreData] = await Promise.all([
        fetchQuestions({ source_id: sourceId }).catch(() => ({
          questions: [],
          count: 0,
          pending: 0,
          blocking: 0,
        })),
        fetchLearnedEntities(sourceId).catch(() => ({ entities: [], count: 0 })),
        fetchKnowledgeScore(sourceId).catch(() => null),
      ]);
      setQuestions(questionsData.questions || []);
      setBlocking(questionsData.blocking || 0);
      setEntities(entitiesData.entities || []);
      setScore(scoreData);
    },
    []
  );

  const refreshAll = useCallback(
    async (sourceId?: string) => {
      try {
        const [statusData, sourcesData] = await Promise.all([
          fetchLearningStatus(),
          fetchLearningSources(),
        ]);
        setStatus(statusData);
        setSources(sourcesData || []);
        const activeSourceId =
          sourceId ||
          selectedSourceId ||
          sourcesData?.[0]?.source_id ||
          "";
        if (activeSourceId) {
          setSelectedSourceId(activeSourceId);
          await refreshForSource(activeSourceId);
          const source = (sourcesData || []).find(
            (item) => item.source_id === activeSourceId
          );
          if (source?.active_run?.id) {
            await loadRun(source.active_run.id);
          }
        }
        setFeedRefresh((value) => value + 1);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "No se pudo cargar el aprendizaje de conocimiento"
        );
      } finally {
        setLoading(false);
      }
    },
    [loadRun, refreshForSource, selectedSourceId]
  );

  useEffect(() => {
    if (!session) return;
    void refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (!selectedSourceId) return;
    void refreshForSource(selectedSourceId);
    const source = sources.find((item) => item.source_id === selectedSourceId);
    if (source?.active_run?.id) {
      void loadRun(source.active_run.id);
    } else {
      setRun(null);
      setSteps([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSourceId]);

  // SSE con replay durable + poll de respaldo mientras el run avanza.
  useEffect(() => {
    if (!run?.id || TERMINAL.has(run.status)) {
      streamRef.current?.close();
      streamRef.current = null;
      return;
    }
    streamRef.current = streamRunEvents({
      runId: run.id,
      onEvent: (event) => {
        setLiveEvents((current) => [event, ...current].slice(0, 400));
        if (
          [
            "stage.completed",
            "schema.discovered",
            "question.generated",
            "knowledge.confirmed",
            "knowledge.score.computed",
            "learning.completed",
            "learning.failed",
          ].includes(event.event_type)
        ) {
          if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
          refreshTimerRef.current = window.setTimeout(() => {
            void loadRun(run.id);
            void refreshAll(selectedSourceId);
          }, 600);
        }
      },
    });
    const poll = window.setInterval(() => {
      void loadRun(run.id);
    }, 4000);
    return () => {
      streamRef.current?.close();
      streamRef.current = null;
      window.clearInterval(poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.status]);

  // Al terminar (o entrar en awaiting_validation) refrescar datos derivados.
  useEffect(() => {
    if (!run) return;
    if (run.status === "awaiting_validation" || TERMINAL.has(run.status)) {
      void refreshAll(selectedSourceId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  async function handleStart() {
    if (!selectedSourceId) return;
    setBusy(true);
    setError("");
    try {
      const result = await startLearning(selectedSourceId);
      setRun(result.run);
      setSteps([]);
      pushToast("info", "Aprendizaje iniciado", "Zent está analizando tu fuente.");
      await refreshAll(selectedSourceId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "No se pudo iniciar";
      if (message.includes("409") || message.toLowerCase().includes("activo")) {
        pushToast("warn", "Ya hay un aprendizaje en curso", "Mostrando el run activo.");
        await refreshAll(selectedSourceId);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleAnswer(
    question: KnowledgeQuestion,
    payload: { answer: string; structured_answer: Record<string, unknown>; choice?: string }
  ) {
    setAnswerBusyId(question.id);
    try {
      const result = await answerQuestion(question.id, payload);
      const applied = result.applied_to?.length ?? 0;
      pushToast(
        "success",
        "Zent aprendió",
        applied > 0
          ? `${applied} concepto(s) actualizados en el conocimiento.`
          : "Tu respuesta quedó registrada."
      );
      await refreshAll(selectedSourceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la respuesta");
    } finally {
      setAnswerBusyId(null);
    }
  }

  async function handleCancel(runId: string) {
    setBusy(true);
    setError("");
    try {
      await cancelLearning(runId);
      pushToast("info", "Aprendizaje cancelado", "Puedes reiniciarlo cuando quieras.");
      setRun(null);
      setSteps([]);
      await refreshAll(selectedSourceId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "No se pudo cancelar";
      if (message.includes("409") || message.toLowerCase().includes("estado")) {
        pushToast("warn", "El run ya terminó", "Refrescando estado actual.");
        await refreshAll(selectedSourceId);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleSkip(question: KnowledgeQuestion, reason: string) {
    setAnswerBusyId(question.id);
    try {
      await skipQuestion(question.id, reason);
      pushToast("info", "Pregunta descartada", "Puedes retomarla más adelante.");
      await refreshAll(selectedSourceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo descartar");
    } finally {
      setAnswerBusyId(null);
    }
  }

  async function handleDefer(question: KnowledgeQuestion) {
    setAnswerBusyId(question.id);
    try {
      await deferQuestion(question.id);
      pushToast("info", "Pregunta diferida", "Te la mostraremos de nuevo luego.");
      await refreshAll(selectedSourceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo diferir");
    } finally {
      setAnswerBusyId(null);
    }
  }

  const counts = status?.counts;
  const activity = activityFromEvents(liveEvents, run);
  const overallReadiness = selectedSource?.knowledge.overall ?? status?.readiness.overall ?? null;

  if (loading) {
    return (
      <KnowledgeLayout>
        <PageHeader title="Knowledge Intelligence" />
        <SkeletonBlock rows={6} />
      </KnowledgeLayout>
    );
  }

  return (
    <KnowledgeLayout>
      <div data-testid="learning-page">
        <PageHeader
          title="Knowledge Intelligence"
          subtitle="Zent está aprendiendo cómo funciona tu negocio: descubrimiento, semántica, relaciones, validación y readiness reales."
          actions={
            <>
              <Link className="btn btn-secondary min-h-9" to="/knowledge/map">
                <Graph size={15} aria-hidden />
                Ver mapa
              </Link>
              <label className="sr-only" htmlFor="learning-source">
                Fuente
              </label>
              <select
                id="learning-source"
                className="field min-h-9"
                data-testid="source-select"
                value={selectedSourceId}
                onChange={(event) => setSelectedSourceId(event.target.value)}
              >
                {sources.length === 0 && <option value="">Sin fuentes</option>}
                {sources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {(source.engine || "Fuente")} · {source.source_id.slice(0, 8)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-primary min-h-9"
                data-testid="start-learning"
                disabled={busy || !selectedSourceId || running}
                onClick={() => void handleStart()}
              >
                {running ? (
                  <ArrowClockwise size={15} className="animate-spin" aria-hidden />
                ) : (
                  <Play size={15} aria-hidden />
                )}
                {running ? "Aprendiendo…" : "Iniciar aprendizaje"}
              </button>
            </>
          }
        />

        {error && <ErrorInline>{error}</ErrorInline>}

        {sources.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon={Database}
              title="Sin fuentes conectadas"
              body="Conecta una fuente de datos para que Zent pueda aprender su estructura y su negocio."
              action={
                <Link className="btn btn-primary min-h-9" to="/knowledge/sources">
                  Ir a fuentes
                </Link>
              }
            />
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
              <StatCard
                label="Knowledge Readiness"
                value={overallReadiness !== null ? `${Math.round(overallReadiness)}%` : "—"}
                hint={
                  selectedSource
                    ? GATE_LABELS[selectedSource.knowledge.gate]
                    : status
                      ? GATE_LABELS[status.readiness.gate]
                      : undefined
                }
                icon={Sparkle}
                tone={
                  selectedSource?.knowledge.gate === "READY"
                    ? "ok"
                    : selectedSource?.knowledge.gate === "DEGRADED"
                      ? "danger"
                      : "default"
                }
              />
              <StatCard
                label="Fuentes conectadas"
                value={fmtNum(counts?.sources_connected ?? sources.length)}
                icon={Database}
              />
              <StatCard
                label="Entidades entendidas"
                value={fmtNum(counts?.entities_understood ?? 0)}
                hint={`de ${fmtNum(counts?.entities_total ?? 0)} detectadas`}
                icon={Sparkle}
              />
              <StatCard
                label="Relaciones descubiertas"
                value={fmtNum(counts?.relationships_total ?? 0)}
                hint={`${fmtNum(counts?.relationships_confirmed ?? 0)} confirmadas`}
                icon={Graph}
              />
              <StatCard
                label="Preguntas pendientes"
                value={fmtNum(counts?.pending_questions ?? questions.length)}
                hint={blocking > 0 ? `${blocking} bloqueantes` : "sin bloqueantes"}
                icon={Question}
                tone={blocking > 0 ? "warn" : "default"}
              />
              <StatCard
                label="Conocimiento verificado"
                value={fmtNum(counts?.verified_knowledge ?? 0)}
                hint="conceptos aprobados por personas"
                icon={CheckCircle}
                tone="ok"
              />
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[1.1fr_1fr]">
              <KnowledgeReadinessCard score={score} />
              <section className="panel" data-testid="live-panel">
                <h2 className="text-sm font-semibold text-text">
                  {running
                    ? "Aprendiendo tu negocio"
                    : run?.status === "awaiting_validation"
                      ? "Zent necesita tu ayuda"
                      : run?.status === "failed"
                        ? "El aprendizaje falló"
                        : "Estado del aprendizaje"}
                </h2>
                {run ? (
                  <>
                    <div className="mt-3 flex flex-col items-center gap-4 sm:flex-row">
                      <KnowledgeLearningOrb
                        activeStage={run.current_stage}
                        running={running}
                      />
                      <div className="w-full min-w-0 flex-1" aria-live="polite">
                        <LearningProgress
                          overallProgress={run.overall_progress}
                          currentStage={run.current_stage}
                          stageProgress={run.stage_progress}
                          status={run.status}
                        />
                        {activity && (
                          <div className="mt-3 rounded-md border border-border bg-soft/40 p-3">
                            <p className="text-[11px] font-medium uppercase tracking-wide text-faint">
                              Zent piensa
                            </p>
                            <p className="mt-1 text-[13px] leading-relaxed text-text">
                              {activity.message}
                            </p>
                            {activity.confidence !== null && (
                              <p className="mt-1 text-[11px] text-muted">
                                Confianza: {Math.round(activity.confidence * 100)}%
                              </p>
                            )}
                            {activity.evidence.length > 0 && (
                              <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted">
                                {activity.evidence.map((item) => (
                                  <li key={item}>✓ {item}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}
                        {run.status === "failed" && (
                          <p className="mt-2 text-[12px] text-danger">
                            {String(run.error_summary?.error || "Error desconocido").slice(0, 240)}
                          </p>
                        )}
                      </div>
                    </div>
                    {steps && steps.length > 0 && (
                      <div className="mt-4 border-t border-border pt-3">
                        <LearningStageTimeline steps={steps} />
                      </div>
                    )}
                    {["queued", "running", "awaiting_validation"].includes(
                      run.status
                    ) && (
                      <div className="mt-4 flex justify-end border-t border-border pt-3">
                        <button
                          type="button"
                          className="btn btn-danger min-h-8"
                          data-testid="run-cancel"
                          disabled={busy}
                          onClick={() => void handleCancel(run.id)}
                        >
                          Cancelar aprendizaje
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="mt-2">
                    <EmptyState
                      icon={Lightning}
                      title="Sin aprendizaje reciente"
                      body="Inicia un aprendizaje para ver el descubrimiento en tiempo real."
                    />
                  </div>
                )}
              </section>
            </div>

            <section className="mt-4" data-testid="sources-strip">
              <h2 className="mb-2 text-sm font-semibold text-text">Fuentes</h2>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {sources.map((source) => (
                  <article
                    key={source.source_id}
                    className={`panel ${source.source_id === selectedSourceId ? "border-accent/40" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-text">
                        {source.engine || "Fuente"} · {source.source_id.slice(0, 8)}
                      </span>
                      <span className={`badge ${gateTone(source.knowledge.gate)}`}>
                        {GATE_LABELS[source.knowledge.gate]}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px] text-muted">
                      <span>Tablas: {source.tables.analyzed}/{source.tables.total}</span>
                      <span>Campos: {source.fields.understood}/{source.fields.total}</span>
                      <span>Relaciones: {source.relationships.discovered}</span>
                      <span>Preguntas: {source.pending_questions}</span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[11px] text-faint">
                      <span>
                        {source.last_learning_at
                          ? `Último aprendizaje ${timeAgo(source.last_learning_at)}`
                          : "Sin aprendizaje"}
                      </span>
                      {source.connectivity !== "healthy" && (
                        <span className="text-warn">{source.connectivity}</span>
                      )}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn btn-secondary min-h-8 text-[12px]"
                        disabled={busy || source.active_run?.status === "running"}
                        onClick={() => {
                          setSelectedSourceId(source.source_id);
                          void handleStart();
                        }}
                      >
                        Aprender de nuevo
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost min-h-8 text-[12px]"
                        onClick={() => setSelectedSourceId(source.source_id)}
                      >
                        Ver conocimiento
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            {questions.length > 0 && (
              <section className="mt-6" data-testid="questions-section">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold text-text">
                      Ayuda a Zent a entender tu negocio
                    </h2>
                    <p className="text-[12px] text-muted">
                      Zent encontró conceptos que requieren tu experiencia.
                    </p>
                  </div>
                  <span className="text-[12px] text-faint">
                    {questions.length} pendiente{questions.length === 1 ? "" : "s"}
                    {blocking > 0 ? ` · ${blocking} bloqueantes` : ""}
                  </span>
                </div>
                <div className="space-y-3">
                  {questions.slice(0, 8).map((question, index) => (
                    <KnowledgeQuestionCard
                      key={question.id}
                      question={question}
                      index={index}
                      total={questions.length}
                      busy={answerBusyId === question.id}
                      onAnswer={(payload) => void handleAnswer(question, payload)}
                      onSkip={(reason) => void handleSkip(question, reason)}
                      onDefer={() => void handleDefer(question)}
                    />
                  ))}
                </div>
              </section>
            )}

            <section className="mt-6" data-testid="entities-section">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-text">Lo que Zent aprendió</h2>
                <span className="text-[12px] text-faint">
                  {entities.length} entidad{entities.length === 1 ? "" : "es"} con contexto
                </span>
              </div>
              {entities.length === 0 ? (
                <div className="panel">
                  <EmptyState
                    title="Todavía sin entidades"
                    body="Ejecuta un aprendizaje para que Zent identifique entidades de negocio."
                  />
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {entities.slice(0, 12).map((entity) => (
                    <KnowledgeEntityCard key={entity.entity_id} entity={entity} />
                  ))}
                </div>
              )}
            </section>

            <div className="mt-6">
              <LearningActivityFeed
                runId={run?.id ?? null}
                sourceId={selectedSourceId || null}
                liveEvents={liveEvents}
                refreshKey={feedRefresh}
              />
            </div>
          </>
        )}
      </div>
    </KnowledgeLayout>
  );
}
