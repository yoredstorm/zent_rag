/**
 * Integraciones API — Universal API Connector (misión §11-§17).
 *
 * Importar OpenAPI (URL o archivo) → revisar borrador → instalar → probar
 * acciones con formularios de negocio. El detalle técnico (método/URL) vive
 * en "Avanzado"; las credenciales van al SecretStore.
 */
import {
  CaretDown,
  CaretRight,
  CheckCircle,
  Flask,
  Key,
  Plugs,
  Trash,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner, SuccessInline } from "../components/ui";
import { BusinessParameterForm } from "../components/workflowStudio/BusinessParameterForm";
import { DataView } from "../components/workflowStudio/DataView";
import type { BusinessParameter, ParameterLevel } from "../lib/businessSchema";

type DraftSummary = {
  draft_id: string;
  slug: string;
  name: string;
  status: string;
  base_url?: string | null;
  source_kind: string;
  source_url?: string | null;
  actions: number;
  auth: { kind: string };
  updated_at?: string | null;
};

type DraftAction = {
  action_id: string;
  display_name: string;
  description?: string;
  method?: string;
  path_template?: string;
  enabled?: boolean;
  requires_approval?: boolean;
  read_only?: boolean;
};

type Capability = { slug: string; name: string; actions: DraftAction[] };

type DraftDetail = {
  draft_id: string;
  slug: string;
  name: string;
  status: string;
  install_id?: string | null;
  integration_slug?: string | null;
  report?: {
    operations_total?: number;
    actions_generated?: number;
    skipped?: { method: string; path: string; reason: string }[];
    warnings?: { code: string; message: string }[];
    host?: string;
  };
  draft: {
    description?: string;
    base_url: string;
    auth: { kind: string; header_name?: string | null; notes?: string[] };
    rate_limits?: Record<string, number>;
    capabilities: Capability[];
  };
};

type InstallRow = {
  id: string;
  status: string;
  integration: { slug: string; name: string; provider: string; category: string; rate_limits?: Record<string, number> };
  enabled_actions: string[];
  credentials: { id: string; status: string }[];
};

type InstalledContext = {
  install_id: string;
  integration: { slug: string; name: string; manifest_status: string };
  status: string[];
  actions: { action_id: string; display_name: string; read_only: boolean }[];
};

const TAB = [
  { key: "installed", label: "Instaladas" },
  { key: "drafts", label: "Importaciones" },
] as const;

const LEVEL: ParameterLevel = "simple";

