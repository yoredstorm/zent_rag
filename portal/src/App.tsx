import { MagnifyingGlass, List } from "@phosphor-icons/react";
import { motion, useAnimation, useReducedMotion } from "motion/react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { ApiKeyCreatedModal } from "./components/ApiKeyCreatedModal";
import { Topbar } from "./components/Topbar";
import { api, clearSession, loadSession, SIGNUP_API_KEY_STORAGE } from "./api";
import { useAuth } from "./auth";
import { IMPERSONATING_KEY } from "./platformAuth";
import { SyncBanner, SyncJobProvider } from "./syncJob";
import { ToastProvider } from "./Toast";
import { CommandPaletteRoot, openCommandPalette } from "./components/CommandPalette";
import { IdleSessionWarning } from "./components/IdleSessionWarning";
import { DemoBanner } from "./components/DemoBanner";
import { TenantStepUpModal } from "./components/TenantStepUpModal";
import { ProductTourRoot } from "./components/ProductTour";
import { EntitlementsProvider } from "./lib/entitlements";
import { AppSidebar } from "./components/shell/AppSidebar";
import { MobileNav } from "./components/shell/MobileNav";
import { Brand } from "./components/Brand";
import { PageSkeleton } from "./components/ui/states";

const IDLE_SESSION_MINUTES = 30;
const SIDEBAR_COLLAPSED_KEY = "zent_sidebar_collapsed";

