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
  MagnifyingGlass,
  Plugs,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Badge,
  Button,
  Checkbox,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Panel,
  PanelHeader,
  PasswordInput,
  ResultCount,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
  WarningInline,
  type Column,
} from "../components/ui";
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

const LEVEL: ParameterLevel = "simple";

/** Fila del catálogo de importaciones. */
const DRAFT_COLUMNS: Column<DraftSummary>[] = [
  {
    key: "name",
    header: "Importación",
    render: (draft) => (
      <span className="block min-w-0" data-testid={`api-draft-${draft.slug}`}>
        <span className="block truncate text-[13px] font-medium text-text">{draft.name}</span>
        <span className="mono block truncate text-[11px] text-faint">
          {draft.base_url || draft.slug}
        </span>
      </span>
    ),
  },
  {
    key: "actions",
    header: "Acciones",
    align: "right",
    width: "1%",
    render: (draft) => <span className="mono text-xs text-muted">{draft.actions}</span>,
  },
  {
    key: "status",
    header: "Estado",
    width: "1%",
    render: (draft) => (
      <StatusBadge status={draft.status} label={draft.status === "installed" ? "Instalada" : undefined} />
    ),
  },
];

export default function IntegrationsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState("installed");
  const [installs, setInstalls] = useState<InstallRow[]>([]);
  const [context, setContext] = useState<InstalledContext[]>([]);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Catálogo
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");

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

  const categories = useMemo(
    () => Array.from(new Set(installs.map((i) => i.integration.category).filter(Boolean))).sort(),
    [installs],
  );

  const term = search.trim().toLowerCase();
  const filteredInstalls = useMemo(() => {
    return installs.filter((install) => {
      if (category && install.integration.category !== category) return false;
      if (!term) return true;
      return (
        install.integration.name.toLowerCase().includes(term) ||
        install.integration.provider.toLowerCase().includes(term) ||
        install.integration.slug.toLowerCase().includes(term)
      );
    });
  }, [installs, term, category]);

  const testActions = installedById[testInstallId]?.actions ?? [];

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Construir", to: "/workflows" }, { label: "Integraciones API" }]} />
      <PageHeader
        title="Integraciones API"
        subtitle="Conecta APIs externas importando su OpenAPI, o usa las integraciones instaladas."
        actions={
          <Button
            variant="primary"
            leadingIcon={UploadSimple}
            data-testid="api-import-open"
            onClick={() => setImportOpen(true)}
          >
            Conectar una API
          </Button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={success} />

      <Tabs value={tab} onValueChange={setTab} variant="pill">
        <TabsList>
          <TabsTrigger value="installed" data-testid="api-tab-installed">
            Instaladas
            {installs.length > 0 && <span className="mono text-[11px] text-faint">{installs.length}</span>}
          </TabsTrigger>
          <TabsTrigger value="drafts" data-testid="api-tab-drafts">
            Importaciones
            {drafts.length > 0 && <span className="mono text-[11px] text-faint">{drafts.length}</span>}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {loading ? (
        <Panel className="p-4">
          <SkeletonBlock rows={4} />
        </Panel>
      ) : tab === "installed" ? (
        <section className="flex flex-col gap-4">
          {installs.length === 0 ? (
            <Panel className="p-2" data-testid="api-installed-empty">
              <EmptyState
                icon={Plugs}
                title="Todavía no hay integraciones instaladas"
                body="Importa el OpenAPI de una API o instala una del marketplace para probar sus acciones desde acá."
                action={
                  <Button variant="primary" leadingIcon={UploadSimple} onClick={() => setImportOpen(true)}>
                    Conectar una API
                  </Button>
                }
              />
            </Panel>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  icon={MagnifyingGlass}
                  className="w-full sm:max-w-72"
                  placeholder="Buscar por nombre, proveedor o slug…"
                  aria-label="Buscar integración"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {categories.length > 1 && (
                  <div className="flex flex-wrap items-center gap-1">
                    <Button
                      variant={category === "" ? "secondary" : "ghost"}
                      size="sm"
                      aria-pressed={category === ""}
                      onClick={() => setCategory("")}
                    >
                      Todas
                    </Button>
                    {categories.map((c) => (
                      <Button
                        key={c}
                        variant={category === c ? "secondary" : "ghost"}
                        size="sm"
                        aria-pressed={category === c}
                        onClick={() => setCategory(c)}
                      >
                        {c}
                      </Button>
                    ))}
                  </div>
                )}
                <span className="flex-1" aria-hidden />
                <ResultCount shown={filteredInstalls.length} total={installs.length} noun="integraciones" />
              </div>

              {filteredInstalls.length === 0 ? (
                <Panel>
                  <EmptyState
                    compact
                    icon={MagnifyingGlass}
                    title="Sin resultados"
                    body="Ninguna integración coincide con la búsqueda o la categoría elegida."
                    action={
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setSearch("");
                          setCategory("");
                        }}
                      >
                        Limpiar filtros
                      </Button>
                    }
                  />
                </Panel>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {filteredInstalls.map((install) => {
                    const ctx = installedById[install.id];
                    const needsCredentials = (ctx?.status ?? []).includes("credentials_missing");
                    const deprecated = ctx?.integration.manifest_status === "DEPRECATED";
                    return (
                      <Panel
                        key={install.id}
                        className="flex flex-col gap-3 p-4"
                        data-testid={`api-install-${install.integration.slug}`}
                      >
                        <div className="flex items-start gap-2">
                          <span
                            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-soft text-accent"
                            aria-hidden
                          >
                            <Plugs size={15} />
                          </span>
                          <div className="min-w-0 flex-1">
                            <h3 className="truncate text-[13px] font-medium text-text">
                              {install.integration.name}
                            </h3>
                            <p className="truncate text-xs text-faint">
                              {install.integration.provider} ·{" "}
                              {ctx?.actions.length ?? install.enabled_actions.length} acciones
                            </p>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-1.5">
                          {needsCredentials ? (
                            <Badge tone="warn" icon={Key}>
                              Requiere credenciales
                            </Badge>
                          ) : (
                            <Badge tone="ok" icon={CheckCircle}>
                              Conectada
                            </Badge>
                          )}
                          {deprecated && <Badge tone="warn">Obsoleta</Badge>}
                          {install.integration.category && (
                            <Badge tone="neutral">{install.integration.category}</Badge>
                          )}
                        </div>

                        <div className="mt-auto flex flex-wrap gap-2">
                          <Button
                            variant="secondary"
                            size="sm"
                            leadingIcon={Flask}
                            data-testid={`api-test-${install.integration.slug}`}
                            onClick={() => void openTest(install.id)}
                          >
                            Probar
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            leadingIcon={Key}
                            data-testid={`api-creds-${install.integration.slug}`}
                            onClick={() => {
                              setCredInstall(install);
                              setCredKind("api_key");
                              setCredValues({});
                            }}
                          >
                            Credenciales
                          </Button>
                        </div>
                      </Panel>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </section>
      ) : (
        <DataTable
          columns={DRAFT_COLUMNS}
          rows={drafts}
          rowKey={(draft) => draft.draft_id}
          caption="Importaciones OpenAPI"
          empty={
            <div data-testid="api-drafts-empty">
              <EmptyState
                icon={UploadSimple}
                title="Sin importaciones pendientes"
                body="Usa “Conectar una API” para analizar un documento OpenAPI."
                action={
                  <Button variant="primary" leadingIcon={UploadSimple} onClick={() => setImportOpen(true)}>
                    Conectar una API
                  </Button>
                }
              />
            </div>
          }
          rowActions={(draft) => (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void openReview(draft.draft_id)}
            >
              {draft.status === "installed" ? "Ver" : "Revisar"}
            </Button>
          )}
        />
      )}

      {testInstallId && (
        <Panel data-testid="api-test-console">
          <PanelHeader
            title={
              <span className="flex items-center gap-2">
                <Flask size={16} className="text-accent" aria-hidden /> Probar acción
              </span>
            }
            description={installedById[testInstallId]?.integration.name}
            actions={
              <IconButton
                label="Cerrar consola"
                icon={X}
                variant="ghost"
                onClick={() => setTestInstallId("")}
              />
            }
          />
          <div className="panel-body flex flex-col gap-3">
            <Field label="Acción">
              <Select
                value={testActionId}
                data-testid="api-test-action"
                onChange={(e) => void pickAction(e.target.value)}
                placeholder="Elige una acción…"
              >
                {testActions.map((action) => (
                  <option key={action.action_id} value={action.action_id}>
                    {action.display_name}
                  </option>
                ))}
              </Select>
            </Field>

            {testActionId && (
              <>
                {testParams === null ? (
                  <SkeletonBlock rows={2} />
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
                <div>
                  <Button
                    variant="primary"
                    loading={testBusy}
                    leadingIcon={Flask}
                    data-testid="api-test-run"
                    onClick={() => void runTest()}
                  >
                    Ejecutar
                  </Button>
                </div>
                <ErrorInline message={testError} className="mb-0" />
                {testResult !== null && (
                  <div data-testid="api-test-result">
                    <p className="eyebrow mb-2">Resultado</p>
                    <DataView data={testResult} />
                  </div>
                )}
              </>
            )}
          </div>
        </Panel>
      )}

      <Drawer
        open={credInstall !== null}
        onOpenChange={(open) => {
          if (!open) setCredInstall(null);
        }}
        title={credInstall ? `Credenciales · ${credInstall.integration.name}` : "Credenciales"}
        description="Se guardan cifradas en el SecretStore: nunca viajan al grafo ni vuelven al navegador."
        width={480}
        data-testid="api-credentials"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCredInstall(null)} disabled={credBusy}>
              Cancelar
            </Button>
            <Button variant="primary" loading={credBusy} onClick={() => void saveCredentials()}>
              Guardar credenciales
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Tipo de autenticación">
            <Select value={credKind} onChange={(e) => setCredKind(e.target.value)}>
              <option value="api_key">API Key (header)</option>
              <option value="bearer">Bearer token</option>
              <option value="basic">Basic Auth (usuario y clave)</option>
              <option value="oauth2">Token OAuth2 temporal</option>
            </Select>
          </Field>

          <Field label="URL base de la API">
            <Input
              placeholder="https://api.miempresa.com/v1"
              value={credValues.endpoint_base_url ?? ""}
              onChange={(e) => setCredValues((v) => ({ ...v, endpoint_base_url: e.target.value }))}
              autoComplete="off"
            />
          </Field>

          {credKind === "api_key" && (
            <Field label="API Key">
              <PasswordInput
                autoComplete="off"
                value={credValues.api_key ?? ""}
                onChange={(e) => setCredValues((v) => ({ ...v, api_key: e.target.value }))}
              />
            </Field>
          )}

          {(credKind === "bearer" || credKind === "oauth2") && (
            <Field label="Token">
              <PasswordInput
                autoComplete="off"
                value={credValues.oauth_token ?? ""}
                onChange={(e) => setCredValues((v) => ({ ...v, oauth_token: e.target.value }))}
              />
            </Field>
          )}

          {credKind === "basic" && (
            <>
              <Field label="Usuario">
                <Input
                  autoComplete="off"
                  value={credValues.basic_username ?? ""}
                  onChange={(e) => setCredValues((v) => ({ ...v, basic_username: e.target.value }))}
                />
              </Field>
              <Field label="Clave">
                <PasswordInput
                  autoComplete="off"
                  value={credValues.basic_password ?? ""}
                  onChange={(e) => setCredValues((v) => ({ ...v, basic_password: e.target.value }))}
                />
              </Field>
            </>
          )}

          <p className="text-xs leading-relaxed text-faint">
            El valor guardado no se vuelve a mostrar: si necesitas rotarlo, vuelve a guardar uno nuevo.
          </p>
        </div>
      </Drawer>

      <Drawer
        open={review !== null}
        onOpenChange={(open) => {
          if (!open) setReview(null);
        }}
        title="Revisar importación"
        description={review?.draft.base_url}
        width={620}
        data-testid="api-review"
        footer={
          <>
            <Button
              variant="ghost"
              data-testid="api-review-discard"
              disabled={reviewBusy}
              onClick={() => void discardReview()}
            >
              Descartar borrador
            </Button>
            <Button
              variant="primary"
              leadingIcon={CheckCircle}
              loading={reviewBusy}
              data-testid="api-review-install"
              onClick={() => void installReview()}
            >
              Instalar integración
            </Button>
          </>
        }
      >
        {review && <ReviewBody draft={review} onPatch={(patch) => void patchReview(patch)} />}
      </Drawer>

      <Modal
        open={importOpen}
        onOpenChange={setImportOpen}
        title="Conectar una API"
        description="Pega la URL de un documento OpenAPI 3, o súbelo/pega su contenido. Zent analiza el documento y nunca ejecuta los endpoints durante el análisis."
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setImportOpen(false)} disabled={importBusy}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={importBusy}
              leadingIcon={Plugs}
              data-testid="api-import-submit"
              onClick={() => void importOpenApi()}
            >
              Analizar documento
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="URL del documento">
            <Input
              placeholder="https://api.miempresa.com/openapi.json"
              value={importUrl}
              data-testid="api-import-url"
              onChange={(e) => {
                setImportUrl(e.target.value);
                setImportDoc("");
              }}
              autoComplete="off"
            />
          </Field>

          <Field label="…o pega el JSON/YAML" hint="Se analiza tal cual, sin ejecutar endpoints.">
            <Textarea
              className="h-32 font-mono text-xs"
              placeholder='{"openapi": "3.0.0", ...}'
              value={importDoc}
              data-testid="api-import-doc"
              onChange={(e) => {
                setImportDoc(e.target.value);
                setImportUrl("");
              }}
              spellCheck={false}
            />
          </Field>

          <div className="flex flex-wrap items-end gap-3">
            <label className="btn btn-secondary btn-sm cursor-pointer">
              <UploadSimple size={14} aria-hidden /> Subir archivo
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
            <Field label="Nombre (opcional)" className="min-w-0 flex-1">
              <Input
                placeholder="ej. Acme Commerce"
                value={importName}
                onChange={(e) => setImportName(e.target.value)}
                autoComplete="off"
              />
            </Field>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function ReviewBody({
  draft,
  onPatch,
}: {
  draft: DraftDetail;
  onPatch: (patch: Record<string, unknown>) => void;
}) {
  const body = draft.draft;
  const [showTech, setShowTech] = useState(false);
  const [name, setName] = useState(draft.name);
  const [authKind, setAuthKind] = useState(body.auth?.kind || "none");
  const report = draft.report ?? {};
  const technical = body.capabilities.flatMap((capability) =>
    capability.actions.map((action) => `${action.method ?? "GET"} ${action.path_template ?? ""}`.trim()),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nombre de la integración">
          <Input
            value={name}
            data-testid="api-review-name"
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name !== draft.name && onPatch({ name })}
          />
        </Field>
        <Field label="Autenticación detectada">
          <Select
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
          </Select>
        </Field>
      </div>

      <p className="text-xs leading-relaxed text-faint">
        Servidor: <span className="mono">{body.base_url}</span> · {report.actions_generated ?? 0} acciones
        en {body.capabilities.length} grupos
        {report.operations_total ? ` (de ${report.operations_total} operaciones)` : ""}
      </p>

      {(report.warnings ?? []).length > 0 && (
        <WarningInline
          className="mb-0"
          message={
            <ul className="flex flex-col gap-1">
              {(report.warnings ?? []).map((warning, index) => (
                <li key={index}>{warning.message}</li>
              ))}
            </ul>
          }
        />
      )}

      <div className="flex flex-col gap-3">
        {body.capabilities.map((capability) => (
          <div key={capability.slug} className="rounded-md border border-border">
            <p className="border-b border-border px-3 py-2 text-[13px] font-medium text-text">
              {capability.name}
            </p>
            <div className="flex flex-col divide-y divide-border-soft">
              {capability.actions.map((action) => (
                <div key={action.action_id} className="flex items-center gap-2 px-3 py-2">
                  <Checkbox
                    checked={action.enabled !== false}
                    onCheckedChange={(checked) =>
                      onPatch({ actions: [{ action_id: action.action_id, enabled: checked }] })
                    }
                    label={<span className="sr-only">{action.display_name}</span>}
                    data-testid={`api-review-enable-${action.action_id}`}
                  />
                  <Input
                    className="min-w-0 flex-1 border-transparent bg-transparent"
                    defaultValue={action.display_name}
                    aria-label={`Nombre visible de ${action.display_name}`}
                    data-testid={`api-review-label-${action.action_id}`}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value && value !== action.display_name) {
                        onPatch({ actions: [{ action_id: action.action_id, display_name: value }] });
                      }
                    }}
                  />
                  {!action.read_only && <Badge tone="warn">escritura</Badge>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={showTech}
          data-testid="api-review-tech"
          onClick={() => setShowTech((value) => !value)}
        >
          {showTech ? <CaretDown size={12} aria-hidden /> : <CaretRight size={12} aria-hidden />}
          Ver detalles técnicos (método y ruta)
        </Button>
        {showTech && (
          <CodeBlock
            className="mt-2"
            code={technical.join("\n")}
            language="http"
            filename="endpoints"
            maxHeight={220}
          />
        )}
      </div>
    </div>
  );
}
