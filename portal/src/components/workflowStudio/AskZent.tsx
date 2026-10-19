/**
 * AskZent — selector del camino de creación con IA.
 *
 * Camino canónico: Workflow Architect (semántico). Legacy: Copilot V2, solo
 * como rollback del flag `RAG_WORKFLOW_ARCHITECT_ENABLED`.
 */
import { useEffect, useState } from "react";
import { useAuth } from "../../auth";
import { Panel, Skeleton } from "../ui";
import { ArchitectAskZent } from "./ArchitectAskZent";
import { AskZentLegacy } from "./AskZentLegacy";
import { fetchArchitectConfig } from "./workflowArchitect";

type Props = {
  initialPrompt?: string;
  agentId?: string;
  agentName?: string;
};

type Mode = "loading" | "architect" | "legacy";

export function AskZent(props: Props) {
  const { session } = useAuth();
  const [mode, setMode] = useState<Mode>("loading");
  const token = session?.token;
  const organizationId = session?.organizationId;

  useEffect(() => {
    let cancelled = false;
    if (!token || !organizationId) {
      setMode("legacy");
      return;
    }
    void fetchArchitectConfig({ token, organizationId, companyName: "" }).then((config) => {
      if (cancelled) return;
      setMode(config?.enabled === true ? "architect" : "legacy");
    });
    return () => {
      cancelled = true;
    };
  }, [token, organizationId]);

  if (mode === "loading") {
    return (
      <Panel className="space-y-3 p-5" data-testid="ask-loading">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-3 w-full max-w-xl" />
        <Skeleton className="h-28 w-full rounded-md" />
        <span className="sr-only">Preparando el diseñador de automatizaciones</span>
      </Panel>
    );
  }
  if (mode === "architect") {
    return <ArchitectAskZent {...props} />;
  }
  return <AskZentLegacy {...props} />;
}
