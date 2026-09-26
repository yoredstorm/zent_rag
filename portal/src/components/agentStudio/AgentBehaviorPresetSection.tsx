// =============================================================================
// AgentBehaviorPresetSection — COMPORTAMIENTO de alto nivel.
// =============================================================================
// Presets semánticos sobre el mismo sistema de `response_profile`: elegir un
// preset escribe el perfil completo. Un perfil guardado que no coincide con
// ningún preset se muestra como "Personalizado" y NO se pisa.
// =============================================================================
import { Sparkle } from "@phosphor-icons/react";
import { Badge, Button } from "../ui";
import { AgentOptionCard } from "./AgentField";
import { CUSTOM_PROFILE } from "./agentModes";
import { RESPONSE_PROFILE_PRESETS } from "./types";

export function AgentBehaviorPresetSection({
  presetId,
  summary,
  onPreset,
  onCustomize,
  onCreateWithAi,
  aiBusy = false,
}: {
  /** Id del preset que coincide, o `custom`. */
  presetId: string;
  /** Resumen del perfil cuando es personalizado. */
  summary?: string;
  onPreset: (presetId: string) => void;
  /** Abre los controles detallados del perfil. */
  onCustomize: () => void;
  onCreateWithAi?: () => void;
  aiBusy?: boolean;
}) {
  const isCustom = presetId === CUSTOM_PROFILE;
  return (
    <section className="grid gap-3" data-testid="agent-behavior">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold tracking-[-0.01em] text-text">
            Comportamiento
            {isCustom && <Badge tone="neutral">Personalizado</Badge>}
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Cómo explica lo que sabe. No cambia qué puede concluir: eso lo deciden la evidencia y el
            análisis.
          </p>
          {isCustom && summary && (
            <p className="mt-1 text-xs leading-relaxed text-faint" data-testid="agent-behavior-summary">
              {summary}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {onCreateWithAi && (
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={Sparkle}
              loading={aiBusy}
              onClick={onCreateWithAi}
            >
              Crear con IA
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={isCustom}
            aria-controls="agent-behavior-detail"
            onClick={onCustomize}
          >
            Personalizar comportamiento
          </Button>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2" aria-label="Comportamiento del agente" role="group">
        {RESPONSE_PROFILE_PRESETS.map((preset) => (
          <AgentOptionCard
            key={preset.id}
            id={`response-preset-${preset.id}`}
            label={preset.label}
            hint={preset.hint}
            selected={presetId === preset.id}
            onSelect={() => onPreset(preset.id)}
            trailing={preset.id === "balanced" ? <Badge tone="accent">Recomendado</Badge> : undefined}
          />
        ))}
      </div>
    </section>
  );
}
