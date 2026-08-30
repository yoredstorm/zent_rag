import {
  ChartBar,
  ChatCircleDots,
  CreditCard,
  Database,
  Files,
  FolderSimple,
  Gear,
  Key,
  List,
  MagnifyingGlass,
  NotePencil,
  Plugs,
  SignOut,
  SquaresFour,
  UsersThree,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { ApiKeyCreatedModal } from "./components/ApiKeyCreatedModal";
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
const UsersPage = lazy(() => import("./pages/Users"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const AgentsPage = lazy(() => import("./pages/Agents"));
const AgentBuilderPage = lazy(() => import("./pages/AgentBuilder"));
const ConnectorsPage = lazy(() => import("./pages/Connectors"));
const AuditLogsPage = lazy(() => import("./pages/AuditLogs"));
const BillingPage = lazy(() => import("./pages/Billing"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const KnowledgeSourcesPage = lazy(() => import("./pages/knowledge/Sources"));
const KnowledgeCollectionsPage = lazy(() => import("./pages/knowledge/Collections"));
const KnowledgeDocumentsPage = lazy(() => import("./pages/knowledge/Documents"));
const KnowledgeSqlPage = lazy(() => import("./pages/knowledge/SqlSources"));
const KnowledgeJobsPage = lazy(() => import("./pages/knowledge/Jobs"));
const KnowledgePlaygroundPage = lazy(() => import("./pages/knowledge/Playground"));
const AdminLayout = lazy(() => import("./pages/admin/AdminLayout"));
const AdminLoginPage = lazy(() => import("./pages/admin/Login"));
const AdminDashboardPage = lazy(() => import("./pages/admin/Dashboard"));
const AdminCustomersPage = lazy(() => import("./pages/admin/Customers"));
const AdminCustomerDetailPage = lazy(() => import("./pages/admin/CustomerDetail"));
const AdminPlansPage = lazy(() => import("./pages/admin/Plans"));
const AdminUsagePage = lazy(() => import("./pages/admin/Usage"));
const EvaluationDatasetsPage = lazy(() => import("./pages/evaluation/Datasets"));
const EvaluationRunsPage = lazy(() => import("./pages/evaluation/Runs"));
const EvaluationRunDetailPage = lazy(() => import("./pages/evaluation/RunDetail"));
const EvaluationComparePage = lazy(() => import("./pages/evaluation/Compare"));

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
type NavGroup = { label: string | null; items: NavLeaf[] };

const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { to: "/", label: "Dashboard", icon: SquaresFour, end: true },
      { to: "/chat", label: "Chat", icon: ChatCircleDots },
    ],
  },
  {
    label: "Conocimiento",
    items: [
      { to: "/knowledge/sources", label: "Fuentes", icon: Database },
      { to: "/knowledge/collections", label: "Colecciones", icon: FolderSimple },
      { to: "/knowledge/documents", label: "Documentos", icon: Files },
      { to: "/knowledge/sql", label: "Fuentes SQL", icon: Database },
      { to: "/knowledge/jobs", label: "Trabajos de sync", icon: List },
      { to: "/knowledge/playground", label: "Playground de búsqueda", icon: MagnifyingGlass },
    ],
  },
  {
    label: "Espacio de trabajo",
    items: [
      { to: "/projects", label: "Proyectos", icon: SquaresFour },
      { to: "/agents", label: "Agentes", icon: ChatCircleDots },
      { to: "/evaluation", label: "Evaluación", icon: ChartBar, key: "eval_ui" },
      { to: "/connectors", label: "Conectores", icon: Plugs, key: "connectors" },
      { to: "/prompts", label: "Prompts", icon: NotePencil, key: "prompts" },
    ],
  },
  {
    label: "Cuenta",
    items: [
      { to: "/users", label: "Usuarios", icon: UsersThree, key: "users" },
      { to: "/keys", label: "Claves", icon: Key, key: "keys" },
      { to: "/usage", label: "Uso", icon: ChartBar },
      { to: "/billing", label: "Facturación", icon: CreditCard, key: "billing" },
      { to: "/audit", label: "Auditoría", icon: List, key: "audit" },
      { to: "/settings", label: "Ajustes", icon: Gear, key: "settings" },
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
        Zent<span className="text-accent">RAG</span>
      </span>
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { session, logout } = useAuth();
  const [confirming, setConfirming] = useState(false);
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
      <div className="px-5 pt-5 pb-4">
        <Brand />
      </div>
      <nav className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3" aria-label="Principal">
        {groups.map((group) => (
          <div key={group.label || "root"}>
            {group.label && (
              <p className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-faint">
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
                    `group flex min-h-11 items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] transition-colors duration-150 ${
                      isActive
                        ? "bg-accent-soft font-medium text-accent"
                        : "text-muted hover:bg-soft hover:text-text"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <IconEl
                        size={18}
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
        ))}
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

          <main id="contenido" className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 lg:px-10">
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
      </SyncJobProvider>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Suspense fallback={<PageFallback />}><LoginPage /></Suspense>} />
      <Route path="/signup" element={<Suspense fallback={<PageFallback />}><SignupPage /></Suspense>} />
      <Route path="/admin/login" element={<Suspense fallback={<PageFallback />}><AdminLoginPage /></Suspense>} />
      <Route
        path="/admin"
        element={
          <Suspense fallback={<PageFallback />}>
            <AdminLayout />
          </Suspense>
        }
      >
        <Route index element={<Suspense fallback={<PageFallback />}><AdminDashboardPage /></Suspense>} />
        <Route path="customers" element={<Suspense fallback={<PageFallback />}><AdminCustomersPage /></Suspense>} />
        <Route path="customers/:orgId" element={<Suspense fallback={<PageFallback />}><AdminCustomerDetailPage /></Suspense>} />
        <Route path="plans" element={<Suspense fallback={<PageFallback />}><AdminPlansPage /></Suspense>} />
        <Route path="usage" element={<Suspense fallback={<PageFallback />}><AdminUsagePage /></Suspense>} />
      </Route>
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Suspense fallback={<PageFallback />}><DashboardPage /></Suspense>} />
        <Route path="/usage" element={<Suspense fallback={<PageFallback />}><UsagePage /></Suspense>} />
        <Route path="/keys" element={<Suspense fallback={<PageFallback />}><KeysPage /></Suspense>} />
        <Route path="/ingestion" element={<Navigate to="/knowledge/sql" replace />} />
        <Route path="/knowledge-bases" element={<Navigate to="/knowledge/collections" replace />} />
        <Route path="/knowledge/sources" element={<Suspense fallback={<PageFallback />}><KnowledgeSourcesPage /></Suspense>} />
        <Route path="/knowledge/collections" element={<Suspense fallback={<PageFallback />}><KnowledgeCollectionsPage /></Suspense>} />
        <Route path="/knowledge/documents" element={<Suspense fallback={<PageFallback />}><KnowledgeDocumentsPage /></Suspense>} />
        <Route path="/knowledge/sql" element={<Suspense fallback={<PageFallback />}><KnowledgeSqlPage /></Suspense>} />
        <Route path="/knowledge/jobs" element={<Suspense fallback={<PageFallback />}><KnowledgeJobsPage /></Suspense>} />
        <Route path="/knowledge/playground" element={<Suspense fallback={<PageFallback />}><KnowledgePlaygroundPage /></Suspense>} />
        <Route path="/prompts" element={<Suspense fallback={<PageFallback />}><PromptsPage /></Suspense>} />
        <Route path="/chat" element={<Suspense fallback={<PageFallback />}><ChatPage /></Suspense>} />
        <Route path="/users" element={<Suspense fallback={<PageFallback />}><UsersPage /></Suspense>} />
        <Route path="/projects" element={<Suspense fallback={<PageFallback />}><ProjectsPage /></Suspense>} />
        <Route path="/agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
        <Route path="/agents/new" element={<Suspense fallback={<PageFallback />}><AgentBuilderPage /></Suspense>} />
        <Route path="/agents/:id" element={<Suspense fallback={<PageFallback />}><AgentBuilderPage /></Suspense>} />
        <Route path="/connectors" element={<Suspense fallback={<PageFallback />}><ConnectorsPage /></Suspense>} />
        <Route path="/audit" element={<Suspense fallback={<PageFallback />}><AuditLogsPage /></Suspense>} />
        <Route path="/billing" element={<Suspense fallback={<PageFallback />}><BillingPage /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={<PageFallback />}><SettingsPage /></Suspense>} />
        <Route path="/evaluation" element={<Navigate to="/evaluation/datasets" replace />} />
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
