/**
 * P19-04 — editor de «Identificar solicitud».
 *
 * Configura rutas cerradas y prueba una frase. No ejecuta la ruta ni concede
 * identidad: solo muestra intent, entidades, confianza y slots faltantes.
 */
import { Compass, Play } from "@phosphor-icons/react";
import { useState } from "react";
import { studioApi as api } from "../../lib/studioApi";
import { useAuth } from "../../auth";
import type { ParameterLevel } from "../../lib/businessSchema";
import { Button, Field, Input, StatusBadge } from "../ui";

type RouteSpec = {
  id: string;
  description: string;
  examples?: string[];
  requires_identity_verification?: boolean;
};

type IntentResult = {
  intent: string;
  confidence: number;
  entities: Record<string, string>;
  missing_slots: string[];
  route: string;
  decision_source: string;
  reason_codes: string[];
  requires_identity_verification: boolean;
};

type Props = {
  config: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
  level?: ParameterLevel;
};

const DEFAULT_ROUTES: RouteSpec[] = [
  { id: "price_lookup", description: "Precio o disponibilidad de un producto" },
  { id: "loyalty_balance", description: "Saldo o movimientos de puntos", requires_identity_verification: true },
  { id: "order_status", description: "Estado o seguimiento de un pedido", requires_identity_verification: true },
  { id: "other", description: "Solicitud distinta o no identificada" },
];

function routeList(config: Record<string, unknown>): RouteSpec[] {
  const raw = config.routes;
  if (!Array.isArray(raw)) return DEFAULT_ROUTES;
  const parsed = raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => ({
      id: String(item.id ?? ""),
      description: String(item.description ?? ""),
      examples: Array.isArray(item.examples) ? item.examples.map(String) : [],
      requires_identity_verification: Boolean(item.requires_identity_verification),
    }))
    .filter((item) => item.id);
  return parsed.length > 0 ? parsed : DEFAULT_ROUTES;
}

export function IntentRouteForm({ config, onChange, level = "simple" }: Props) {
  const { session } = useAuth();
  const routes = routeList(config);
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(routes.map((route) => [route.id, true])),
  );
  const [text, setText] = useState("");
  const [result, setResult] = useState<IntentResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const activeRoutes = routes.filter((route) => enabled[route.id] !== false);
  const confidence = Number(config.confidence_min ?? 0.75);

  function toggle(routeId: string, active: boolean) {
    const next = { ...enabled, [routeId]: active };
    setEnabled(next);
    onChange({
      routes: routes.filter((route) => next[route.id] !== false),
    });
  }

  async function testIntent() {
    if (!session || !text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const response = await api<IntentResult>("/api/v1/workflows/intent-route/test", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          text,
          config: {
            confidence_min: confidence,
            ambiguity_policy: String(config.ambiguity_policy ?? "ask_clarification"),
            routes: activeRoutes,
          },
        }),
      });
      setResult(response);
    } catch (exc) {
      setResult(null);
      setError(exc instanceof Error ? exc.message : "No pude probar la frase.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3" data-testid="wf-intent-form">
      <div className="space-y-1.5">
        <p className="eyebrow">¿Qué solicitudes reconoces?</p>
        {routes.map((route) => (
          <label
            key={route.id}
            className="flex items-start gap-2 rounded-md border border-border bg-soft/40 p-2 text-[12px]"
          >
            <input
              type="checkbox"
              className="mt-0.5"
              checked={enabled[route.id] !== false}
              onChange={(event) => toggle(route.id, event.target.checked)}
              aria-label={`Reconocer ${route.id}`}
            />
            <span className="min-w-0">
              <span className="block font-medium text-text">{route.description || route.id}</span>
              <span className="font-mono text-[10px] text-faint">{route.id}</span>
              {route.requires_identity_verification && (
                <span className="ml-1 text-[10px] text-warning">· requiere identidad</span>
              )}
            </span>
          </label>
        ))}
      </div>

      <Field label="Confianza mínima" hint="Si baja, se pide aclaración en vez de inventar.">
        <Input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={confidence}
          onChange={(event) => onChange({ confidence_min: Number(event.target.value) })}
          data-testid="wf-intent-confidence"
        />
      </Field>

      <Field label="Probar una frase" hint="No ejecuta la ruta; solo clasifica.">
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="¿Cuánto cuesta el arroz?"
          data-testid="wf-intent-text"
        />
      </Field>

      <Button
        variant="secondary"
        size="sm"
        leadingIcon={Play}
        disabled={!text.trim() || busy}
        onClick={testIntent}
        data-testid="wf-intent-test"
      >
        {busy ? "Probando…" : "Probar identificación"}
      </Button>

      {error && (
        <p className="rounded-md border border-danger/30 bg-danger/5 p-2 text-[12px] text-danger" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-2 rounded-md border border-border p-2.5" data-testid="wf-intent-result">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[12px] font-medium text-text">
              <Compass size={14} /> {result.route === "other" ? "No entendí" : result.intent}
            </span>
            <StatusBadge status={result.route === "other" ? "warning" : "success"} raw />
          </div>
          <p className="text-[11px] text-faint">
            Confianza {Math.round(result.confidence * 100)}% · {result.decision_source}
          </p>
          {Object.keys(result.entities).length > 0 && (
            <pre className="overflow-auto rounded-sm bg-soft p-2 font-mono text-[10px] text-text">
              {JSON.stringify(result.entities, null, 2)}
            </pre>
          )}
          {result.missing_slots.length > 0 && (
            <p className="text-[11px] text-muted">Falta: {result.missing_slots.join(", ")}</p>
          )}
          {result.reason_codes.length > 0 && (
            <p className="font-mono text-[10px] text-faint">{result.reason_codes.join(", ")}</p>
          )}
          {result.requires_identity_verification && (
            <p className="text-[11px] text-warning">
              Esta ruta exige identidad verificada antes de consultar datos.
            </p>
          )}
          {level === "advanced" && (
            <p className="font-mono text-[10px] text-faint">decision_source={result.decision_source}</p>
          )}
        </div>
      )}
    </div>
  );
}
