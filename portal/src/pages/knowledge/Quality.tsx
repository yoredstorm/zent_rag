import {
  CheckCircle,
  GitMerge,
  Question,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  cn,
  EmptyState,
  ErrorInline,
  Modal,
  Panel,
  PageHeader,
  Select,
  Skeleton,
  Textarea,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { HealthSummary } from "../../components/knowledge/HealthSummary";
import { KnowledgeQuestionCard } from "../../components/knowledgeLearning/KnowledgeQuestionCard";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import {
  answerQuestion,
  deferQuestion,
  fetchQuestions,
  skipQuestion,
  type KnowledgeQuestion,
} from "../../lib/knowledgeLearning";
import {
  fetchKnowledgeConflicts,
  fetchKnowledgeGaps,
  fetchKnowledgeHealth,
  fetchKnowledgeQuality,
  fetchIngestionQuality,
  gapTypeLabel,
  priorityTone,
  resolveKnowledgeConflict,
  resolveKnowledgeGap,
  conflictClassificationLabel,
  type IngestionQualityReport,
  type KnowledgeConflict,
  type KnowledgeGap,
  type KnowledgeHealth,
  type QualityReport,
} from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";

type QualityTab = "issues" | "conflicts" | "ingestion" | "gaps" | "questions" | "reviews" | "improvements";

const TABS: { id: QualityTab; label: string }[] = [
  { id: "issues", label: "Problemas" },
  { id: "conflicts", label: "Conflictos" },
  { id: "ingestion", label: "Calidad de ingesta" },
  { id: "gaps", label: "Vacíos de conocimiento" },
  { id: "questions", label: "Preguntas de negocio" },
  { id: "reviews", label: "Cola de revisión" },
  { id: "improvements", label: "Mejoras" },
];

const SEVERITY_TONE: Record<string, string> = {
  high: "badge-danger",
  medium: "badge-pending",
  low: "badge-muted",
};

const SEVERITY_LABEL: Record<string, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
};

type Suggestion = {
  id: string;
  type: string;
  title: string;
  description: string | null;
  confidence: string;
  status: string;
  evidence: unknown[];
  created_at: string | null;
};

type Improvement = {
  id: string;
  title: string;
  description: string | null;
  gap_type: string;
  priority: string;
  status: string;
  recommended_action: string | null;
  affected_queries: number;
  affected_agents: number;
};

