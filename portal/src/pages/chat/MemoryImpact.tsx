import {
  CheckCircle,
  Clock,
  Info,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Badge, type Tone, Skeleton } from "../../components/ui";

export type ImpactItem = {
  memory_id: string;
  display_id: string;
  title: string;
  memory_type: string;
  status: string;
  confidence: number | null;
  support_count: number | null;
  success_rate: number | null;
  phase: string | null;
  outcome: string | null;
  needs_evidence: boolean;
  previous_support: number | null;
  previous_confidence: number | null;
  support_after: number | null;
  confidence_after: number | null;
};

export type QueryImpact = {
  query_id: string;
  truncated: boolean;
  counts: {
    used: number;
    created: number;
    reinforced: number;
    contradicted: number;
    validated: number;
  };
  used: ImpactItem[];
  created: ImpactItem[];
  reinforced: ImpactItem[];
  contradicted: ImpactItem[];
  validated: ImpactItem[];
};

export type ImpactLoad = "idle" | "loading" | "error" | "ready";

const STATUS: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  observed: { label: "Observada", tone: "info", icon: Clock },
  reinforced: { label: "Reforzada", tone: "ok", icon: CheckCircle },
  pattern: { label: "Patrón", tone: "accent", icon: CheckCircle },
  validated: { label: "Validada", tone: "ok", icon: CheckCircle },
  active: { label: "Activa", tone: "ok", icon: CheckCircle },
  contradicted: { label: "Contradicha", tone: "danger", icon: WarningCircle },
  stale: { label: "Antigua", tone: "warn", icon: Clock },
  rejected: { label: "Rechazada", tone: "danger", icon: XCircle },
  expired: { label: "Vencida", tone: "warn", icon: Clock },
  superseded: { label: "Reemplazada", tone: "neutral", icon: Info },
};

const COUNTS: { key: keyof QueryImpact["counts"]; label: string }[] = [
  { key: "used", label: "Usadas" },
  { key: "created", label: "Creadas" },
  { key: "reinforced", label: "Reforzadas" },
  { key: "contradicted", label: "Contradichas" },
  { key: "validated", label: "Validadas" },
];

const ROUTE_LABEL: Record<string, string> = {
  SQL: "SQL",
  Documentos: "Documentos",
  Directa: "Directa",
  Herramientas: "Herramientas",
  Nodos: "Nodos",
};

