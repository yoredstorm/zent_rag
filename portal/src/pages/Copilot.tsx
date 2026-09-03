import { ChatCircleDots, DownloadSimple, Lightbulb, Robot, Sparkle } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type MarketAgent = { id: string; name: string; slug: string; description: string; category: string; tags: string[]; rating: number; installs: number; featured: boolean };
type Install = { id: string; agent_id: string | null; agent_name: string; slug: string; category: string; usage_count: number; installed_at: string };
type Msg = { id: string; role: string; content: string; intent: string | null; created_at: string };
type Sugg = { intent: string; repeats: number; last_seen: string; suggested_name: string; sample_questions: string[]; suggestion: string };

export default function CopilotPage() {
  const { session } = useAuth();
  const [market, setMarket] = useState<MarketAgent[]>([]);
  const [installs, setInstalls] = useState<Install[]>([]);
  const [sugg, setSugg] = useState<Sugg[]>([]);
  const [sessions, setSessions] = useState<{ id: string; title: string; last_activity_at: string; messages: number }[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, i, s, ss] = await Promise.all([
        api<{ agents: MarketAgent[] }>("/api/v1/copilot/marketplace", { token: session.token, organizationId: session.organizationId }),
        api<{ installs: Install[] }>("/api/v1/copilot/marketplace/installs", { token: session.token, organizationId: session.organizationId }),
        api<{ suggestions: Sugg[] }>("/api/v1/copilot/automations/suggest", { token: session.token, organizationId: session.organizationId }),
        api<{ sessions: { id: string; title: string; last_activity_at: string; messages: number }[] }>("/api/v1/copilot/sessions", { token: session.token, organizationId: session.organizationId }),
      ]);
      setMarket(m.agents || []);
      setInstalls(i.installs || []);
      setSugg(s.suggestions || []);
      setSessions(ss.sessions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(`i-${slug}`);
    setError("");
    try {
      const out = await api<{ installed: boolean; agent_id: string }>("/api/v1/copilot/marketplace/install", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ slug }),
      });
      setError(out.installed ? `Instalado: ${out.agent_id.slice(0, 8)}…` : "");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(installId: string) {
    if (!session) return;
    await api(`/api/v1/copilot/marketplace/${installId}/remove`, { method: "POST", token: session.token, organizationId: session.organizationId });
    await load();
  }

  async function send() {
    if (!session || !input.trim()) return;
    const text = input.trim();
    setInput("");
    setBusy("chat");
    try {
      const out = await api<{ session_id: string; intent: string | null; reply: string }>("/api/v1/copilot/chat", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ message: text, session_id: activeSession, title: text.slice(0, 60) }),
      });
      setActiveSession(out.session_id);
      await loadMsgs(out.session_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function loadMsgs(sid: string) {
    if (!session) return;
    const m = await api<{ messages: Msg[] }>(`/api/v1/copilot/sessions/${sid}`, { token: session.token, organizationId: session.organizationId });
    setMsgs(m.messages || []);
  }

  async function openSession(sid: string) {
    setActiveSession(sid);
    await loadMsgs(sid);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Copilot & Asistentes" subtitle="Marketplace de agentes pre-entrenados, chat contextual con router por intención y automatizaciones sugeridas." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="panel flex h-[420px] flex-col p-4">
              <div className="flex items-center gap-2 border-b border-border pb-2">
                <ChatCircleDots size={16} className="text-accent" />
                <h2 className="text-sm font-semibold text-text">Copilot</h2>
                <select className="ml-auto rounded-md border border-border bg-soft px-2 py-1 text-xs" value={activeSession ?? ""} onChange={(e) => { if (e.target.value) void openSession(e.target.value); }}>
                  <option value="">nueva conversación…</option>
                  {sessions.map((s) => (<option key={s.id} value={s.id}>{s.title.slice(0, 40)} ({s.messages})</option>))}
                </select>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto py-3">
                {msgs.map((m) => (
                  <div key={m.id} className={`max-w-[85%] rounded-lg px-3 py-2 text-xs ${m.role === "user" ? "ml-auto bg-accent/15 text-text" : "bg-soft text-text"}`}>
                    <p className="whitespace-pre-wrap">{m.content}</p>
                    {m.intent && <p className="mt-1 text-[10px] text-faint">intención: {m.intent}</p>}
                  </div>
                ))}
                {msgs.length === 0 && (
                  <p className="mt-8 text-center text-xs text-faint">Pregúntame: "consulta mi base de conocimiento", "crea un agente", "cuánto cuesta el plan", "despliega el agente"…</p>
                )}
                <div ref={endRef} />
              </div>
              <div className="flex gap-2 border-t border-border pt-2">
                <input
                  className="flex-1 rounded-md border border-border bg-soft px-3 py-2 text-xs text-text"
                  placeholder="Escribe tu consulta…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !busy) void send(); }}
                />
                <button type="button" className="btn btn-primary min-h-8 text-xs" disabled={busy || !input.trim()} onClick={() => void send()}>
                  <Sparkle size={13} /> Enviar
                </button>
              </div>
            </div>

            <section className="mt-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Lightbulb size={15} /> Automatizaciones sugeridas ({sugg.length})</h3>
              <div className="space-y-2">
                {sugg.map((s) => (
                  <div key={s.intent} className="panel p-3 text-xs">
                    <p className="font-medium text-text">{s.suggested_name} · {s.repeats} consultas esta semana</p>
                    <p className="mt-1 text-faint">{s.suggestion}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(s.sample_questions ?? []).map((q, i) => (<span key={i} className="badge badge-muted">{q.slice(0, 60)}</span>))}
                    </div>
                  </div>
                ))}
                {sugg.length === 0 && <p className="panel p-3 text-xs text-faint">Usa el copilot unas veces y sugeriremos automatizaciones.</p>}
              </div>
            </section>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Robot size={15} /> Marketplace</h3>
            <div className="space-y-2">
              {market.map((m) => {
                const installed = installs.some((i) => i.slug === m.slug);
                return (
                  <div key={m.id} className="panel p-3">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-semibold text-text">{m.name}</p>
                      {m.featured && <span className="badge badge-warning">destacado</span>}
                      <span className="badge badge-muted">{m.category}</span>
                      <span className="ml-auto text-[10px] text-faint">★ {m.rating} · {m.installs}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-faint">{m.description}</p>
                    {installed ? (
                      <button type="button" className="btn btn-ghost mt-2 min-h-7 px-2 text-[11px]" onClick={() => void remove(installs.find((i) => i.slug === m.slug)!.id)}>Desinstalar</button>
                    ) : (
                      <button type="button" className="btn btn-secondary mt-2 min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void install(m.slug)}>
                        <DownloadSimple size={12} /> Instalar
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}