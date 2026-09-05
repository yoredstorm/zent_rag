import { Plus, Pulse } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Health = {
  model: string;
  requests: number;
  tokens: number;
  cost: number;
  errors: number;
  error_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  circuit_state: string;
};

type Budget = {
  organization_id: string;
  model: string;
  budget_cents: number | null;
  allowed: boolean;
  throttle_factor: number;
  usage_pct: number;
  note: string | null;
};

type Guardrail = {
  id: string;
  organization_id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  action: string;
  enabled: boolean;
};

type Circuit = {
  model: string;
  state: string;
  failures: number;
  failure_threshold: number;
  window_seconds: number;
  cooldown_seconds: number;
  opened_until: string | null;
};

const KINDS = ["toxicity", "pii", "banned_topics", "length_limit", "custom_pattern"];
const ACTIONS = ["mask", "block", "warn"];
const CIRCUIT = { open: "badge-danger", half_open: "badge-warning", closed: "badge-ok" } as Record<string, string>;

export default function AdminModelHealthPage() {
  const { session } = usePlatformAuth();
  const [health, setHealth] = useState<Health[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [guardrails, setGuardrails] = useState<Guardrail[]>([]);
  const [circuits, setCircuits] = useState<Circuit[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [hours, setHours] = useState(24);
  const [grForm, setGrForm] = useState({ name: "", kind: "banned_topics", action: "mask", config: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [h, b, g, c] = await Promise.all([
        platformApi<{ models: Health[] }>(`/api/v1/platform/model-health/dashboard?hours=${hours}`, { token: session.token }),
        platformApi<{ budgets: Budget[] }>(`/api/v1/platform/model-health/budgets${q}`, { token: session.token }),
        platformApi<{ guardrails: Guardrail[] }>(`/api/v1/platform/model-health/guardrails${q}`, { token: session.token }),
        platformApi<{ circuits: Circuit[] }>("/api/v1/platform/model-health/circuits", { token: session.token }),
      ]);
      setHealth(h.models || []);
      setBudgets(b.budgets || []);
      setGuardrails(g.guardrails || []);
      setCircuits(c.circuits || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
        if (o.organizations?.length) setOrgId(o.organizations[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, hours]);

  async function createGuardrail() {
    if (!session) return;
    setBusy("gr");
    setError("");
    try {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(grForm.config || "{}");
      } catch {
        setError("config JSON inválido");
        return;
      }
      await platformApi("/api/v1/platform/model-health/guardrails", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, name: grForm.name, kind: grForm.kind, action: grForm.action, config }),
      });
      setGrForm({ name: "", kind: "banned_topics", action: "mask", config: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggle(g: Guardrail) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/model-health/guardrails/${g.id}/toggle`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !g.enabled }),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function circuit(model: string, action: "trip" | "reset") {
    if (!session) return;
    setBusy(`${action}-${model}`);
    try {
      await platformApi(`/api/v1/platform/model-health/circuits/${model}/${action}`, {
        method: "POST",
        token: session.token,
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Model Health" subtitle="Budgets con throttling, guardrails de salida y circuit breakers por modelo." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {health.map((m) => (
              <div key={m.model} className={`panel p-4 ${m.circuit_state === "open" ? "border-danger" : ""}`}>
                <div className="flex items-baseline justify-between">
                  <p className="mono text-sm font-semibold text-text">{m.model}</p>
                  <span className={`badge ${CIRCUIT[m.circuit_state] ?? "badge-muted"}`}>{m.circuit_state}</span>
                </div>
                <p className="mt-1 text-[11px] text-faint">{m.requests} req · {m.tokens.toLocaleString()} tok · ${m.cost.toFixed(3)}</p>
                <p className="text-[11px] text-faint">p95 {m.p95_latency_ms.toFixed(0)}ms · err {m.errors} ({(m.error_rate * 100).toFixed(1)}%)</p>
              </div>
            ))}
            {health.length === 0 && <div className="panel p-4 text-xs text-faint">Sin tráfico en la ventana.</div>}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
            {[1, 6, 24].map((h) => (
              <button key={h} type="button" onClick={() => setHours(h)} className={`btn min-h-8 px-3 text-xs ${hours === h ? "btn-primary" : "btn-secondary"}`}>{h}h</button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Budgets por modelo (mes)</h3>
              <div className="space-y-1">
                {budgets.map((b) => (
                  <div key={`${b.organization_id}:${b.model}`} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="mono text-text">{b.model}</span>
                      <span className={`badge ${b.allowed ? (b.throttle_factor < 1 ? "badge-warning" : "badge-ok") : "badge-danger"}`}>
                        {b.allowed ? (b.throttle_factor < 1 ? `throttled ×${b.throttle_factor}` : "ok") : "bloqueado"}
                      </span>
                    </div>
                    <p className="text-faint">${(b.budget_cents ?? 0) / 100} · {b.usage_pct}% usado · {b.note ?? ""}</p>
                  </div>
                ))}
                {budgets.length === 0 && <p className="text-xs text-faint">Sin budgets configurados (Model Gateway).</p>}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Guardrails de salida</h3>
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="nombre" value={grForm.name} onChange={(e) => setGrForm((f) => ({ ...f, name: e.target.value }))} />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={grForm.kind} onChange={(e) => setGrForm((f) => ({ ...f, kind: e.target.value }))}>
                  {KINDS.map((k) => (<option key={k} value={k}>{k}</option>))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={grForm.action} onChange={(e) => setGrForm((f) => ({ ...f, action: e.target.value }))}>
                  {ACTIONS.map((a) => (<option key={a} value={a}>{a}</option>))}
                </select>
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder='config {"words":["x"]}' value={grForm.config} onChange={(e) => setGrForm((f) => ({ ...f, config: e.target.value }))} />
              </div>
              <button type="button" className="btn btn-primary mt-2 min-h-8 text-xs" disabled={!!busy || !orgId} onClick={() => void createGuardrail()}>
                <Plus size={12} aria-hidden /> Crear
              </button>
              <div className="mt-2 space-y-1">
                {guardrails.map((g) => (
                  <div key={g.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="truncate text-text">{g.name}</span>
                    <span className="text-faint">{g.kind} · {g.action}</span>
                    <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" onClick={() => void toggle(g)}>
                      {g.enabled ? "On" : "Off"}
                    </button>
                  </div>
                ))}
                {guardrails.length === 0 && <p className="text-xs text-faint">Sin guardrails.</p>}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <Pulse size={15} aria-hidden /> Circuit breakers
              </h3>
              <div className="space-y-1">
                {circuits.map((c) => (
                  <div key={c.model} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="mono text-text">{c.model}</span>
                    <span className={`badge ${CIRCUIT[c.state] ?? "badge-muted"}`}>{c.state}</span>
                    <span className="text-faint">{c.failures}/{c.failure_threshold} fallos</span>
                    <span className="flex gap-1">
                      <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" disabled={!!busy} onClick={() => void circuit(c.model, "trip")}>Trip</button>
                      <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" disabled={!!busy} onClick={() => void circuit(c.model, "reset")}>Reset</button>
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[10px] text-faint">Auto-fallback: el runtime salta al siguiente candidato del router si el modelo está open.</p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}