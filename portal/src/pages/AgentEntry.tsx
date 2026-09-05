import { lazy } from "react";
import { Navigate, useParams, useSearchParams } from "react-router-dom";

const AgentOverviewPage = lazy(() => import("./AgentOverview"));

/**
 * /agents/:id muestra el resumen del agente (FASE 05).
 * Las URLs legacy con ?tab=… (builder plano) se redirigen al builder por etapas.
 */
export default function AgentEntry() {
  const { id } = useParams<{ id: string }>();
  const [sp] = useSearchParams();
  const tab = sp.get("tab");
  if (tab) {
    return <Navigate to={`/agents/${id}/builder?tab=${encodeURIComponent(tab)}`} replace />;
  }
  return <AgentOverviewPage />;
}