const ChatPage = lazy(() => import("./pages/Chat"));
const DashboardPage = lazy(() => import("./pages/Dashboard"));
const KeysPage = lazy(() => import("./pages/Keys"));
const LoginPage = lazy(() => import("./pages/Login"));
const PromptsPage = lazy(() => import("./pages/Prompts"));
const SignupPage = lazy(() => import("./pages/Signup"));
const UsagePage = lazy(() => import("./pages/Usage"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const AgentsPage = lazy(() => import("./pages/Agents"));
const AgentStudioPage = lazy(() => import("./pages/AgentStudio"));
const AgentBuilderRedirectPage = lazy(() =>
  import("./pages/AgentEntry").then((m) => ({ default: m.AgentBuilderRedirect })),
);
const ConnectorsPage = lazy(() => import("./pages/Connectors"));
const BillingPage = lazy(() => import("./pages/Billing"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const KnowledgeSourcesPage = lazy(() => import("./pages/knowledge/Sources"));
const KnowledgeOverviewPage = lazy(() => import("./pages/knowledge/Overview"));
const KnowledgeOnboardingPage = lazy(() => import("./pages/onboarding/data/OnboardingWizard"));
const KnowledgeUnderstandingPage = lazy(() => import("./pages/knowledge/Understanding"));
const KnowledgeCollectionsPage = lazy(() => import("./pages/knowledge/Collections"));
const KnowledgeDocumentsPage = lazy(() => import("./pages/knowledge/Documents"));
const KnowledgeSqlPage = lazy(() => import("./pages/knowledge/SqlSources"));
const KnowledgeJobsPage = lazy(() => import("./pages/knowledge/Jobs"));
const KnowledgePlaygroundPage = lazy(() => import("./pages/knowledge/Playground"));
const KnowledgeCatalogPage = lazy(() => import("./pages/knowledge/Catalog"));
const KnowledgeGlossaryPage = lazy(() => import("./pages/knowledge/Glossary"));
const KnowledgeReviewPage = lazy(() => import("./pages/knowledge/Review"));
const KnowledgeImprovementsPage = lazy(() => import("./pages/knowledge/Improvements"));
const KnowledgeDatabasePage = lazy(() => import("./pages/knowledge/DatabaseBuilder"));
const KnowledgeManagedImportPage = lazy(() => import("./pages/knowledge/ManagedImport"));
const KnowledgeSourceDetailPage = lazy(() => import("./pages/knowledge/SourceDetail"));
const KnowledgeLearningPage = lazy(() => import("./pages/knowledge/Learning"));
const KnowledgeMapPage = lazy(() => import("./pages/knowledge/Map"));
const KnowledgeWorkspacesPage = lazy(() => import("./pages/knowledge/KnowledgeWorkspaces"));
const KnowledgeWorkspacePage = lazy(() => import("./pages/knowledge/KnowledgeWorkspace"));
const TransitionWizardPage = lazy(() => import("./pages/onboarding/TransitionWizard"));
const StartModePage = lazy(() => import("./pages/onboarding/StartMode"));
const EvaluationGapsPage = lazy(() => import("./pages/evaluation/Gaps"));
const EvaluationImpactPage = lazy(() => import("./pages/evaluation/Impact"));
const WorkspacesPage = lazy(() => import("./pages/Workspaces"));
const TrainingPage = lazy(() => import("./pages/Training"));
const DeveloperCenterPage = lazy(() => import("./pages/DeveloperCenter"));
const AdminLayout = lazy(() => import("./pages/admin/AdminLayout"));
const AdminLoginPage = lazy(() => import("./pages/admin/Login"));
const AdminDashboardPage = lazy(() => import("./pages/admin/Dashboard"));
const AdminCustomersPage = lazy(() => import("./pages/admin/Customers"));
const AdminCustomerDetailPage = lazy(() => import("./pages/admin/CustomerDetail"));
const AdminPlansPage = lazy(() => import("./pages/admin/Plans"));
const AdminUsagePage = lazy(() => import("./pages/admin/Usage"));
const AdminSubscriptionsPage = lazy(() => import("./pages/admin/Subscriptions"));
const AdminOperationsPage = lazy(() => import("./pages/admin/Operations"));
const AdminSecurityPage = lazy(() => import("./pages/admin/Security"));
const AdminAuditPage = lazy(() => import("./pages/admin/Audit"));
const AdminSettingsPage = lazy(() => import("./pages/admin/Settings"));
const AdminFinOpsPage = lazy(() => import("./pages/admin/FinOps"));
const AdminSystemStatusPage = lazy(() => import("./pages/admin/SystemStatus"));
const SsoCallbackPage = lazy(() => import("./pages/SsoCallback"));
const AdminDisasterRecoveryPage = lazy(() => import("./pages/admin/DisasterRecovery"));
const AdminGovernancePage = lazy(() => import("./pages/admin/Governance"));
const DisasterRecoveryPage = lazy(() => import("./pages/DisasterRecovery"));
const AdminCustomerSuccessPage = lazy(() => import("./pages/admin/CustomerSuccess"));
const AdminAuditIntelligencePage = lazy(() => import("./pages/admin/AuditIntelligence"));
const AdminOptimizerPage = lazy(() => import("./pages/admin/Optimizer"));
const AdminFederatedAnalyticsPage = lazy(() => import("./pages/admin/FederatedAnalytics"));
const AdminMarketplacePage = lazy(() => import("./pages/admin/Marketplace"));
const AdminMarketplaceFactoryPage = lazy(() => import("./pages/admin/MarketplaceFactory"));
const SharedAgentPage = lazy(() => import("./pages/SharedAgent"));
const AdminWorkflowsPage = lazy(() => import("./pages/admin/Workflows"));
const ChatInsightsPage = lazy(() => import("./pages/ChatInsights"));
const AdminChatInsightsPage = lazy(() => import("./pages/admin/ChatInsights"));
const KnowledgeHubPage = lazy(() => import("./pages/KnowledgeHub"));
const AdminKnowledgeHubPage = lazy(() => import("./pages/admin/KnowledgeHub"));
const RiskCenterPage = lazy(() => import("./pages/RiskCenter"));
const AdminRiskCenterPage = lazy(() => import("./pages/admin/RiskCenter"));
const EcosystemMarketplacePage = lazy(() => import("./pages/EcosystemMarketplace"));
const MarketplaceProductsPage = lazy(() => import("./pages/MarketplaceProducts"));
const AdminEcosystemPage = lazy(() => import("./pages/admin/Ecosystem"));
const SecurityCenterPage = lazy(() => import("./pages/SecurityCenter"));
const AdminSecurityCenterPage = lazy(() => import("./pages/admin/SecurityCenter"));
const AdminTrustPage = lazy(() => import("./pages/admin/Trust"));
const GovernancePage = lazy(() => import("./pages/Governance"));
const AdminModelGatewayPage = lazy(() => import("./pages/admin/ModelGateway"));
const AdminDecisionEnginePage = lazy(() => import("./pages/admin/DecisionEngine"));
const AdminRuntimePage = lazy(() => import("./pages/admin/Runtime"));
const AdminRealtimePage = lazy(() => import("./pages/admin/Realtime"));
const AdminOnboardingPage = lazy(() => import("./pages/admin/Onboarding"));
const AdminCapacityPage = lazy(() => import("./pages/admin/Capacity"));
const DeveloperToolsPage = lazy(() => import("./pages/DeveloperTools"));
const PlaygroundPage = lazy(() => import("./pages/Playground"));
const AdminPartnersPage = lazy(() => import("./pages/admin/Partners"));
const AdminEvalsLabPage = lazy(() => import("./pages/admin/EvalsLab"));
const AdminMeteringPage = lazy(() => import("./pages/admin/Metering"));
const AdminInferenceProxyPage = lazy(() => import("./pages/admin/InferenceProxy"));
const AdminRegionsPage = lazy(() => import("./pages/admin/Regions"));
const AdminCostGovernancePage = lazy(() => import("./pages/admin/CostGovernance"));
const AdminOpsCenterPage = lazy(() => import("./pages/admin/OpsCenter"));
const AdminModelHealthPage = lazy(() => import("./pages/admin/ModelHealth"));
const AdminRevenuePage = lazy(() => import("./pages/admin/Revenue"));
const AdminDataExportPage = lazy(() => import("./pages/admin/DataExport"));
const AdminTrustSafetyPage = lazy(() => import("./pages/admin/TrustSafety"));
const AdminTracesPage = lazy(() => import("./pages/admin/Traces"));
const AdminNotificationsPage = lazy(() => import("./pages/admin/Notifications"));
const NotificationsPage = lazy(() => import("./pages/Notifications"));
const AuditCompliancePage = lazy(() => import("./pages/AuditCompliance"));
const AdminCompliancePage = lazy(() => import("./pages/admin/Compliance"));
const AdminFeedbackPage = lazy(() => import("./pages/admin/Feedback"));
const AdminMigrationsPage = lazy(() => import("./pages/admin/Migrations"));
const AdminReleasesPage = lazy(() => import("./pages/admin/Releases"));
const ReleasesPage = lazy(() => import("./pages/Releases"));
const CopilotPage = lazy(() => import("./pages/Copilot"));
const AdminCopilotPage = lazy(() => import("./pages/admin/Copilot"));
const WorkflowsPage = lazy(() => import("./pages/Workflows"));
const WatchersPage = lazy(() => import("./pages/Watchers"));
const DemoCenterPage = lazy(() => import("./pages/DemoCenter"));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage"));
const IntelligencePage = lazy(() => import("./pages/Intelligence"));
const AssistantsPage = lazy(() => import("./pages/AssistantsPage"));
const AssistantDetailPage = lazy(() => import("./pages/AssistantDetailPage"));
const WorkflowNewPage = lazy(() => import("./pages/WorkflowNew"));
const AskZentPage = lazy(() => import("./pages/AskZentPage"));
const WorkflowStudioPage = lazy(() => import("./pages/WorkflowStudio"));
const MigrationsPage = lazy(() => import("./pages/Migrations"));
const OnboardingPage = lazy(() => import("./pages/Onboarding"));
const EvaluationDatasetsPage = lazy(() => import("./pages/evaluation/Datasets"));
const EvaluationOverviewPage = lazy(() => import("./pages/evaluation/Overview"));
const EvaluationRunsPage = lazy(() => import("./pages/evaluation/Runs"));
const EvaluationRunDetailPage = lazy(() => import("./pages/evaluation/RunDetail"));
const EvaluationComparePage = lazy(() => import("./pages/evaluation/Compare"));
const AiQualityPage = lazy(() => import("./pages/AiQuality"));
const DeploymentsPage = lazy(() => import("./pages/Deployments"));
const EnvironmentsPage = lazy(() => import("./pages/Environments"));
const DataSourcesPage = lazy(() => import("./pages/DataSources"));
const CompanyOverviewPage = lazy(
  () => import("./pages/companyIntelligence/Overview"),
);
const CompanyMapPage = lazy(() => import("./pages/companyIntelligence/CompanyMap"));
const CompanyEntitiesPage = lazy(
  () => import("./pages/companyIntelligence/Entities"),
);
const CompanyEntityDetailPage = lazy(
  () => import("./pages/companyIntelligence/EntityDetail"),
);
const CompanyRelationshipsPage = lazy(
  () => import("./pages/companyIntelligence/Relationships"),
);
const CompanySourceAuthorityPage = lazy(
  () => import("./pages/companyIntelligence/SourceAuthority"),
);
const CompanyKnowledgeGapsPage = lazy(
  () => import("./pages/companyIntelligence/KnowledgeGaps"),
);
const CompanyChangesPage = lazy(() => import("./pages/companyIntelligence/Changes"));
const CompanyInstitutionalPage = lazy(
  () => import("./pages/companyIntelligence/Institutional"),
);
const CompanyAskPage = lazy(() => import("./pages/companyIntelligence/Ask"));
const WebhooksPage = lazy(() => import("./pages/Webhooks"));
const TeamAccessPage = lazy(() => import("./pages/TeamAccess"));
const SecurityAuditPage = lazy(() => import("./pages/SecurityAudit"));
const McpPage = lazy(() => import("./pages/Mcp"));

function PageFallback() {
  return (
    <div className="mx-auto w-full max-w-[1360px] px-4 py-6 sm:px-6 lg:px-8">
      <PageSkeleton />
    </div>
  );
}

function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function ProtectedLayout() {
  const { session, ready, logout } = useAuth();
  const { pathname } = useLocation();
  // El estudio de workflows es un lienzo: necesita todo el ancho, sin max-w ni padding.
  const fullBleed = /^\/workflows\/[^/]+$/.test(pathname);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [signupKey, setSignupKey] = useState<string | null>(null);
  const [impersonationMeta, setImpersonationMeta] = useState<{
    tenant: string;
    reason?: string;
    expiresAt?: number;
  } | null>(null);
  const [nowTs, setNowTs] = useState(0);
  const pageControls = useAnimation();
  const reduceMotion = useReducedMotion();
  const lastPath = useRef<string | null>(null);

  // Entrada de página sin remount: anima el wrapper al cambiar de ruta.
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    if (reduceMotion) return;
    void pageControls.start({
      opacity: [0, 1],
      y: [4, 0],
      transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] },
    });
  }, [pathname, pageControls, reduceMotion]);
  const impersonating =
    typeof sessionStorage !== "undefined" ? sessionStorage.getItem(IMPERSONATING_KEY) : null;

  useEffect(() => {
    document.documentElement.setAttribute("data-sidebar", collapsed ? "collapsed" : "expanded");
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // sin persistencia
    }
  }, [collapsed]);

  useEffect(() => {
    setNowTs(Math.floor(Date.now() / 1000));
    const id = window.setInterval(() => setNowTs(Math.floor(Date.now() / 1000)), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (impersonating) {
      try {
        const raw = sessionStorage.getItem("zent_impersonation_meta");
        if (raw)
          setImpersonationMeta(
            JSON.parse(raw) as { tenant: string; reason?: string; expiresAt?: number }
          );
      } catch {
        setImpersonationMeta(null);
      }
    }
  }, [impersonating]);

  useEffect(() => {
    const key = sessionStorage.getItem(SIGNUP_API_KEY_STORAGE);
    if (key) setSignupKey(key);
  }, []);

  // Al cambiar de ruta se cierra la navegación móvil.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  async function exitImpersonation() {
    // FASE 09: revoca la sesión impersonada server-side y vuelve al Control Center.
    const current = loadSession();
    if (current?.token) {
      await api("/api/v1/auth/impersonation/exit", {
        method: "POST",
        token: current.token,
        organizationId: current.organizationId,
      }).catch(() => undefined);
    }
    sessionStorage.removeItem(IMPERSONATING_KEY);
    sessionStorage.removeItem("zent_impersonation_meta");
    clearSession();
    logout();
    window.location.assign("/control-center/tenants");
  }

  if (!ready) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center gap-3 text-muted">
        <span
          role="status"
          className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border-strong border-t-accent"
          aria-label="Cargando"
        />
        Cargando sesión…
      </div>
    );
  }
  if (!session) return <Navigate to="/login" replace />;
  if (session.needsStartMode) return <Navigate to="/onboarding/start" replace />;

  return (
    <EntitlementsProvider>
      <ToastProvider>
        <SyncJobProvider>
          {signupKey && (
            <ApiKeyCreatedModal
              apiKey={signupKey}
              onClose={() => {
                sessionStorage.removeItem(SIGNUP_API_KEY_STORAGE);
                setSignupKey(null);
              }}
            />
          )}
          <a href="#contenido" className="skip-link">
            Saltar al contenido
          </a>
          <ProductTourRoot
            session={session}
            blocked={Boolean(impersonating) || Boolean(signupKey)}
            layoutKey={navOpen}
            onTourActive={(active) => {
              if (active && !window.matchMedia("(min-width: 1024px)").matches) {
                setNavOpen(true);
              }
            }}
          />
          <div className="min-h-[100dvh]">
            <aside className="app-sidebar fixed inset-y-0 left-0 z-30 hidden border-r border-border bg-surface lg:block">
              <AppSidebar
                collapsed={collapsed}
                onToggleCollapsed={() => setCollapsed((v) => !v)}
                instanceId="desktop"
              />
            </aside>

            <div className="app-main flex min-h-[100dvh] min-w-0 flex-col">
              <Topbar
                sidebarCollapsed={collapsed}
                onExpandSidebar={() => setCollapsed(false)}
              />
              <DemoBanner />
              <TenantStepUpModal />

              <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-border bg-bg/90 px-4 py-2.5 backdrop-blur-md lg:hidden">
                <button
                  type="button"
                  className="btn btn-secondary btn-icon h-10 w-10 min-h-0"
                  aria-label="Abrir menú"
                  aria-expanded={navOpen}
                  onClick={() => setNavOpen(true)}
                >
                  <List size={18} aria-hidden />
                </button>
                <Brand compact />
                <span className="flex-1" />
                <button
                  type="button"
                  className="inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-sm border border-border bg-control text-muted"
                  onClick={() => openCommandPalette("tenant")}
                  aria-label="Buscar (Ctrl+K)"
                >
                  <MagnifyingGlass size={16} aria-hidden />
                </button>
              </header>

              <MobileNav open={navOpen} onOpenChange={setNavOpen} />

              <main
                id="contenido"
                className={
                  fullBleed
                    ? "flex w-full min-w-0 flex-1 flex-col px-3 py-3 sm:px-4"
                    : "mx-auto w-full max-w-[1360px] flex-1 px-4 py-6 sm:px-6 lg:px-8"
                }
              >
                <CommandPaletteRoot mode="tenant" />
                <IdleSessionWarning minutes={IDLE_SESSION_MINUTES} onLogout={logout} />
                {impersonating && (
                  <div
                    className="state-rail mb-5 flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-text"
                    data-state="failed"
                    role="status"
                  >
                    <span className="min-w-0">
                      <strong className="font-semibold text-danger">Modo impersonación</strong> — operando
                      como <span className="font-medium text-text">{impersonating}</span>
                      {impersonationMeta && (
                        <>
                          {impersonationMeta.reason && (
                            <span className="text-muted"> · motivo: {impersonationMeta.reason}</span>
                          )}
                          {impersonationMeta.expiresAt && (
                            <span className="mono text-muted">
                              {" "}
                              · expira en {Math.max(0, impersonationMeta.expiresAt - nowTs)}s
                            </span>
                          )}
                        </>
                      )}
                    </span>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      onClick={() => void exitImpersonation()}
                    >
                      Salir de impersonación
                    </button>
                  </div>
                )}
                <SyncBanner />
                <motion.div
                  animate={pageControls}
                  className={fullBleed ? "flex min-h-0 min-w-0 flex-1 flex-col" : undefined}
                >
                  <ErrorBoundary>
                    <Outlet />
                  </ErrorBoundary>
                </motion.div>
              </main>
            </div>
          </div>
        </SyncJobProvider>
      </ToastProvider>
    </EntitlementsProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Suspense fallback={<PageFallback />}><LoginPage /></Suspense>} />
      <Route path="/signup" element={<Suspense fallback={<PageFallback />}><SignupPage /></Suspense>} />
      <Route path="/onboarding/start" element={<Suspense fallback={<PageFallback />}><StartModePage /></Suspense>} />
        <Route path="/sso/callback" element={<Suspense fallback={<PageFallback />}><SsoCallbackPage /></Suspense>} />
        <Route path="/share/agent/:token" element={<Suspense fallback={<PageFallback />}><SharedAgentPage /></Suspense>} />
      <Route path="/admin/login" element={<Suspense fallback={<PageFallback />}><AdminLoginPage /></Suspense>} />
      <Route path="/control-center/login" element={<Suspense fallback={<PageFallback />}><AdminLoginPage /></Suspense>} />
      {/* Redirects legacy /admin → /control-center (backward compat) */}
      <Route path="/admin" element={<Navigate to="/control-center" replace />} />
      <Route path="/admin/customers" element={<Navigate to="/control-center/tenants" replace />} />
      <Route path="/admin/customers/:orgId" element={<Navigate to="/control-center/tenants/:orgId" replace />} />
      <Route path="/admin/plans" element={<Navigate to="/control-center/settings/plans" replace />} />
      <Route path="/admin/usage" element={<Navigate to="/control-center/costs" replace />} />
      <Route
        path="/control-center"
        element={
          <Suspense fallback={<PageFallback />}>
            <AdminLayout />
          </Suspense>
        }
      >
        <Route index element={<Suspense fallback={<PageFallback />}><AdminDashboardPage /></Suspense>} />
        <Route path="tenants" element={<Suspense fallback={<PageFallback />}><AdminCustomersPage /></Suspense>} />
        <Route path="tenants/:orgId" element={<Suspense fallback={<PageFallback />}><AdminCustomerDetailPage /></Suspense>} />
        <Route path="subscriptions" element={<Suspense fallback={<PageFallback />}><AdminSubscriptionsPage /></Suspense>} />
        <Route path="usage" element={<Suspense fallback={<PageFallback />}><AdminUsagePage /></Suspense>} />
        <Route path="costs" element={<Suspense fallback={<PageFallback />}><AdminFinOpsPage /></Suspense>} />
        <Route path="status" element={<Suspense fallback={<PageFallback />}><AdminSystemStatusPage /></Suspense>} />
        <Route path="dr" element={<Suspense fallback={<PageFallback />}><AdminDisasterRecoveryPage /></Suspense>} />
        <Route path="governance" element={<Suspense fallback={<PageFallback />}><AdminGovernancePage /></Suspense>} />
        <Route path="customers" element={<Suspense fallback={<PageFallback />}><AdminCustomerSuccessPage /></Suspense>} />
        <Route path="audit-intel" element={<Suspense fallback={<PageFallback />}><AdminAuditIntelligencePage /></Suspense>} />
        <Route path="optimizer" element={<Suspense fallback={<PageFallback />}><AdminOptimizerPage /></Suspense>} />
        <Route path="analytics" element={<Suspense fallback={<PageFallback />}><AdminFederatedAnalyticsPage /></Suspense>} />
        <Route path="marketplace" element={<Suspense fallback={<PageFallback />}><AdminMarketplacePage /></Suspense>} />
        <Route path="marketplace-factory" element={<Suspense fallback={<PageFallback />}><AdminMarketplaceFactoryPage /></Suspense>} />
        <Route path="workflows" element={<Suspense fallback={<PageFallback />}><AdminWorkflowsPage /></Suspense>} />
        <Route path="chat-insights" element={<Suspense fallback={<PageFallback />}><AdminChatInsightsPage /></Suspense>} />
        <Route path="knowledge-hub" element={<Suspense fallback={<PageFallback />}><AdminKnowledgeHubPage /></Suspense>} />
        <Route path="risk-center" element={<Suspense fallback={<PageFallback />}><AdminRiskCenterPage /></Suspense>} />
        <Route path="ecosystem" element={<Suspense fallback={<PageFallback />}><AdminEcosystemPage /></Suspense>} />
        <Route path="soc" element={<Suspense fallback={<PageFallback />}><AdminSecurityCenterPage /></Suspense>} />
        <Route path="trust" element={<Suspense fallback={<PageFallback />}><AdminTrustPage /></Suspense>} />
        <Route path="security-center" element={<Suspense fallback={<PageFallback />}><AdminSecurityCenterPage /></Suspense>} />
        <Route path="model-gateway" element={<Suspense fallback={<PageFallback />}><AdminModelGatewayPage /></Suspense>} />
        <Route path="decision-engine" element={<Suspense fallback={<PageFallback />}><AdminDecisionEnginePage /></Suspense>} />
        <Route path="ai-runtime" element={<Suspense fallback={<PageFallback />}><AdminRuntimePage /></Suspense>} />
        <Route path="realtime" element={<Suspense fallback={<PageFallback />}><AdminRealtimePage /></Suspense>} />
        <Route path="onboarding" element={<Suspense fallback={<PageFallback />}><AdminOnboardingPage /></Suspense>} />
        <Route path="capacity" element={<Suspense fallback={<PageFallback />}><AdminCapacityPage /></Suspense>} />
        <Route path="partners" element={<Suspense fallback={<PageFallback />}><AdminPartnersPage /></Suspense>} />
        <Route path="evals" element={<Suspense fallback={<PageFallback />}><AdminEvalsLabPage /></Suspense>} />
        <Route path="metering" element={<Suspense fallback={<PageFallback />}><AdminMeteringPage /></Suspense>} />
        <Route path="inference-proxy" element={<Suspense fallback={<PageFallback />}><AdminInferenceProxyPage /></Suspense>} />
        <Route path="regions" element={<Suspense fallback={<PageFallback />}><AdminRegionsPage /></Suspense>} />
        <Route path="cost-governance" element={<Suspense fallback={<PageFallback />}><AdminCostGovernancePage /></Suspense>} />
        <Route path="ops-center" element={<Suspense fallback={<PageFallback />}><AdminOpsCenterPage /></Suspense>} />
        <Route path="model-health" element={<Suspense fallback={<PageFallback />}><AdminModelHealthPage /></Suspense>} />
        <Route path="revenue" element={<Suspense fallback={<PageFallback />}><AdminRevenuePage /></Suspense>} />
        <Route path="data-export" element={<Suspense fallback={<PageFallback />}><AdminDataExportPage /></Suspense>} />
        <Route path="trust-safety" element={<Suspense fallback={<PageFallback />}><AdminTrustSafetyPage /></Suspense>} />
        <Route path="traces" element={<Suspense fallback={<PageFallback />}><AdminTracesPage /></Suspense>} />
        <Route path="notifications" element={<Suspense fallback={<PageFallback />}><AdminNotificationsPage /></Suspense>} />
        <Route path="compliance" element={<Suspense fallback={<PageFallback />}><AdminCompliancePage /></Suspense>} />
        <Route path="operations" element={<Suspense fallback={<PageFallback />}><AdminOperationsPage /></Suspense>} />
        <Route path="security" element={<Suspense fallback={<PageFallback />}><AdminSecurityPage /></Suspense>} />
        <Route path="audit" element={<Suspense fallback={<PageFallback />}><AdminAuditPage /></Suspense>} />
        <Route path="settings" element={<Suspense fallback={<PageFallback />}><AdminSettingsPage /></Suspense>} />
        <Route path="settings/plans" element={<Suspense fallback={<PageFallback />}><AdminPlansPage /></Suspense>} />
        <Route path="feedback" element={<Suspense fallback={<PageFallback />}><AdminFeedbackPage /></Suspense>} />
        <Route path="migrations" element={<Suspense fallback={<PageFallback />}><AdminMigrationsPage /></Suspense>} />
        <Route path="releases" element={<Suspense fallback={<PageFallback />}><AdminReleasesPage /></Suspense>} />
        <Route path="copilot" element={<Suspense fallback={<PageFallback />}><AdminCopilotPage /></Suspense>} />
        <Route path="*" element={<Navigate to="/control-center" replace />} />
      </Route>
      <Route element={<ProtectedLayout />}>
        {/* Aliases de producto */}
        <Route path="/overview" element={<Navigate to="/" replace />} />
        <Route path="/api-keys" element={<Navigate to="/keys" replace />} />
        <Route path="/analytics" element={<Navigate to="/usage" replace />} />
        <Route path="/agent-instructions" element={<Navigate to="/prompts" replace />} />
        <Route path="/users" element={<Navigate to="/team" replace />} />
        <Route path="/audit" element={<Navigate to="/security" replace />} />
        <Route path="/ingestion" element={<Navigate to="/knowledge/sql" replace />} />
        <Route path="/knowledge-bases" element={<Navigate to="/knowledge/collections" replace />} />
        <Route path="/" element={<Suspense fallback={<PageFallback />}><DashboardPage /></Suspense>} />
        <Route path="/usage" element={<Suspense fallback={<PageFallback />}><UsagePage /></Suspense>} />
        <Route path="/keys" element={<Suspense fallback={<PageFallback />}><KeysPage /></Suspense>} />
        <Route path="/webhooks" element={<Suspense fallback={<PageFallback />}><WebhooksPage /></Suspense>} />
        <Route path="/knowledge" element={<Suspense fallback={<PageFallback />}><KnowledgeOverviewPage /></Suspense>} />
        <Route path="/company-intelligence" element={<Suspense fallback={<PageFallback />}><CompanyOverviewPage /></Suspense>} />
        <Route path="/company-intelligence/map" element={<Suspense fallback={<PageFallback />}><CompanyMapPage /></Suspense>} />
        <Route path="/company-intelligence/concepts" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/processes" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/systems" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/data" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/rules" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/events" element={<Suspense fallback={<PageFallback />}><CompanyEntitiesPage /></Suspense>} />
        <Route path="/company-intelligence/relationships" element={<Suspense fallback={<PageFallback />}><CompanyRelationshipsPage /></Suspense>} />
        <Route path="/company-intelligence/authority" element={<Suspense fallback={<PageFallback />}><CompanySourceAuthorityPage /></Suspense>} />
        <Route path="/company-intelligence/gaps" element={<Suspense fallback={<PageFallback />}><CompanyKnowledgeGapsPage /></Suspense>} />
        <Route path="/company-intelligence/changes" element={<Suspense fallback={<PageFallback />}><CompanyChangesPage /></Suspense>} />
        <Route path="/company-intelligence/people" element={<Suspense fallback={<PageFallback />}><CompanyInstitutionalPage /></Suspense>} />
        <Route path="/company-intelligence/ask" element={<Suspense fallback={<PageFallback />}><CompanyAskPage /></Suspense>} />
        <Route path="/company-intelligence/entity/:entityId" element={<Suspense fallback={<PageFallback />}><CompanyEntityDetailPage /></Suspense>} />
        <Route path="/knowledge/learning" element={<Suspense fallback={<PageFallback />}><KnowledgeLearningPage /></Suspense>} />
        <Route path="/knowledge/map" element={<Suspense fallback={<PageFallback />}><KnowledgeMapPage /></Suspense>} />
        <Route path="/knowledge/understanding" element={<Suspense fallback={<PageFallback />}><KnowledgeUnderstandingPage /></Suspense>} />
        <Route path="/knowledge/add/:sessionId" element={<Suspense fallback={<PageFallback />}><KnowledgeOnboardingPage /></Suspense>} />
        <Route path="/knowledge/add" element={<Suspense fallback={<PageFallback />}><KnowledgeOnboardingPage /></Suspense>} />
        <Route path="/knowledge/sources/:sourceId" element={<Suspense fallback={<PageFallback />}><KnowledgeSourceDetailPage /></Suspense>} />
        <Route path="/knowledge/sources" element={<Suspense fallback={<PageFallback />}><KnowledgeSourcesPage /></Suspense>} />
        <Route path="/knowledge/database/import" element={<Suspense fallback={<PageFallback />}><KnowledgeManagedImportPage /></Suspense>} />
        <Route path="/knowledge/database" element={<Suspense fallback={<PageFallback />}><KnowledgeDatabasePage /></Suspense>} />
        <Route path="/onboarding/transition" element={<Suspense fallback={<PageFallback />}><TransitionWizardPage /></Suspense>} />
        <Route path="/knowledge/collections" element={<Suspense fallback={<PageFallback />}><KnowledgeCollectionsPage /></Suspense>} />
        <Route path="/knowledge/documents" element={<Suspense fallback={<PageFallback />}><KnowledgeDocumentsPage /></Suspense>} />
        <Route path="/knowledge/sql" element={<Suspense fallback={<PageFallback />}><KnowledgeSqlPage /></Suspense>} />
        <Route path="/knowledge/jobs" element={<Suspense fallback={<PageFallback />}><KnowledgeJobsPage /></Suspense>} />
        <Route path="/knowledge/playground" element={<Suspense fallback={<PageFallback />}><KnowledgePlaygroundPage /></Suspense>} />
        <Route path="/knowledge/workspaces/:corpusId" element={<Suspense fallback={<PageFallback />}><KnowledgeWorkspacePage /></Suspense>} />
        <Route path="/knowledge/workspaces" element={<Suspense fallback={<PageFallback />}><KnowledgeWorkspacesPage /></Suspense>} />
        <Route path="/knowledge/catalog" element={<Suspense fallback={<PageFallback />}><KnowledgeCatalogPage /></Suspense>} />
        <Route path="/knowledge/glossary" element={<Suspense fallback={<PageFallback />}><KnowledgeGlossaryPage /></Suspense>} />
