import { BookOpen, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { total_sources: number; total_documents: number; duplicates_removed: number; failed_refreshes_7d: number; open_gaps: number; sources_by_type: { source_type: string; count: number }[]; top_gaps: { query: string; occurrences: number }[] };

export default function AdminKnowledgeHubPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/knowledge-hub/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Hub" subtitle="Fuentes de conocimiento en todas las organizaciones: cobertura, deduplicación y huecos." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.total_sources ?? 0}</p><p className="text-xs text-faint">Fuentes</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.total_documents ?? 0}</p><p className="text-xs text-faint">Documentos</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.duplicates_removed ?? 0}</p><p className="text-xs text-faint">Duplicados evitados</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.failed_refreshes_7d ?? 0}</p><p className="text-xs text-faint">Refrescos fallidos 7d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.open_gaps ?? 0}</p><p className="text-xs text-faint">Huecos abiertos</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><BookOpen size={15} /> Fuentes por tipo</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.sources_by_type ?? []).map((t) => (
                  <div key={t.source_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{t.source_type}</span>
                    <span className="text-faint">{t.count}</span>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Warning size={15} /> Huecos más frecuentes</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_gaps ?? []).map((g) => (
                  <div key={g.query} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 truncate text-text">{g.query}</span>
                    <span className="text-faint">×{g.occurrences}</span>
                  </div>
                ))}
                {(dash?.top_gaps ?? []).length === 0 && <p className="text-xs text-faint">Sin huecos.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}