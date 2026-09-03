import { BookOpen, Compass, GearSix, Lightbulb, Play, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Source = { id: string; name: string; source_type: string; config: Record<string, unknown>; refresh_interval_h: number; last_refresh_at: string | null; next_refresh_at: string | null; status: string; documents: number };
type Coverage = { total_documents: number; sources: { name: string; source_type: string; documents: number; avg_confidence: number; avg_freshness: number }[]; categories: { category: string; documents: number }[]; last_refreshes: { source: string; status: string; added: number; duplicated: number; started_at: string }[]; open_gaps: number; gap_occurrences: number };
type Gap = { id: string; query: string; intent: string | null; occurrences: number; status: string; created_at: string; last_seen_at: string };

export default function KnowledgeHubPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [draft, setDraft] = useState({ name: "", source_type: "url", config: "", refresh_interval_h: 24 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, c, g] = await Promise.all([
        api<{ sources: Source[] }>("/api/v1/knowledge-hub/sources", { token: session.token, organizationId: session.organizationId }),
        api<Coverage>("/api/v1/knowledge-hub/coverage", { token: session.token, organizationId: session.organizationId }),
        api<{ gaps: Gap[] }>("/api/v1/knowledge-hub/gaps", { token: session.token, organizationId: session.organizationId }),
      ]);
      setSources(s.sources || []);
      setCoverage(c);
      setGaps(g.gaps || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    try {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(draft.config || "{}");
      } catch {
        setError("config no es JSON válido");
        setBusy("");
        return;
      }
      const out = await api<{ source_id: string }>("/api/v1/knowledge-hub/sources", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: draft.name, source_type: draft.source_type, config, refresh_interval_h: draft.refresh_interval_h }),
      });
      setError(`Fuente creada: ${out.source_id.slice(0, 8)}…`);
      setDraft({ name: "", source_type: "url", config: "", refresh_interval_h: 24 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(id: string, action: "refresh" | "pause" | "resume") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/knowledge-hub/sources/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setError(`${action}: ${JSON.stringify(out).slice(0, 100)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolveGap(id: string) {
    if (!session) return;
    await api(`/api/v1/knowledge-hub/gaps/${id}/resolve`, { method: "POST", token: session.token, organizationId: session.organizationId });
    await load();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Hub" subtitle="Auto-descubrimiento de fuentes, deduplicación semántica y curación de conocimiento." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><GearSix size={14} /> Nueva fuente</h2>
            <div className="grid grid-cols-1 gap-2">
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="nombre…" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.source_type} onChange={(e) => setDraft((d) => ({ ...d, source_type: e.target.value }))}>
                {["url", "rss", "repo", "s3", "manual"].map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
              <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.refresh_interval_h} onChange={(e) => setDraft((d) => ({ ...d, refresh_interval_h: Number(e.target.value) }))} />
              <textarea className="h-24 rounded-md border border-border bg-soft px-2 py-2 font-mono text-[11px]" placeholder='{"url": "https://docs.miempresa.com", "prefix": "Docs", "author": "equipo", "items": [{"title": "X", "content": "y"}]}' value={draft.config} onChange={(e) => setDraft((d) => ({ ...d, config: e.target.value }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !draft.name} onClick={() => void create()}>Crear</button>
            </div>
            <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Fuentes ({sources.length})</h3>
            <div className="space-y-1">
              {sources.map((s) => (
                <div key={s.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <BookOpen size={12} className="text-faint" />
                    <span className="flex-1 font-medium text-text">{s.name}</span>
                    <span className={`badge ${s.status === "active" ? "badge-ok" : "badge-warning"}`}>{s.status}</span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-faint">{s.source_type} · {s.documents} docs · cada {s.refresh_interval_h}h</p>
                  <div className="mt-1 flex gap-1">
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(s.id, "refresh")}><Play size={10} /> Refrescar</button>
                    {s.status === "active" ? (
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(s.id, "pause")}>Pausar</button>
                    ) : (
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(s.id, "resume")}>Reanudar</button>
                    )}
                  </div>
                </div>
              ))}
              {sources.length === 0 && <p className="text-xs text-faint">Sin fuentes.</p>}
            </div>
          </section>

          <section className="lg:col-span-2">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{coverage?.total_documents ?? 0}</p><p className="text-xs text-faint">Documentos</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{coverage?.open_gaps ?? 0}</p><p className="text-xs text-faint">Huecos abiertos</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{coverage?.gap_occurrences ?? 0}</p><p className="text-xs text-faint">Consultas sin respuesta</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{coverage?.sources.length ?? 0}</p><p className="text-xs text-faint">Fuentes</p></div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <section className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Compass size={14} /> Cobertura por fuente</h3>
                {(coverage?.sources ?? []).map((s) => (
                  <div key={s.name} className="mb-1">
                    <div className="flex justify-between text-[11px]"><span className="text-text">{s.name}</span><span className="text-faint">{s.documents} docs · conf {s.avg_confidence} · fresh {s.avg_freshness}</span></div>
                    <div className="h-1.5 rounded bg-soft"><div className="h-1.5 rounded bg-accent" style={{ width: `${Math.min((s.documents / 5) * 100, 100)}%` }} /></div>
                  </div>
                ))}
                {(coverage?.sources ?? []).length === 0 && <p className="text-xs text-faint">Crea una fuente y refresca.</p>}
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Por categoría</h4>
                <div className="flex flex-wrap gap-1">
                  {(coverage?.categories ?? []).map((cat) => (
                    <span key={cat.category} className="badge badge-muted">{cat.category} · {cat.documents}</span>
                  ))}
                </div>
              </section>

              <section className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Lightbulb size={14} /> Huecos de conocimiento</h3>
                <div className="space-y-1">
                  {gaps.map((g) => (
                    <div key={g.id} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <div className="flex items-center gap-2">
                        <Warning size={11} className="text-amber-400" />
                        <span className="flex-1 text-text">{g.query.slice(0, 60)}</span>
                        <span className="text-faint">×{g.occurrences}</span>
                        <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" onClick={() => void resolveGap(g.id)}>Resolver</button>
                      </div>
                    </div>
                  ))}
                  {gaps.length === 0 && <p className="text-xs text-faint">Sin huecos — consultas sin intención detectada generan huecos.</p>}
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Últimos refrescos</h4>
                {(coverage?.last_refreshes ?? []).slice(0, 4).map((r, i) => (
                  <p key={i} className="rounded bg-soft px-2 py-1 text-[10px] text-faint">
                    {r.source} · {r.status} · +{r.added} · {r.duplicated} dup
                  </p>
                ))}
              </section>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}