<Route path="/knowledge/review" element={<Suspense fallback={<PageFallback />}><KnowledgeReviewPage /></Suspense>} />
        <Route path="/knowledge/improvements" element={<Suspense fallback={<PageFallback />}><KnowledgeImprovementsPage /></Suspense>} />
        <Route path="/prompts" element={<Suspense fallback={<PageFallback />}><PromptsPage /></Suspense>} />
        <Route path="/chat" element={<Suspense fallback={<PageFallback />}><ChatPage /></Suspense>} />
        <Route path="/team" element={<Suspense fallback={<PageFallback />}><TeamAccessPage /></Suspense>} />
        <Route path="/projects" element={<Suspense fallback={<PageFallback />}><ProjectsPage /></Suspense>} />
        <Route path="/workspaces" element={<Suspense fallback={<PageFallback />}><WorkspacesPage /></Suspense>} />
        <Route path="/training" element={<Suspense fallback={<PageFallback />}><TrainingPage /></Suspense>} />
        <Route path="/developers" element={<Suspense fallback={<PageFallback />}><DeveloperCenterPage /></Suspense>} />
        <Route path="/developers/mcp" element={<Suspense fallback={<PageFallback />}><McpPage /></Suspense>} />
        <Route path="/developers/tools" element={<Suspense fallback={<PageFallback />}><DeveloperToolsPage /></Suspense>} />
        <Route path="/developers/playground" element={<Suspense fallback={<PageFallback />}><PlaygroundPage /></Suspense>} />
        <Route path="/agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
        <Route path="/agents/new" element={<Suspense fallback={<PageFallback />}><AgentStudioPage /></Suspense>} />
        <Route path="/agents/:id/builder" element={<Suspense fallback={<PageFallback />}><AgentBuilderRedirectPage /></Suspense>} />
        <Route path="/agents/:id" element={<Suspense fallback={<PageFallback />}><AgentStudioPage /></Suspense>} />
        <Route path="/connectors" element={<Suspense fallback={<PageFallback />}><ConnectorsPage /></Suspense>} />
        <Route path="/billing" element={<Suspense fallback={<PageFallback />}><BillingPage /></Suspense>} />
        <Route path="/ai-quality" element={<Suspense fallback={<PageFallback />}><AiQualityPage /></Suspense>} />
        <Route path="/deployments" element={<Suspense fallback={<PageFallback />}><DeploymentsPage /></Suspense>} />
              <Route path="/environments" element={<Suspense fallback={<PageFallback />}><EnvironmentsPage /></Suspense>} />
        <Route path="/data-sources" element={<Suspense fallback={<PageFallback />}><DataSourcesPage /></Suspense>} />
        <Route path="/security" element={<Suspense fallback={<PageFallback />}><SecurityAuditPage /></Suspense>} />
        <Route path="/audit/compliance" element={<Suspense fallback={<PageFallback />}><AuditCompliancePage /></Suspense>} />
        <Route path="/notifications" element={<Suspense fallback={<PageFallback />}><NotificationsPage /></Suspense>} />
        <Route path="/onboarding" element={<Suspense fallback={<PageFallback />}><OnboardingPage /></Suspense>} />
        <Route path="/migrations" element={<Suspense fallback={<PageFallback />}><MigrationsPage /></Suspense>} />
        <Route path="/releases" element={<Suspense fallback={<PageFallback />}><ReleasesPage /></Suspense>} />
        <Route path="/copilot" element={<Suspense fallback={<PageFallback />}><CopilotPage /></Suspense>} />
        <Route path="/workflows" element={<Suspense fallback={<PageFallback />}><WorkflowsPage /></Suspense>} />
        <Route path="/watchers" element={<Suspense fallback={<PageFallback />}><WatchersPage /></Suspense>} />
        <Route path="/demos" element={<Suspense fallback={<PageFallback />}><DemoCenterPage /></Suspense>} />
        <Route path="/integrations" element={<Suspense fallback={<PageFallback />}><IntegrationsPage /></Suspense>} />
        <Route path="/assistants" element={<Suspense fallback={<PageFallback />}><AssistantsPage /></Suspense>} />
        <Route path="/assistants/:id" element={<Suspense fallback={<PageFallback />}><AssistantDetailPage /></Suspense>} />
        <Route path="/intelligence" element={<Suspense fallback={<PageFallback />}><IntelligencePage /></Suspense>} />
        <Route path="/workflows/new" element={<Suspense fallback={<PageFallback />}><WorkflowNewPage /></Suspense>} />
        <Route path="/workflows/new/ask" element={<Suspense fallback={<PageFallback />}><AskZentPage /></Suspense>} />
        <Route path="/workflows/new/manual" element={<Suspense fallback={<PageFallback />}><WorkflowStudioPage /></Suspense>} />
        <Route path="/workflows/:id" element={<Suspense fallback={<PageFallback />}><WorkflowStudioPage /></Suspense>} />
        <Route path="/chat-insights" element={<Suspense fallback={<PageFallback />}><ChatInsightsPage /></Suspense>} />
        <Route path="/knowledge-hub" element={<Suspense fallback={<PageFallback />}><KnowledgeHubPage /></Suspense>} />
        <Route path="/risk-center" element={<Suspense fallback={<PageFallback />}><RiskCenterPage /></Suspense>} />
        <Route path="/marketplace" element={<Suspense fallback={<PageFallback />}><EcosystemMarketplacePage /></Suspense>} />
