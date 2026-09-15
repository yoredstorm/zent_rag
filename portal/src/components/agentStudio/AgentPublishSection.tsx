import { ChartLineUp, FloppyDisk, PaperPlaneRight, Robot, Sparkle } from "@phosphor-icons/react";
import { Fragment } from "react";
import { Link } from "react-router-dom";
import type { Session } from "../../api";
import { fmtDateTime } from "../../lib/format";
import QualityGatesPanel from "../QualityGatesPanel";
import {
  EmptyState,
  EnvironmentBadge,
  ErrorInline,
  ReadinessScore,
  SkeletonBlock,
  Spinner,
  StatusBadge,
  SuccessInline,
  VersionBadge,
} from "../ui";
import { AgentField, AgentFieldGroup, FIELD_INPUT_CLASS } from "./AgentField";
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

const DEPLOYMENT_COLUMNS = 7;

/** Pestaña "Publicar": readiness, versiones, despliegue, widget y evaluación. */
export function AgentPublishSection({
  isNew,
  id,
  session,
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
    <div className="mt-4 grid gap-6">
      <section>
        {isNew || !readiness ? (
          <EmptyState
            icon={ChartLineUp}
            title="Guarda el agente primero"
            body="El puntaje se calcula con el propósito, las fuentes y el despliegue."
          />
        ) : (
          <ReadinessScore score={readiness.score} items={readiness.items} />
        )}
      </section>

      {deployMsg && <SuccessInline message={deployMsg} />}
      {deployError && <ErrorInline message={deployError} />}

      <AgentFieldGroup title={COPY.publish.versionsTitle} hint={COPY.publish.versionsHint}>
        <div>
          <button
            type="button"
            className="btn btn-primary min-h-10"
            disabled={deployBusy || !id}
            onClick={onCreateSnapshot}
          >
            {deployBusy ? <Spinner size={14} /> : <FloppyDisk size={15} aria-hidden />}
            Crear versión
          </button>
        </div>
        {versionsLoading ? (
          <SkeletonBlock rows={3} />
        ) : versions.length === 0 ? (
          <EmptyState icon={Robot} title="Sin versiones" body="Guarda el agente y crea la primera versión." />
        ) : (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Versión</th>
                  <th>Estado</th>
                  <th>Notas</th>
                  <th>Creada</th>
                  <th>Acciones</th>
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
                    <td className="text-sm text-muted">{v.notes || "—"}</td>
                    <td className="text-sm text-muted">{fmtDateTime(v.created_at)}</td>
                    <td>
                      {v.status === "draft" && (
                        <button
                          type="button"
                          className="btn btn-ghost min-h-8 text-xs"
                          disabled={deployBusy}
                          onClick={() => onPromote(v.id, "ready")}
                        >
                          Marcar como lista
                        </button>
                      )}
                      {v.status === "ready" && (
                        <span className="inline-flex gap-2">
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 text-xs"
                            disabled={deployBusy}
                            onClick={() => onPromote(v.id, "staging")}
                          >
                            En pruebas
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 text-xs"
                            disabled={deployBusy}
                            onClick={() => onPromote(v.id, "production")}
                          >
                            En producción
                          </button>
                        </span>
                      )}
                      {(v.status === "staging" || v.status === "production") && (
                        <button
                          type="button"
                          className="btn btn-ghost min-h-8 text-xs"
                          disabled={deployBusy}
                          onClick={() => onPromote(v.id, "archived")}
                        >
                          Archivar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AgentFieldGroup>

      <AgentFieldGroup title={COPY.publish.deployTitle} hint={COPY.publish.deployHint}>
        <div className="flex flex-wrap items-end gap-3">
          <AgentField id="agent-deploy-version" label="Versión a publicar">
            <select
              id="agent-deploy-version"
              className={`${FIELD_INPUT_CLASS} min-w-44`}
              value={deployVersionId}
              onChange={(e) => setDeployVersionId(e.target.value)}
            >
              {versions.length === 0 && <option value="">Sin versiones</option>}
              {versions.map((v) => (
                <option key={v.id} value={v.id} disabled={v.status === "draft" || v.status === "archived"}>
                  v{v.version_number} · {v.status}
                </option>
              ))}
            </select>
          </AgentField>
          <AgentField id="agent-deploy-env" label="Entorno">
            <select
              id="agent-deploy-env"
              className={`${FIELD_INPUT_CLASS} min-w-44`}
              value={deployEnvId}
              onChange={(e) => setDeployEnvId(e.target.value)}
            >
              {environments.length === 0 && <option value="">Sin entornos</option>}
              {environments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </select>
          </AgentField>
          <button
            type="button"
            className="btn btn-primary min-h-10"
            disabled={deployBusy || !deployVersionId || !deployEnvId || !id}
            onClick={onDeploy}
          >
            {deployBusy ? <Spinner size={14} /> : <PaperPlaneRight size={15} aria-hidden />}
            Publicar
          </button>
          <button
            type="button"
            className="btn btn-secondary min-h-10"
            disabled={deployBusy || !id}
            onClick={onGoLive}
          >
            Publicar en producción
          </button>
        </div>
        {deployments.length === 0 ? (
          <EmptyState
            icon={ChartLineUp}
            title="Sin publicaciones"
            body="Publica una versión lista en un entorno para que empiece a atender."
          />
        ) : (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Publicación</th>
                  <th>Entorno</th>
                  <th>Estado</th>
                  <th>Endpoint</th>
                  <th>Publicada</th>
                  <th>Historial</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {deployments.map((d) => {
                  const eventsOpen = eventsFor?.deploymentId === d.id;
                  return (
                    <Fragment key={d.id}>
                      <tr>
                        <td className="font-mono text-xs">{d.slug}</td>
                        <td>
                          <EnvironmentBadge
                            name={environments.find((e) => e.id === d.environment_id)?.name || d.environment_id}
                          />
                        </td>
                        <td>
                          <StatusBadge status={d.status} />
                        </td>
                        <td className="font-mono text-xs text-muted">{d.endpoint || "—"}</td>
                        <td className="text-sm text-muted">{fmtDateTime(d.deployed_at)}</td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 text-xs"
                            aria-expanded={eventsOpen}
                            onClick={() => onLoadEvents(d.id)}
                          >
                            {eventsOpen ? "Ocultar historial" : "Ver historial"}
                          </button>
                        </td>
                        <td>
                          {(d.status === "healthy" || d.status === "degraded") && (
                            <button
                              type="button"
                              className="btn btn-ghost min-h-8 text-xs"
                              disabled={deployBusy}
                              onClick={() => onRollback(d.id)}
                            >
                              Volver atrás
                            </button>
                          )}
                        </td>
                      </tr>
                      {eventsOpen && (
                        <tr>
                          <td colSpan={DEPLOYMENT_COLUMNS}>
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
      </AgentFieldGroup>

      <AgentFieldGroup title={COPY.publish.embedTitle} hint={COPY.publish.embedHint}>
        {isNew ? (
          <EmptyState
            icon={Robot}
            title="Guarda el agente primero"
            body="El widget necesita un agente guardado para generar su token."
          />
        ) : (
          <>
            <AgentField
              id="agent-embed-origins"
              label="Sitios donde puede aparecer"
              hint="Dominios separados por coma. Solo desde ahí funcionará el widget."
            >
              <input
                id="agent-embed-origins"
                aria-describedby="agent-embed-origins-hint"
                className={FIELD_INPUT_CLASS}
                value={embedOrigins}
                onChange={(e) => setEmbedOrigins(e.target.value)}
                placeholder="https://farmacia.cl, https://www.farmacia.cl"
              />
            </AgentField>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-primary min-h-11" disabled={embedBusy} onClick={onCreateEmbed}>
                {embedBusy ? <Spinner size={14} /> : "Crear token"}
              </button>
              <button type="button" className="btn btn-secondary min-h-11" disabled={embedBusy} onClick={onRevokeEmbed}>
                Revocar
              </button>
            </div>
            {embedToken && (
              <p className="break-all rounded-md border border-border bg-soft p-3 font-mono text-xs">{embedToken}</p>
            )}
            {embedScript && (
              <AgentField
                id="agent-embed-snippet"
                label="Código para pegar en tu web"
                hint="Cópialo tal cual antes de cerrar la etiqueta body."
              >
                <textarea
                  id="agent-embed-snippet"
                  aria-describedby="agent-embed-snippet-hint"
                  readOnly
                  className={`${FIELD_INPUT_CLASS} min-h-20 font-mono text-xs`}
                  value={embedScript}
                />
              </AgentField>
            )}
          </>
        )}
      </AgentFieldGroup>

      <details className="rounded-md border border-border">
        <summary className="cursor-pointer list-none px-3 py-2.5 text-sm font-medium text-text">
          {COPY.publish.evaluationTitle}
          <span className="ml-2 text-xs font-normal text-muted">{COPY.publish.evaluationHint}</span>
        </summary>
        <div className="border-t border-border px-3 py-3">
          <div className="flex flex-wrap gap-2">
            <Link to="/evaluation/datasets" className="btn btn-secondary min-h-11">
              <Sparkle size={15} aria-hidden />
              Conjuntos de prueba
            </Link>
            <Link to="/evaluation/runs" className="btn btn-secondary min-h-11">
              Ejecuciones
            </Link>
            <Link to="/evaluation/compare" className="btn btn-secondary min-h-11">
              Comparar regresiones
            </Link>
          </div>
        </div>
      </details>

      <details className="rounded-md border border-border">
        <summary className="cursor-pointer list-none px-3 py-2.5 text-sm font-medium text-text">
          {COPY.publish.gatesTitle}
          <span className="ml-2 text-xs font-normal text-muted">
            se aplican a toda la organización
          </span>
        </summary>
        <div className="border-t border-border px-3 py-3">
          <QualityGatesPanel session={session} />
        </div>
      </details>
    </div>
  );
}
