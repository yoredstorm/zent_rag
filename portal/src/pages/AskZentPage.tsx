import { useSearchParams } from "react-router-dom";
import { Breadcrumb } from "../components/Breadcrumb";
import { AskZent } from "../components/workflowStudio/AskZent";

export default function AskZentPage() {
  const [params] = useSearchParams();
  const agentId = params.get("agent") || "";
  const agentName = params.get("agent_name") || "";
  return (
    <div className="space-y-4">
      <Breadcrumb
        items={[
          { label: "Workflows", to: "/workflows" },
          { label: "Nuevo workflow", to: "/workflows/new" },
          { label: "Crear con IA" },
        ]}
      />
      <AskZent
        initialPrompt={params.get("q") || ""}
        agentId={agentId}
        agentName={agentName}
      />
    </div>
  );
}
