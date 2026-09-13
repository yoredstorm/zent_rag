import {
  ChartLineUp,
  FloppyDisk,
  Gauge,
  PaperPlaneRight,
  Robot,
  Sparkle,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import type { Session } from "../../api";
import { PageTabs } from "../PageTabs";
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
import {
  ADVANCED_TAB_LABELS,
  type AdvancedTab,
  type AgentConfig,
  type AgentVersion,
  type Deployment,
  type Environment,
  parseSchema,
} from "./types";

type Readiness = {
  score: number;
  items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
};

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
  eventsFor: { deploymentId: string; events: { event: string; created_at: string | null; metadata: Record<string, unknown> }[] } | null;
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
  const gatewayValue = routes.some((r) => r.name === model)
    ? model
    : model && canCustomModel
      ? "__custom__"
      : "zent-default";

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
        Avanzado
        <span className="ml-2 text-xs font-normal text-muted">modelo, tools extra, versiones y despliegue</span>
      </summary>
      <div className="border-t border-border px-4 py-4">
        <PageTabs
          idPrefix="agent-advanced"
          tabs={Object.entries(ADVANCED_TAB_LABELS).map(([id, label]) => ({ id, label }))}
          active={tab}
          onChange={(next) => onTab(next as AdvancedTab)}
        />

        {tab === "model" && (
          <section className="mt-4 grid gap-4">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Ruta del gateway</span>
              <select
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={gatewayValue}
                onChange={(e) => {
                  const next = e.target.value;
                  if (next === "__custom__") {
                    setModel("");
                    return;
                  }
                  setModel(next);
                }}
              >
                <option value="zent-fast">zent-fast</option>
                <option value="zent-cheap">zent-cheap</option>
                <option value="zent-default">zent-default</option>
                <option value="zent-quality">zent-quality</option>
                <option value="zent-routed">zent-routed (routing con policy)</option>
                {routes
                  .filter(
                    (r) =>
                      r.name !== "zent-default" &&
                      !["zent-fast", "zent-cheap", "zent-quality", "zent-routed"].includes(r.name),
                  )
                  .map((r) => (
                    <option key={r.name} value={r.name}>
                      {r.name}
                    </option>
                  ))}
                {canCustomModel && <option value="__custom__">Modelo custom…</option>}
              </select>
            </label>
            {canCustomModel && (!routes.some((r) => r.name === model) || model === "") && (
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-text">Modelo custom</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  placeholder="openai/gpt-4o-mini"
                  value={routes.some((r) => r.name === model) ? "" : model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </label>
            )}
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">
                Temperature ({config.temperature.toFixed(2)})
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={config.temperature}
                onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })}
                className="w-full"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Tono</span>
              <select
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={config.tone}
                onChange={(e) => setConfig({ ...config, tone: e.target.value as AgentConfig["tone"] })}
              >
                <option value="professional">Profesional</option>
                <option value="friendly">Cercano</option>
                <option value="concise">Conciso</option>
              </select>
            </label>
          </section>
        )}

        {tab === "tools" && (
          <fieldset className="mt-4 grid gap-3">
            <legend className="mb-1 text-sm font-medium text-text">Capacidades extra</legend>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} />
              <span className="text-sm text-text">Búsqueda semántica (search_knowledge)</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={sql} onChange={(e) => setSql(e.target.checked)} />
              <span className="text-sm text-text">SQL Expert (query_database)</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={apiCalls} onChange={(e) => setApiCalls(e.target.checked)} />
              <span className="text-sm text-text">API Calls (call_api)</span>
            </label>
          </fieldset>
        )}

        {tab === "security" && (
          <fieldset className="mt-4 grid gap-3">
            <legend className="mb-2 text-sm font-medium text-text">Seguridad</legend>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={sql} onChange={(e) => setSql(e.target.checked)} />
              <span className="text-sm text-text">Permitir SQL Expert</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={apiCalls} onChange={(e) => setApiCalls(e.target.checked)} />
              <span className="text-sm text-text">Permitir API Calls</span>
            </label>
          </fieldset>
        )}

        {tab === "limits" && (
          <section className="mt-4 grid gap-4 sm:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Max steps</span>
              <input
                type="number"
                min={1}
                max={100}
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
                value={config.limits?.max_steps ?? 8}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    limits: { ...(config.limits || { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 }), max_steps: Number(e.target.value) },
                  })
                }
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Max tokens</span>
              <input
                type="number"
                min={1}
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
                value={config.limits?.max_tokens ?? 4000}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    limits: { ...(config.limits || { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 }), max_tokens: Number(e.target.value) },
                  })
                }
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Max cost USD</span>
              <input
                type="number"
                min={0}
                step={0.01}
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
                value={config.limits?.max_cost_usd ?? 0.5}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    limits: {
                      ...(config.limits || { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 }),
                      max_cost_usd: Number(e.target.value),
                    },
                  })
                }
              />
            </label>
          </section>
        )}

        {tab === "retrieval" && (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Estrategia
              <select className="input" value={retrieval.strategy} onChange={(e) => setRetrieval({ ...retrieval, strategy: e.target.value })}>
                <option value="vector">vector</option>
                <option value="lexical">lexical</option>
                <option value="hybrid">hybrid</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Top-K
              <input
                type="number"
                className="input"
                min={1}
                max={50}
                value={retrieval.top_k}
                onChange={(e) => setRetrieval({ ...retrieval, top_k: Number(e.target.value) || 8 })}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Score threshold
              <input
                type="number"
                className="input"
                step={0.05}
                min={0}
                max={1}
                value={retrieval.score_threshold}
                onChange={(e) => setRetrieval({ ...retrieval, score_threshold: Number(e.target.value) || 0 })}
              />
            </label>
          </div>
        )}

        {tab === "output" && (
          <div className="mt-4">
            <textarea
              className="input min-h-52 w-full font-mono text-xs"
              value={outputSchema}
              onChange={(e) => setOutputSchema(e.target.value)}
              placeholder={'{"product": "string", "warehouse": "string", "stock": "integer"}'}
              spellCheck={false}
            />
            {outputSchema.trim() && !parseSchema(outputSchema) && (
              <p className="mt-2 text-xs text-danger">JSON inválido. Revisa la sintaxis.</p>
            )}
          </div>
        )}

        {tab === "readiness" && (
          <div className="mt-4">
            {isNew || !readiness ? (
              <EmptyState icon={Gauge} title="Guarda el agente primero" body="El readiness se calcula con propósito, fuentes y despliegue." />
            ) : (
              <ReadinessScore score={readiness.score} items={readiness.items} />
            )}
          </div>
        )}

        {tab === "evaluation" && (
          <section className="mt-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Sparkle size={15} aria-hidden /> Evaluación
            </h3>
            <div className="flex flex-wrap gap-2">
              <Link to="/evaluation/datasets" className="btn btn-secondary min-h-11">
                Datasets
              </Link>
              <Link to="/evaluation/runs" className="btn btn-secondary min-h-11">
                Runs
              </Link>
              <Link to="/evaluation/compare" className="btn btn-secondary min-h-11">
                Regresiones
              </Link>
            </div>
          </section>
        )}

        {tab === "versions" && (
          <section className="mt-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-text">Versiones del agente</h3>
              <button type="button" className="btn btn-primary min-h-10" disabled={deployBusy || !id} onClick={onCreateSnapshot}>
                {deployBusy ? <Spinner size={14} /> : <FloppyDisk size={15} aria-hidden />}
                Crear snapshot
              </button>
            </div>
            {deployMsg && <SuccessInline message={deployMsg} />}
            {deployError && <ErrorInline message={deployError} />}
            {versionsLoading ? (
              <SkeletonBlock rows={3} />
            ) : versions.length === 0 ? (
              <EmptyState icon={Robot} title="Sin versiones" body="Guarda el agente y crea un snapshot." />
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
                        <td className="text-sm text-muted">{new Date(v.created_at).toLocaleString("es-PE")}</td>
                        <td>
                          {v.status === "draft" && (
                            <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={deployBusy} onClick={() => onPromote(v.id, "ready")}>
                              Promover a ready
                            </button>
                          )}
                          {v.status === "ready" && (
                            <span className="inline-flex gap-2">
                              <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={deployBusy} onClick={() => onPromote(v.id, "staging")}>
                                Staging
                              </button>
                              <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={deployBusy} onClick={() => onPromote(v.id, "production")}>
                                Production
                              </button>
                            </span>
                          )}
                          {(v.status === "staging" || v.status === "production") && (
                            <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={deployBusy} onClick={() => onPromote(v.id, "archived")}>
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
            <QualityGatesPanel session={session} />
          </section>
        )}

        {tab === "deployments" && (
          <section className="mt-4">
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-muted">
                Versión
                <select className="input min-w-44" value={deployVersionId} onChange={(e) => setDeployVersionId(e.target.value)}>
                  {versions.length === 0 && <option value="">Sin versiones</option>}
                  {versions.map((v) => (
                    <option key={v.id} value={v.id} disabled={v.status === "draft" || v.status === "archived"}>
                      v{v.version_number} · {v.status}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                Entorno
                <select className="input min-w-44" value={deployEnvId} onChange={(e) => setDeployEnvId(e.target.value)}>
                  {environments.length === 0 && <option value="">Sin entornos</option>}
                  {environments.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="btn btn-primary min-h-10" disabled={deployBusy || !id} onClick={onGoLive}>
                Go live (production)
              </button>
              <button type="button" className="btn btn-primary min-h-10" disabled={deployBusy || !deployVersionId || !deployEnvId || !id} onClick={onDeploy}>
                {deployBusy ? <Spinner size={14} /> : <PaperPlaneRight size={15} aria-hidden />}
                Desplegar
              </button>
            </div>
            {deployMsg && <SuccessInline message={deployMsg} />}
            {deployError && <ErrorInline message={deployError} />}
            {deployments.length === 0 ? (
              <EmptyState icon={ChartLineUp} title="Sin deployments" body="Despliega una versión ready a un entorno." />
            ) : (
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Deployment</th>
                      <th>Entorno</th>
                      <th>Estado</th>
                      <th>Endpoint</th>
                      <th>Desplegado</th>
                      <th>Historial</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deployments.map((d) => (
                      <tr key={d.id}>
                        <td className="font-mono text-xs">{d.slug}</td>
                        <td>
                          <EnvironmentBadge name={environments.find((e) => e.id === d.environment_id)?.name || d.environment_id} />
                        </td>
                        <td>
                          <StatusBadge status={d.status} />
                        </td>
                        <td className="font-mono text-xs text-muted">{d.endpoint || "—"}</td>
                        <td className="text-sm text-muted">{d.deployed_at ? new Date(d.deployed_at).toLocaleString("es-PE") : "—"}</td>
                        <td>
                          <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => onLoadEvents(d.id)}>
                            {eventsFor?.deploymentId === d.id ? "Ocultar" : "Eventos"}
                          </button>
                        </td>
                        <td>
                          {(d.status === "healthy" || d.status === "degraded") && (
                            <button type="button" className="btn btn-ghost min-h-8 text-xs" disabled={deployBusy} onClick={() => onRollback(d.id)}>
                              Rollback
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {tab === "embed" && (
          <section className="mt-4 grid gap-4">
            {isNew ? (
              <EmptyState icon={Robot} title="Guarda el agente primero" body="El widget requiere un token de embed." />
            ) : (
              <>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-text">Orígenes permitidos</span>
                  <input
                    className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
                    value={embedOrigins}
                    onChange={(e) => setEmbedOrigins(e.target.value)}
                    placeholder="https://farmacia.cl, https://www.farmacia.cl"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn btn-primary min-h-11" disabled={embedBusy} onClick={onCreateEmbed}>
                    {embedBusy ? <Spinner size={14} /> : "Crear token"}
                  </button>
                  <button type="button" className="btn btn-secondary min-h-11" disabled={embedBusy} onClick={onRevokeEmbed}>
                    Revocar
                  </button>
                </div>
                {embedToken && <p className="break-all rounded-md border border-border bg-soft p-3 font-mono text-xs">{embedToken}</p>}
                {embedScript && (
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-text">Snippet</span>
                    <textarea readOnly className="min-h-20 w-full rounded-md border border-border bg-soft p-3 font-mono text-xs" value={embedScript} />
                  </label>
                )}
              </>
            )}
          </section>
        )}
      </div>
    </details>
  );
}
