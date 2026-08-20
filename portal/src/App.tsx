import {
  ChartBar,
  ChatCircleDots,
  Database,
  Key,
  List,
  NotePencil,
  SignOut,
  SquaresFour,
  UsersThree,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { Suspense, lazy, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { useAuth } from "./auth";
import { SyncBanner, SyncJobProvider } from "./syncJob";
import { ToastProvider } from "./Toast";

const ChatPage = lazy(() => import("./pages/Chat"));
const DashboardPage = lazy(() => import("./pages/Dashboard"));
const IngestionPage = lazy(() => import("./pages/Ingestion"));
const KeysPage = lazy(() => import("./pages/Keys"));
const LoginPage = lazy(() => import("./pages/Login"));
const PromptsPage = lazy(() => import("./pages/Prompts"));
const SignupPage = lazy(() => import("./pages/Signup"));
const UsagePage = lazy(() => import("./pages/Usage"));
const UsersPage = lazy(() => import("./pages/Users"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const KnowledgeBasesPage = lazy(() => import("./pages/KnowledgeBases"));
const AgentsPage = lazy(() => import("./pages/Agents"));
const ConnectorsPage = lazy(() => import("./pages/Connectors"));
const AuditLogsPage = lazy(() => import("./pages/AuditLogs"));

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

const NAV_ITEMS: { to: string; label: string; icon: Icon; end?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: SquaresFour, end: true },
  { to: "/chat", label: "Pregúntale a tus datos", icon: ChatCircleDots },
  { to: "/ingestion", label: "Ingestión", icon: Database },
  { to: "/projects", label: "Proyectos", icon: SquaresFour },
  { to: "/knowledge-bases", label: "Knowledge bases", icon: Database },
  { to: "/agents", label: "Agentes", icon: ChatCircleDots },
  { to: "/connectors", label: "Conectores", icon: Database },
  { to: "/users", label: "Usuarios y roles", icon: UsersThree },
  { to: "/keys", label: "Claves", icon: Key },
  { to: "/usage", label: "Uso", icon: ChartBar },
  { to: "/prompts", label: "Prompts", icon: NotePencil },
  { to: "/audit", label: "Auditoría", icon: List },
];

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
  const identity =
    session?.email || session?.companyName || session?.organizationId.slice(0, 8) || "";

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-5 pb-4">
        <Brand />
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 px-3" aria-label="Principal">
        {NAV_ITEMS.map(({ to, label, icon: IconEl, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              `group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] transition-colors duration-150 ${
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
  const { session, ready } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);

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
              className="btn btn-secondary px-2.5"
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
                  className="absolute top-4 right-4 cursor-pointer rounded-xs p-1 text-faint hover:bg-soft hover:text-text"
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
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Suspense fallback={<PageFallback />}><DashboardPage /></Suspense>} />
        <Route path="/usage" element={<Suspense fallback={<PageFallback />}><UsagePage /></Suspense>} />
        <Route path="/keys" element={<Suspense fallback={<PageFallback />}><KeysPage /></Suspense>} />
        <Route path="/ingestion" element={<Suspense fallback={<PageFallback />}><IngestionPage /></Suspense>} />
        <Route path="/prompts" element={<Suspense fallback={<PageFallback />}><PromptsPage /></Suspense>} />
        <Route path="/chat" element={<Suspense fallback={<PageFallback />}><ChatPage /></Suspense>} />
        <Route path="/users" element={<Suspense fallback={<PageFallback />}><UsersPage /></Suspense>} />
        <Route path="/projects" element={<Suspense fallback={<PageFallback />}><ProjectsPage /></Suspense>} />
        <Route path="/knowledge-bases" element={<Suspense fallback={<PageFallback />}><KnowledgeBasesPage /></Suspense>} />
        <Route path="/agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
        <Route path="/connectors" element={<Suspense fallback={<PageFallback />}><ConnectorsPage /></Suspense>} />
        <Route path="/audit" element={<Suspense fallback={<PageFallback />}><AuditLogsPage /></Suspense>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
