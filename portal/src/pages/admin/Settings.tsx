import { GearSix, Cards } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";

type Settings = {
  environment: string;
  sql_expert_enabled: boolean;
  mcp_enabled: boolean;
  lazy_ingestion_enabled: boolean;
  admin_enabled: boolean;
  seed_demo_data: boolean;
  embedding_model: string;
  default_model: string;
  portal_session_ttl_hours: number;
  rate_limit_per_minute: number;
};

export default function Settings() {
  const { session } = usePlatformAuth();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    platformApi<Settings>("/api/v1/platform/settings", { token: session.token })
      .then(setSettings)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, [session]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        subtitle="Configuración de la plataforma (solo lecturas; sin secrets)."
        actions={
          <Link className="btn btn-ghost min-h-10" to="/control-center/settings/plans">
            <Cards size={15} aria-hidden /> Planes y entitlements
          </Link>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {!settings ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="panel max-w-2xl">
          <dl className="divide-y divide-border">
            {(
              [
                ["Entorno", settings.environment],
                ["SQL Expert", settings.sql_expert_enabled ? "habilitado" : "deshabilitado"],
                ["MCP Server", settings.mcp_enabled ? "habilitado" : "deshabilitado"],
                ["Lazy ingestion", settings.lazy_ingestion_enabled ? "habilitado" : "deshabilitado"],
                ["Admin console", settings.admin_enabled ? "habilitado" : "deshabilitado"],
                ["Seed demo", settings.seed_demo_data ? "activo" : "inactivo"],
                ["Embedding model", settings.embedding_model],
                ["Modelo por defecto", settings.default_model],
                ["TTL sesión portal (h)", String(settings.portal_session_ttl_hours)],
                ["Rate limit global (req/min)", String(settings.rate_limit_per_minute)],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-4 py-2.5">
                <dt className="text-sm text-muted">{label}</dt>
                <dd className="flex items-center gap-2 font-mono text-xs text-text">
                  <GearSix size={14} className="text-faint" aria-hidden />
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}