export default function KnowledgeQualityPage() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as QualityTab) || "issues";

  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [conflicts, setConflicts] = useState<KnowledgeConflict[]>([]);
  const [ingestion, setIngestion] = useState<IngestionQualityReport | null>(null);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [questions, setQuestions] = useState<KnowledgeQuestion[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [improvements, setImprovements] = useState<Improvement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  const [conflictTarget, setConflictTarget] = useState<KnowledgeConflict | null>(null);
  const [conflictChoice, setConflictChoice] = useState<"chose_a" | "chose_b" | "merged">("chose_a");
  const [conflictReason, setConflictReason] = useState("");
  const [actionMessage, setActionMessage] = useState("");

  const setTab = (next: QualityTab) => {
    const updated = new URLSearchParams(params);
    updated.set("tab", next);
    setParams(updated, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      void fetchKnowledgeHealth()
        .then((data) => setHealth(data))
        .catch(() => {
          // La salud es informativa: su fallo no oculta los problemas accionables.
        });
      if (tab === "issues") {
        setQuality(await fetchKnowledgeQuality(30));
      } else if (tab === "conflicts") {
        const data = await fetchKnowledgeConflicts("open");
        setConflicts(data.conflicts);
      } else if (tab === "ingestion") {
        setIngestion(await fetchIngestionQuality("open", 100));
      } else if (tab === "gaps") {
        const data = await fetchKnowledgeGaps({ status: "open", limit: 100 });
        setGaps(data.gaps);
      } else if (tab === "questions") {
        const data = await fetchQuestions({ status: "pending", limit: 100 });
        setQuestions(data.questions);
      } else if (tab === "reviews" && session) {
        const data = await api<{ suggestions: Suggestion[] }>(
          "/api/v1/catalog/suggestions?status=pending&limit=100",
          { token: session.token, organizationId: session.organizationId }
        );
        setSuggestions(data.suggestions ?? []);
      } else if (tab === "improvements" && session) {
        const data = await api<Improvement[]>("/api/v1/learning/improvements?limit=100", {
          token: session.token,
          organizationId: session.organizationId,
        });
        setImprovements(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No pudimos cargar esta sección. No significa que no haya problemas."
      );
    } finally {
      setLoading(false);
    }
  }, [tab, session]);

  useEffect(() => {
    void load();
  }, [load]);

  const resolveConflict = async () => {
    if (!conflictTarget) return;
    setBusyId(conflictTarget.id);
    setError("");
    try {
      await resolveKnowledgeConflict(conflictTarget.id, {
        resolution: conflictChoice,
        resolved_value: null,
        reason: conflictReason || null,
      });
      setConflictTarget(null);
      setConflictReason("");
      setActionMessage("Conflicto resuelto. La afirmación elegida queda como canónica.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo resolver el conflicto.");
    } finally {
      setBusyId("");
    }
  };

  const resolveGap = async (gap: KnowledgeGap) => {
    setBusyId(gap.id);
    try {
      await resolveKnowledgeGap(gap.id, { status: "resolved" });
      setGaps((prev) => prev.filter((item) => item.id !== gap.id));
      setActionMessage("Gap resuelto.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo resolver el gap.");
    } finally {
      setBusyId("");
    }
  };

  const reviewSuggestion = async (suggestion: Suggestion, action: "approve" | "reject") => {
    if (!session) return;
    setBusyId(suggestion.id);
    try {
      await api(`/api/v1/catalog/suggestions/${suggestion.id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({}),
      });
      setSuggestions((prev) => prev.filter((item) => item.id !== suggestion.id));
      setActionMessage(action === "approve" ? "Sugerencia aprobada." : "Sugerencia rechazada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo revisar la sugerencia.");
    } finally {
      setBusyId("");
    }
  };

  const setImprovementStatus = async (item: Improvement, status: string) => {
    if (!session) return;
    setBusyId(item.id);
    try {
      await api(`/api/v1/learning/improvements/${item.id}/status`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ status }),
      });
      setImprovements((prev) =>
        prev.map((row) => (row.id === item.id ? { ...row, status } : row))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar la mejora.");
    } finally {
      setBusyId("");
    }
  };

  const answerPendingQuestion = async (
    question: KnowledgeQuestion,
    payload: { answer: string; structured_answer: Record<string, unknown>; choice?: string }
  ) => {
    setBusyId(question.id);
    try {
      await answerQuestion(question.id, payload);
      setQuestions((prev) => prev.filter((item) => item.id !== question.id));
      setActionMessage("Respuesta aplicada al conocimiento.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo responder la pregunta.");
    } finally {
      setBusyId("");
    }
  };

  const skipPendingQuestion = async (question: KnowledgeQuestion) => {
    setBusyId(question.id);
    try {
      await skipQuestion(question.id, "descartada desde Calidad");
      setQuestions((prev) => prev.filter((item) => item.id !== question.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo descartar la pregunta.");
    } finally {
      setBusyId("");
    }
  };

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.quality}
        subtitle="Qué tan sano está el conocimiento y qué necesita una decisión humana: conflictos, vacíos, baja confianza y evidencia faltante."
        actions={
          <Link to="/knowledge/explorer" className="btn btn-secondary min-h-9 px-3 text-xs">
            Explorar conocimiento
          </Link>
        }
      />

      <div className="flex flex-col gap-4">
        <HealthSummary health={health} loading={loading && !health} />

        <div className="tabs" role="tablist" aria-label="Secciones de salud">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              className={`tab ${tab === item.id ? "" : "opacity-70 hover:opacity-100"}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {actionMessage && (
          <p className="text-sm text-ok" data-testid="quality-action-message">
            {actionMessage}
          </p>
        )}
        <ErrorInline message={error} className="mb-0" />

        {loading && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-[96px] rounded-lg" />
            <Skeleton className="h-[96px] rounded-lg" />
          </div>
        )}

        {!loading && tab === "issues" && quality && (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone="danger">{quality.by_severity.high ?? 0} alta</Badge>
              <Badge tone="warn">{quality.by_severity.medium ?? 0} media</Badge>
              <Badge tone="neutral">{quality.by_severity.low ?? 0} baja</Badge>
            </div>
            {quality.issues.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={ShieldCheck}
                  title="Sin problemas de calidad"
                  body="No hay conflictos, gaps críticos, evidencia faltante ni fuentes con fallos."
                />
              </Panel>
            ) : (
              quality.issues.map((issue) => (
                <Panel key={issue.kind}>
                  <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
                    <div className="flex items-center gap-2">
                      <WarningCircle
                        size={16}
                        className={cn(
                          issue.severity === "high" ? "text-danger" : "text-warn"
                        )}
                        aria-hidden
                      />
                      <h2 className="text-sm font-medium text-text">{issue.title}</h2>
                      <span className={cn("badge", SEVERITY_TONE[issue.severity])}>
                        {SEVERITY_LABEL[issue.severity]}
                      </span>
                    </div>
                    <span className="text-xs text-muted">{issue.action}</span>
                  </div>
                  <ul className="flex flex-col gap-2 px-4 py-3">
                    {issue.items.slice(0, 6).map((item, index) => (
                      <li key={`${issue.kind}-${index}`} className="text-sm text-muted">
                        {String(
                          item.name ??
                            item.subject ??
                            item.title ??
                            item.query ??
                            item.id ??
                            "—"
                        )}
                        {item.value ? (
                          <span className="text-text"> · {String(item.value)}</span>
                        ) : null}
                        {item.confidence != null ? (
                          <span className="ml-2 text-xs">
                            {Math.round(Number(item.confidence) * 100)}%
                          </span>
                        ) : null}
                      </li>
                    ))}
                    {issue.count > 6 && (
                      <li className="text-xs text-muted">+{issue.count - 6} más</li>
                    )}
                  </ul>
                </Panel>
              ))
            )}
          </>
        )}

        {!loading && tab === "conflicts" && (
          <>
            {conflicts.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={GitMerge}
                  title="Sin conflictos abiertos"
                  body="Ninguna fuente contradice a otra en este momento. Los fragmentos y la falta de contexto viven en Calidad de ingesta."
                />
              </Panel>
            ) : (
              conflicts.map((conflict) => (
                <Panel key={conflict.id}>
                  <div className="flex flex-col gap-3 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[11px] uppercase tracking-wide text-faint">
                          {conflictClassificationLabel(
                            conflict.classification?.classification ?? conflict.conflict_type
                          )}
                        </p>
                        <h2 className="truncate text-sm font-medium text-text">
                          {conflict.subject_label} · {conflict.predicate}
                        </h2>
                      </div>
                      <span className="badge badge-pending">{conflict.status}</span>
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="rounded-md border border-border p-3">
                        <p className="eyebrow mb-1">Afirmación A</p>
                        <p className="text-sm text-text">{conflict.value_a || "—"}</p>
                        <p className="mt-1 text-xs text-muted">
                          {conflict.source_a ? `Fuente ${conflict.source_a}` : "Sin fuente"}
                        </p>
                      </div>
                      <div className="rounded-md border border-border p-3">
                        <p className="eyebrow mb-1">Afirmación B</p>
                        <p className="text-sm text-text">{conflict.value_b || "—"}</p>
                        <p className="mt-1 text-xs text-muted">
                          {conflict.source_b ? `Fuente ${conflict.source_b}` : "Sin fuente"}
                        </p>
                      </div>
                    </div>
                    {(conflict.classification?.possible_explanation || conflict.reason) && (
                      <p className="text-xs leading-relaxed text-muted">
                        ZENT detectó:{" "}
                        {conflict.classification?.possible_explanation || conflict.reason}
                      </p>
                    )}
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] text-faint">
                        {conflict.classification?.confidence != null
                          ? `Confianza ${Math.round(
                              Number(conflict.classification.confidence) * 100
                            )}%`
                          : ""}
                        {conflict.classification?.source_independence ===
                        "independent_sources"
                          ? " · fuentes independientes"
                          : ""}
                      </span>
                      <Button
                        variant="primary"
                        onClick={() => {
                          setConflictTarget(conflict);
                          setConflictChoice("chose_a");
                        }}
                      >
                        Resolver
                      </Button>
                    </div>
                  </div>
                </Panel>
              ))
            )}
          </>
        )}

        {!loading && tab === "ingestion" && (
          <>
            <Panel>
              <div className="flex flex-col gap-1 p-4">
                <h2 className="text-sm font-medium text-text">Calidad de ingesta</h2>
                <p className="text-xs text-muted">
                  Problemas de parsing, fragmentos y procedencia faltante. No son
                  conflictos de conocimiento: se corrigen en el pipeline de ingesta.
                </p>
                {ingestion && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone="danger">
                      {ingestion.summary.by_severity.high ?? 0} alta
                    </Badge>
                    <Badge tone="warn">
                      {ingestion.summary.by_severity.medium ?? 0} media
                    </Badge>
                    <Badge tone="neutral">
                      {ingestion.summary.by_severity.low ?? 0} baja
                    </Badge>
                  </div>
                )}
              </div>
            </Panel>
            {ingestion && ingestion.issues.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={CheckCircle}
                  title="Sin problemas de ingesta"
                  body="El parser y el compilador no reportaron fragmentos ni procedencia faltante."
                />
              </Panel>
            ) : (
              ingestion?.issues.map((issue) => (
                <Panel key={issue.id}>
                  <div className="flex flex-col gap-1 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("badge", SEVERITY_TONE[issue.severity])}>
                        {SEVERITY_LABEL[issue.severity] ?? issue.severity}
                      </span>
                      <span className="badge badge-muted">{issue.kind}</span>
                      {issue.status !== "open" && (
                        <span className="badge badge-muted">{issue.status}</span>
                      )}
                    </div>
                    <p className="truncate text-sm text-text" title={issue.subject}>
                      {issue.subject || "—"}
                    </p>
                    {issue.evidence_excerpt && (
                      <p className="truncate text-xs text-muted" title={issue.evidence_excerpt}>
                        {issue.evidence_excerpt}
                      </p>
                    )}
                    <p className="text-[11px] text-faint">
                      {issue.evidence_locator || "Sin locator"}
                      {issue.created_at ? ` · ${fmtDateTime(issue.created_at)}` : ""}
                    </p>
                  </div>
                </Panel>
              ))
            )}
          </>
        )}

        {!loading && tab === "gaps" && (
          <>
            {gaps.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={CheckCircle}
                  title="Sin gaps abiertos"
                  body="Zent no tiene preguntas pendientes ni conocimiento faltante priorizado."
                />
              </Panel>
            ) : (
              gaps.map((gap) => (
                <Panel key={`${gap.origin}-${gap.id}`}>
                  <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={cn("badge", priorityTone(gap.priority))}>
                          {gap.priority}
                        </span>
                        <span className="badge badge-muted">{gapTypeLabel(gap.type)}</span>
                        {gap.origin === "knowledge_question" && (
                          <span className="badge badge-info">pregunta</span>
                        )}
                      </div>
                      <h2 className="mt-2 text-sm font-medium text-text">{gap.title}</h2>
                      {gap.description && (
                        <p className="mt-1 text-xs text-muted">{gap.description}</p>
                      )}
                      <p className="mt-1 text-xs text-muted">
                        {gap.impact_objects > 0
                          ? `Afecta ${gap.impact_objects} objetos`
                          : "Impacto no calculado"}
                        {gap.occurrences > 1 ? ` · ${gap.occurrences} ocurrencias` : ""}
                        {gap.last_seen_at ? ` · ${fmtDateTime(gap.last_seen_at)}` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {gap.object_id && (
                        <Link
                          to={`/knowledge/model?focus=${gap.object_id}`}
                          className="btn btn-secondary min-h-9 px-3 text-xs"
                        >
                          Ver objeto
                        </Link>
                      )}
                      <Button
                        variant="ghost"
                        disabled={busyId === gap.id || gap.origin === "knowledge_question"}
                        onClick={() => void resolveGap(gap)}
                      >
                        Resolver
                      </Button>
                    </div>
                  </div>
                </Panel>
              ))
            )}
          </>
        )}

        {!loading && tab === "questions" && (
          <>
            {questions.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={Question}
                  title="Sin preguntas pendientes"
                  body="Cuando Zent encuentre ambigüedad real, aparecerán aquí con su evidencia."
                />
              </Panel>
            ) : (
              questions.map((question, index) => (
                <KnowledgeQuestionCard
                  key={question.id}
                  question={question}
                  index={index}
                  total={questions.length}
                  busy={busyId === question.id}
                  onAnswer={(payload) => void answerPendingQuestion(question, payload)}
                  onSkip={() => void skipPendingQuestion(question)}
                  onDefer={async () => {
                    setBusyId(question.id);
                    try {
                      await deferQuestion(question.id);
                      setQuestions((prev) => prev.filter((item) => item.id !== question.id));
                    } finally {
                      setBusyId("");
                    }
                  }}
                />
              ))
            )}
          </>
        )}

        {!loading && tab === "reviews" && (
          <>
            {suggestions.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={CheckCircle}
                  title="Cola de revisión vacía"
                  body="No hay sugerencias del catálogo esperando decisión."
                />
              </Panel>
            ) : (
              suggestions.map((suggestion) => (
                <Panel key={suggestion.id}>
                  <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="badge badge-muted">{suggestion.type}</span>
                        <span className="text-xs text-muted">{suggestion.confidence}</span>
                      </div>
                      <p className="mt-1.5 text-sm text-text">{suggestion.title}</p>
                      {suggestion.description && (
                        <p className="text-xs text-muted">{suggestion.description}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button
                        variant="secondary"
                        disabled={busyId === suggestion.id}
                        onClick={() => void reviewSuggestion(suggestion, "reject")}
                      >
                        Rechazar
                      </Button>
                      <Button
                        variant="primary"
                        disabled={busyId === suggestion.id}
                        onClick={() => void reviewSuggestion(suggestion, "approve")}
                      >
                        Aprobar
                      </Button>
                    </div>
                  </div>
                </Panel>
              ))
            )}
          </>
        )}

        {!loading && tab === "improvements" && (
          <>
            {improvements.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={CheckCircle}
                  title="Sin mejoras pendientes"
                  body="El backlog de mejora de inteligencia está vacío."
                />
              </Panel>
            ) : (
              improvements.map((item) => (
                <Panel key={item.id}>
                  <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={cn("badge", priorityTone(item.priority))}>
                          {item.priority}
                        </span>
                        <span className="badge badge-muted">{item.status}</span>
                        <span className="text-xs text-muted">{item.gap_type}</span>
                      </div>
                      <p className="mt-1.5 text-sm text-text">{item.title}</p>
                      {item.recommended_action && (
                        <p className="text-xs text-muted">{item.recommended_action}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Select
                        aria-label={`Estado de ${item.title}`}
                        value={item.status}
                        disabled={busyId === item.id}
                        onChange={(e) => void setImprovementStatus(item, e.target.value)}
                        className="w-[170px]"
                      >
                        <option value="OPEN">Abierta</option>
                        <option value="IN_REVIEW">En revisión</option>
                        <option value="RESOLVED">Resuelta</option>
                        <option value="DISMISSED">Descartada</option>
                        <option value="BLOCKED">Bloqueada</option>
                      </Select>
                    </div>
                  </div>
                </Panel>
              ))
            )}
          </>
        )}
      </div>

      <Modal
        open={conflictTarget !== null}
        onOpenChange={(open) => {
          if (!open) setConflictTarget(null);
        }}
        title="Resolver conflicto"
        description={
          conflictTarget
            ? `${conflictTarget.subject_label} · ${conflictTarget.predicate}`
            : undefined
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setConflictTarget(null)}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              disabled={busyId === conflictTarget?.id}
              onClick={() => void resolveConflict()}
            >
              Aplicar resolución
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Select
            aria-label="Resolución"
            value={conflictChoice}
            onChange={(e) =>
              setConflictChoice(e.target.value as "chose_a" | "chose_b" | "merged")
            }
          >
            <option value="chose_a">Canónico: valor A ({conflictTarget?.value_a})</option>
            <option value="chose_b">Canónico: valor B ({conflictTarget?.value_b})</option>
            <option value="merged">Mantener contexto (ambos)</option>
          </Select>
          <Textarea
            aria-label="Motivo"
            placeholder="Motivo de la decisión (queda auditado)"
            value={conflictReason}
            onChange={(e) => setConflictReason(e.target.value)}
            rows={3}
          />
        </div>
      </Modal>
    </KnowledgeLayout>
  );
}
