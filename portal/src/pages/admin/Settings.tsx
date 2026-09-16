import { Cards, GearSix } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import {
  Badge,
  ButtonLink,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
  type Tone,
} from "../../components/ui";

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

function Flag({ enabled, on, off }: { enabled: boolean; on: string; off: string }) {
  const tone: Tone = enabled ? "ok" : "neutral";
  return <Badge tone={tone}>{enabled ? on : off}</Badge>;
}

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

  const envTone: Tone =
    settings?.environment === "production"
      ? "ok"
      : settings?.environment === "staging"
        ? "warn"
        : "neutral";

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Settings"
        subtitle="Configuración de la plataforma (solo lecturas; sin secrets)."
        actions={
          <ButtonLink
            variant="secondary"
            to="/control-center/settings/plans"
            leadingIcon={Cards}
          >
            Planes y entitlements
          </ButtonLink>
        }
      />
      {error && <ErrorInline message={error} />}
      {!settings ? (
        <Skeleton className="h-[320px] rounded-lg" />
      ) : (
        <>
          <MetricGrid cols={3}>
            <Metric
              size="md"
              label="Entorno"
              value={settings.environment}
              tone={settings.environment === "production" ? "ok" : "warn"}
              hint="instancia activa"
              icon={GearSix}
            />
            <Metric
              size="md"
              label="TTL sesión portal"
              value={`${settings.portal_session_ttl_hours} h`}
              hint="expiración de sesión"
            />
            <Metric
              size="md"
              label="Rate limit global"
              value={settings.rate_limit_per_minute}
              hint="requests por minuto"
            />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title="Runtime"
              description="Modelos y features habilitadas en esta instancia."
            />
            <dl className="divide-y divide-border-soft">
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Entorno</dt>
                <dd>
                  <Badge tone={envTone}>{settings.environment}</Badge>
                </dd>
              </div>
              {(
                [
                  ["SQL Expert", settings.sql_expert_enabled],
                  ["MCP Server", settings.mcp_enabled],
                  ["Lazy ingestion", settings.lazy_ingestion_enabled],
                  ["Admin console", settings.admin_enabled],
                ] as [string, boolean][]
              ).map(([label, enabled]) => (
                <div
                  key={label}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5"
                >
                  <dt className="text-[13px] text-muted">{label}</dt>
                  <dd>
                    <Flag enabled={enabled} on="habilitado" off="deshabilitado" />
                  </dd>
                </div>
              ))}
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Seed demo</dt>
                <dd>
                  <Badge tone={settings.seed_demo_data ? "warn" : "neutral"}>
                    {settings.seed_demo_data ? "activo" : "inactivo"}
                  </Badge>
                </dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Embedding model</dt>
                <dd className="mono text-xs text-text">{settings.embedding_model}</dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Modelo por defecto</dt>
                <dd className="mono text-xs text-text">{settings.default_model}</dd>
              </div>
            </dl>
          </Panel>
        </>
      )}
    </div>
  );
}
