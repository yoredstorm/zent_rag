import { ArrowLeft, ChatCircleDots, FloppyDisk, Sparkle } from "@phosphor-icons/react";
import { Link, useNavigate } from "react-router-dom";
import { AgentAdvancedPanel } from "../components/agentStudio/AgentAdvancedPanel";
import { AgentAiConfigSuggestion } from "../components/agentStudio/AgentAiConfigSuggestion";
import { AgentBehaviorPresetSection } from "../components/agentStudio/AgentBehaviorPresetSection";
import { AgentStatusBadge } from "../components/agentStudio/AgentField";
import { AgentIntelligenceSection } from "../components/agentStudio/AgentIntelligenceSection";
import { AgentKnowledgeSection } from "../components/agentStudio/AgentKnowledgeSection";
import { AgentPurposeForm } from "../components/agentStudio/AgentPurposeForm";
import { AgentReadinessChecklist } from "../components/agentStudio/AgentReadinessChecklist";
import { AgentResponseProfileSection } from "../components/agentStudio/AgentResponseProfileSection";
import { AgentStageNav, AgentStagePanel } from "../components/agentStudio/AgentStageNav";
import { AgentTestChat } from "../components/agentStudio/AgentTestChat";
import { AgentPublishSection } from "../components/agentStudio/AgentPublishSection";
import { responseProfileSummary } from "../components/agentStudio/agentModes";
import { useAgentStudio } from "../components/agentStudio/useAgentStudio";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Button,
  ConfirmDialog,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SaveStatus,
  SkeletonBlock,
  SuccessInline,
  Switch,
  type SaveState,
} from "../components/ui";

/**
 * Agent Studio. Cuatro decisiones antes de probar: cómo se llama, qué debe
 * lograr, qué información puede consultar y cómo responde. Todo lo demás existe
 * y sigue configurable, pero vive detrás de "Personalizar" o de la etapa
 * Publicar. El estado está en `useAgentStudio`; acá sólo se ensambla.
 */
