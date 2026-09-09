import { Link } from "react-router-dom";
import { useAuth } from "../auth";

export function DemoBanner() {
  const { session } = useAuth();
  if (session?.workspaceKind !== "demo") return null;
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-accent-soft px-4 py-2 text-sm"
      data-testid="demo-banner"
    >
      <p className="text-text">Estás explorando Zent con datos de prueba.</p>
      <div className="flex gap-2">
        <span className="btn btn-secondary min-h-9 px-3 text-xs">Continuar demo</span>
        <Link to="/onboarding/transition" className="btn btn-primary min-h-9 px-3 text-xs">
          Empezar con mis datos
        </Link>
      </div>
    </div>
  );
}
