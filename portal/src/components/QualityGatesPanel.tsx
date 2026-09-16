import { ArrowClockwise, FloppyDisk } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api, type Session } from "../api";
import {
  Button,
  ErrorInline,
  Field,
  Input,
  Skeleton,
  SuccessInline,
} from "./ui";

type GateState = Record<string, number>;

const METRICS = [
  { key: "composite_score", label: "Puntaje compuesto", hint: "0-1 · composite_score" },
  { key: "faithfulness", label: "Fidelidad a las fuentes", hint: "0-1 · faithfulness" },
  { key: "answer_relevance", label: "Relevancia de la respuesta", hint: "0-1 · answer_relevance" },
  {
    key: "sql_accuracy",
    label: "Precisión SQL",
    hint: "0-1 · sql_accuracy (datasets con expected_sql)",
  },
];

/** FASE 03 (S4/S5): umbrales de calidad por org + regresión máxima permitida. */
export default function QualityGatesPanel({ session }: { session: Session | null }) {
  const [gate, setGate] = useState<GateState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    if (!session) return;
    setLoading(true);
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
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error cargando umbrales");
    } finally {
      setLoading(false);
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
      setMsg("Umbrales guardados. Se aplican al promover a producción.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error guardando");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !gate) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-5 w-44" />
        <Skeleton className="h-3.5 w-full max-w-md" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[62px] rounded-sm" />
          ))}
        </div>
      </div>
    );
  }

  if (!gate) {
    return (
      <div className="flex flex-col gap-3">
        <ErrorInline
          message={err || "No pudimos cargar los umbrales de calidad."}
          className="mb-0"
        />
        <div>
          <Button size="sm" variant="secondary" leadingIcon={ArrowClockwise} onClick={() => void load()}>
            Reintentar
          </Button>
        </div>
      </div>
    );
  }

  return (
    <section aria-labelledby="quality-gates-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h3 id="quality-gates-title" className="text-h3">
            Umbrales de calidad
          </h3>
          <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
            Mínimos que debe alcanzar una versión para pasar a producción. Si empeora frente a la
            versión ya publicada, también se bloquea.
          </p>
        </div>
        <Button
          variant="primary"
          loading={saving}
          leadingIcon={FloppyDisk}
          onClick={() => void save()}
        >
          Guardar umbrales
        </Button>
      </div>

      <SuccessInline message={msg} className="mt-3 mb-0" />
      <ErrorInline message={err} className="mt-3 mb-0" />

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {METRICS.map((metric) => (
          <Field key={metric.key} label={metric.label} hint={metric.hint}>
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              className="mono"
              value={gate[metric.key] ?? 0}
              onChange={(e) =>
                setGate((current) =>
                  current ? { ...current, [metric.key]: Number(e.target.value) } : current
                )
              }
            />
          </Field>
        ))}
        <Field label="Alucinación máxima" hint="0-1 · max_hallucination">
          <Input
            type="number"
            min={0}
            max={1}
            step={0.05}
            className="mono"
            value={gate.max_hallucination ?? 0}
            onChange={(e) =>
              setGate((current) =>
                current ? { ...current, max_hallucination: Number(e.target.value) } : current
              )
            }
          />
        </Field>
        <Field label="Regresión máxima (%)" hint="% · max_regression_pct">
          <Input
            type="number"
            min={0}
            max={50}
            step={1}
            className="mono"
            value={gate.max_regression_pct ?? 5}
            onChange={(e) =>
              setGate((current) =>
                current ? { ...current, max_regression_pct: Number(e.target.value) } : current
              )
            }
          />
        </Field>
      </div>
    </section>
  );
}
