// =============================================================================
// AgentReadinessChecklist — estado del agente en el header.
// =============================================================================
// Traduce el readiness real del backend a lenguaje de producto. No inventa
// ningún ítem: los `key` son los que devuelve `/agents/{id}/readiness`. Los
// pesos y los detalles técnicos quedan en el detalle (etapa Publicar).
// =============================================================================
import { Check, Circle } from "@phosphor-icons/react";
import { Badge, cn } from "../ui";

export type ReadinessItem = {
  key: string;
  label: string;
  met: boolean;
  weight: number;
  detail: string;
};

/** Etiqueta de producto por ítem del backend; lo desconocido cae al label real. */
const PRODUCT_LABELS: Record<string, string> = {
  model: "Modelo elegido",
  prompt: "Instrucciones cargadas",
  knowledge: "Conocimiento disponible",
  datasource: "Fuentes de datos conectadas",
  evaluation: "Conjunto de prueba",
  security: "Herramientas definidas",
  version: "Versión lista",
  deployment: "Publicado y atendiendo",
  rate_limits: "Límites de uso activos",
  observability: "Observabilidad activa",
};

function readinessLabel(item: ReadinessItem): string {
  return PRODUCT_LABELS[item.key] ?? item.label;
}

export function AgentReadinessChecklist({
  score,
  items,
  onOpenDetail,
  maxVisible = 5,
}: {
  score: number;
  items: ReadinessItem[];
  onOpenDetail?: () => void;
  /** Los ítems informativos (peso 0) no se mezclan con los que puntúan. */
  maxVisible?: number;
}) {
  const scored = (items ?? []).filter((item) => item.weight > 0);
  const pending = scored.filter((item) => !item.met);
  const visible = scored.slice(0, maxVisible);

  return (
    <div className="grid gap-2" data-testid="agent-readiness-checklist">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="cursor-pointer text-[12.5px] font-medium text-accent transition-colors hover:text-accent-strong"
          onClick={onOpenDetail}
        >
          Estado del agente · {score}%
        </button>
        <Badge tone={pending.length === 0 ? "ok" : "neutral"}>
          {pending.length === 0
            ? "Listo para publicar"
            : `${pending.length} punto${pending.length === 1 ? "" : "s"} por resolver`}
        </Badge>
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1">
        {visible.map((item) => (
          <li
            key={item.key}
            className={cn(
              "flex items-center gap-1.5 text-[11.5px]",
              item.met ? "text-muted" : "text-faint",
            )}
            title={item.detail}
          >
            {item.met ? (
              <Check size={11} weight="bold" className="shrink-0 text-ok" aria-hidden />
            ) : (
              <Circle size={11} className="shrink-0" aria-hidden />
            )}
            <span>{readinessLabel(item)}</span>
            <span className="sr-only">{item.met ? " cumplido" : " pendiente"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