export default function AgentStudioPage() {
  const studio = useAgentStudio();
  const navigate = useNavigate();

  if (studio.loading) {
    return (
      <Panel className="p-4">
        <SkeletonBlock rows={6} />
      </Panel>
    );
  }

  const saveState: SaveState = studio.saving ? "saving" : studio.dirty ? "dirty" : "idle";
  const playground = (
    <AgentTestChat
      turns={studio.turns}
      input={studio.playInput}
      status={studio.playStatus}
      playing={studio.playing}
      inactive={!studio.isNew && !studio.isActive}
      sources={studio.sources}
      selectedIds={studio.config.source_ids}
      agentName={studio.name.trim() || undefined}
      model={studio.model}
      onInput={studio.setPlayInput}
      onSubmit={(event) => void studio.runPlayground(event)}
      onSuggest={(question) => void studio.runPlaygroundMessage(question)}
      onClear={studio.clearPlayground}
      onActivate={() => studio.setIsActive(true)}
      session={studio.session}
    />
  );

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "Agentes", to: "/agents" },
          { label: studio.isNew ? "Nuevo agente" : studio.name || "Agente" },
        ]}
      />
      <div className="sticky top-0 z-20 mb-4 border-b border-border bg-bg py-3">
        <PageHeader
          className="mb-0"
          title={studio.isNew ? "Nuevo agente" : studio.name || "Agente"}
          subtitle="Dile qué hace, elige qué puede consultar y pruébalo. Zent nunca te pide entender el motor."
          meta={
            <>
              {!studio.isNew ? <AgentStatusBadge active={studio.isActive} /> : null}
              <SaveStatus state={saveState} dirtyLabel="Cambios sin guardar" />
            </>
          }
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {!studio.isNew && (
                <Switch
                  checked={studio.isActive}
                  onCheckedChange={studio.setIsActive}
                  label="Activo"
                  className="w-auto items-center gap-2 rounded-md border border-border bg-raised px-3 py-2"
                />
              )}
              {!studio.isNew && studio.id && (
                <Link to={`/chat?target=agent&id=${studio.id}`} className="btn btn-ghost">
                  <ChatCircleDots size={16} aria-hidden />
                  Probar en Playground
                </Link>
              )}
              <Button
                variant="secondary"
                leadingIcon={Sparkle}
                onClick={studio.openAiSuggestion}
              >
                Crear configuración con IA
              </Button>
              <Button
                variant="primary"
                leadingIcon={FloppyDisk}
                loading={studio.saving}
                disabled={!studio.name.trim()}
                onClick={() => void studio.saveAndStay()}
              >
                {studio.isNew ? "Crear agente" : "Guardar"}
              </Button>
              <Button
                variant="ghost"
                leadingIcon={ArrowLeft}
                onClick={() => {
                  if (studio.dirty) {
                    studio.setLeaveOpen(true);
                    return;
                  }
                  navigate("/agents");
                }}
              >
                Volver
              </Button>
            </div>
          }
        />

        {!studio.isNew && studio.readiness && (
          <div className="mt-2">
            <AgentReadinessChecklist
              score={studio.readiness.score}
              items={studio.readiness.items}
              onOpenDetail={() => studio.goStage("publish")}
            />
          </div>
        )}
      </div>

      <ErrorInline message={studio.error} />
      <SuccessInline message={studio.msg} />

      <AgentStageNav stage={studio.stage} onStage={studio.goStage} className="mb-4" />

      <AgentStagePanel stage={studio.stage}>
        {studio.stage === "develop" && (
          <>
            <div className="grid gap-4 lg:h-[calc(100dvh-16rem)] lg:min-h-[28rem] lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,27rem)_minmax(0,1fr)]">
              <Panel className="flex min-h-0 flex-col overflow-hidden">
                <PanelHeader
                  title="Diseño del agente"
                  description="Lo esencial para que funcione. Lo demás está en Personalizar."
                />
                <div className="grid min-h-0 flex-1 auto-rows-min gap-6 overflow-y-auto p-4">
                  {studio.aiSuggestionOpen && (
                    <AgentAiConfigSuggestion
                      recommendation={studio.recommendation}
                      onApply={studio.applyRecommendation}
                      onDismiss={studio.dismissAiSuggestion}
                      aiBusy={studio.aiBusy}
                      aiError={studio.aiError}
                      aiNotice={studio.aiNotice}
                      onRequestAi={() => void studio.requestProfileDraft()}
                    />
                  )}

                  <AgentPurposeForm
                    name={studio.name}
                    purpose={studio.config.purpose || ""}
                    instructions={studio.systemPrompt}
                    nameError={
                      studio.nameTouched && !studio.name.trim()
                        ? "Necesitas un nombre para guardar."
                        : undefined
                    }
                    onName={studio.setName}
                    onPurpose={(value) => studio.setConfig({ ...studio.config, purpose: value })}
                    onInstructions={studio.setSystemPrompt}
                    agentId={studio.isNew ? undefined : studio.id}
                    token={studio.session?.token}
                    organizationId={studio.session?.organizationId}
                  />

                  <AgentKnowledgeSection
                    sources={studio.sources}
                    selectedIds={studio.config.source_ids}
                    jobs={studio.jobs}
                    loading={studio.sourcesLoading}
                    indexingId={studio.indexingId}
                    capabilitySummary={studio.capabilityLabels.join(" · ")}
                    onToggle={studio.toggleSource}
                    onSetSelected={studio.setSelectedSources}
                    onIndex={(sourceId) => void studio.indexSource(sourceId)}
                  />

                  <AgentBehaviorPresetSection
                    presetId={studio.profilePresetId}
                    summary={responseProfileSummary(studio.config.response_profile)}
                    onPreset={studio.applyPreset}
                    onCustomize={() => {
                      studio.setProfileCustomOpen(!studio.profileCustomOpen);
                      if (studio.advancedOpen) studio.goAdvancedGroup("response");
                    }}
                    onCreateWithAi={studio.openAiSuggestion}
                  />

                  {studio.profileCustomOpen && !studio.advancedOpen && (
                    <div id="agent-behavior-detail" className="animate-rise">
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

                  <AgentIntelligenceSection
                    runtime={studio.config.runtime}
                    onCustomize={() => studio.goAdvancedGroup("intelligence")}
                    onRestore={() =>
                      studio.updateRuntime({
                        tool_routing: null,
                        termination_gate: null,
                        answer_gate: null,
                      })
                    }
                  />
                </div>
              </Panel>

              <div className="min-h-0 h-full">{playground}</div>
            </div>

            <AgentAdvancedPanel
              studio={studio}
              group={studio.advancedGroup}
              onGroup={studio.goAdvancedGroup}
              open={studio.advancedOpen}
              onOpenChange={(next) =>
                studio.goAdvancedGroup(next ? studio.advancedGroup ?? "model" : null)
              }
            />
          </>
        )}

        {studio.stage === "test" && (
          <div className="min-h-[32rem] h-[calc(100dvh-18rem)]">{playground}</div>
        )}

        {studio.stage === "publish" && (
          <AgentPublishSection
            isNew={studio.isNew}
            id={studio.id}
            session={studio.session}
            focus={studio.publishFocus}
            readiness={studio.readiness}
            versions={studio.versions}
            versionsLoading={studio.versionsLoading}
            deployments={studio.deployments}
            environments={studio.environments}
            deployVersionId={studio.deployVersionId}
            setDeployVersionId={studio.setDeployVersionId}
            deployEnvId={studio.deployEnvId}
            setDeployEnvId={studio.setDeployEnvId}
            deployBusy={studio.deployBusy}
            deployMsg={studio.deployMsg}
            deployError={studio.deployError}
            eventsFor={studio.eventsFor}
            embedOrigins={studio.embedOrigins}
            setEmbedOrigins={studio.setEmbedOrigins}
            embedToken={studio.embedToken}
            embedScript={studio.embedScript}
            embedBusy={studio.embedBusy}
            onCreateSnapshot={() => void studio.createSnapshot()}
            onPromote={(versionId, status) => void studio.promoteVersion(versionId, status)}
            onDeploy={() => void studio.deploy()}
            onGoLive={() => void studio.goLive()}
            onRollback={(deploymentId) => void studio.rollback(deploymentId)}
            onLoadEvents={(deploymentId) => void studio.loadEvents(deploymentId)}
            onCreateEmbed={() => void studio.createEmbed()}
            onRevokeEmbed={() => void studio.revokeEmbed()}
          />
        )}
      </AgentStagePanel>

      <ConfirmDialog
        open={studio.leaveOpen}
        onOpenChange={studio.setLeaveOpen}
        title="Salir sin guardar"
        body="Hay cambios sin guardar en este agente. Si sales ahora, se pierden."
        confirmLabel="Salir sin guardar"
        cancelLabel="Seguir editando"
        onConfirm={() => {
          studio.setLeaveOpen(false);
          navigate("/agents");
        }}
      />
    </div>
  );
}
