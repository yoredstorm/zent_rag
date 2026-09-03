import { ChatText, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { sessions_30d: number; messages_30d: number; messages_per_session: number; organizations_using: number; escalations_30d: number; top_topics: { topic: string; message_count: number }[]; daily_trend: { date: string; messages: number; resolution_rate: number }[] };

export default function AdminChatInsightsPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/chat-insights/dashboard", { token: session.token });
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
      <PageHeader title="Chat Insights" subtitle="Conversaciones en todas las organizaciones: volumen, temas, resolución y escalaciones." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.sessions_30d ?? 0}</p><p className="text-xs text-faint">Sesiones 30d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.messages_30d ?? 0}</p><p className="text-xs text-faint">Mensajes 30d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.messages_per_session ?? 0}</p><p className="text-xs text-faint">Msgs/sesión</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.organizations_using ?? 0}</p><p className="text-xs text-faint">Organizaciones</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.escalations_30d ?? 0}</p><p className="text-xs text-faint">Escalaciones 30d</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ChatText size={15} /> Temas globales</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_topics ?? []).map((t) => (
                  <div key={t.topic} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{t.topic}</span>
                    <span className="text-faint">{t.message_count}</span>
                  </div>
                ))}
                {(dash?.top_topics ?? []).length === 0 && <p className="text-xs text-faint">Sin temas aún.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={15} /> Tendencia diaria (7d)</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.daily_trend ?? []).map((d) => (
                  <div key={d.date} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{d.date}</span>
                    <span className="text-faint">{d.messages} msgs · {d.resolution_rate}% reso</span>
                  </div>
                ))}
                {(dash?.daily_trend ?? []).length === 0 && <p className="text-xs text-faint">Sin agregación diaria aún.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}