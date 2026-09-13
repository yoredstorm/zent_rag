import { lazy } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";

const AgentStudioPage = lazy(() => import("./AgentStudio"));

function mapBuilderQuery(tab: string | null): string {
  const next = new URLSearchParams();
  if (tab === "playground") next.set("panel", "test");
  else if (tab && tab !== "instructions" && tab !== "knowledge") {
    next.set("panel", "advanced");
    next.set("tab", tab);
  }
  const query = next.toString();
  return query ? `?${query}` : "";
}

export function AgentBuilderRedirect() {
  const { id } = useParams<{ id: string }>();
  const [sp] = useSearchParams();
  return <Navigate to={`/agents/${id}${mapBuilderQuery(sp.get("tab"))}`} replace />;
}

export default function AgentEntry() {
  return <AgentStudioPage />;
}
