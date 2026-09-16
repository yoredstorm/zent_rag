import { ArrowClockwise, Robot, Star, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import {
  Badge,
  CodeBlock,
  EmptyState,
  Panel,
  SkeletonBlock,
} from "../components/ui";

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
      <div className="mx-auto mt-16 max-w-2xl p-6">
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos abrir este agente"
            body={error}
            hint="El link puede haber expirado o el agente ya no está compartido."
          />
        </Panel>
      </div>
    );
  }

  if (!agent) return null;

  const hasConfig = Object.keys(agent.config ?? {}).length > 0;

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <Panel className="flex flex-col gap-4 p-6">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-accent-line bg-accent-soft text-accent">
            <Robot size={22} aria-hidden />
          </span>
          <div className="min-w-0">
            <h1 className="text-h1">{agent.name}</h1>
            <p className="mt-0.5 text-[13px] text-muted">
              {agent.description || "Agente compartido"}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <Badge tone="accent">{agent.model || "modelo default"}</Badge>
          {agent.tools.map((t) => (
            <Badge key={t} tone="neutral">
              {t}
            </Badge>
          ))}
        </div>

        <section>
          <p className="eyebrow mb-2">System prompt</p>
          <CodeBlock
            code={agent.system_prompt}
            language="text"
            filename="system_prompt"
            maxHeight={320}
          />
        </section>

        {hasConfig && (
          <section>
            <p className="eyebrow mb-2">Configuración</p>
            <CodeBlock
              code={JSON.stringify(agent.config, null, 2)}
              language="json"
              filename="config.json"
              maxHeight={260}
            />
          </section>
        )}

        <p className="flex items-center gap-1.5 text-xs text-faint">
          <Star size={12} aria-hidden />
          Compartido vía Zent RAG
        </p>
      </Panel>
      <p className="text-center text-xs text-faint">
        <ArrowClockwise size={11} className="mr-1 inline" aria-hidden />
        El agente puede clonarse en tu organización desde el portal.
      </p>
    </div>
  );
}
