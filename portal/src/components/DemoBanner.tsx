import { Link } from "react-router-dom";
import { useAuth } from "../auth";

export function DemoBanner() {
  const { session } = useAuth();
  if (session?.workspaceKind !== "demo") return null;
  return (
    <div
      className="state-rail flex flex-wrap items-center justify-between gap-3 border-b border-border bg-accent-soft px-4 py-2"
      data-state="running"
      data-testid="demo-banner"
    >
      <p className="min-w-0 text-[13px] text-text">
        Estás explorando Zent con datos de prueba. Nada de lo que hagas acá afecta tu organización.
      </p>
      <Link to="/onboarding/transition" className="btn btn-primary btn-sm shrink-0">
        Empezar con mis datos
      </Link>
    </div>
  );
}
