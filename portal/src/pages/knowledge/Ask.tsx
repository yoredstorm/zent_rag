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
};
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
  const [question, setQuestion] = useState("");
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
          body: JSON.stringify({ query: question.trim() }),
        },
      );
      setResult(data.grounded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos responder la pregunta.");
    } finally {
      setAnswering(false);
    }
  }

  async function resolveEvidence(citationIndex: number) {
    if (!session || !result?.evidence_ids?.[citationIndex]) {
      setEvidence((prev) => ({ ...prev, [citationIndex]: "missing" }));
      return;
    }
    setEvidence((prev) => ({ ...prev, [citationIndex]: "loading" }));
    try {
      const item = await api<Evidence>(
        `/api/v1/knowledge/evidence/${result.evidence_ids[citationIndex]}`,
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
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void resolveEvidence(index)}
                          >
                            Ver dónde lo encontró
                          </Button>
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
                            <WarningCircle size={12} aria-hidden /> Evidencia no medible o no autorizada.
                          </p>
                        ) : resolved ? (
                          <div className="mt-2 rounded-sm border border-border bg-surface p-2 text-[11px] text-muted">
                            <p>{resolved.excerpt}</p>
                            {resolved.source_id ? (
                              <Link
                                to={`/knowledge/sources/${resolved.source_id}`}
                                className="mt-1 inline-block text-accent hover:underline"
                              >
                                Abrir fuente
                              </Link>
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
