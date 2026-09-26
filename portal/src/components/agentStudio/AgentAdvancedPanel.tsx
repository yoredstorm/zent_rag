// =============================================================================
// AgentAdvancedPanel — configuración avanzada con progressive disclosure.
// =============================================================================
// No es un cajón de parámetros: son siete grupos, cada uno con su estado
// resumido y su detalle detrás de "Personalizar". Todos leen y escriben el
// mismo `AgentConfig`; ningún grupo guarda copia propia del estado.
// =============================================================================
import { AgentDisclosure } from "./AgentField";
import { AgentResponseProfileSection } from "./AgentResponseProfileSection";
import {
  AgentIntegrationGroup,
  AgentIntelligenceGroup,
  AgentLimitsGroup,
  AgentModelGroup,
  AgentRetrievalGroup,
  AgentToolsGroup,
} from "./AgentSettingGroups";
import { ADVANCED_SUMMARY_HINT, ADVANCED_SUMMARY_TITLE } from "./advancedCopy";
import { ADVANCED_GROUP_LABELS, ADVANCED_GROUPS, type AdvancedGroup } from "./types";
import type { AgentStudioModel } from "./useAgentStudio";
import { cn } from "../ui";

export function AgentAdvancedPanel({
  studio,
  group,
  onGroup,
  open,
  onOpenChange,
}: {
  studio: AgentStudioModel;
  group: AdvancedGroup | null;
  onGroup: (group: AdvancedGroup | null) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isOpen = (id: AdvancedGroup) => open && group === id;
  const toggle = (id: AdvancedGroup) => (next: boolean) => onGroup(next ? id : null);

  return (
    <AgentDisclosure
      id="agent-advanced"
      className="mt-4"
      title={ADVANCED_SUMMARY_TITLE}
      hint={ADVANCED_SUMMARY_HINT}
      open={open}
      onToggle={onOpenChange}
    >
      <div className="grid gap-6">
        <div
          className="flex flex-wrap gap-1.5"
          role="list"
          aria-label="Secciones de configuración avanzada"
        >
          {ADVANCED_GROUPS.map((id) => (
            <button
              key={id}
              type="button"
              role="listitem"
              aria-pressed={group === id}
              onClick={() => onGroup(group === id ? null : id)}
              className={cn(
                "cursor-pointer rounded-sm border px-2.5 py-1.5 text-[12.5px] transition-colors duration-150",
                group === id
                  ? "border-accent-line bg-accent-soft/40 text-text"
                  : "border-border bg-raised text-muted hover:border-border-strong hover:text-text",
              )}
            >
              {ADVANCED_GROUP_LABELS[id]}
            </button>
          ))}
        </div>

        <AgentModelGroup
          model={studio.model}
          setModel={studio.setModel}
          routes={studio.routes}
          canCustomModel={studio.canCustomModel}
          config={studio.config}
          setConfig={studio.setConfig}
          open={isOpen("model")}
          onOpenChange={toggle("model")}
        />

        <div className="grid gap-3" data-testid="agent-group-response">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <h4 className="text-[13px] font-semibold tracking-[-0.01em] text-text">Respuesta</h4>
            <button
              type="button"
              className="cursor-pointer rounded-sm px-1.5 py-1 text-[12.5px] font-medium text-accent transition-colors hover:text-accent-strong"
              aria-expanded={isOpen("response")}
              aria-controls="agent-group-response-detail"
              onClick={() => onGroup(isOpen("response") ? null : "response")}
            >
              {isOpen("response") ? "Ocultar" : "Personalizar"}
            </button>
          </div>
          {isOpen("response") && (
            <div id="agent-group-response-detail" className="animate-rise">
              <AgentResponseProfileSection
                profile={studio.profile}
                onChange={studio.applyResponseProfile}
                agentId={studio.isNew ? undefined : studio.id}
                token={studio.session?.token}
                organizationId={studio.session?.organizationId}
                sourceTitles={studio.selectedSources.map((source) => source.name)}
              />
            </div>
          )}
        </div>

        <AgentToolsGroup
          flags={studio.capabilities}
          onToggle={studio.toggleCapability}
          sourceTypes={studio.sourceTypes}
          onEnableAvailable={studio.enableAvailableCapabilities}
          open={isOpen("tools")}
          onOpenChange={toggle("tools")}
        />

        <AgentRetrievalGroup
          retrieval={studio.retrieval}
          setRetrieval={studio.setRetrieval}
          open={isOpen("retrieval")}
          onOpenChange={toggle("retrieval")}
        />

        <AgentIntelligenceGroup
          runtime={studio.config.runtime}
          onOverride={studio.updateRuntime}
          open={isOpen("intelligence")}
          onOpenChange={toggle("intelligence")}
        />

        <AgentLimitsGroup
          config={studio.config}
          setConfig={studio.setConfig}
          open={isOpen("limits")}
          onOpenChange={toggle("limits")}
        />

        <AgentIntegrationGroup
          outputSchema={studio.outputSchema}
          setOutputSchema={studio.setOutputSchema}
          open={isOpen("integration")}
          onOpenChange={toggle("integration")}
        />
      </div>
    </AgentDisclosure>
  );
}
