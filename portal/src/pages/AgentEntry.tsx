import { lazy } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";

const AgentStudioPage = lazy(() => import("./AgentStudio"));

/** Pestañas viejas de publicación: viven en la etapa Publicar. */
const PUBLISH_TABS = new Set(["publish", "readiness", "evaluation", "versions", "deployments", "embed"]);

/**
 * `/agents/:id/builder?tab=…` fue la URL del builder antiguo. Se traduce a la
 * etapa o al grupo correspondiente para que ningún enlace guardado se rompa.
 */
export function AgentBuilderRedirect() {
  const { id } = useParams<{ id: string }>();
  const [sp] = useSearchParams();
  const tab = sp.get("tab");
  const next = new URLSearchParams();
  if (tab === "playground") {
    next.set("panel", "test");
  } else if (tab && PUBLISH_TABS.has(tab)) {
    next.set("panel", "publish");
    if (tab !== "publish") next.set("tab", tab);
  } else if (tab && tab !== "instructions" && tab !== "knowledge") {
    next.set("panel", "advanced");
    next.set("tab", tab);
  }
  const query = next.toString();
  return <Navigate to={`/agents/${id}${query ? `?${query}` : ""}`} replace />;
}

export default function AgentEntry() {
  return <AgentStudioPage />;
}
