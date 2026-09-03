import { Robot, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { sessions: number; organizations_using: number; top_assistants: { key: string; events: number }[]; intents: { intent: string; messages: number }[]; installs: { name: string; slug: string; active: number }[] };

export default function AdminCopilotPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/copilot/dashboard", { token: session.token });
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
      <PageHeader title="Copilot & Asistentes" subtitle="Uso del asistente, intenciones y adopción del marketplace en todas las organizaciones." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.sessions ?? 0}</p><p className="text-xs text-faint">Sesiones de copilot</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.organizations_using ?? 0}</p><p className="text-xs text-faint">Organizaciones activas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.installs ?? []).reduce((n, i) => n + i.active, 0)}</p><p className="text-xs text-faint">Instalaciones activas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.intents ?? []).length}</p><p className="text-xs text-faint">Intenciones detectadas</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={15} /> Top asistentes (eventos)</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_assistants ?? []).map((a) => (
                  <div key={a.key} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{a.key}</span>
                    <span className="text-faint">{a.events}</span>
                  </div>
                ))}
                {(dash?.top_assistants ?? []).length === 0 && <p className="text-xs text-faint">Sin eventos aún.</p>}
              </div>
              <h3 className="mb-2 mt-4 flex items-center gap-2 text-sm font-semibold text-text"><Robot size={15} /> Marketplace (instalaciones)</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.installs ?? []).map((i) => (
                  <div key={i.slug} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{i.name}</span>
                    <span className="text-faint">{i.active} activas</span>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text">Intenciones por mensaje</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.intents ?? []).map((i) => (
                  <div key={i.intent} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{i.intent}</span>
                    <span className="text-faint">{i.messages} msgs</span>
                  </div>
                ))}
                {(dash?.intents ?? []).length === 0 && <p className="text-xs text-faint">Sin intenciones aún.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}