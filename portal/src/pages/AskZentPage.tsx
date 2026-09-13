import { Breadcrumb } from "../components/Breadcrumb";
import { AskZent } from "../components/workflowStudio/AskZent";

export default function AskZentPage() {
  return (
    <div className="space-y-4">
      <Breadcrumb
        items={[
          { label: "Workflows", to: "/workflows" },
          { label: "Nuevo workflow", to: "/workflows/new" },
          { label: "Crear con IA" },
        ]}
      />
      <AskZent />
    </div>
  );
}
