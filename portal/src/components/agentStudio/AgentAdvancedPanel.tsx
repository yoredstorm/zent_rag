import type { Session } from "../../api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui";
import { AgentDisclosure } from "./AgentField";
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
 * cómo se publica. Colapsado por defecto: la vista principal es propósito,
 * fuentes y prueba. Cada sección vive en su propio archivo.
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
  jevMode,
  setJevMode,
  answerGate,
  setAnswerGate,
  onEnableAll,
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
  jevMode: "inherit" | "on" | "off";
  setJevMode: (value: "inherit" | "on" | "off") => void;
  answerGate: "inherit" | "on" | "off";
  setAnswerGate: (value: "inherit" | "on" | "off") => void;
  onEnableAll: () => void;
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
    <AgentDisclosure
      id="agent-advanced"
      className="mt-4"
      title={ADVANCED_SUMMARY_TITLE}
      hint={ADVANCED_SUMMARY_HINT}
      open={open}
      onToggle={onToggle}
    >
      <Tabs value={tab} onValueChange={(next) => onTab(next as AdvancedTab)}>
        <TabsList>
          {TABS.map((item) => (
            <TabsTrigger key={item.id} value={item.id}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="behavior">
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
        </TabsContent>

        <TabsContent value="capabilities">
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
            jevMode={jevMode}
            setJevMode={setJevMode}
            answerGate={answerGate}
            setAnswerGate={setAnswerGate}
            onEnableAll={onEnableAll}
          />
        </TabsContent>

        <TabsContent value="publish">
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
        </TabsContent>
      </Tabs>
    </AgentDisclosure>
  );
}
