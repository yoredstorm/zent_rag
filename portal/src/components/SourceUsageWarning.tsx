import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

export type SourceUsageAgent = {
  id: string;
  name: string;
  is_active: boolean;
  /** `source` = la eligió directo; `knowledge_base` = la usa por su colección. */
  via: "source" | "knowledge_base";
};

/** Agentes que usan la fuente (para avisar antes de eliminarla). */
export function useSourceUsage(sourceId: string | null | undefined) {
  const { session } = useAuth();
  const [agents, setAgents] = useState<SourceUsageAgent[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sourceId || !session) {
      setAgents([]);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    api<{ agents: SourceUsageAgent[] }>(`/api/v1/sources/${sourceId}/usage`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        if (alive) setAgents(data.agents || []);
      })
      .catch(() => {
        if (alive) setAgents([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sourceId, session]);

  return { agents, loading };
}

/** Lista de agentes afectados; se usa dentro del diálogo de eliminación. */
export function SourceUsageWarning({
  agents,
  loading = false,
}: {
  agents: SourceUsageAgent[];
  loading?: boolean;
}) {
  if (loading) {
    return <p className="mt-3 text-xs text-muted">Revisando qué agentes la usan…</p>;
  }
  if (agents.length === 0) return null;
  return (
    <div className="mt-3 rounded-md border border-warn/30 bg-warn-soft p-3 text-[13px] leading-relaxed text-text">
      <p className="font-medium">
        {agents.length === 1
          ? "Este agente dejará de usar la fuente:"
          : "Estos agentes dejarán de usar la fuente:"}
      </p>
      <ul className="mt-1.5 flex flex-col gap-0.5 pl-4">
        {agents.map((agent) => (
          <li key={agent.id} className="list-disc">
            {agent.name}
            {agent.is_active ? null : <span className="text-muted"> (inactivo)</span>}
            {agent.via === "knowledge_base" ? (
              <span className="text-muted"> · la usa por su colección</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
