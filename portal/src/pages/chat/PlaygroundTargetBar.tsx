import { Link } from "react-router-dom";
import type {
  PlaygroundAgent,
  PlaygroundTarget,
  PlaygroundTargetKind,
  PlaygroundWorkflow,
} from "./playgroundTargets";

const SELECT_CLASS =
  "w-auto min-w-[10rem] cursor-pointer rounded-md border border-border bg-soft px-3 py-2 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent";

export function PlaygroundTargetBar({
  target,
  agents,
  workflows,
  loading,
  role,
  onRole,
  onChange,
}: {
  target: PlaygroundTarget;
  agents: PlaygroundAgent[];
  workflows: PlaygroundWorkflow[];
  loading: boolean;
  role: "admin" | "customer";
  onRole: (role: "admin" | "customer") => void;
  onChange: (next: PlaygroundTarget) => void;
}) {
  const agent = agents.find((a) => a.id === target.id);
  const editTo =
    target.kind === "agent" && target.id
      ? `/agents/${target.id}`
      : target.kind === "workflow" && target.id
        ? `/workflows/${target.id}`
        : "";

  function setKind(kind: PlaygroundTargetKind) {
    if (kind === "knowledge") {
      onChange({ kind: "knowledge", id: "" });
      return;
    }
    if (kind === "agent") {
      onChange({ kind: "agent", id: agents.find((a) => a.is_active)?.id || agents[0]?.id || "" });
      return;
    }
    onChange({ kind: "workflow", id: workflows[0]?.id || "" });
  }

  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="playground-target-bar">
      <label className="block text-xs text-muted">
        Probar
        <select
          className={`${SELECT_CLASS} mt-1 block`}
          value={target.kind}
          disabled={loading}
          aria-label="Qué probar"
          onChange={(e) => setKind(e.target.value as PlaygroundTargetKind)}
        >
          <option value="agent">Agente</option>
          <option value="workflow">Flujo</option>
          <option value="knowledge">Conocimiento</option>
        </select>
      </label>

      {target.kind === "agent" && (
        <label className="block text-xs text-muted">
          Agente
          <select
            className={`${SELECT_CLASS} mt-1 block min-w-[14rem]`}
            value={target.id}
            disabled={loading || agents.length === 0}
            aria-label="Agente a probar"
            onChange={(e) => onChange({ kind: "agent", id: e.target.value })}
          >
            {agents.length === 0 && <option value="">No hay agentes</option>}
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.is_active ? "" : " (inactivo)"}
              </option>
            ))}
          </select>
        </label>
      )}

      {target.kind === "workflow" && (
        <label className="block text-xs text-muted">
          Flujo
          <select
            className={`${SELECT_CLASS} mt-1 block min-w-[14rem]`}
            value={target.id}
            disabled={loading || workflows.length === 0}
            aria-label="Flujo a probar"
            onChange={(e) => onChange({ kind: "workflow", id: e.target.value })}
          >
            {workflows.length === 0 && <option value="">No hay flujos</option>}
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {target.kind === "knowledge" && (
        <label className="block text-xs text-muted">
          Vista
          <select
            id="role"
            className={`${SELECT_CLASS} mt-1 block`}
            value={role}
            aria-label="Vista"
            title={
              role === "admin"
                ? "Vista equipo: acceso a métricas y datos internos"
                : "Vista cliente: catálogo y productos"
            }
            onChange={(e) => onRole(e.target.value as "admin" | "customer")}
          >
            <option value="admin">Equipo</option>
            <option value="customer">Cliente</option>
          </select>
        </label>
      )}

      {target.kind === "workflow" && target.id && (
        <span className="badge badge-muted mb-1">Simulación</span>
      )}
      {target.kind === "agent" && agent && (
        <span className={`badge mb-1 ${agent.is_active ? "badge-ok" : "badge-pending"}`}>
          {agent.is_active ? "Activo" : "Inactivo"}
        </span>
      )}

      {editTo && (
        <Link to={editTo} className="btn btn-ghost mb-0.5 min-h-9 px-3 text-xs">
          {target.kind === "workflow" ? "Abrir flujo" : "Editar"}
        </Link>
      )}

      {target.kind === "agent" && agents.length === 0 && !loading && (
        <Link to="/agents/new" className="btn btn-primary mb-0.5 min-h-9 px-3 text-xs">
          Crear agente
        </Link>
      )}
      {target.kind === "workflow" && workflows.length === 0 && !loading && (
        <Link to="/workflows/new" className="btn btn-primary mb-0.5 min-h-9 px-3 text-xs">
          Crear flujo
        </Link>
      )}
    </div>
  );
}
