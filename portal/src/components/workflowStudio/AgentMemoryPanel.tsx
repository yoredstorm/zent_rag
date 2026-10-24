import { useEffect, useState } from "react";
import { api } from "../../api";
import { ErrorInline, SkeletonBlock } from "../ui";
import type { AgentOption } from "./types";

export type AgentMemoryItem = {
  memory_id: string;
  title: string;
  scope: string;
  confidence: number;
  memory_type: string;
  updated_at?: string | null;
};

export type AgentMemoryView = {
  agent_id: string;
  policy: string;
  included: number;
  omitted: number;
  inspected: number;
  items: AgentMemoryItem[];
  omitted_items?: { memory_id?: string; reason: string }[];
};

type Props = {
  agents: AgentOption[];
  /** Inyectable en tests; por defecto consulta el backend real. */
  loadContext?: (agentId: string) => Promise<AgentMemoryView>;
};

const DEFAULT_LOAD = (agentId: string) =>
  api<AgentMemoryView>(`/api/v1/memory/agents/${agentId}/context`);

/**
 * “Lo que el agente sabe”: memoria que la política del rol permite ver.
 * No edita ni activa memoria; solo explica inclusión y omisiones.
 */
export function AgentMemoryPanel({ agents, loadContext = DEFAULT_LOAD }: Props) {
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [data, setData] = useState<AgentMemoryView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void loadContext(agentId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "No se pudo cargar la memoria");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, loadContext]);

  if (agents.length === 0) {
    return (
      <div className="panel p-3 text-sm text-muted" data-testid="wf-agent-memory-empty">
        Este workflow no tiene agentes. Añade un nodo de IA con un agente para ver su memoria.
      </div>
    );
  }

  return (
    <div className="panel space-y-3 p-3" data-testid="wf-agent-memory">
      <label className="block text-xs text-muted">
        Agente
        <select
          className="mt-1 min-h-9 w-full rounded-md border border-border bg-bg px-2 text-sm"
          value={agentId}
          onChange={(event) => setAgentId(event.target.value)}
          data-testid="wf-agent-memory-select"
        >
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </label>

      {loading && <SkeletonBlock className="h-16" />}
      {error && <ErrorInline message={error} />}

      {data && !loading && (
        <>
          <div className="flex flex-wrap gap-2 text-xs" data-testid="wf-agent-memory-summary">
            <span className="badge">{data.policy}</span>
            <span>{data.included} incluidas</span>
            <span>{data.omitted} omitidas</span>
            <span>{data.inspected} revisadas</span>
          </div>
          <ul className="space-y-1.5" data-testid="wf-agent-memory-items">
            {data.items.map((item) => (
              <li
                key={item.memory_id}
                className="rounded-md border border-border bg-soft/40 p-2 text-sm"
                data-testid={`wf-agent-memory-item-${item.memory_id}`}
              >
                <p className="font-medium">{item.title}</p>
                <p className="text-xs text-muted">
                  {item.scope} · {item.memory_type} · confianza {item.confidence}
                </p>
              </li>
            ))}
            {data.items.length === 0 && (
              <li className="text-sm text-muted" data-testid="wf-agent-memory-none">
                La política del rol no autoriza memoria para este agente.
              </li>
            )}
          </ul>
          {(data.omitted_items ?? []).length > 0 && (
            <details className="text-xs text-muted" data-testid="wf-agent-memory-omitted">
              <summary>Por qué se omitió otra memoria</summary>
              <ul className="mt-1 space-y-0.5">
                {(data.omitted_items ?? []).slice(0, 8).map((item, index) => (
                  <li key={`${item.memory_id ?? "omitted"}-${index}`}>{item.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