<Route path="/products" element={<Suspense fallback={<PageFallback />}><MarketplaceProductsPage /></Suspense>} />
        <Route path="/security-center" element={<Suspense fallback={<PageFallback />}><SecurityCenterPage /></Suspense>} />
        <Route path="/governance" element={<Suspense fallback={<PageFallback />}><GovernancePage /></Suspense>} />
        <Route path="/disaster-recovery" element={<Suspense fallback={<PageFallback />}><DisasterRecoveryPage /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={<PageFallback />}><SettingsPage /></Suspense>} />
        <Route path="/evaluation" element={<Suspense fallback={<PageFallback />}><EvaluationOverviewPage /></Suspense>} />
        <Route path="/evaluation/datasets" element={<Suspense fallback={<PageFallback />}><EvaluationDatasetsPage /></Suspense>} />
        <Route path="/evaluation/runs" element={<Suspense fallback={<PageFallback />}><EvaluationRunsPage /></Suspense>} />
        <Route path="/evaluation/runs/:runId" element={<Suspense fallback={<PageFallback />}><EvaluationRunDetailPage /></Suspense>} />
<Route path="/evaluation/compare" element={<Suspense fallback={<PageFallback />}><EvaluationComparePage /></Suspense>} />
        <Route path="/evaluation/gaps" element={<Suspense fallback={<PageFallback />}><EvaluationGapsPage /></Suspense>} />
        <Route path="/evaluation/impact" element={<Suspense fallback={<PageFallback />}><EvaluationImpactPage /></Suspense>} />
        <Route path="/evaluation/playground-compare" element={<Navigate to="/evaluation/compare" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
