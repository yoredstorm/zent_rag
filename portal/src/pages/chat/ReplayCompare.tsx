import type { ReactNode } from "react";
import { Badge } from "../../components/ui";

export type ReplayField = { original: unknown; current: unknown };

export type ReplayChange = {
  kind: string;
  original?: unknown;
  current?: unknown;
  added?: string[];
  removed?: string[];
  memory_id?: string;
  display_id?: string;
  title?: string;
};

export type ReplayResult = {
  replay_id: string;
  source_query_id: string;
  replay_query_id: string;
  original_unchanged: boolean;
  comparison: {
    fields: Record<string, ReplayField>;
    improvement: { quality: number | null; cost: number | null };
  };
  what_changed: ReplayChange[];
};

const LABELS: Record<string, string> = {
  route: "Ruta",
  retrieval_strategy: "Estrategia de búsqueda",
  sources: "Fuentes",
  grounding: "Grounding",
  cost: "Costo",
  latency_ms: "Latencia",
  outcome: "Resultado",
};

function shown(value: unknown): string {
  if (value == null || value === "") return "N/A";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "N/A";
  if (typeof value === "number") {
    if (Number.isNaN(value)) return "N/A";
    return String(value);
  }
  return String(value);
}

function percent(value: number | null): string | null {
  if (value == null || Number.isNaN(value)) return null;
  const points = value * 100;
  const sign = points > 0 ? "+" : "";
  return `${sign}${points.toFixed(1)}%`;
}

export function ReplayCompare({
  result,
  error,
  pending,
  onReplay,
}: {
  result: ReplayResult | null;
  error: string;
  pending: boolean;
  onReplay: () => void;
}) {
  const fields = result?.comparison.fields ?? {};
  const quality = percent(result?.comparison.improvement.quality ?? null);
  const cost = percent(result?.comparison.improvement.cost ?? null);
  return (
    <section aria-label="Replay" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Replay</p>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          disabled={pending}
          onClick={onReplay}
        >
          {pending ? "Reejecutando" : "Reejecutar con el sistema actual"}
        </button>
      </div>
      <p className="text-[12.5px] text-muted">
        No modifica esta respuesta. No envía correos, no escribe en la base y no ejecuta acciones con efecto.
      </p>
      {error ? <p className="text-[13px] text-danger">{error}</p> : null}
      {result ? (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Column title="Original">
              <Rows side="original" fields={fields} />
            </Column>
            <Column title="Actual">
              <Rows side="current" fields={fields} />
            </Column>
          </div>
          {quality || cost ? (
            <p className="text-[12.5px] text-text">
              {quality ? <span>Calidad {quality}</span> : null}
              {quality && cost ? <span> · </span> : null}
              {cost ? <span>Costo {cost}</span> : null}
            </p>
          ) : null}
          <div>
            <h3 className="mb-2 text-[12px] font-medium text-text">Qué cambió</h3>
            {result.what_changed.length === 0 ? (
              <p className="text-[12.5px] text-muted">No hay diferencias verificables.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {result.what_changed.map((change, index) => (
                  <li key={`${change.kind}-${change.memory_id ?? index}`} className="text-[12.5px] text-muted">
                    <ChangeLine change={change} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Column({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-sm border border-border-soft px-2.5 py-2">
      <div className="mb-2 flex items-center gap-2">
        <Badge tone="neutral">{title}</Badge>
      </div>
      {children}
    </div>
  );
}

function Rows({ side, fields }: { side: "original" | "current"; fields: Record<string, ReplayField> }) {
  const keys = Object.keys(LABELS).filter((key) => fields[key]);
  if (keys.length === 0) return <p className="text-[12.5px] text-muted">N/A</p>;
  return (
    <dl className="flex flex-col gap-1 text-[12.5px]">
      {keys.map((key) => (
        <div key={key}>
          <dt className="text-faint">{LABELS[key]}</dt>
          <dd className="text-text">{shown(fields[key][side])}</dd>
        </div>
      ))}
    </dl>
  );
}

function ChangeLine({ change }: { change: ReplayChange }) {
  if (change.kind === "memory") {
    return (
      <span>
        Memoria {change.display_id} {change.title}
      </span>
    );
  }
  if (change.kind === "sources") {
    const added = change.added ?? [];
    const removed = change.removed ?? [];
    return (
      <span>
        Fuentes
        {added.length ? ` añadidas ${added.join(", ")}` : ""}
        {removed.length ? ` retiradas ${removed.join(", ")}` : ""}
      </span>
    );
  }
  const label = LABELS[change.kind] ?? change.kind;
  return (
    <span>
      {label}: {shown(change.original)} a {shown(change.current)}
    </span>
  );
}
