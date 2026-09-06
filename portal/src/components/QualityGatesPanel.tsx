import { useEffect, useState } from "react";
import { api, type Session } from "../api";

type GateState = Record<string, number>;

const METRICS = [
  { key: "composite_score", label: "Composite score", hint: "0-1" },
  { key: "faithfulness", label: "Faithfulness", hint: "0-1" },
  { key: "answer_relevance", label: "Answer relevance", hint: "0-1" },
  { key: "sql_accuracy", label: "SQL accuracy", hint: "0-1 (datasets con expected_sql)" },
];

/** FASE 03 (S4/S5): umbrales de calidad por org + regresión máxima permitida. */
export default function QualityGatesPanel({ session }: { session: Session | null }) {
  const [gate, setGate] = useState<GateState | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    if (!session) return;
    try {
      const out = await api<{
        gate: { thresholds: Record<string, number>; max_hallucination: number | null; max_regression_pct: number };
      }>("/api/v1/organizations/quality-gates", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setGate({
        ...out.gate.thresholds,
        max_hallucination: out.gate.max_hallucination ?? 0.3,
        max_regression_pct: out.gate.max_regression_pct,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error cargando gates");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function save() {
    if (!session || !gate) return;
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      const { max_hallucination, max_regression_pct, ...thresholds } = gate;
      await api("/api/v1/organizations/quality-gates", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ thresholds, max_hallucination, max_regression_pct }),
      });
      setMsg("Gates guardados. Se aplican al promover a production.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error guardando");
    } finally {
      setSaving(false);
    }
  }

  if (!gate) return null;

  return (
    <section className="panel mt-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-text">Quality gates</h3>
          <p className="mt-1 text-xs text-muted">
            Umbrales sobre métricas que el engine calcula. Se aplican al promover a production;
            una regresión vs la versión desplegada también bloquea.
          </p>
        </div>
        <button type="button" className="btn btn-secondary min-h-9 text-xs" disabled={saving} onClick={() => void save()}>
          {saving ? "Guardando…" : "Guardar gates"}
        </button>
      </div>
      {msg && <p className="mt-2 text-xs text-ok" role="status">{msg}</p>}
      {err && <p className="mt-2 text-xs text-danger" role="alert">{err}</p>}
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {METRICS.map((m) => (
          <label key={m.key} className="block text-xs text-muted">
            <span className="mb-1 block">{m.label}</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-sm"
              value={gate[m.key] ?? 0}
              onChange={(e) => setGate((g) => (g ? { ...g, [m.key]: Number(e.target.value) } : g))}
              title={m.hint}
            />
          </label>
        ))}
        <label className="block text-xs text-muted">
          <span className="mb-1 block">Max hallucination</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-sm"
            value={gate.max_hallucination ?? 0}
            onChange={(e) => setGate((g) => (g ? { ...g, max_hallucination: Number(e.target.value) } : g))}
          />
        </label>
        <label className="block text-xs text-muted">
          <span className="mb-1 block">Max regresión (%)</span>
          <input
            type="number"
            min={0}
            max={50}
            step={1}
            className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-sm"
            value={gate.max_regression_pct ?? 5}
            onChange={(e) => setGate((g) => (g ? { ...g, max_regression_pct: Number(e.target.value) } : g))}
          />
        </label>
      </div>
    </section>
  );
}