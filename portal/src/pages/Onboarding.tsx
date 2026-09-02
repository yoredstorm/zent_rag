import { ArrowRight, CheckCircle, Circle, Rocket } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type State = {
  done_steps: string[];
  pending_steps: string[];
  next_step: string;
  progress_pct: number;
  completed: boolean;
  time_to_first_value_seconds: number | null;
  guide: { title: string; body: string; href: string };
  steps_labels: Record<string, string>;
};

const STEPS = ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"];

export default function OnboardingPage() {
  const { session } = useAuth();
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const s = await api<State>("/api/v1/onboarding", { token: session.token, organizationId: session.organizationId });
      setState(s);
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

  async function complete(step: string) {
    if (!session) return;
    try {
      await api(`/api/v1/onboarding/steps/${step}/complete`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div>
      <PageHeader
        title="Onboarding"
        subtitle={state?.completed ? "¡Tenant activado! 🎉" : "Sigue el checklist para activar tu primer agente."}
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading || !state ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="panel p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-text">Checklist de activación</h2>
                <span className="stat-value">{state.progress_pct}%</span>
              </div>
              <div className="mb-4 h-2 overflow-hidden rounded-full bg-soft">
                <div className="h-2 rounded-full bg-accent transition-all" style={{ width: `${state.progress_pct}%` }} />
              </div>
              <div className="space-y-2">
                {STEPS.map((step, i) => {
                  const done = state.done_steps.includes(step);
                  const isNext = state.next_step === step && !done;
                  return (
                    <div key={step} className={`flex items-center gap-3 rounded-md border px-4 py-3 ${done ? "border-border bg-soft/50" : isNext ? "border-accent/40 bg-soft" : "border-border"}`}>
                      {done ? (
                        <CheckCircle size={18} className="text-emerald-400" weight="fill" />
                      ) : (
                        <Circle size={18} className="text-faint" />
                      )}
                      <div className="flex-1">
                        <p className={`text-sm ${done ? "text-faint line-through" : "font-medium text-text"}`}>
                          {i + 1}. {state.steps_labels[step]}
                        </p>
                      </div>
                      {isNext && <span className="badge badge-warning">siguiente</span>}
                      {done && state.time_to_first_value_seconds != null && state.completed && (
                        <span className="text-[10px] text-faint">TTFV {Math.round(state.time_to_first_value_seconds / 60)}m</span>
                      )}
                      {!done && (
                        <button
                          type="button"
                          className="btn btn-ghost min-h-8 px-2 text-xs"
                          onClick={() => session && (window.location.href = state.guide.href)}
                        >
                          Ir <ArrowRight size={12} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="panel p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Rocket size={15} /> Guía: {state.guide.title}
            </h2>
            <p className="text-xs text-faint">{state.guide.body}</p>
            {!state.completed && (
              <div className="mt-3 space-y-2">
                <a href={state.guide.href} className="btn btn-primary block min-h-9 text-center text-xs">
                  Abrir {state.guide.href}
                </a>
                <button
                  type="button"
                  className="btn btn-secondary block min-h-8 w-full text-xs"
                  onClick={() => void complete(state.next_step)}
                >
                  Marcar completado manualmente
                </button>
              </div>
            )}
            {state.completed && (
              <p className="mt-3 text-xs text-emerald-400">
                Activación completa en {state.time_to_first_value_seconds != null ? `${Math.round(state.time_to_first_value_seconds / 60)} min` : "—"}.
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}