const GATE_VERDICT_LABEL: Record<string, string> = {
  approve: "aprobada",
  revise: "revisada",
  revise_exhausted: "aprobada (revisión ya usada)",
  abstain: "abstención",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function textOrNa(value: number | null, digits?: number): string {
  if (value == null || Number.isNaN(value)) return "N/A";
  return digits == null ? String(value) : value.toFixed(digits);
}

function phaseLabel(phase: string | null): string | null {
  if (!phase) return null;
  if (phase === "pre_retrieval") return "Estrategia de búsqueda";
  return phase;
}

function StatusBadge({ status }: { status: string }) {
  const known = STATUS[status];
  if (!known) {
    return (
      <Badge tone="neutral" icon={Info}>
        {status}
      </Badge>
    );
  }
  return (
    <Badge tone={known.tone} icon={known.icon}>
      {known.label}
    </Badge>
  );
}

function Delta({
  before,
  after,
  digits,
}: {
  before: number | null;
  after: number | null;
  digits?: number;
}) {
  if (before != null && after != null) {
    return (
      <span>
        {textOrNa(before, digits)} a{" "}
        <span className="motion-safe:animate-fade-in">{textOrNa(after, digits)}</span>
      </span>
    );
  }
  if (after != null) return <span>{textOrNa(after, digits)}</span>;
  return <span>N/A</span>;
}

function MemoryCard({ item, children }: { item: ImpactItem; children?: ReactNode }) {
  return (
    <li className="rounded-sm border border-border-soft px-2.5 py-2 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 font-medium text-text">{item.title}</span>
        <span className="mono text-[11px] text-faint">{item.display_id}</span>
        <StatusBadge status={item.status} />
      </div>
      {children}
    </li>
  );
}

function ImpactBody({ impact }: { impact: QueryImpact }) {
  const empty = COUNTS.every((row) => impact.counts[row.key] === 0);
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {COUNTS.map((row) => (
          <div key={row.key}>
            <dt className="text-[11px] text-faint">{row.label}</dt>
            <dd className="mono tabular-nums text-text">{impact.counts[row.key]}</dd>
          </div>
        ))}
      </dl>
      {empty ? (
        <p className="text-[13px] text-muted">Esta respuesta no usó ni creó memoria.</p>
      ) : null}
      {impact.truncated ? (
        <p className="text-[12.5px] text-muted">Hay más eventos de los que muestra este resumen.</p>
      ) : null}
      {impact.used.length > 0 ? (
        <Group title="Usadas en esta respuesta">
          {impact.used.map((item) => {
            const aporte = phaseLabel(item.phase);
            const exito =
              item.success_rate == null ? "N/A" : `${(item.success_rate * 100).toFixed(1)}%`;
            return (
              <MemoryCard key={item.memory_id} item={item}>
                <p className="mt-1 text-[11px] text-faint">Estado actual de la memoria</p>
                <p className="mt-1 text-muted">
                  Soporte {textOrNa(item.support_count)} · Confianza {textOrNa(item.confidence, 2)} · Éxito{" "}
                  {exito}
                </p>
                {aporte ? <p className="text-muted">Aporte {aporte}</p> : null}
              </MemoryCard>
            );
          })}
        </Group>
      ) : null}
      {impact.created.length > 0 ? (
        <Group title="Creadas en esta respuesta">
          {impact.created.map((item) => (
            <MemoryCard key={item.memory_id} item={item}>
              {item.needs_evidence ? (
                <p className="mt-1 text-muted">
                  Esta observación necesita más evidencia antes de influir en producción.
                </p>
              ) : null}
              <p className="mt-1 text-muted">
                Confianza {textOrNa(item.confidence_after, 2)} · Soporte {textOrNa(item.support_after)}
              </p>
            </MemoryCard>
          ))}
        </Group>
      ) : null}
      {impact.reinforced.length > 0 ? (
        <Group title="Reforzadas en esta respuesta">
          {impact.reinforced.map((item) => (
            <MemoryCard key={item.memory_id} item={item}>
              <p className="mt-1 text-muted">
                Soporte <Delta before={item.previous_support} after={item.support_after} /> · Confianza{" "}
                <Delta before={item.previous_confidence} after={item.confidence_after} digits={2} />
              </p>
            </MemoryCard>
          ))}
        </Group>
      ) : null}
      {impact.contradicted.length > 0 ? (
        <Group title="Contradichas en esta respuesta">
          {impact.contradicted.map((item) => (
            <MemoryCard key={item.memory_id} item={item} />
          ))}
        </Group>
      ) : null}
      {impact.counts.validated > 0 ? (
        <Group title="Validadas en esta respuesta">
          {impact.validated.map((item) => (
            <MemoryCard key={item.memory_id} item={item} />
          ))}
        </Group>
      ) : null}
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[12px] font-medium text-text">{title}</h3>
      <ul className="flex flex-col gap-2">{children}</ul>
    </div>
  );
}

export function MemoryImpact({ state, impact }: { state: ImpactLoad; impact: QueryImpact | null }) {
  if (state === "idle") return null;
  return (
    <section aria-label="Memoria">
      <p className="eyebrow mb-2">Memoria</p>
      {state === "loading" ? <Skeleton className="h-24" /> : null}
      {state === "error" ? (
        <p className="text-[13px] text-danger">No se pudo cargar la memoria de esta respuesta.</p>
      ) : null}
      {state === "ready" && impact ? <ImpactBody impact={impact} /> : null}
    </section>
  );
}

export function DecisionSignals({
  flow,
  used,
  impactReady,
}: {
  flow: Record<string, unknown> | null;
  used: ImpactItem[];
  impactReady: boolean;
}) {
  const verdict = asRecord(flow?.verdict);
  const jev = asRecord(flow?.jev);
  const routeRaw = verdict.route == null || verdict.route === "" ? "" : String(verdict.route);
  const route = routeRaw ? (ROUTE_LABEL[routeRaw] ?? routeRaw) : "";
  const jevUsed = jev.used === true;
  const jevScore = typeof jev.score === "number" ? jev.score : null;
  const jevVerdict =
    jevUsed && jev.verdict != null && jev.verdict !== ""
      ? (GATE_VERDICT_LABEL[String(jev.verdict)] ?? String(jev.verdict))
      : "";
  const showJev = jevUsed && jevScore != null;
  const memories = impactReady ? used : [];
  if (!route && !showJev && memories.length === 0) return null;
  return (
    <div>
      <p className="eyebrow mb-2">Señales</p>
      <ul className="flex flex-col gap-1 text-[12.5px] text-muted">
        {route ? <li className="text-text">Ruta {route}</li> : null}
        {showJev ? (
          <li>
            JEV <span className="text-text">{jevScore.toFixed(2)}</span>
            {jevVerdict ? <span className="text-text">, {jevVerdict}</span> : null}
          </li>
        ) : null}
        {memories.map((item) => (
          <li key={item.memory_id}>
            Memoria <span className="text-text">{item.title}</span>{" "}
            <span className="mono text-faint">{item.display_id}</span>
            {item.success_rate != null ? (
              <span className="text-text"> · éxito {(item.success_rate * 100).toFixed(1)}%</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
