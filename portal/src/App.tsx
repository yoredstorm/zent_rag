import {
  Bell,
  Books,
  Buildings,
  ChartBar,
  ChartLineUp,
  ChatCircleDots,
  ChatsCircle,
  ClipboardText,
  Code,
  Compass,
  CreditCard,
  Database,
  FolderSimple,
  FlowArrow,
  Gear,
  GraduationCap,
  Key,
  Lifebuoy,
  List,
  NotePencil,
  Plugs,
  Robot,
  Rocket,
  RocketLaunch,
  Scales,
  ShieldCheck,
  ShieldStar,
  SignOut,
  Sparkle,
  SquaresFour,
  Storefront,
  Swap,
  Target,
  WarningOctagon,
  UsersThree,
  WebhooksLogo,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { ApiKeyCreatedModal } from "./components/ApiKeyCreatedModal";
import { Topbar } from "./components/Topbar";
import { WorkspaceSelector } from "./components/WorkspaceSelector";
import { api, SIGNUP_API_KEY_STORAGE, type Session } from "./api";
import { useAuth } from "./auth";
import { IMPERSONATING_KEY } from "./platformAuth";
import { SyncBanner, SyncJobProvider } from "./syncJob";
import { ToastProvider } from "./Toast";

const ChatPage = lazy(() => import("./pages/Chat"));
const DashboardPage = lazy(() => import("./pages/Dashboard"));
const KeysPage = lazy(() => import("./pages/Keys"));
const LoginPage = lazy(() => import("./pages/Login"));
const PromptsPage = lazy(() => import("./pages/Prompts"));
const SignupPage = lazy(() => import("./pages/Signup"));
const UsagePage = lazy(() => import("./pages/Usage"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const AgentsPage = lazy(() => import("./pages/Agents"));
const AgentBuilderPage = lazy(() => import("./pages/AgentBuilder"));
const ConnectorsPage = lazy(() => import("./pages/Connectors"));
const BillingPage = lazy(() => import("./pages/Billing"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const KnowledgeSourcesPage = lazy(() => import("./pages/knowledge/Sources"));
const KnowledgeCollectionsPage = lazy(() => import("./pages/knowledge/Collections"));
const KnowledgeDocumentsPage = lazy(() => import("./pages/knowledge/Documents"));
const KnowledgeSqlPage = lazy(() => import("./pages/knowledge/SqlSources"));
const KnowledgeJobsPage = lazy(() => import("./pages/knowledge/Jobs"));
const KnowledgePlaygroundPage = lazy(() => import("./pages/knowledge/Playground"));
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
const SharedAgentPage = lazy(() => import("./pages/SharedAgent"));
const AdminWorkflowsPage = lazy(() => import("./pages/admin/Workflows"));
const ChatInsightsPage = lazy(() => import("./pages/ChatInsights"));
const AdminChatInsightsPage = lazy(() => import("./pages/admin/ChatInsights"));
const KnowledgeHubPage = lazy(() => import("./pages/KnowledgeHub"));
const AdminKnowledgeHubPage = lazy(() => import("./pages/admin/KnowledgeHub"));
const RiskCenterPage = lazy(() => import("./pages/RiskCenter"));
const AdminRiskCenterPage = lazy(() => import("./pages/admin/RiskCenter"));
const EcosystemMarketplacePage = lazy(() => import("./pages/EcosystemMarketplace"));
const AdminEcosystemPage = lazy(() => import("./pages/admin/Ecosystem"));
const SecurityCenterPage = lazy(() => import("./pages/SecurityCenter"));
const AdminSecurityCenterPage = lazy(() => import("./pages/admin/SecurityCenter"));
const GovernancePage = lazy(() => import("./pages/Governance"));
const AdminModelGatewayPage = lazy(() => import("./pages/admin/ModelGateway"));
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
const MigrationsPage = lazy(() => import("./pages/Migrations"));
const OnboardingPage = lazy(() => import("./pages/Onboarding"));
const EvaluationDatasetsPage = lazy(() => import("./pages/evaluation/Datasets"));
const EvaluationOverviewPage = lazy(() => import("./pages/evaluation/Overview"));
const EvaluationRunsPage = lazy(() => import("./pages/evaluation/Runs"));
const EvaluationRunDetailPage = lazy(() => import("./pages/evaluation/RunDetail"));
const EvaluationComparePage = lazy(() => import("./pages/evaluation/Compare"));
const AiQualityPage = lazy(() => import("./pages/AiQuality"));
const DeploymentsPage = lazy(() => import("./pages/Deployments"));
const DataSourcesPage = lazy(() => import("./pages/DataSources"));
const WebhooksPage = lazy(() => import("./pages/Webhooks"));
const TeamAccessPage = lazy(() => import("./pages/TeamAccess"));
const SecurityAuditPage = lazy(() => import("./pages/SecurityAudit"));

function PageFallback() {
  return (
    <div className="flex justify-center py-16">
      <span
        className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-border-strong border-t-accent"
        aria-label="Cargando"
      />
    </div>
  );
}

type Entitlements = Record<string, boolean | number | null>;

type NavLeaf = { to: string; label: string; icon: Icon; end?: boolean; key?: string };
type NavGroup = { label: string | null; items: NavLeaf[]; collapsible?: boolean };

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Panel general",
    items: [
      { to: "/", label: "Panel general", icon: SquaresFour, end: true },
      { to: "/chat", label: "Playground", icon: ChatCircleDots },
    ],
  },
  {
    label: "Construir",
    items: [
      { to: "/agents", label: "Agentes", icon: Robot },
      { to: "/knowledge/sources", label: "Conocimiento", icon: Database },
      { to: "/data-sources", label: "Fuentes de datos", icon: Plugs },
      { to: "/prompts", label: "Instrucciones", icon: NotePencil, key: "prompts" },
    ],
  },
  {
    label: "Operar",
    items: [
      { to: "/usage", label: "Analítica", icon: ChartLineUp },
      { to: "/ai-quality", label: "Calidad de IA", icon: Target },
      { to: "/deployments", label: "Despliegues", icon: RocketLaunch },
    ],
  },
  {
    label: "Desarrolladores",
    items: [
      { to: "/keys", label: "API y Claves", icon: Key, key: "keys" },
      { to: "/webhooks", label: "Webhooks", icon: WebhooksLogo, key: "keys" },
      { to: "/developers", label: "Centro de desarrolladores", icon: Code },
    ],
  },
  {
    label: "Organización",
    items: [
      { to: "/team", label: "Equipo y Acceso", icon: UsersThree, key: "users" },
      { to: "/billing", label: "Facturación", icon: CreditCard, key: "billing" },
      { to: "/security", label: "Seguridad y Auditoría", icon: ShieldCheck, key: "audit" },
      { to: "/settings", label: "Configuración", icon: Gear, key: "settings" },
    ],
  },
  {
    label: "Avanzado",
    collapsible: true,
    items: [
      { to: "/projects", label: "Proyectos", icon: FolderSimple },
      { to: "/evaluation", label: "Evaluación", icon: ChartBar, key: "eval_ui" },
      { to: "/connectors", label: "Conectores", icon: Plugs, key: "connectors" },
      { to: "/workspaces", label: "Workspaces", icon: Buildings },
      { to: "/security-center", label: "Security Center", icon: ShieldStar },
      { to: "/governance", label: "Gobernanza", icon: Scales },
      { to: "/risk-center", label: "Risk Center", icon: WarningOctagon },
      { to: "/knowledge-hub", label: "Knowledge Hub", icon: Books },
      { to: "/workflows", label: "Workflows", icon: FlowArrow },
      { to: "/chat-insights", label: "Chat Insights", icon: ChatsCircle },
      { to: "/copilot", label: "Copilot", icon: Sparkle },
      { to: "/marketplace", label: "Marketplace", icon: Storefront },
      { to: "/migrations", label: "Migraciones", icon: Swap },
      { to: "/releases", label: "Releases", icon: Rocket },
      { to: "/training", label: "Training", icon: GraduationCap },
      { to: "/onboarding", label: "Onboarding", icon: Compass },
      { to: "/disaster-recovery", label: "Disaster Recovery", icon: Lifebuoy },
      { to: "/audit/compliance", label: "Audit Compliance", icon: ClipboardText },
      { to: "/notifications", label: "Notificaciones", icon: Bell },
    ],
  },
];

function isViewerOnly(roles: string[] | undefined): boolean {
  const r = roles || [];
  if (r.some((role) => role === "owner" || role === "admin" || role === "member")) {
    return false;
  }
  return r.includes("viewer");
}

function canSeeNavItem(
  session: Session | null,
  key?: string,
  entitlements: Entitlements = {}
): boolean {
  if (!key) return true;
  const roles = session?.roles || [];
  const perms = session?.permissions || [];
  const orgAdmin = roles.includes("owner") || roles.includes("admin");
  if (key === "users" || key === "keys") return orgAdmin;
  if (key === "billing" || key === "settings") return orgAdmin;
  if (key === "audit") return orgAdmin || perms.includes("audit:read");
  if (key === "prompts" || key === "connectors") return !isViewerOnly(roles);
  if (key === "eval_ui") return entitlements.eval_ui === true;
  return true;
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-8 w-8 items-center justify-center rounded-md border border-accent/30 bg-accent-soft shadow-glow">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M4 6.5 12 3l8 3.5v6.2c0 4.6-3.2 7.8-8 9.3-4.8-1.5-8-4.7-8-9.3V6.5Z"
            stroke="var(--color-accent)"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
          <path
            d="m8.5 12.5 2.4 2.4 4.6-4.9"
            stroke="var(--color-accent)"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <span className="text-[15px] font-semibold tracking-tight text-text">
        Zent
      </span>
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { session, logout } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [entitlements, setEntitlements] = useState<Entitlements>({});
  const identity =
    session?.email || session?.companyName || session?.organizationId.slice(0, 8) || "";

  useEffect(() => {
    if (!session) return;
    api<{ entitlements: Entitlements }>("/api/v1/billing/entitlements", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => setEntitlements(out.entitlements || {}))
      .catch(() => setEntitlements({}));
  }, [session]);

  const groups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => canSeeNavItem(session, item.key, entitlements)),
      })).filter((group) => group.items.length > 0),
    [session, entitlements]
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-3 px-5 pt-5 pb-4">
        <Brand />
        <WorkspaceSelector />
      </div>
      <nav className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3" aria-label="Principal">
        {groups.map((group) => {
          if (group.collapsible) {
            return (
              <div key={group.label || "root"}>
                <button
                  type="button"
                  className="mb-1 flex w-full items-center justify-between rounded-xs px-2.5 py-1 text-[10px] font-semibold tracking-wider text-faint uppercase transition-colors duration-150 hover:text-muted"
                  aria-expanded={advancedOpen}
                  onClick={() => setAdvancedOpen((v) => !v)}
                >
                  {group.label}
                  <span
                    className={`transition-transform duration-150 ${advancedOpen ? "rotate-90" : ""}`}
                    aria-hidden
                  >
                    ▸
                  </span>
                </button>
                {advancedOpen && (
                  <div className="flex flex-col gap-0.5">
                    {group.items.map(({ to, label, icon: IconEl, end }) => (
                      <NavLink
                        key={to}
                        to={to}
                        end={end}
                        onClick={onNavigate}
                        className={({ isActive }) =>
                          `group flex min-h-9 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-150 ${
                            isActive
                              ? "bg-accent-soft font-medium text-accent"
                              : "text-muted hover:bg-soft hover:text-text"
                          }`
                        }
                      >
                        {({ isActive }) => (
                          <>
                            <IconEl
                              size={16}
                              weight={isActive ? "fill" : "regular"}
                              aria-hidden
                            />
                            <span className="truncate">{label}</span>
                          </>
                        )}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          }
          return (
            <div key={group.label || "root"}>
              {group.label && (
                <p className="mb-1 px-2.5 text-[10px] font-semibold tracking-wider text-faint uppercase">
                  {group.label}
                </p>
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map(({ to, label, icon: IconEl, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `group flex min-h-9 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-150 ${
                        isActive
                          ? "bg-accent-soft font-medium text-accent"
                          : "text-muted hover:bg-soft hover:text-text"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <IconEl
                          size={16}
                          weight={isActive ? "fill" : "regular"}
                          aria-hidden
                        />
                        <span className="truncate">{label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>
      <div className="border-t border-border p-4">
        <p className="mb-3 truncate text-xs text-faint" title={identity}>
          {identity}
        </p>
        {confirming ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-danger flex-1 px-2 py-1.5 text-xs"
              onClick={logout}
            >
              Sí, salir
            </button>
            <button
              type="button"
              className="btn btn-secondary flex-1 px-2 py-1.5 text-xs"
              onClick={() => setConfirming(false)}
            >
              Cancelar
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn-ghost w-full justify-start gap-2 px-2 py-1.5 text-[13px]"
            onClick={() => setConfirming(true)}
          >
            <SignOut size={16} aria-hidden />
            Cerrar sesión
          </button>
        )}
      </div>
    </div>
  );
}

function ProtectedLayout() {
  const { session, ready, logout } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [signupKey, setSignupKey] = useState<string | null>(null);
  const impersonating =
    typeof localStorage !== "undefined" ? localStorage.getItem(IMPERSONATING_KEY) : null;

  useEffect(() => {
    const key = sessionStorage.getItem(SIGNUP_API_KEY_STORAGE);
    if (key) setSignupKey(key);
  }, []);

  if (!ready) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center gap-3 text-muted">
        <span
          className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border-strong border-t-accent"
          aria-label="Cargando"
        />
        Cargando sesión…
      </div>
    );
  }
  if (!session) return <Navigate to="/login" replace />;

  return (
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
        <div className="min-h-[100dvh] lg:pl-[248px]">
          <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-border bg-surface/70 backdrop-blur-xl lg:block">
            <SidebarContent />
          </aside>

          <div className="flex min-h-[100dvh] flex-col">
            <Topbar />

            <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-border bg-bg/85 px-4 py-3 backdrop-blur-md lg:hidden">
              <button
                type="button"
                className="btn btn-secondary min-h-11 px-2.5"
                aria-label="Abrir menú"
                aria-expanded={drawerOpen}
                onClick={() => setDrawerOpen(true)}
              >
                <List size={18} aria-hidden />
              </button>
              <Brand />
            </header>

            {drawerOpen && (
              <div className="fixed inset-0 z-40 lg:hidden">
                <div
                  className="absolute inset-0 animate-fade-in bg-black/60"
                  onClick={() => setDrawerOpen(false)}
                  aria-hidden
                />
                <div className="absolute inset-y-0 left-0 w-[280px] animate-page-in border-r border-border bg-surface shadow-pop">
                  <button
                    type="button"
                    className="absolute top-4 right-4 min-h-11 min-w-11 cursor-pointer rounded-xs p-1 text-faint hover:bg-soft hover:text-text"
                    aria-label="Cerrar menú"
                    onClick={() => setDrawerOpen(false)}
                  >
                    <X size={18} aria-hidden />
                  </button>
                  <SidebarContent onNavigate={() => setDrawerOpen(false)} />
                </div>
              </div>
            )}

            <main id="contenido" className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-6 lg:px-10">
              {impersonating && (
                <div
                  className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-text"
                  role="status"
                >
                  <span>Estás impersonando {impersonating}.</span>
                  <button
                    type="button"
                    className="btn btn-secondary min-h-11"
                    onClick={() => {
                      localStorage.removeItem(IMPERSONATING_KEY);
                      logout();
                      window.location.assign("/admin/customers");
                    }}
                  >
                    Volver al Control Center
                  </button>
                </div>
              )}
              <SyncBanner />
              <div className="animate-page-in">
                <ErrorBoundary>
                  <Outlet />
                </ErrorBoundary>
              </div>
            </main>
          </div>
        </div>
      </SyncJobProvider>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Suspense fallback={<PageFallback />}><LoginPage /></Suspense>} />
      <Route path="/signup" element={<Suspense fallback={<PageFallback />}><SignupPage /></Suspense>} />
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
        <Route path="workflows" element={<Suspense fallback={<PageFallback />}><AdminWorkflowsPage /></Suspense>} />
        <Route path="chat-insights" element={<Suspense fallback={<PageFallback />}><AdminChatInsightsPage /></Suspense>} />
        <Route path="knowledge-hub" element={<Suspense fallback={<PageFallback />}><AdminKnowledgeHubPage /></Suspense>} />
        <Route path="risk-center" element={<Suspense fallback={<PageFallback />}><AdminRiskCenterPage /></Suspense>} />
        <Route path="ecosystem" element={<Suspense fallback={<PageFallback />}><AdminEcosystemPage /></Suspense>} />
        <Route path="soc" element={<Suspense fallback={<PageFallback />}><AdminSecurityCenterPage /></Suspense>} />
        <Route path="security-center" element={<Suspense fallback={<PageFallback />}><AdminSecurityCenterPage /></Suspense>} />
        <Route path="model-gateway" element={<Suspense fallback={<PageFallback />}><AdminModelGatewayPage /></Suspense>} />
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
        <Route path="/knowledge/sources" element={<Suspense fallback={<PageFallback />}><KnowledgeSourcesPage /></Suspense>} />
        <Route path="/knowledge/collections" element={<Suspense fallback={<PageFallback />}><KnowledgeCollectionsPage /></Suspense>} />
        <Route path="/knowledge/documents" element={<Suspense fallback={<PageFallback />}><KnowledgeDocumentsPage /></Suspense>} />
        <Route path="/knowledge/sql" element={<Suspense fallback={<PageFallback />}><KnowledgeSqlPage /></Suspense>} />
        <Route path="/knowledge/jobs" element={<Suspense fallback={<PageFallback />}><KnowledgeJobsPage /></Suspense>} />
        <Route path="/knowledge/playground" element={<Suspense fallback={<PageFallback />}><KnowledgePlaygroundPage /></Suspense>} />
        <Route path="/prompts" element={<Suspense fallback={<PageFallback />}><PromptsPage /></Suspense>} />
        <Route path="/chat" element={<Suspense fallback={<PageFallback />}><ChatPage /></Suspense>} />
        <Route path="/team" element={<Suspense fallback={<PageFallback />}><TeamAccessPage /></Suspense>} />
        <Route path="/projects" element={<Suspense fallback={<PageFallback />}><ProjectsPage /></Suspense>} />
        <Route path="/workspaces" element={<Suspense fallback={<PageFallback />}><WorkspacesPage /></Suspense>} />
        <Route path="/training" element={<Suspense fallback={<PageFallback />}><TrainingPage /></Suspense>} />
        <Route path="/developers" element={<Suspense fallback={<PageFallback />}><DeveloperCenterPage /></Suspense>} />
        <Route path="/developers/tools" element={<Suspense fallback={<PageFallback />}><DeveloperToolsPage /></Suspense>} />
        <Route path="/developers/playground" element={<Suspense fallback={<PageFallback />}><PlaygroundPage /></Suspense>} />
        <Route path="/agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
        <Route path="/agents/new" element={<Suspense fallback={<PageFallback />}><AgentBuilderPage /></Suspense>} />
        <Route path="/agents/:id" element={<Suspense fallback={<PageFallback />}><AgentBuilderPage /></Suspense>} />
        <Route path="/connectors" element={<Suspense fallback={<PageFallback />}><ConnectorsPage /></Suspense>} />
        <Route path="/billing" element={<Suspense fallback={<PageFallback />}><BillingPage /></Suspense>} />
        <Route path="/ai-quality" element={<Suspense fallback={<PageFallback />}><AiQualityPage /></Suspense>} />
        <Route path="/deployments" element={<Suspense fallback={<PageFallback />}><DeploymentsPage /></Suspense>} />
        <Route path="/data-sources" element={<Suspense fallback={<PageFallback />}><DataSourcesPage /></Suspense>} />
        <Route path="/security" element={<Suspense fallback={<PageFallback />}><SecurityAuditPage /></Suspense>} />
        <Route path="/audit/compliance" element={<Suspense fallback={<PageFallback />}><AuditCompliancePage /></Suspense>} />
        <Route path="/notifications" element={<Suspense fallback={<PageFallback />}><NotificationsPage /></Suspense>} />
        <Route path="/onboarding" element={<Suspense fallback={<PageFallback />}><OnboardingPage /></Suspense>} />
        <Route path="/migrations" element={<Suspense fallback={<PageFallback />}><MigrationsPage /></Suspense>} />
        <Route path="/releases" element={<Suspense fallback={<PageFallback />}><ReleasesPage /></Suspense>} />
        <Route path="/copilot" element={<Suspense fallback={<PageFallback />}><CopilotPage /></Suspense>} />
        <Route path="/workflows" element={<Suspense fallback={<PageFallback />}><WorkflowsPage /></Suspense>} />
        <Route path="/chat-insights" element={<Suspense fallback={<PageFallback />}><ChatInsightsPage /></Suspense>} />
        <Route path="/knowledge-hub" element={<Suspense fallback={<PageFallback />}><KnowledgeHubPage /></Suspense>} />
        <Route path="/risk-center" element={<Suspense fallback={<PageFallback />}><RiskCenterPage /></Suspense>} />
        <Route path="/marketplace" element={<Suspense fallback={<PageFallback />}><EcosystemMarketplacePage /></Suspense>} />
        <Route path="/security-center" element={<Suspense fallback={<PageFallback />}><SecurityCenterPage /></Suspense>} />
        <Route path="/governance" element={<Suspense fallback={<PageFallback />}><GovernancePage /></Suspense>} />
        <Route path="/disaster-recovery" element={<Suspense fallback={<PageFallback />}><DisasterRecoveryPage /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={<PageFallback />}><SettingsPage /></Suspense>} />
        <Route path="/evaluation" element={<Suspense fallback={<PageFallback />}><EvaluationOverviewPage /></Suspense>} />
        <Route path="/evaluation/datasets" element={<Suspense fallback={<PageFallback />}><EvaluationDatasetsPage /></Suspense>} />
        <Route path="/evaluation/runs" element={<Suspense fallback={<PageFallback />}><EvaluationRunsPage /></Suspense>} />
        <Route path="/evaluation/runs/:runId" element={<Suspense fallback={<PageFallback />}><EvaluationRunDetailPage /></Suspense>} />
        <Route path="/evaluation/compare" element={<Suspense fallback={<PageFallback />}><EvaluationComparePage /></Suspense>} />
        <Route path="/evaluation/playground-compare" element={<Navigate to="/evaluation/compare" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}