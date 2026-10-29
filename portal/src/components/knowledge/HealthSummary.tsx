// =============================================================================
// HealthSummary — la salud del conocimiento explicada, no solo medida
// =============================================================================
import { CaretDown, Heartbeat, WarningCircle } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Badge, Panel, cn } from "../ui";
import type { KnowledgeAttention, KnowledgeHealth } from "../../lib/knowledgeModel";
import { dimensionSummary, interpretHealth } from "../../lib/knowledgeLanguage";
import { HealthIndicator } from "./badges";

function toneFor(score: number | null): string {
  if (score == null) return "text-faint";
  if (score >= 75) return "text-ok";
  if (score >= 50) return "text-warn";
  return "text-danger";
}

export function HealthSummary({
  health,
  attention,
  loading = false,
}: {
  health: KnowledgeHealth | null;
  attention?: KnowledgeAttention[];
  loading?: boolean;
}) {
  if (loading && !health) {
    return (
      <Panel className="p-5" aria-busy="true">
        <div className="h-40 animate-pulse rounded-md bg-soft" />
      </Panel>
    );
  }
  if (!health) return null;
  const notApplicable = health.not_applicable_dimensions ?? 0;
  const unmeasured = Math.max(
    0,
    health.total_dimensions - health.measured_dimensions - notApplicable,
  );
  const narrativeProfile = health.scoring_profile === "narrative";
  const applicableDimensions = Math.max(
    0,
    health.total_dimensions - notApplicable,
  );
  const partial =
    health.overall != null &&
    applicableDimensions > 0 &&
    health.measured_dimensions / applicableDimensions < 0.6;
  const coverageObjects = Number(
    health.dimensions.find((dimension) => dimension.key === "coverage")?.signals
      ?.objects_total ?? 0,
  );

  return (
    <Panel className="overflow-hidden" data-testid="knowledge-health-summary">
      <div className="grid gap-6 p-5 lg:grid-cols-[280px_1fr]">
        <div className="flex flex-col items-start gap-3">
          <p className="eyebrow flex items-center gap-2">
            <Heartbeat size={12} className="text-accent" aria-hidden />
            {narrativeProfile ? "Calidad del documento" : "Calidad del conocimiento"}
          </p>
          <div className="flex items-center gap-4">
            <HealthIndicator value={health.overall} size={92} />
            <div>
              <p className="text-h3">
                {health.overall != null
                  ? `Calidad${partial ? " parcial" : ""} medida: ${Math.round(
                      health.overall,
                    )} de 100`
                  : "Sin medir"}
              </p>
              <p className="text-xs text-muted">
                {health.measured_dimensions} de {health.total_dimensions} señales
                medidas.
                {notApplicable > 0
                  ? ` ${notApplicable} no aplica(n) a este tipo de documento.`
                  : ""}
                {unmeasured > 0
                  ? ` ${unmeasured} aún sin datos.`
                  : ""}{" "}
                Las no medidas no cuentan como cero.
              </p>
            </div>
          </div>
          <p className="text-[13px] leading-relaxed text-text">
            {interpretHealth(health)}
          </p>
          {narrativeProfile ? (
            <p className="rounded-sm border border-border-soft bg-soft px-2.5 py-2 text-[11px] leading-relaxed text-muted">
              Perfil narrativo: se evalúan extracción, estructura y citas. Una
              novela no se evalúa por reglas de negocio ni métricas.
              {coverageObjects === 0
                ? " No hay objetos canónicos: el libro se explora por pasajes y propuestas."
                : ""}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          {health.dimensions.map((dimension) => {
            const applicable = dimension.applicable !== false;
            const measured = applicable && dimension.measured && dimension.score != null;
            return (
              <details key={dimension.key} className="group kh-dimension">
                <summary className="flex cursor-pointer list-none items-center gap-3 py-1.5">
                  <span className="min-w-0 flex-1 truncate text-sm text-text">
                    {dimension.label}
                  </span>
                  {!applicable ? (
                    <Badge tone="neutral">No aplica</Badge>
                  ) : measured ? (
                    <>
                      <span className={cn("mono text-sm tabular-nums", toneFor(dimension.score))}>
                        {Math.round(dimension.score!)}
                      </span>
                      <span className="hidden text-[11px] text-faint sm:inline">
                        {dimensionSummary(dimension)}
                      </span>
                    </>
                  ) : (
                    <Badge tone="neutral">No medido</Badge>
                  )}
                  <CaretDown
                    size={12}
                    className="shrink-0 text-ghost transition-transform group-open:rotate-180"
                    aria-hidden
                  />
                </summary>
                <div className="pb-2 text-xs leading-relaxed text-muted">
                  <p>{dimension.reason || "Sin detalle."}</p>
                  {dimension.formula && applicable && (
                    <p className="mt-1">
                      Fórmula: <span className="mono">{dimension.formula}</span>
                    </p>
                  )}
                  {dimension.issues.length > 0 && (
                    <ul className="mt-1 list-disc pl-4">
                      {dimension.issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  )}
                  {applicable && !measured && dimension.missing.length > 0 && (
                    <p className="mt-1">Falta medir: {dimension.missing.join(", ")}.</p>
                  )}
                </div>
              </details>
            );
          })}
        </div>
      </div>

      {attention && attention.length > 0 && (
        <div className="border-t border-border px-5 py-4">
          <p className="eyebrow mb-2">Necesita tu atención</p>
          <ul className="flex flex-col gap-2">
            {attention.map((item) => (
              <li key={`${item.kind}-${item.title}`}>
                <Link
                  to={item.href}
                  className="flex items-center gap-2 text-sm text-text hover:underline"
                >
                  <WarningCircle
                    size={14}
                    className={cn(
                      "shrink-0",
                      item.severity === "high" ? "text-danger" : "text-warn"
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">{item.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
