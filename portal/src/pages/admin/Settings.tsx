import { Cards, GearSix } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { loadSession, platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { closeTenantSession, enterTenantSession } from "../../lib/impersonation";
import {
  Badge,
  Button,
  ButtonLink,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  SuccessInline,
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
  embedding_fallback_enabled?: boolean;
  embedding_fallback_provider_label?: string | null;
  embedding_fallback_model?: string | null;
  embedding_fallback_base_url_host?: string | null;
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

          <ScreenSwitchPanel />

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
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                <dt className="text-[13px] text-muted">Respaldo</dt>
                <dd className="flex flex-wrap items-center gap-2 text-xs">
                  {settings.embedding_fallback_enabled ? (
                    <>
                      <Badge tone="ok">
                        {settings.embedding_fallback_provider_label ?? "respaldo"}
                      </Badge>
                      <span className="mono text-text">
                        {settings.embedding_fallback_model ?? ""}
                      </span>
                      <span className="text-muted">
                        {settings.embedding_fallback_base_url_host ?? ""}
                      </span>
                    </>
                  ) : (
                    <span className="text-muted">sin respaldo</span>
                  )}
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

type OrgOption = {
  id: string;
  name: string;
  company_name?: string | null;
  plan?: string | null;
};

type OrgUserOption = {
  id: string;
  email: string | null;
  roles: string[];
};

/** Organización demo del seed de desarrollo (si existe se preselecciona). */
const PREFERRED_TEST_ORG_ID = "00000000-0000-0000-0000-000000000001";

/**
 * Cambio rápido de pantalla para pruebas: impersona un usuario del tenant
 * elegido (endpoint auditable) y volverá desde Configuración del portal.
 */
function ScreenSwitchPanel() {
  const { session } = usePlatformAuth();
  const [orgs, setOrgs] = useState<OrgOption[]>([]);
  const [orgId, setOrgId] = useState("");
  const [users, setUsers] = useState<OrgUserOption[]>([]);
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("Cambio de pantalla para pruebas");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [portalName, setPortalName] = useState<string | null>(() => {
    const current = loadSession();
    return current?.token ? current.companyName || "sesión activa" : null;
  });

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    platformApi<{ organizations: OrgOption[] }>("/api/v1/platform/organizations", {
      token: session.token,
    })
      .then((data) => {
        if (cancelled) return;
        const list = data.organizations || [];
        setOrgs(list);
        setOrgId((current) => {
          if (current) return current;
          const preferred = list.find((org) => org.id === PREFERRED_TEST_ORG_ID);
          return preferred?.id || list[0]?.id || "";
        });
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "No se pudieron cargar las organizaciones"
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  useEffect(() => {
    if (!session || !orgId) return;
    let cancelled = false;
    platformApi<{ users: OrgUserOption[] }>(
      `/api/v1/platform/organizations/${orgId}/users`,
      { token: session.token }
    )
      .then((data) => {
        if (!cancelled) setUsers(data.users || []);
      })
      .catch(() => {
        if (!cancelled) setUsers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [session, orgId]);

  const selectedOrg = orgs.find((org) => org.id === orgId);

  async function enterAsTenant() {
    if (!session || !orgId) return;
    const trimmed = reason.trim();
    if (trimmed.length < 3) {
      setError("El motivo necesita al menos 3 caracteres.");
      return;
    }
    setBusy("enter");
    setError("");
    setNotice("");
    try {
      const out = await platformApi<{ access_token: string; expires_seconds?: number }>(
        `/api/v1/platform/organizations/${orgId}/impersonate`,
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({
            expires_seconds: 3600,
            reason: trimmed,
            user_id: userId || null,
          }),
        }
      );
      enterTenantSession({
        token: out.access_token,
        organizationId: orgId,
        companyName: selectedOrg?.company_name || selectedOrg?.name || "Cliente",
        reason: trimmed,
        expiresSeconds: out.expires_seconds || 3600,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo entrar como usuario");
      setBusy("");
    }
  }

  async function closeClient() {
    setBusy("close");
    setError("");
    setNotice("");
    try {
      await closeTenantSession();
      setPortalName(null);
      setNotice("Sesión de cliente cerrada.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cerrar la sesión de cliente");
    } finally {
      setBusy("");
    }
  }

  return (
    <Panel>
      <PanelHeader
        title="Cambio de pantalla (pruebas)"
        description="Entra al portal como usuario de un cliente y vuelve al Control Center al terminar. La sesión dura 1 hora y queda auditada."
      />
      <div className="panel-body flex flex-col gap-4">
        <ErrorInline message={error} />
        <SuccessInline message={notice} />
        {portalName && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-sm border border-border-soft bg-control px-3 py-2 text-[13px]">
            <span className="text-muted">
              Sesión de cliente guardada:{" "}
              <span className="font-medium text-text">{portalName}</span>
            </span>
            <span className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => window.location.assign("/")}
              >
                Abrir portal de clientes
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={busy === "close"}
                onClick={() => void closeClient()}
              >
                Cerrar sesión de cliente
              </Button>
            </span>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Organización">
            <Select
              value={orgId}
              onChange={(e) => {
                setOrgId(e.target.value);
                setUserId("");
              }}
            >
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.company_name || org.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Usuario" hint="Por defecto se impersona al owner del tenant.">
            <Select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="Usuario por defecto"
            >
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.email || user.id}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Motivo"
            className="sm:col-span-2"
            hint="Queda registrado en la auditoría de impersonación."
          >
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
            />
          </Field>
        </div>
      </div>
      <div className="panel-footer justify-end">
        <Button
          variant="primary"
          loading={busy === "enter"}
          disabled={!orgId}
          onClick={() => void enterAsTenant()}
        >
          Entrar como usuario
        </Button>
      </div>
    </Panel>
  );
}
