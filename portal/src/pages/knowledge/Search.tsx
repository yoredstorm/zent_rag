import { useSearchParams } from "react-router-dom";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeSearch } from "../../components/knowledge/KnowledgeSearch";

export default function KnowledgeSearchPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";

  return (
    <KnowledgeLayout>
      <header className="mb-5">
        <h1 className="text-h1">Búsqueda de conocimiento</h1>
        <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
          Un solo lugar para conceptos, entidades, reglas, métricas, fuentes y
          documentos. Cada resultado abre su objeto con relaciones y evidencia.
        </p>
      </header>
      <KnowledgeSearch
        initialQuery={query}
        autoFocus
        onQueryChange={(value) => {
          const next = new URLSearchParams(params);
          if (value.trim()) next.set("q", value);
          else next.delete("q");
          setParams(next, { replace: true });
        }}
      />
    </KnowledgeLayout>
  );
}
