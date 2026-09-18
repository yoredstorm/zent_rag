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
  knowledge_v2_enabled?: boolean;
  knowledge_tabular_sql_first?: boolean;
  embedding_model: string;
  embedding_provider: string;
  embedding_provider_label: string;
  embedding_served_model: string;
  embedding_dimension: number;
  embedding_hosted: boolean;
  embedding_base_url_host: string | null;
  default_model: string;
  llm_provider_label: string;
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
              title="Motor de embeddings"
              description="Proveedor que vectoriza documentos y tablas. Cambiarlo requiere reindexar las fuentes."
            />
            <div className="flex flex-wrap items-center gap-2 border-b border-border-soft px-4 py-3">
              <Badge tone={settings.embedding_hosted ? "ok" : "warn"}>
                {settings.embedding_provider_label}
              </Badge>
              <Badge tone="neutral">
                {settings.embedding_hosted ? "remoto" : "local"}
              </Badge>
              <span className="text-[12px] text-muted">
                dimensión {settings.embedding_dimension} · endpoint{" "}
                {settings.embedding_base_url_host ?? "local"}
              </span>
            </div>
            <dl className="divide-y divide-border-soft">
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Modelo configurado</dt>
                <dd className="mono text-xs text-text">{settings.embedding_model}</dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Modelo servido</dt>
                <dd className="mono text-xs text-text">
                  {settings.embedding_served_model}
                </dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Dimensión vectorial</dt>
                <dd className="mono text-xs text-text">
                  {settings.embedding_dimension}
                </dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Endpoint</dt>
                <dd className="mono text-xs text-text">
                  {settings.embedding_base_url_host ?? "—"}
                </dd>
              </div>
            </dl>
            <p className="px-4 py-3 text-[12px] text-muted">
              Para volver a embeddings locales (Ollama) descomenta el servicio en
              docker-compose y define <code className="mono">RAG_EMBEDDING_MODEL=ollama/bge-m3</code>.
              Los vectores existentes siguen siendo válidos si la dimensión no cambia.
            </p>
          </Panel>

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
                  [
                    "Knowledge V2",
                    settings.knowledge_v2_enabled ?? false,
                  ],
                  [
                    "Tabular SQL-first",
                    settings.knowledge_tabular_sql_first ?? false,
                  ],
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
                <dt className="text-[13px] text-muted">Modelo por defecto</dt>
                <dd className="mono text-xs text-text">
                  {settings.default_model}{" "}
                  <span className="text-muted">({settings.llm_provider_label})</span>
                </dd>
              </div>
            </dl>
          </Panel>
        </>
      )}
    </div>
  );
}