export default function IntegrationsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<(typeof TAB)[number]["key"]>("installed");
  const [installs, setInstalls] = useState<InstallRow[]>([]);
  const [context, setContext] = useState<InstalledContext[]>([]);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Consola de prueba
  const [testInstallId, setTestInstallId] = useState("");
  const [testActionId, setTestActionId] = useState("");
  const [testParams, setTestParams] = useState<BusinessParameter[] | null>(null);
  const [testValues, setTestValues] = useState<Record<string, unknown>>({});
  const [testResult, setTestResult] = useState<unknown>(null);
  const [testError, setTestError] = useState("");
  const [testBusy, setTestBusy] = useState(false);

  // Credenciales
  const [credInstall, setCredInstall] = useState<InstallRow | null>(null);
  const [credKind, setCredKind] = useState("api_key");
  const [credValues, setCredValues] = useState<Record<string, string>>({});
  const [credBusy, setCredBusy] = useState(false);

  // Importación
  const [importOpen, setImportOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importDoc, setImportDoc] = useState("");
  const [importName, setImportName] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [review, setReview] = useState<DraftDetail | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const [installData, ctxData, draftData] = await Promise.all([
        api<{ installs: InstallRow[] }>("/api/v1/integrations/installs", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ installed: InstalledContext[] }>("/api/v1/workflows/marketplace/context", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ drafts: DraftSummary[] }>("/api/v1/integrations/drafts", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setInstalls(installData.installs || []);
      setContext(ctxData.installed || []);
      setDrafts(draftData.drafts || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const installedById = useMemo(() => {
    const map: Record<string, InstalledContext> = {};
    for (const item of context) map[item.install_id] = item;
    return map;
  }, [context]);

  async function openTest(installId: string) {
    setTestInstallId(installId);
    setTestActionId("");
    setTestParams(null);
    setTestResult(null);
    setTestError("");
    setTestValues({});
  }

  async function pickAction(actionId: string) {
    setTestActionId(actionId);
    setTestResult(null);
    setTestError("");
    if (!session) return;
    setTestParams(null);
    try {
      const data = await api<{ input_parameters?: BusinessParameter[] }>(
        `/api/v1/workflows/marketplace/ports/${encodeURIComponent(actionId)}`,
        { token: session.token, organizationId: session.organizationId },
      );
      setTestParams(data.input_parameters ?? []);
    } catch (e) {
      setTestParams([]);
      setTestError(e instanceof Error ? e.message : "No pude cargar los parámetros");
    }
  }

  async function runTest() {
    if (!session || !testInstallId || !testActionId) return;
    setTestBusy(true);
    setTestError("");
    setTestResult(null);
    try {
      const inputs: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(testValues)) {
        if (value !== "" && value !== undefined && value !== null) inputs[key] = value;
      }
      const data = await api<{ ok: boolean; error_code?: string; message?: string; data?: unknown }>(
        `/api/v1/integrations/installs/${testInstallId}/actions/${encodeURIComponent(testActionId)}/execute`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ inputs, force_refresh: true }),
        },
      );
      if (!data.ok) setTestError(data.message || data.error_code || "La acción falló");
      else setTestResult(data.data);
    } catch (e) {
      setTestError(e instanceof Error ? e.message : "Error");
    } finally {
      setTestBusy(false);
    }
  }

  async function saveCredentials() {
    if (!session || !credInstall) return;
    setCredBusy(true);
    setError("");
    try {
      const secrets: Record<string, string> = {};
      if (credValues.endpoint_base_url) secrets.endpoint_base_url = credValues.endpoint_base_url;
      if (credKind === "api_key" && credValues.api_key) secrets.api_key = credValues.api_key;
      if (credKind === "bearer" && credValues.oauth_token) secrets.oauth_token = credValues.oauth_token;
      if (credKind === "basic") {
        if (credValues.basic_username) secrets.basic_username = credValues.basic_username;
        if (credValues.basic_password) secrets.basic_password = credValues.basic_password;
      }
      if (credValues.api_key && credKind !== "api_key") secrets.api_key = credValues.api_key;
      await api(`/api/v1/integrations/installs/${credInstall.id}/credentials`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          auth_mode: "BYOC",
          cred_type: credKind.toUpperCase(),
          secrets,
        }),
      });
      setCredInstall(null);
      setCredValues({});
      setSuccess("Credenciales guardadas en el SecretStore. Ya puedes probar la integración.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setCredBusy(false);
    }
  }

  async function importOpenApi() {
    if (!session) return;
    if (!importUrl && !importDoc) {
      setError("Pega la URL del documento OpenAPI o su contenido.");
      return;
    }
    setImportBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {};
      if (importUrl) payload.url = importUrl.trim();
      else payload.document = importDoc;
      if (importName.trim()) payload.name = importName.trim();
      const created = await api<{ draft_id: string }>("/api/v1/integrations/import/openapi", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(payload),
      });
      const detail = await api<DraftDetail>(`/api/v1/integrations/drafts/${created.draft_id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setReview(detail);
      setImportOpen(false);
      setImportUrl("");
      setImportDoc("");
      setImportName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude importar el documento");
    } finally {
      setImportBusy(false);
    }
  }

  async function openReview(draftId: string) {
    if (!session) return;
    setError("");
    try {
      const detail = await api<DraftDetail>(`/api/v1/integrations/drafts/${draftId}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setReview(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function patchReview(patch: Record<string, unknown>) {
    if (!session || !review) return;
    try {
      const detail = await api<DraftDetail>(`/api/v1/integrations/drafts/${review.draft_id}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(patch),
      });
      setReview(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function installReview() {
    if (!session || !review) return;
    setReviewBusy(true);
    setError("");
    try {
      const result = await api<{ install_id: string; integration_slug: string; credentials_required: boolean }>(
        `/api/v1/integrations/drafts/${review.draft_id}/install`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      setReview(null);
      setTab("installed");
      setSuccess(
        result.credentials_required
          ? `Integración ${result.integration_slug} instalada. Conecta sus credenciales para usarla.`
          : `Integración ${result.integration_slug} lista para usar.`,
      );
      await openTest(result.install_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude instalar la integración");
    } finally {
      setReviewBusy(false);
    }
  }

  async function discardReview() {
    if (!session || !review) return;
    try {
      await api(`/api/v1/integrations/drafts/${review.draft_id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setReview(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function readFile(file: File) {
    const text = await file.text();
    setImportDoc(text);
    setImportUrl("");
    if (!importName) setImportName(file.name.replace(/\.(json|ya?ml)$/i, ""));
  }

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Construir", to: "/workflows" }, { label: "Integraciones API" }]} />
      <PageHeader
        title="Integraciones API"
        subtitle="Conecta APIs externas importando su OpenAPI, o usa las integraciones instaladas."
        actions={
          <button
            type="button"
            className="btn btn-primary min-h-11 gap-1.5 px-3 text-xs"
            data-testid="api-import-open"
            onClick={() => setImportOpen(true)}
          >
            <UploadSimple size={14} aria-hidden /> Conectar una API
          </button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={success} />

      <div className="flex rounded-md border border-border p-0.5" role="tablist" aria-label="Vista de integraciones">
        {TAB.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            className={`flex-1 rounded px-2 py-1.5 text-[11px] ${
              tab === item.key ? "bg-accent/15 font-medium text-text" : "text-faint hover:text-muted"
            }`}
            data-testid={`api-tab-${item.key}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
            {item.key === "drafts" && drafts.length > 0 && (
              <span className="ml-1.5 rounded bg-soft px-1.5 text-[9px]">{drafts.length}</span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="panel p-5"><SkeletonBlock rows={4} /></div>
      ) : tab === "installed" ? (
        <InstalledTab
          installs={installs}
          context={installedById}
          onTest={(id) => void openTest(id)}
          onCredentials={(install) => {
            setCredInstall(install);
            setCredKind("api_key");
            setCredValues({});
          }}
          onConnectApi={() => setImportOpen(true)}
        />
      ) : (
        <DraftsTab drafts={drafts} onReview={(id) => void openReview(id)} />
      )}

      {testInstallId && (
        <section className="panel space-y-3 p-4" data-testid="api-test-console">
          <div className="flex items-center gap-2">
            <Flask size={16} className="text-accent" aria-hidden />
            <h2 className="flex-1 text-sm font-semibold text-text">Probar acción</h2>
            <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar consola" onClick={() => setTestInstallId("")}>
              <X size={14} />
            </button>
          </div>
          <label className="block">
            <span className="mb-0.5 block text-[10px] font-medium text-muted">Acción</span>
            <select
              className="w-full rounded-md border border-border bg-soft px-2 py-2 text-[11px]"
              value={testActionId}
              data-testid="api-test-action"
              onChange={(e) => void pickAction(e.target.value)}
            >
              <option value="">Elige una acción…</option>
              {(installedById[testInstallId]?.actions ?? []).map((action) => (
                <option key={action.action_id} value={action.action_id}>{action.display_name}</option>
              ))}
            </select>
          </label>
          {testActionId && (
            <>
              {testParams === null ? (
                <p className="text-[10px] text-faint">Cargando formulario…</p>
              ) : (
                <BusinessParameterForm
                  parameters={testParams}
                  level={LEVEL}
                  values={testValues}
                  onChange={(key, value) => setTestValues((prev) => ({ ...prev, [key]: value }))}
                  dataSources={[]}
                  emptyHint="Esta acción no necesita parámetros."
                />
              )}
              <button
                type="button"
                className="btn btn-primary min-h-9 w-full gap-1.5 text-xs"
                disabled={testBusy}
                data-testid="api-test-run"
                onClick={() => void runTest()}
              >
                {testBusy ? <Spinner size={13} /> : <Flask size={13} aria-hidden />} Ejecutar
              </button>
              <ErrorInline message={testError} />
              {testResult !== null && (
                <div className="rounded-md border border-border bg-soft/40 p-2" data-testid="api-test-result">
                  <p className="mb-1 text-[10px] font-medium text-muted">Resultado</p>
                  <DataView data={testResult} />
                </div>
              )}
            </>
          )}
        </section>
      )}

      {credInstall && (
        <section className="panel space-y-3 p-4" data-testid="api-credentials">
          <div className="flex items-center gap-2">
            <Key size={16} className="text-accent" aria-hidden />
            <h2 className="flex-1 text-sm font-semibold text-text">Credenciales · {credInstall.integration.name}</h2>
            <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar credenciales" onClick={() => setCredInstall(null)}>
              <X size={14} />
            </button>
          </div>
          <label className="block">
            <span className="mb-0.5 block text-[10px] font-medium text-muted">Tipo de autenticación</span>
            <select
              className="w-full rounded-md border border-border bg-soft px-2 py-2 text-[11px]"
              value={credKind}
              onChange={(e) => setCredKind(e.target.value)}
            >
              <option value="api_key">API Key (header)</option>
              <option value="bearer">Bearer token</option>
              <option value="basic">Basic Auth (usuario y clave)</option>
              <option value="oauth2">Token OAuth2 temporal</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-0.5 block text-[10px] font-medium text-muted">URL base de la API</span>
            <input
              className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
              placeholder="https://api.miempresa.com/v1"
              value={credValues.endpoint_base_url ?? ""}
              onChange={(e) => setCredValues((v) => ({ ...v, endpoint_base_url: e.target.value }))}
            />
          </label>
          {credKind === "api_key" && (
            <SecretField
              label="API Key"
              value={credValues.api_key ?? ""}
              onChange={(value) => setCredValues((v) => ({ ...v, api_key: value }))}
            />
          )}
          {(credKind === "bearer" || credKind === "oauth2") && (
            <SecretField
              label="Token"
              value={credValues.oauth_token ?? ""}
              onChange={(value) => setCredValues((v) => ({ ...v, oauth_token: value }))}
            />
          )}
          {credKind === "basic" && (
            <>
              <label className="block">
                <span className="mb-0.5 block text-[10px] font-medium text-muted">Usuario</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
                  value={credValues.basic_username ?? ""}
                  onChange={(e) => setCredValues((v) => ({ ...v, basic_username: e.target.value }))}
                />
              </label>
              <SecretField
                label="Clave"
                value={credValues.basic_password ?? ""}
                onChange={(value) => setCredValues((v) => ({ ...v, basic_password: value }))}
              />
            </>
          )}
          <p className="text-[10px] text-faint">
            Se guardan cifradas en el SecretStore. Nunca viajan al grafo del workflow ni vuelven al navegador.
          </p>
          <button
            type="button"
            className="btn btn-primary min-h-9 w-full text-xs"
            disabled={credBusy}
            onClick={() => void saveCredentials()}
          >
            {credBusy ? <Spinner size={13} /> : null} Guardar credenciales
          </button>
        </section>
      )}

      {review && (
        <ReviewPanel
          draft={review}
          busy={reviewBusy}
          onClose={() => setReview(null)}
          onPatch={(patch) => void patchReview(patch)}
          onInstall={() => void installReview()}
          onDiscard={() => void discardReview()}
        />
      )}

      {importOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4" role="dialog" aria-label="Conectar una API">
          <div className="mt-16 w-full max-w-lg rounded-lg border border-border bg-surface p-4 shadow-panel">
            <div className="flex items-center gap-2">
              <Plugs size={16} className="text-accent" aria-hidden />
              <h2 className="flex-1 text-sm font-semibold text-text">Conectar una API</h2>
              <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar" onClick={() => setImportOpen(false)}>
                <X size={14} />
              </button>
            </div>
            <p className="mt-1 text-[11px] text-muted">
              Pega la URL de un documento OpenAPI 3, o súbelo/pega su contenido. Zent analiza el documento
              y nunca ejecuta los endpoints durante el análisis.
            </p>
            <label className="mt-3 block">
              <span className="mb-0.5 block text-[10px] font-medium text-muted">URL del documento</span>
              <input
                className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
                placeholder="https://api.miempresa.com/openapi.json"
                value={importUrl}
                data-testid="api-import-url"
                onChange={(e) => {
                  setImportUrl(e.target.value);
                  setImportDoc("");
                }}
              />
            </label>
            <label className="mt-2 block">
              <span className="mb-0.5 block text-[10px] font-medium text-muted">…o pega el JSON/YAML</span>
              <textarea
                className="h-24 w-full rounded-md border border-border bg-soft px-2 py-1.5 font-mono text-[10px]"
                placeholder='{"openapi": "3.0.0", ...}'
                value={importDoc}
                data-testid="api-import-doc"
                onChange={(e) => {
                  setImportDoc(e.target.value);
                  setImportUrl("");
                }}
              />
            </label>
            <div className="mt-2 flex items-center gap-2">
              <label className="btn btn-secondary min-h-8 cursor-pointer px-2 text-[10px]">
                <UploadSimple size={12} aria-hidden className="mr-1" /> Subir archivo
                <input
                  type="file"
                  accept=".json,.yaml,.yml"
                  className="hidden"
                  data-testid="api-import-file"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void readFile(file);
                  }}
                />
              </label>
              <label className="flex-1">
                <input
                  className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
                  placeholder="Nombre (opcional)"
                  value={importName}
                  onChange={(e) => setImportName(e.target.value)}
                />
              </label>
            </div>
            <button
              type="button"
              className="btn btn-primary mt-3 min-h-10 w-full gap-1.5 text-xs"
              disabled={importBusy}
              data-testid="api-import-submit"
              onClick={() => void importOpenApi()}
            >
              {importBusy ? <Spinner size={13} /> : <Plugs size={13} aria-hidden />} Analizar documento
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SecretField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[10px] font-medium text-muted">{label}</span>
      <input
        type="password"
        autoComplete="off"
        className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function InstalledTab({
  installs,
  context,
  onTest,
  onCredentials,
  onConnectApi,
}: {
  installs: InstallRow[];
  context: Record<string, InstalledContext>;
  onTest: (id: string) => void;
  onCredentials: (install: InstallRow) => void;
  onConnectApi: () => void;
}) {
  if (installs.length === 0) {
    return (
      <div className="panel space-y-2 p-5 text-sm text-muted" data-testid="api-installed-empty">
        <p>Todavía no hay integraciones instaladas.</p>
        <button type="button" className="btn btn-secondary min-h-9 text-xs" onClick={onConnectApi}>
          Conectar una API
        </button>
      </div>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {installs.map((install) => {
        const ctx = context[install.id];
        const needsCredentials = (ctx?.status ?? []).includes("credentials_missing");
        return (
          <article key={install.id} className="panel flex flex-col gap-2 p-4" data-testid={`api-install-${install.integration.slug}`}>
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 text-accent" aria-hidden>
                <Plugs size={14} />
              </span>
              <h3 className="flex-1 truncate text-sm font-semibold text-text">{install.integration.name}</h3>
              {needsCredentials ? (
                <span className="badge badge-warn">faltan credenciales</span>
              ) : (
                <span className="badge badge-ok"><CheckCircle size={10} className="mr-1" aria-hidden /> lista</span>
              )}
            </div>
            <p className="text-[10px] text-faint">
              {install.integration.provider} · {ctx?.actions.length ?? install.enabled_actions.length} acciones
            </p>
            <div className="mt-auto flex gap-2">
              <button
                type="button"
                className="btn btn-secondary min-h-8 flex-1 text-[10px]"
                data-testid={`api-test-${install.integration.slug}`}
                onClick={() => onTest(install.id)}
              >
                <Flask size={11} aria-hidden className="mr-1" /> Probar
              </button>
              <button
                type="button"
                className="btn btn-ghost min-h-8 flex-1 text-[10px]"
                data-testid={`api-creds-${install.integration.slug}`}
                onClick={() => onCredentials(install)}
              >
                <Key size={11} aria-hidden className="mr-1" /> Credenciales
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function DraftsTab({ drafts, onReview }: { drafts: DraftSummary[]; onReview: (id: string) => void }) {
  if (drafts.length === 0) {
    return (
      <div className="panel p-5 text-sm text-muted" data-testid="api-drafts-empty">
        No hay importaciones pendientes. Usa “Conectar una API” para analizar un documento OpenAPI.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {drafts.map((draft) => (
        <article key={draft.draft_id} className="panel flex items-center gap-3 p-3" data-testid={`api-draft-${draft.slug}`}>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-text">{draft.name}</p>
            <p className="truncate text-[10px] text-faint">
              {draft.base_url || draft.slug} · {draft.actions} acciones · {draft.status === "installed" ? "instalada" : "borrador"}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary min-h-8 px-3 text-[10px]"
            onClick={() => onReview(draft.draft_id)}
          >
            {draft.status === "installed" ? "Ver" : "Revisar"}
          </button>
        </article>
      ))}
    </div>
  );
}

function ReviewPanel({
  draft,
  busy,
  onClose,
  onPatch,
  onInstall,
  onDiscard,
}: {
  draft: DraftDetail;
  busy: boolean;
  onClose: () => void;
  onPatch: (patch: Record<string, unknown>) => void;
  onInstall: () => void;
  onDiscard: () => void;
}) {
  const body = draft.draft;
  const [showTech, setShowTech] = useState(false);
  const [name, setName] = useState(draft.name);
  const [authKind, setAuthKind] = useState(body.auth?.kind || "none");
  const report = draft.report ?? {};
  return (
    <section className="panel space-y-3 p-4" data-testid="api-review">
      <div className="flex items-center gap-2">
        <Plugs size={16} className="text-accent" aria-hidden />
        <h2 className="flex-1 text-sm font-semibold text-text">Revisar importación</h2>
        <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar revisión" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-0.5 block text-[10px] font-medium text-muted">Nombre de la integración</span>
          <input
            className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
            value={name}
            data-testid="api-review-name"
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name !== draft.name && onPatch({ name })}
          />
        </label>
        <label className="block">
          <span className="mb-0.5 block text-[10px] font-medium text-muted">Autenticación detectada</span>
          <select
            className="w-full rounded-md border border-border bg-soft px-2 py-2 text-[11px]"
            value={authKind}
            data-testid="api-review-auth"
            onChange={(e) => {
              setAuthKind(e.target.value);
              onPatch({ auth_kind: e.target.value });
            }}
          >
            <option value="none">Sin autenticación</option>
            <option value="api_key">API Key</option>
            <option value="bearer">Bearer token</option>
            <option value="basic">Basic Auth</option>
            <option value="oauth2">OAuth2 / token</option>
          </select>
        </label>
      </div>
      <p className="text-[10px] text-faint">
        Servidor: {body.base_url} · {report.actions_generated ?? 0} acciones en {body.capabilities.length} grupos
        {report.operations_total ? ` (de ${report.operations_total} operaciones)` : ""}
      </p>
      {(report.warnings ?? []).length > 0 && (
        <div className="rounded-md border border-warn/40 bg-warn-soft/40 p-2 text-[10px] text-text">
          {(report.warnings ?? []).map((warning, index) => (
            <p key={index}>· {warning.message}</p>
          ))}
        </div>
      )}
      <div className="space-y-2">
        {body.capabilities.map((capability) => (
          <div key={capability.slug} className="rounded-md border border-border p-2">
            <p className="text-[11px] font-medium text-text">{capability.name}</p>
            <div className="mt-1 space-y-1">
              {capability.actions.map((action) => (
                <div key={action.action_id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="accent-[var(--accent)]"
                    checked={action.enabled !== false}
                    data-testid={`api-review-enable-${action.action_id}`}
                    onChange={(e) => onPatch({ actions: [{ action_id: action.action_id, enabled: e.target.checked }] })}
                  />
                  <input
                    className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-[11px] text-text hover:border-border focus:border-border"
                    defaultValue={action.display_name}
                    data-testid={`api-review-label-${action.action_id}`}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value && value !== action.display_name) {
                        onPatch({ actions: [{ action_id: action.action_id, display_name: value }] });
                      }
                    }}
                  />
                  {!action.read_only && <span className="badge badge-warn">escritura</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="btn btn-ghost min-h-7 gap-1 px-1 text-[10px] text-muted"
        data-testid="api-review-tech"
        onClick={() => setShowTech((value) => !value)}
      >
        {showTech ? <CaretDown size={11} /> : <CaretRight size={11} />} Ver detalles técnicos (método y ruta)
      </button>
      {showTech && (
        <div className="rounded-md border border-border bg-soft/30 p-2 font-mono text-[9px] text-faint">
          {body.capabilities.flatMap((capability) =>
            capability.actions.map((action) => (
              <p key={action.action_id}>{action.method} {action.path_template}</p>
            )),
          )}
        </div>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          className="btn btn-primary min-h-10 flex-1 text-xs"
          disabled={busy}
          data-testid="api-review-install"
          onClick={onInstall}
        >
          {busy ? <Spinner size={13} /> : <CheckCircle size={13} aria-hidden className="mr-1" />} Instalar integración
        </button>
        <button
          type="button"
          className="btn btn-ghost min-h-10 px-3 text-xs text-danger"
          data-testid="api-review-discard"
          onClick={onDiscard}
        >
          <Trash size={13} aria-hidden />
        </button>
      </div>
    </section>
  );
}
