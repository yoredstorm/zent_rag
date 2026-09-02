import { ArrowClockwise, Robot, Star } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ErrorInline, SkeletonBlock } from "../components/ui";
import { api } from "../api";

type SharedAgent = {
  name: string;
  description: string | null;
  system_prompt: string;
  tools: string[];
  model: string;
  config: Record<string, unknown>;
};

export default function SharedAgentPage() {
  const { token } = useParams<{ token: string }>();
  const [agent, setAgent] = useState<SharedAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    api<SharedAgent>(`/api/v1/share/agents/${token}`, {})
      .then(setAgent)
      .catch((e) => setError(e instanceof Error ? e.message : "Link inválido"))
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) return <SkeletonBlock className="mx-auto mt-16 h-40 max-w-2xl" />;
  if (error) {
    return (
      <div className="mx-auto mt-16 max-w-md p-6">
        <ErrorInline>{error}</ErrorInline>
      </div>
    );
  }
  if (!agent) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <div className="panel flex flex-col gap-3 p-6">
        <div className="flex items-center gap-3">
          <Robot size={28} className="text-accent" aria-hidden />
          <div>
            <h1 className="text-lg font-semibold text-text">{agent.name}</h1>
            <p className="text-sm text-muted">{agent.description || "Agente compartido"}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="badge badge-ok">{agent.model || "modelo default"}</span>
          {agent.tools.map((t) => (
            <span key={t} className="badge badge-muted">
              {t}
            </span>
          ))}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-faint">System prompt</p>
          <pre className="whitespace-pre-wrap rounded-md bg-soft p-3 text-xs leading-relaxed text-text">
            {agent.system_prompt}
          </pre>
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-faint">Configuración</p>
          <pre className="whitespace-pre-wrap rounded-md bg-soft p-3 text-[11px] text-faint">
            {JSON.stringify(agent.config, null, 2)}
          </pre>
        </div>
        <p className="flex items-center gap-1 text-xs text-faint">
          <Star size={12} aria-hidden /> Compartido vía Zent RAG
        </p>
      </div>
      <p className="text-center text-xs text-faint">
        <ArrowClockwise size={11} className="mr-1 inline" aria-hidden />
        El agente puede clonarse en tu organización desde el portal.
      </p>
    </div>
  );
}