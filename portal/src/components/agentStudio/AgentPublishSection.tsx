import { ChartLineUp, FloppyDisk, PaperPlaneRight, Robot, Sparkle } from "@phosphor-icons/react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import type { Session } from "../../api";
import { fmtDateTime } from "../../lib/format";
import QualityGatesPanel from "../QualityGatesPanel";
import {
  Button,
  CodeBlock,
  CopyButton,
  EmptyState,
  EnvironmentBadge,
  ErrorInline,
  Input,
  Panel,
  PanelHeader,
  ReadinessScore,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  VersionBadge,
} from "../ui";
import { AgentDisclosure, AgentField } from "./AgentField";
import { COPY } from "./advancedCopy";
import type { AgentVersion, Deployment, Environment } from "./types";

export type Readiness = {
  score: number;
  items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
};

export type DeploymentEvents = {
  deploymentId: string;
  events: { event: string; created_at: string | null; metadata: Record<string, unknown> }[];
};

const DEPLOYMENT_COLUMNS = [
  "Publicación",
  "Entorno",
  "Estado",
  "Endpoint",
  "Publicada",
  "Historial",
  "Acciones",
];

/** Pestaña "Publicar": readiness, versiones, despliegue, widget y evaluación. */
export function AgentPublishSection({
  isNew,
  id,
  session,
  focus,
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
  isNew: boolean;
  id?: string;
  session: Session | null;
  /** Sub-sección que pidió la URL (`?tab=evaluation`), para abrirla directo. */
  focus?: string | null;
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
  const [evaluationOpen, setEvaluationOpen] = useState(focus === "evaluation");
  const [gatesOpen, setGatesOpen] = useState(false);

  return (
    <div className="grid gap-4">
      <section>
        {isNew || !readiness ? (
          <EmptyState
            icon={ChartLineUp}
            title="Guarda el agente primero"
            body="El puntaje se calcula con el propósito, las fuentes y el despliegue."
            compact
            className="panel"
          />
        ) : (
          <ReadinessScore score={readiness.score} items={readiness.items} />
        )}
      </section>

      <SuccessInline message={deployMsg} className="mb-0" />
      <ErrorInline message={deployError} className="mb-0" />

      <Panel>
        <PanelHeader
          title={COPY.publish.versionsTitle}
          description={COPY.publish.versionsHint}
          actions={
            <Button
              variant="primary"
              size="sm"
              leadingIcon={FloppyDisk}
              loading={deployBusy}
              disabled={!id}
              onClick={onCreateSnapshot}
            >
              Crear versión
            </Button>
          }
        />
        {versionsLoading ? (
          <div className="p-4">
            <SkeletonBlock rows={3} />
          </div>
        ) : versions.length === 0 ? (
          <EmptyState
            icon={Robot}
            title="Sin versiones"
            body="Guarda el agente y crea la primera versión."
            compact
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Versión</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Notas</th>
                  <th scope="col">Creada</th>
                  <th scope="col" className="text-right">
                    Acciones
                  </th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <VersionBadge versionNumber={v.version_number} status={v.status} />
                    </td>
                    <td>
                      <StatusBadge status={v.status} />
                    </td>
                    <td className="text-muted">{v.notes || "—"}</td>
                    <td className="text-muted">{fmtDateTime(v.created_at)}</td>
                    <td className="text-right whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        {v.status === "draft" && (
                          <Button size="sm" variant="ghost" disabled={deployBusy} onClick={() => onPromote(v.id, "ready")}>
                            Marcar como lista
                          </Button>
                        )}
                        {v.status === "ready" && (
                          <>
                            <Button size="sm" variant="ghost" disabled={deployBusy} onClick={() => onPromote(v.id, "staging")}>
                              En pruebas
                            </Button>
                            <Button size="sm" variant="ghost" disabled={deployBusy} onClick={() => onPromote(v.id, "production")}>
                              En producción
                            </Button>
                          </>
                        )}
                        {(v.status === "staging" || v.status === "production") && (
                          <Button size="sm" variant="ghost" disabled={deployBusy} onClick={() => onPromote(v.id, "archived")}>
                            Archivar
                          </Button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel>
        <PanelHeader title={COPY.publish.deployTitle} description={COPY.publish.deployHint} />
        <div className="flex flex-wrap items-end gap-3 border-b border-border p-4">
          <AgentField id="agent-deploy-version" label="Versión a publicar" className="w-52">
            <Select
              id="agent-deploy-version"
              value={deployVersionId}
              onChange={(e) => setDeployVersionId(e.target.value)}
            >
              {versions.length === 0 && <option value="">Sin versiones</option>}
              {versions.map((v) => (
                <option key={v.id} value={v.id} disabled={v.status === "draft" || v.status === "archived"}>
                  v{v.version_number} · {v.status}
                </option>
              ))}
            </Select>
          </AgentField>
          <AgentField id="agent-deploy-env" label="Entorno" className="w-52">
            <Select id="agent-deploy-env" value={deployEnvId} onChange={(e) => setDeployEnvId(e.target.value)}>
              {environments.length === 0 && <option value="">Sin entornos</option>}
              {environments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </AgentField>
          <Button
            variant="primary"
            leadingIcon={PaperPlaneRight}
            loading={deployBusy}
            disabled={!deployVersionId || !deployEnvId || !id}
            onClick={onDeploy}
          >
            Publicar
          </Button>
          <Button disabled={deployBusy || !id} onClick={onGoLive}>
            Publicar en producción
          </Button>
        </div>
        {deployments.length === 0 ? (
          <EmptyState
            icon={ChartLineUp}
            title="Sin publicaciones"
            body="Publica una versión lista en un entorno para que empiece a atender."
            compact
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  {DEPLOYMENT_COLUMNS.map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {deployments.map((d) => {
                  const eventsOpen = eventsFor?.deploymentId === d.id;
                  return (
                    <Fragment key={d.id}>
                      <tr>
                        <td className="mono text-xs">{d.slug}</td>
                        <td>
                          <EnvironmentBadge
                            name={environments.find((e) => e.id === d.environment_id)?.name || d.environment_id}
                          />
                        </td>
                        <td>
                          <StatusBadge status={d.status} />
                        </td>
                        <td className="mono text-xs text-muted">{d.endpoint || "—"}</td>
                        <td className="text-muted">{fmtDateTime(d.deployed_at)}</td>
                        <td>
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-expanded={eventsOpen}
                            onClick={() => onLoadEvents(d.id)}
                          >
                            {eventsOpen ? "Ocultar historial" : "Ver historial"}
                          </Button>
                        </td>
                        <td>
                          {(d.status === "healthy" || d.status === "degraded") && (
                            <Button size="sm" variant="ghost" disabled={deployBusy} onClick={() => onRollback(d.id)}>
                              Volver atrás
                            </Button>
                          )}
                        </td>
                      </tr>
                      {eventsOpen && (
                        <tr>
                          <td colSpan={DEPLOYMENT_COLUMNS.length}>
                            {eventsFor.events.length === 0 ? (
                              <p className="text-xs text-muted">Sin movimientos registrados.</p>
                            ) : (
                              <ul className="grid gap-1">
                                {eventsFor.events.map((event, index) => (
                                  <li
                                    key={`${event.event}-${event.created_at ?? index}`}
                                    className="flex flex-wrap items-center gap-2 text-xs"
                                  >
                                    <span className="font-medium text-text">{event.event}</span>
                                    <span className="text-muted">{fmtDateTime(event.created_at)}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel>
        <PanelHeader title={COPY.publish.embedTitle} description={COPY.publish.embedHint} />
        {isNew ? (
          <EmptyState
            icon={Robot}
            title="Guarda el agente primero"
            body="El widget necesita un agente guardado para generar su token."
            compact
          />
        ) : (
          <div className="grid gap-4 p-4">
            <AgentField
              id="agent-embed-origins"
              label="Sitios donde puede aparecer"
              hint="Dominios separados por coma. Solo desde ahí funcionará el widget."
              className="max-w-xl"
            >
              <Input
                id="agent-embed-origins"
                value={embedOrigins}
                onChange={(e) => setEmbedOrigins(e.target.value)}
                placeholder="https://farmacia.cl, https://www.farmacia.cl"
              />
            </AgentField>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" loading={embedBusy} onClick={onCreateEmbed}>
                Crear token
              </Button>
              <Button disabled={embedBusy} onClick={onRevokeEmbed}>
                Revocar
              </Button>
            </div>
            {embedToken && (
              <div className="flex items-start gap-2">
                <p className="min-w-0 flex-1 rounded-sm border border-border bg-control p-3 font-mono text-xs break-all">
                  {embedToken}
                </p>
                <CopyButton value={embedToken} label="Copiar token" copiedLabel="Token copiado" variant="secondary" />
              </div>
            )}
            {embedScript && (
              <div className="grid gap-1.5">
                <p className="text-[13px] font-medium text-text">Código para pegar en tu web</p>
                <p className="text-xs text-faint">Cópialo tal cual antes de cerrar la etiqueta body.</p>
                <CodeBlock code={embedScript} language="html" filename="embed.html" maxHeight={160} />
              </div>
            )}
          </div>
        )}
      </Panel>

      <AgentDisclosure
        id="agent-publish-evaluation"
        title={COPY.publish.evaluationTitle}
        hint={COPY.publish.evaluationHint}
        open={evaluationOpen}
        onToggle={setEvaluationOpen}
      >
        <div className="flex flex-wrap gap-2">
          <Link to="/evaluation/datasets" className="btn btn-secondary">
            <Sparkle size={15} aria-hidden />
            Conjuntos de prueba
          </Link>
          <Link to="/evaluation/runs" className="btn btn-secondary">
            Ejecuciones
          </Link>
          <Link to="/evaluation/compare" className="btn btn-secondary">
            Comparar regresiones
          </Link>
        </div>
      </AgentDisclosure>

      <AgentDisclosure
        id="agent-publish-gates"
        title={COPY.publish.gatesTitle}
        hint="se aplican a toda la organización"
        open={gatesOpen}
        onToggle={setGatesOpen}
      >
        <QualityGatesPanel session={session} />
      </AgentDisclosure>
    </div>
  );
}
