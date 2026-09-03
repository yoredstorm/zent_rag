import { ChatText, Funnel, Warning, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Funnel = { total_messages: number; total_sessions: number; active_sessions: number; resolved_sessions: number; resolution_rate: number; escalations: number };
type Topics = { total_user_messages: number; topics: { topic: string; message_count: number; share: number }[] };
type Friction = { summary: { repetitive: number; redirects: number; escalations: number; friction_index: number }; repetitive_sessions: { session_id: string; messages: number }[]; redirect_sessions: { session_id: string; intents: number }[] };
type Channels = { channels: { channel: string; messages: number; avg_latency_ms: number; success_rate: number }[] };

export default function ChatInsightsPage() {
  const { session } = useAuth();
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [topics, setTopics] = useState<Topics | null>(null);
  const [friction, setFriction] = useState<Friction | null>(null);
  const [channels, setChannels] = useState<Channels | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [f, t, fr, c] = await Promise.all([
        api<Funnel>("/api/v1/chat-insights/funnel", { token: session.token, organizationId: session.organizationId }),
        api<Topics>("/api/v1/chat-insights/topics", { token: session.token, organizationId: session.organizationId }),
        api<Friction>("/api/v1/chat-insights/friction", { token: session.token, organizationId: session.organizationId }),
        api<Channels>("/api/v1/chat-insights/channels", { token: session.token, organizationId: session.organizationId }),
      ]);
      setFunnel(f);
      setTopics(t);
      setFriction(fr);
      setChannels(c);
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

  return (
    <div className="space-y-6">
      <PageHeader title="Chat Analytics" subtitle="Embudo conversacional, temas de consultas, fricción y comparativa por canal." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{funnel?.total_sessions ?? 0}</p><p className="text-xs text-faint">Sesiones (30d)</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{funnel?.total_messages ?? 0}</p><p className="text-xs text-faint">Mensajes</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{funnel?.resolution_rate ?? 0}%</p><p className="text-xs text-faint">Resolución</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{funnel?.escalations ?? 0}</p><p className="text-xs text-faint">Escalaciones</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Funnel size={14} /> Embudo</h3>
              {[
                { label: "Mensajes", value: funnel?.total_messages ?? 0 },
                { label: "Sesiones", value: funnel?.total_sessions ?? 0 },
                { label: "Sesiones activas (≥2 msgs)", value: funnel?.active_sessions ?? 0 },
                { label: "Resueltas (rating ≥4)", value: funnel?.resolved_sessions ?? 0 },
              ].map((s, i) => (
                <div key={s.label} className="mb-1">
                  <div className="flex justify-between text-[11px]"><span className="text-faint">{s.label}</span><span className="text-text">{s.value}</span></div>
                  <div className="h-1.5 rounded bg-soft"><div className="h-1.5 rounded bg-accent" style={{ width: `${(s.value / Math.max((funnel?.total_messages ?? 1), 1)) * 100}%` }} /></div>
                </div>
              ))}
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ChatText size={14} /> Temas ({topics?.total_user_messages ?? 0} consultas)</h3>
              {(topics?.topics ?? []).map((t) => (
                <div key={t.topic} className="mb-1">
                  <div className="flex justify-between text-[11px]"><span className="text-text">{t.topic}</span><span className="text-faint">{t.message_count} · {t.share}%</span></div>
                  <div className="h-1.5 rounded bg-soft"><div className="h-1.5 rounded bg-emerald-400" style={{ width: `${t.share}%` }} /></div>
                </div>
              ))}
              {(topics?.topics ?? []).length === 0 && <p className="text-xs text-faint">Usa el copilot para detectar temas.</p>}
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Warning size={14} /> Fricción</h3>
              <p className="text-[11px] text-faint">Índice: <span className="font-bold text-amber-400">{friction?.summary.friction_index ?? 0}</span></p>
              <div className="mt-2 space-y-1 text-[11px]">
                <p className="flex justify-between"><span className="text-faint">Sesiones repetitivas</span><span className="text-text">{friction?.summary.repetitive ?? 0}</span></p>
                <p className="flex justify-between"><span className="text-faint">Redirecciones (≥3 intenciones)</span><span className="text-text">{friction?.summary.redirects ?? 0}</span></p>
                <p className="flex justify-between"><span className="text-faint">Escalaciones</span><span className="text-text">{friction?.summary.escalations ?? 0}</span></p>
              </div>
              {(friction?.repetitive_sessions ?? []).slice(0, 3).map((r) => (
                <p key={r.session_id} className="mt-1 truncate rounded bg-soft px-2 py-1 text-[10px] text-faint">{r.session_id.slice(0, 8)}… · {r.messages} mensajes</p>
              ))}
            </section>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={15} /> Canales</h3>
            <div className="panel grid grid-cols-1 gap-2 p-4 lg:grid-cols-3">
              {(channels?.channels ?? []).map((ch) => (
                <div key={ch.channel} className="rounded-md bg-soft p-3">
                  <p className="text-xs font-semibold text-text">{ch.channel}</p>
                  <p className="mt-1 text-xl font-bold text-text">{ch.messages}</p>
                  <p className="text-[10px] text-faint">{ch.avg_latency_ms}ms media · {ch.success_rate}% éxito</p>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}