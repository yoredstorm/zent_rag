import { MagnifyingGlass, Quotes } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Button,
  EmptyState,
  ErrorInline,
  Field,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
  SplitPane,
  Textarea,
} from "../../components/ui";
import { renderMarkdownHtml } from "../../lib/markdown";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type PlaygroundSource = { content: string; score?: number };
type PlaygroundResult = {
  answer: string;
  sources: PlaygroundSource[];
  method?: string;
};

export default function KnowledgePlaygroundPage() {
  const { session } = useAuth();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || !query.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await api<PlaygroundResult>("/api/v1/rag/query", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ query: query.trim() }),
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al consultar");
    } finally {
      setLoading(false);
    }
  }

  const sources = result?.sources || [];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.playground}
        subtitle="La misma API que usa el chat, sin el hilo de conversación. Sirve para comprobar qué recupera Zent antes de publicar un agente."
      />

      <ErrorInline message={error} />

      <Panel>
        <form className="p-4" onSubmit={onSubmit}>
          <Field
            label="Consulta"
            id="playground-q"
            hint="Se envía tal cual al retrieval: probá con la misma redacción que usaría una persona."
          >
            <Textarea
              rows={3}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="¿Cuál es el stock del ibuprofeno?"
            />
          </Field>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              variant="primary"
              leadingIcon={MagnifyingGlass}
              loading={loading}
              disabled={!query.trim()}
            >
              Buscar
            </Button>
            <span className="text-xs text-faint">
              Respuesta y fuentes se muestran juntas para poder contrastarlas.
            </span>
          </div>
        </form>
      </Panel>

      {loading ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-5" aria-hidden>
          <Skeleton className="h-[220px] rounded-lg lg:col-span-3" />
          <Skeleton className="h-[220px] rounded-lg lg:col-span-2" />
        </div>
      ) : result ? (
        <SplitPane
          className="mt-4"
          secondaryWidth={360}
          primary={
            <Panel>
              <PanelHeader
                title="Respuesta"
                description={
                  result.method ? (
                    <>
                      Método: <span className="mono text-[11px]">{result.method}</span>
                    </>
                  ) : undefined
                }
              />
              <div className="p-4">
                <div
                  className="chat-markdown text-sm leading-relaxed text-text"
                  dangerouslySetInnerHTML={renderMarkdownHtml(result.answer || "—")}
                />
              </div>
            </Panel>
          }
          secondary={
            <Panel>
              <PanelHeader
                title="Fuentes"
                description={
                  sources.length === 1 ? "1 cita recuperada" : `${sources.length} citas recuperadas`
                }
              />
              {sources.length === 0 ? (
                <EmptyState
                  compact
                  icon={Quotes}
                  title="Sin citas"
                  body="La respuesta no trajo fuentes para esta consulta. Revisá la cobertura de la fuente."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {sources.map((s, i) => (
                    <li key={i} className="p-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="eyebrow">Cita {i + 1}</span>
                        {s.score !== undefined && (
                          <span className="mono text-[11px] text-faint tabular-nums">
                            score {String(s.score)}
                          </span>
                        )}
                      </div>
                      <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{s.content}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          }
        />
      ) : (
        <div className="mt-4">
          <EmptyState
            compact
            icon={MagnifyingGlass}
            title="Todavía no hay una consulta"
            body="Escribí una pregunta para ver la respuesta y de dónde sale cada dato."
            hint="Cada consulta es independiente: no hay hilo de conversación."
          />
        </div>
      )}
    </KnowledgeLayout>
  );
}
