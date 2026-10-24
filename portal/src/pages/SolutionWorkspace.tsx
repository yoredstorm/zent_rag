import {
  ArrowRight,
  ChatCircleDots,
  CheckCircle,
  Gear,
  Lightning,
  Sparkle,
  Warning,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";
import { ModeSwitch } from "../components/solution/ModeSwitch";
import { WorkflowPatchPanel } from "../components/workflowStudio/WorkflowPatchPanel";
import type { ParameterLevel } from "../lib/businessSchema";

type Blocker = { code: string; message: string; mitigation?: string; action?: string };
type Solution = {
  record_id: string;
  solution_id: string;
  name: string;
  description?: string;
  version?: string;
  status?: string;
  roles?: { role_ref: string; version?: string; required?: boolean }[];
  agents?: { agent_ref: string; role_ref?: string; name?: string }[];
  workflows?: { workflow_ref: string; name?: string; trigger?: { type?: string } }[];
  expected_outcomes?: { name: string; metric?: string; target?: string; window?: string }[];
  requirements?: string[];
};
type Materialization = {
  solution_id?: string;
  status?: string;
  artifacts?: {
    workflow?: { id: string; created?: boolean };
    agent?: { id: string; created?: boolean };
    role?: { id: string; created?: boolean };
  };
  blockers?: Blocker[];
};
type Workflow = { id: string; name?: string; status?: string; workflow_version?: number };
type Gate = {
  allowed: boolean;
  state: string;
  action?: string;
  graph_hash?: string;
  semantic_plan_hash?: string;
  capability_snapshot_hash?: string;
  required_level?: string;
  blockers?: Blocker[];
  message?: string;
};

export type SolutionWorkspaceData = {
  solution: Solution;
  materialization: Materialization | null;
  workflow: Workflow | null;
  gate: Gate | null;
};

type Auth = { token?: string; organizationId?: string };
type Tab = "resumen" | "proceso" | "configuracion" | "conversacion";

const TABS: { id: Tab; label: string }[] = [
  { id: "resumen", label: "Resumen" },
  { id: "proceso", label: "Proceso" },
  { id: "configuracion", label: "Configuración" },
  { id: "conversacion", label: "Conversación" },
];

export async function loadSolutionWorkspace(
  solutionId: string,
  auth: Auth,
): Promise<SolutionWorkspaceData> {
  const solution = await api<{ solution: Solution }>(
    `/api/v1/studio/solutions/${solutionId}`,
    auth,
  );
  let materialization: Materialization | null = null;
  try {
    materialization = await api<Materialization>(
      `/api/v1/studio/solutions/${solutionId}/materialization`,
      auth,
    );
  } catch {
    // Sin materialización: el workspace muestra el primer paso.
  }
  const workflowId = materialization?.artifacts?.workflow?.id;
  let workflow: Workflow | null = null;
  let gate: Gate | null = null;
  if (workflowId) {
    try {
      workflow = await api<Workflow>(`/api/v1/workflows/${workflowId}`, auth);
      gate = await api<Gate>(
        `/api/v1/workflows/${workflowId}/release-gate?action=publish`,
        auth,
      );
    } catch {
      workflow = null;
      gate = null;
    }
  }
  return { solution: solution.solution, materialization, workflow, gate };
}

function StatusBar({
  data,
  mode,
  busy,
}: {
  data: SolutionWorkspaceData;
  mode: ParameterLevel;
  busy: boolean;
}) {
  const gateLabel = data.gate?.allowed ? "Publicación permitida" : "Publicación bloqueada";
  return (
    <div
      className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface/95 px-3 py-2 text-xs backdrop-blur"
      role="status"
      aria-live="polite"
      data-testid="solution-status-bar"
      data-mode={mode}
    >
      <span className="font-medium text-text">{data.solution.name}</span>
      <span className="badge">{data.solution.status ?? "draft"}</span>
      <span className="badge">{data.workflow?.status ?? "sin proceso"}</span>
      <span className={data.gate?.allowed ? "text-ok" : "text-warn"} data-testid="solution-gate-state">
        {gateLabel}
      </span>
      {data.gate?.blockers && data.gate.blockers.length > 0 && (
        <span className="text-faint">{data.gate.blockers.length} bloqueo(s)</span>
      )}
      {busy && <span className="text-faint">actualizando…</span>}
      <span className="ml-auto text-faint">v{data.solution.version ?? "—"}</span>
    </div>
  );
}

export function SolutionWorkspaceView({
  data,
  mode,
  onMode,
  onPublish,
  publishing = false,
  onRefresh,
}: {
  data: SolutionWorkspaceData;
  mode: ParameterLevel;
  onMode: (mode: ParameterLevel) => void;
  onPublish: () => void;
  publishing?: boolean;
  onRefresh?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("resumen");
  const [copilot, setCopilot] = useState(false);
  const blocks = data.gate?.blockers ?? data.materialization?.blockers ?? [];
  const workflow = data.workflow;
  const simple = mode === "simple";
  const advanced = mode === "advanced";
  const ready = data.materialization?.status === "READY";

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6" data-testid="solution-workspace">
      <PageHeader
        title={data.solution.name}
        subtitle={data.solution.description || "Una solución con conversación, proceso y configuración en un solo lugar."}
        actions={<ModeSwitch value={mode} onChange={onMode} />}
      />
      <StatusBar data={data} mode={mode} busy={publishing} />

      {!data.materialization && (
        <section
          className="rounded-lg border border-accent/40 bg-accent-soft/40 p-4"
          data-testid="solution-first-experience"
        >
          <p className="flex items-center gap-2 text-sm font-medium">
            <Sparkle size={16} aria-hidden /> Primer paso: materializa esta solución
          </p>
          <p className="mt-1 text-sm text-muted">
            Aún no hay proceso ni agentes vinculados. Revisa los recursos y confirma la
            creación como borrador; nada se publica solo.
          </p>
          <Link
            to="/solutions/new"
            className="mt-2 inline-flex items-center gap-1 text-sm text-accent"
            data-testid="solution-first-action"
          >
            Revisar y materializar <ArrowRight size={14} />
          </Link>
        </section>
      )}

      <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Vistas de la solución">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className="min-h-9 px-4 text-sm text-muted aria-selected:border-b-2 aria-selected:border-accent aria-selected:text-text"
            data-testid={`solution-tab-${item.id}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "resumen" && (
        <div className="grid gap-3 md:grid-cols-3" data-testid="solution-tab-panel-resumen">
          <section className="panel p-4 md:col-span-2">
            <h3 className="text-sm font-medium">Resultado esperado</h3>
            <p className="mt-1 text-sm text-muted">
              {data.solution.status === "active" ? "La solución está activa." : "La solución es un borrador revisable."}
            </p>
            <ul className="mt-3 space-y-1 text-sm text-muted">
              {(data.solution.expected_outcomes ?? []).map((outcome) => (
                <li key={outcome.name}>· {outcome.name} {outcome.target ? `(${outcome.target})` : ""}</li>
              ))}
              {(data.solution.expected_outcomes ?? []).length === 0 && (
                <li>Define un resultado medible antes de publicar.</li>
              )}
            </ul>
            {!simple && (
              <div className="mt-4 space-y-2 text-xs text-muted">
                <p>Rol: {data.solution.roles?.[0]?.role_ref ?? "sin rol"}</p>
                <p>Agente: {data.solution.agents?.[0]?.name ?? "sin agente"}</p>
                <p>Proceso: {workflow?.name ?? data.solution.workflows?.[0]?.name ?? "sin proceso"}</p>
              </div>
            )}
          </section>
          <section className="panel p-4" data-testid="solution-readiness">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              {ready ? <CheckCircle size={16} className="text-ok" /> : <Warning size={16} className="text-warn" />}
              Preparación
            </h3>
            <p className="mt-1 text-sm text-muted">
              {ready ? "Recursos materializados como borrador." : data.materialization ? "Faltan dependencias." : "Sin materializar."}
            </p>
            {blocks.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-warn" data-testid="solution-blockers">
                {blocks.slice(0, advanced ? 20 : 4).map((item) => (
                  <li key={`${item.code}-${item.message}`}>{item.message}</li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      {tab === "proceso" && (
        <div className="space-y-3" data-testid="solution-tab-panel-proceso">
          {!workflow && <p className="text-sm text-muted">Todavía no hay proceso materializado.</p>}
          {workflow && (
            <section className="panel flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{workflow.name ?? "Proceso"}</p>
                <p className="text-xs text-muted">Estado: {workflow.status ?? "draft"}</p>
              </div>
              <Link to={`/workflows/${workflow.id}`} className="inline-flex items-center gap-1 text-sm text-accent" data-testid="solution-open-process">
                Abrir proceso <ArrowRight size={14} />
              </Link>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setCopilot((value) => !value)}
                data-testid="solution-toggle-copilot"
              >
                <Sparkle size={14} aria-hidden /> Editar con IA
              </button>
            </section>
          )}
          {copilot && workflow && (
            <section className="panel p-4" data-testid="solution-copilot">
              <WorkflowPatchPanel
                workflowId={workflow.id}
                onClose={() => setCopilot(false)}
                onApplied={() => {
                  setCopilot(false);
                  onRefresh?.();
                }}
              />
            </section>
          )}
          <section className="panel p-4" data-testid="solution-release">
            <h3 className="text-sm font-medium">Publicación</h3>
            <p className="mt-1 text-sm text-muted">
              Solo se habilita cuando la política P01 devuelve ALLOW. Un test verde no publica solo.
            </p>
            {!advanced && <p className="mt-1 text-xs text-faint">Cambia a Avanzado para ver hashes y nivel requerido.</p>}
            {advanced && data.gate && (
              <div className="mt-2 space-y-1 break-all font-mono text-[10px] text-faint">
                <p>gate: {data.gate.state} · required: {data.gate.required_level ?? "—"}</p>
                <p>graph: {data.gate.graph_hash ?? "—"}</p>
                <p>plan: {data.gate.semantic_plan_hash ?? "—"}</p>
                <p>snapshot: {data.gate.capability_snapshot_hash ?? "—"}</p>
              </div>
            )}
            <button
              type="button"
              className="btn btn-primary btn-sm mt-3"
              disabled={!workflow || !data.gate?.allowed || publishing}
              onClick={onPublish}
              data-testid="solution-publish"
              title={
                data.gate?.allowed
                  ? "Publicar según la política de release"
                  : data.gate?.blockers?.[0]?.message ?? "Publicación bloqueada"
              }
            >
              <Lightning size={14} aria-hidden /> {publishing ? "Publicando…" : "Publicar"}
            </button>
            {!data.gate?.allowed && data.gate?.blockers?.[0] && (
              <p className="mt-2 text-xs text-warn" data-testid="solution-publish-blocked">
                {data.gate.blockers[0].message}
              </p>
            )}
          </section>
        </div>
      )}

      {tab === "configuracion" && (
        <div className="grid gap-3 md:grid-cols-2" data-testid="solution-tab-panel-configuracion">
          <section className="panel p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium"><Gear size={15} /> Roles y agentes</h3>
            <ul className="mt-2 space-y-1 text-sm text-muted">
              {(data.solution.roles ?? []).map((role) => (
                <li key={role.role_ref}>Rol: {role.role_ref} {role.version ? `v${role.version}` : ""}</li>
              ))}
              {(data.solution.agents ?? []).map((agent) => (
                <li key={agent.agent_ref}>Agente: {agent.name ?? agent.agent_ref}</li>
              ))}
            </ul>
            <Link to="/roles" className="mt-3 inline-flex text-sm text-accent">Abrir Role Studio</Link>
          </section>
          <section className="panel p-4">
            <h3 className="text-sm font-medium">Requisitos</h3>
            <ul className="mt-2 space-y-1 text-sm text-muted">
              {(data.solution.requirements ?? []).map((item) => <li key={item}>· {item}</li>)}
              {(data.solution.requirements ?? []).length === 0 && <li>Sin requisitos adicionales.</li>}
            </ul>
          </section>
        </div>
      )}

      {tab === "conversacion" && (
        <section className="panel p-4" data-testid="solution-tab-panel-conversacion">
          <h3 className="flex items-center gap-2 text-sm font-medium"><ChatCircleDots size={15} /> Conversación y prueba</h3>
          <p className="mt-1 text-sm text-muted">
            La conversación reutiliza el proceso y el agente de esta solución. Las pruebas viven en el
            Workflow Test Studio y no publican por sí solas.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {workflow && (
              <Link to={`/chat?target=workflow&id=${workflow.id}`} className="btn btn-secondary btn-sm">
                Abrir conversación
              </Link>
            )}
            {workflow && (
              <Link to={`/workflows/${workflow.id}`} className="btn btn-secondary btn-sm">
                Probar proceso
              </Link>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

export default function SolutionWorkspacePage() {
  const { solutionId } = useParams();
  const { session } = useAuth();
  const [data, setData] = useState<SolutionWorkspaceData | null>(null);
  const [mode, setMode] = useState<ParameterLevel>("guided");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const load = useCallback(async () => {
    if (!session || !solutionId) return;
    setBusy(true);
    setError("");
    try {
      setData(await loadSolutionWorkspace(solutionId, { token: session.token, organizationId: session.organizationId }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la solución.");
    } finally {
      setBusy(false);
    }
  }, [session, solutionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function publish() {
    if (!session || !data?.workflow || !data.gate?.allowed) return;
    if (!window.confirm("Publicar esta solución según la política de release?")) return;
    setPublishing(true);
    setError("");
    try {
      await api(`/api/v1/workflows/${data.workflow.id}/publish`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({}),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "La publicación fue bloqueada.");
    } finally {
      setPublishing(false);
    }
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-6xl space-y-3 p-4 sm:p-6">
        <PageHeader title="Solution Workspace" subtitle="Un solo lugar para conversación, proceso y configuración." />
        {error && <ErrorInline message={error} />}
        {busy && <SkeletonBlock className="h-48" />}
      </div>
    );
  }

  return (
    <>
      {error && <div className="mx-auto max-w-6xl px-4 pt-4"><ErrorInline message={error} /></div>}
      <SolutionWorkspaceView
        data={data}
        mode={mode}
        onMode={setMode}
        onPublish={() => void publish()}
        publishing={publishing}
        onRefresh={() => void load()}
      />
    </>
  );
}
