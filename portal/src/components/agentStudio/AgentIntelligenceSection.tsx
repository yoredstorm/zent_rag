// =============================================================================
// AgentIntelligenceSection — INTELIGENCIA de Nivel 1.
// =============================================================================
// Abstrae JEV (ruteo de herramientas, corte por evidencia, verificación),
// estrategia de búsqueda, top_k, umbral, selección de herramientas y topes.
// El usuario normal ve un estado; el experto personaliza cada override.
// =============================================================================
import { Sparkle } from "@phosphor-icons/react";
import { Badge, Button } from "../ui";
import { intelligenceMode, intelligenceSummary } from "./agentModes";
import type { AgentConfig } from "./types";

export function AgentIntelligenceSection({
  runtime,
  onCustomize,
  onRestore,
}: {
  runtime: AgentConfig["runtime"] | null | undefined;
  onCustomize: () => void;
  onRestore: () => void;
}) {
  const mode = intelligenceMode(runtime);
  const automatic = mode === "auto";

  return (
    <section className="grid gap-3" data-testid="agent-intelligence">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold tracking-[-0.01em] text-text">
            <Sparkle size={14} className="text-accent" aria-hidden />
            Inteligencia
            <Badge tone={automatic ? "accent" : "neutral"}>
              {automatic ? "Automático" : "Personalizado"}
            </Badge>
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            {automatic
              ? "Zent decide cómo buscar, qué herramienta usar y cuándo hay evidencia suficiente para responder."
              : intelligenceSummary(runtime)}
          </p>
          {automatic && (
            <p className="mt-1 text-xs leading-relaxed text-faint">
              Hereda la configuración de Control Center.
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {!automatic && (
            <Button variant="ghost" size="sm" onClick={onRestore}>
              Volver a automático
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={onCustomize}
            aria-label="Personalizar inteligencia"
          >
            Personalizar
          </Button>
        </div>
      </div>
    </section>
  );
}
