import { ChatCircleDots, FileText, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { renderMarkdownHtml } from "../../lib/markdown";

type Corpus = { id: string; name: string; source_count?: number };
type Citation = {
  document_name?: string;
  document_id?: string | null;
  page?: number | null;
  section_path?: string[];
  locator?: string;
  excerpt?: string;
};
type Grounded = {
  answer: string;
  citations?: Citation[];
  missing_information?: string[];
  evidence_ids?: string[];
  citation_evidence_ids?: Array<string | null>;
};

type Suggestion = { text: string; intent?: string; basis?: string };
type Evidence = {
  id: string;
  source_id?: string | null;
  document_id?: string | null;
  page?: number | null;
  section_path?: string[];
  table_reference?: string | null;
  row_reference?: string | null;
  excerpt: string;
};

export default function KnowledgeAskPage() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpusId, setCorpusId] = useState(params.get("corpus") || "");
  const [sourceIds, setSourceIds] = useState<string[]>(() => {
    const raw = params.get("source_ids") || params.get("source_id") || "";
    return raw.split(",").map((item) => item.trim()).filter(Boolean);
  });
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [question, setQuestion] = useState(params.get("q") || "");
  const [answering, setAnswering] = useState(false);
  const [result, setResult] = useState<Grounded | null>(null);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<Record<number, Evidence | "loading" | "missing">>({});
  const [feedback, setFeedback] = useState<string>("");
  const [feedbackError, setFeedbackError] = useState("");

  useEffect(() => {
    if (!session) return;
    api<{ corpora: Corpus[] }>("/api/v1/knowledge/workspaces", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        const list = data.corpora || [];
        setCorpora(list);
        if (!corpusId && list[0]) {
          setCorpusId(list[0].id);
          setParams({ corpus: list[0].id }, { replace: true });
        }
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "No pudimos cargar las bases."),
      );
  }, [session, corpusId, setParams]);

  const selected = useMemo(
    () => corpora.find((corpus) => corpus.id === corpusId),
    [corpora, corpusId],
  );

  useEffect(() => {
    if (!session || !corpusId) {
      setSuggestions((prev) => (prev.length > 0 ? [] : prev));
      return;
    }
    let cancelled = false;
    api<{ suggestions: Suggestion[] }>(
      `/api/v1/knowledge/workspaces/${corpusId}/suggestions`,
      { token: session.token, organizationId: session.organizationId },
    )
      .then((data) => {
        if (cancelled) return;
        const next = (data.suggestions || []).slice(0, 3);
        setSuggestions((prev) => (next.length > 0 ? next : prev));
      })
      .catch(() => {
        if (!cancelled) setSuggestions((prev) => (prev.length > 0 ? [] : prev));
      });
    return () => {
      cancelled = true;
    };
  }, [session, corpusId]);

  async function ask() {
    if (!session || !corpusId || !question.trim()) return;
    setAnswering(true);
    setError("");
    setResult(null);
    setEvidence({});
    setFeedback("");
    setFeedbackError("");
    try {
      const data = await api<{ grounded: Grounded }>(
        `/api/v1/knowledge/workspaces/${corpusId}/chat`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({
            query: question.trim(),
            ...(sourceIds.length > 0 ? { source_ids: sourceIds } : {}),
          }),
        },
      );
      setResult(data.grounded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos responder la pregunta.");
    } finally {
      setAnswering(false);
    }
  }

  function evidenceIdFor(citationIndex: number): string | null | undefined {
    const aligned = result?.citation_evidence_ids?.[citationIndex];
    if (aligned !== undefined) return aligned;
    return result?.evidence_ids?.[citationIndex];
  }

  async function resolveEvidence(citationIndex: number) {
    const evidenceId = evidenceIdFor(citationIndex);
    if (!session || !evidenceId) {
      setEvidence((prev) => ({ ...prev, [citationIndex]: "missing" }));
      return;
    }
    setEvidence((prev) => ({ ...prev, [citationIndex]: "loading" }));
    try {
      const item = await api<Evidence>(
        `/api/v1/knowledge/evidence/${evidenceId}`,
        {
          token: session.token,
          organizationId: session.organizationId,
        },
      );
      setEvidence((prev) => ({ ...prev, [citationIndex]: item }));
    } catch {
      setEvidence((prev) => ({ ...prev, [citationIndex]: "missing" }));
    }
  }

  async function sendFeedback(rating: "up" | "down", reason?: string) {
    if (!session || !result) return;
    setFeedbackError("");
    try {
      await api("/api/v1/knowledge/nutrition/feedback", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          query: question,
          citations: result.citations?.length ?? 0,
          evidence_used: result.evidence_ids?.length ?? 0,
          feedback_rating: rating,
          feedback_reason: reason ?? null,
          wrong_source: reason === "wrong_source",
        }),
      });
      setFeedback("Gracias. La señal quedó registrada para revisión.");
    } catch (err) {
      setFeedbackError(
        err instanceof Error ? err.message : "No pudimos registrar la señal.",
      );
    }
  }

  const permissions = session?.permissions ?? [];
  const canWrite =
    permissions.length === 0 ||
    permissions.includes("*") ||
    permissions.includes("knowledge:write");
  const canBindAgents =
    permissions.length === 0 ||
    permissions.includes("*") ||
    permissions.includes("agents:write");

  return (
    <KnowledgeLayout>
      <PageHeader
        title="Preguntar"
        subtitle="Comprobá qué sabe ZENT y abrí la evidencia exacta antes de confiar en una respuesta."
        actions={
          <Select
            aria-label="Base de conocimiento"
            value={corpusId}
            onChange={(event) => {
              const next = event.target.value;
              setCorpusId(next);
              setSourceIds([]);
              setParams({ corpus: next }, { replace: true });
              setResult(null);
            }}
          >
            {corpora.length === 0 ? <option value="">Sin bases</option> : null}
            {corpora.map((corpus) => (
              <option key={corpus.id} value={corpus.id}>
                {corpus.name}
              </option>
            ))}
          </Select>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />

        {corpora.length === 0 && !error ? (
          <Panel className="p-5">
            <p className="text-sm font-medium text-text">Todavía no hay una base para preguntar.</p>
            <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted">
              Añadí información y esperá a que esté lista. Preguntar usa el mismo
              conocimiento y los mismos permisos que Agent Studio.
            </p>
            <Link to="/knowledge/sources?new=1" className="btn btn-primary mt-3 min-h-9 px-3 text-xs">
              Añadir información
            </Link>
          </Panel>
        ) : null}

        {corpora.length > 0 ? (
          <Panel>
            <PanelHeader
              title="Hacé una pregunta"
              description={
                selected
                  ? `Scope: ${selected.name}. La respuesta sólo puede citar fuentes de esta base.`
                  : "Elegí una base para acotar la consulta."
              }
            />
            <div className="panel-body flex flex-col gap-3">
              {suggestions.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <p className="text-[11px] text-faint">
                    Preguntas sugeridas a partir de esta base
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion) => (
                      <button
                        key={suggestion.text}
                        type="button"
                        className="rounded-full border border-border bg-soft px-3 py-1 text-left text-xs text-muted transition-colors hover:border-border-strong hover:text-text"
                        onClick={() => setQuestion(suggestion.text)}
                      >
                        {suggestion.text}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              <Textarea
                aria-label="Pregunta"
                rows={3}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="¿Qué dice la política sobre los plazos de aprobación?"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  leadingIcon={ChatCircleDots}
                  loading={answering}
                  disabled={!question.trim() || !corpusId}
                  onClick={() => void ask()}
                >
                  Preguntar
                </Button>
                <span className="text-[11px] text-faint">
                  Respuesta con citas verificables; si no alcanza, lo dice.
                </span>
              </div>
            </div>
          </Panel>
        ) : null}

        {result ? (
          <Panel>
            <PanelHeader
              title="Respuesta"
              description="La cita abre la evidencia registrada; no se inventan páginas ni fragmentos."
            />
            <div className="panel-body flex flex-col gap-4">
              {result.citations?.length ? (
                <Badge tone="ok">Respaldada por {result.citations.length} cita(s)</Badge>
              ) : (
                <Badge tone="warn">Sin evidencia suficiente</Badge>
              )}
              <div
                className="prose-answer text-sm leading-relaxed text-text"
                dangerouslySetInnerHTML={renderMarkdownHtml(result.answer)}
              />
              {result.missing_information?.length ? (
                <p className="text-xs text-warn">
                  Falta información: {result.missing_information.join(" · ")}
                </p>
              ) : null}

              {result.citations?.length ? (
                <div className="flex flex-col gap-2" data-testid="ask-citations">
                  {result.citations.map((citation, index) => {
                    const resolved = evidence[index];
                    return (
                      <div
                        key={`${citation.document_id}-${index}`}
                        className="rounded-md border border-border bg-soft/50 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <FileText size={14} className="text-accent" aria-hidden />
                          <span className="text-xs font-medium text-text">
                            {citation.document_name || "Documento"}
                          </span>
                          {citation.page ? (
                            <span className="text-[11px] text-muted">página {citation.page}</span>
                          ) : citation.locator ? (
                            <span className="text-[11px] text-muted">{citation.locator}</span>
                          ) : (
                            <span className="text-[11px] text-warn">
                              Sin página o sección registrada
                            </span>
                          )}
                          {evidenceIdFor(index) ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => void resolveEvidence(index)}
                            >
                              Ver dónde lo encontró
                            </Button>
                          ) : (
                            <span className="text-[11px] text-warn">
                              No es posible abrir la evidencia
                            </span>
                          )}
                        </div>
                        {citation.section_path?.length ? (
                          <p className="mt-1 text-[11px] text-faint">
                            {citation.section_path.join(" / ")}
                          </p>
                        ) : null}
                        {citation.excerpt ? (
                          <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted">
                            {citation.excerpt}
                          </p>
                        ) : null}
                        {resolved === "loading" ? (
                          <p className="mt-1 text-[11px] text-faint">Abriendo evidencia…</p>
                        ) : resolved === "missing" ? (
                          <p className="mt-1 flex items-center gap-1 text-[11px] text-warn">
                            <WarningCircle size={12} aria-hidden /> No es posible abrir la
                            evidencia registrada para esta cita.
                          </p>
                        ) : resolved ? (
                          <div className="mt-2 rounded-sm border border-border bg-surface p-2 text-[11px] text-muted">
                            <p>{resolved.excerpt}</p>
                            {resolved.source_id ? (
                              <span className="mt-1 flex flex-wrap gap-3">
                                {resolved.page ? (
                                  <a
                                    href={`/api/v1/knowledge/workspaces/${corpusId}/sources/${resolved.source_id}/file#page=${resolved.page}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-accent hover:underline"
                                  >
                                    Abrir página {resolved.page}
                                  </a>
                                ) : null}
                                <Link
                                  to={`/knowledge/sources/${resolved.source_id}`}
                                  className="text-accent hover:underline"
                                >
                                  Abrir fuente
                                </Link>
                                {canBindAgents ? (
                                  <Link
                                    to={`/agents/new?source_id=${resolved.source_id}`}
                                    className="text-accent hover:underline"
                                  >
                                    Usar en un agente
                                  </Link>
                                ) : null}
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {canWrite ? (
                <div className="flex flex-wrap items-center gap-2 border-t border-border-soft pt-3">
                  <span className="text-xs text-muted">¿Te sirvió?</span>
                  <Button variant="secondary" size="sm" onClick={() => void sendFeedback("up")}>
                    Sí
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void sendFeedback("down", "wrong_source")}
                  >
                    La fuente no coincide
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void sendFeedback("down", "missing_information")}
                  >
                    Falta información
                  </Button>
                  {feedback ? <span className="text-[11px] text-ok">{feedback}</span> : null}
                  {feedbackError ? <span className="text-[11px] text-danger">{feedbackError}</span> : null}
                </div>
              ) : null}
            </div>
          </Panel>
        ) : null}
      </div>
    </KnowledgeLayout>
  );
}
