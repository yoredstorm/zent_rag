import type { Session } from "../../api";
import { PageTabs } from "../PageTabs";
import { AgentBehaviorSection } from "./AgentBehaviorSection";
import { AgentCapabilitiesSection } from "./AgentCapabilitiesSection";
import {
  AgentPublishSection,
  type DeploymentEvents,
  type Readiness,
} from "./AgentPublishSection";
import { ADVANCED_SUMMARY_HINT, ADVANCED_SUMMARY_TITLE } from "./advancedCopy";
import {
  ADVANCED_TAB_LABELS,
  ADVANCED_TABS,
  type AdvancedTab,
  type AgentConfig,
  type AgentVersion,
  type Deployment,
  type Environment,
} from "./types";

const TABS = ADVANCED_TABS.map((id) => ({ id, label: ADVANCED_TAB_LABELS[id] }));

/**
 * Ajustes extra del agente en tres grupos: cómo responde, qué puede hacer y
 * cómo se publica. Cada sección vive en su propio archivo.
 */
export function AgentAdvancedPanel({
  tab,
  onTab,
  open,
  onToggle,
  isNew,
  id,
  session,
  model,
  setModel,
  routes,
  canCustomModel,
  config,
  setConfig,
  semantic,
  setSemantic,
  sql,
  setSql,
  apiCalls,
  setApiCalls,
  retrieval,
  setRetrieval,
  outputSchema,
  setOutputSchema,
  readiness,
  versions,
  versionsLoading,
  deployments,
  environments,
  deployVersionId,
  setDeployVersionId,
  deployEnvId,
  setDeployEnvId,
  deployBusy,
  deployMsg,
  deployError,
  eventsFor,
  embedOrigins,
  setEmbedOrigins,
  embedToken,
  embedScript,
  embedBusy,
  onCreateSnapshot,
  onPromote,
  onDeploy,
  onGoLive,
  onRollback,
  onLoadEvents,
  onCreateEmbed,
  onRevokeEmbed,
}: {
  tab: AdvancedTab;
  onTab: (tab: AdvancedTab) => void;
  open: boolean;
  onToggle: (open: boolean) => void;
  isNew: boolean;
  id?: string;
  session: Session | null;
  model: string;
  setModel: (value: string) => void;
  routes: { name: string; description: string }[];
  canCustomModel: boolean;
  config: AgentConfig;
  setConfig: (config: AgentConfig) => void;
  semantic: boolean;
  setSemantic: (value: boolean) => void;
  sql: boolean;
  setSql: (value: boolean) => void;
  apiCalls: boolean;
  setApiCalls: (value: boolean) => void;
  retrieval: { strategy: string; top_k: number; score_threshold: number };
  setRetrieval: (value: { strategy: string; top_k: number; score_threshold: number }) => void;
  outputSchema: string;
  setOutputSchema: (value: string) => void;
  readiness: Readiness | null;
  versions: AgentVersion[];
  versionsLoading: boolean;
  deployments: Deployment[];
  environments: Environment[];
  deployVersionId: string;
  setDeployVersionId: (value: string) => void;
  deployEnvId: string;
  setDeployEnvId: (value: string) => void;
  deployBusy: boolean;
  deployMsg: string;
  deployError: string;
  eventsFor: DeploymentEvents | null;
  embedOrigins: string;
  setEmbedOrigins: (value: string) => void;
  embedToken: string;
  embedScript: string;
  embedBusy: boolean;
  onCreateSnapshot: () => void;
  onPromote: (versionId: string, status: string) => void;
  onDeploy: () => void;
  onGoLive: () => void;
  onRollback: (deploymentId: string) => void;
  onLoadEvents: (deploymentId: string) => void;
  onCreateEmbed: () => void;
  onRevokeEmbed: () => void;
}) {
  return (
    <details
      className="mt-6 rounded-md border border-border bg-surface"
      open={open}
      onToggle={(e) => {
        const next = (e.target as HTMLDetailsElement).open;
        if (next !== open) onToggle(next);
      }}
    >
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-text">
        {ADVANCED_SUMMARY_TITLE}
        <span className="ml-2 text-xs font-normal text-muted">{ADVANCED_SUMMARY_HINT}</span>
      </summary>
      <div className="border-t border-border px-4 py-4">
        <PageTabs
          idPrefix="agent-advanced"
          tabs={TABS}
          active={tab}
          onChange={(next) => onTab(next as AdvancedTab)}
        />

        <div id={`agent-advanced-panel-${tab}`} role="tabpanel" aria-labelledby={`agent-advanced-${tab}`}>
          {tab === "behavior" && (
            <AgentBehaviorSection
              model={model}
              setModel={setModel}
              routes={routes}
              canCustomModel={canCustomModel}
              config={config}
              setConfig={setConfig}
              outputSchema={outputSchema}
              setOutputSchema={setOutputSchema}
            />
          )}

          {tab === "capabilities" && (
            <AgentCapabilitiesSection
              config={config}
              setConfig={setConfig}
              semantic={semantic}
              setSemantic={setSemantic}
              sql={sql}
              setSql={setSql}
              apiCalls={apiCalls}
              setApiCalls={setApiCalls}
              retrieval={retrieval}
              setRetrieval={setRetrieval}
            />
          )}

          {tab === "publish" && (
            <AgentPublishSection
              isNew={isNew}
              id={id}
              session={session}
              readiness={readiness}
              versions={versions}
              versionsLoading={versionsLoading}
              deployments={deployments}
              environments={environments}
              deployVersionId={deployVersionId}
              setDeployVersionId={setDeployVersionId}
              deployEnvId={deployEnvId}
              setDeployEnvId={setDeployEnvId}
              deployBusy={deployBusy}
              deployMsg={deployMsg}
              deployError={deployError}
              eventsFor={eventsFor}
              embedOrigins={embedOrigins}
              setEmbedOrigins={setEmbedOrigins}
              embedToken={embedToken}
              embedScript={embedScript}
              embedBusy={embedBusy}
              onCreateSnapshot={onCreateSnapshot}
              onPromote={onPromote}
              onDeploy={onDeploy}
              onGoLive={onGoLive}
              onRollback={onRollback}
              onLoadEvents={onLoadEvents}
              onCreateEmbed={onCreateEmbed}
              onRevokeEmbed={onRevokeEmbed}
            />
          )}
        </div>
      </div>
    </details>
  );
}
