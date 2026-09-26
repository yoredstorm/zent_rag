// =============================================================================
// AgentAiConfigSuggestion — "Crear configuración con IA".
// =============================================================================
// Propone un borrador revisable a partir del propósito y las fuentes, y muestra
// QUÉ decidió. La recomendación es determinista (reglas sobre el propósito y
// los tipos de fuente) y nunca enciende una capacidad que el agente no pueda
// usar. Nada se aplica sin que el usuario lo confirme.
// =============================================================================
import { Sparkle, X } from "@phosphor-icons/react";
import { Badge, Button, IconButton } from "../ui";
import type { AgentRecommendation } from "./agentModes";

export function AgentAiConfigSuggestion({
  recommendation,
  onApply,
  onDismiss,
  aiBusy = false,
  aiError = "",
  aiNotice = "",
  onRequestAi,
}: {
  recommendation: AgentRecommendation;
  onApply: () => void;
  onDismiss: () => void;
  aiBusy?: boolean;
  aiError?: string;
  aiNotice?: string;
  onRequestAi?: () => void;
}) {
  return (
    <section
      className="animate-rise grid gap-3 rounded-md border border-accent-line bg-accent-soft/25 p-3"
      data-testid="agent-ai-suggestion"
      aria-labelledby="agent-ai-suggestion-title"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3
            id="agent-ai-suggestion-title"
            className="flex items-center gap-1.5 text-[13px] font-semibold text-text"
          >
            <Sparkle size={14} className="text-accent" aria-hidden />
            Configuración recomendada por Zent
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Un borrador a partir de tu propósito y tus fuentes. Nada se guarda hasta que apliques y
            guardes.
          </p>
        </div>
        <IconButton label="Descartar la recomendación" icon={X} iconSize={14} onClick={onDismiss} />
      </div>

      <ul className="flex flex-wrap gap-1.5" data-testid="agent-ai-decisions">
        {recommendation.decisions.map((decision) => (
          <li key={decision}>
            <Badge tone="neutral">{decision}</Badge>
          </li>
        ))}
      </ul>

      {recommendation.reasons.length > 0 && (
        <ul className="grid gap-1">
          {recommendation.reasons.map((reason) => (
            <li key={reason} className="text-xs leading-relaxed text-muted">
              · {reason}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" onClick={onApply}>
          Aplicar
        </Button>
        {onRequestAi && (
          <Button variant="secondary" size="sm" loading={aiBusy} onClick={onRequestAi}>
            Pedir borrador de estilo con IA
          </Button>
        )}
      </div>

      {aiNotice && (
        <p className="text-xs text-ok" role="status">
          {aiNotice}
        </p>
      )}
      {aiError && (
        <p className="text-xs text-danger" role="alert">
          {aiError}
        </p>
      )}
    </section>
  );
}
