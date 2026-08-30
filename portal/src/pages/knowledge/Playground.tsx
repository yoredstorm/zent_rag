import { MagnifyingGlass } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, PageHeader, Spinner } from "../../components/ui";
import { renderMarkdownHtml } from "../../lib/markdown";

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

  return (
    <div>
      <PageHeader
        title="Playground de búsqueda"
        subtitle="Misma API que el chat (`POST /rag/query`). Útil para probar retrieval sin el hilo de conversación."
      />
      <ErrorInline message={error} />
      <form className="panel p-5" onSubmit={onSubmit}>
        <label className="mb-2 block text-sm font-medium text-text" htmlFor="playground-q">
          Consulta
        </label>
        <textarea
          id="playground-q"
          className="min-h-[96px] w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ej. ¿Cuál es el stock del ibuprofeno?"
        />
        <button
          type="submit"
          className="btn btn-primary mt-3"
          disabled={loading || !query.trim()}
        >
          {loading ? <Spinner size={14} /> : <MagnifyingGlass size={15} aria-hidden />}
          Buscar
        </button>
      </form>
      {result && (
        <div className="mt-4 grid gap-4 lg:grid-cols-5">
          <div className="panel p-5 lg:col-span-3">
            <h2 className="mb-3 text-sm font-semibold text-text">Respuesta</h2>
            <div
              className="prose-chat text-sm leading-relaxed text-muted"
              dangerouslySetInnerHTML={renderMarkdownHtml(result.answer || "—")}
            />
          </div>
          <div className="panel p-5 lg:col-span-2">
            <h2 className="mb-3 text-sm font-semibold text-text">Fuentes</h2>
            {(result.sources || []).length === 0 ? (
              <p className="text-sm text-faint">Sin citas para esta consulta.</p>
            ) : (
              <ul className="space-y-3">
                {result.sources.map((s, i) => (
                  <li key={i} className="rounded-md border border-border bg-soft p-3 text-[13px] text-muted">
                    {s.content}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
