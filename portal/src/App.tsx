import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { SyncBanner, SyncJobProvider } from "./syncJob";
import { ToastProvider } from "./Toast";
import ChatPage from "./pages/Chat";
import DashboardPage from "./pages/Dashboard";
import IngestionPage from "./pages/Ingestion";
import KeysPage from "./pages/Keys";
import LoginPage from "./pages/Login";
import PromptsPage from "./pages/Prompts";
import SignupPage from "./pages/Signup";
import UsagePage from "./pages/Usage";

function ProtectedLayout() {
  const { session, logout } = useAuth();
  if (!session) return <Navigate to="/login" replace />;

  return (
    <ToastProvider>
      <SyncJobProvider>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">
              RAG<span>Portal</span>
            </div>
            <nav className="nav">
              <NavLink to="/" end>
                Dashboard
              </NavLink>
              <NavLink to="/usage">Uso</NavLink>
              <NavLink to="/keys">API Keys</NavLink>
              <NavLink to="/ingestion">Ingestión</NavLink>
              <NavLink to="/prompts">Prompts</NavLink>
              <NavLink to="/chat">Chat demo</NavLink>
            </nav>
            <div className="sidebar-footer">
              <div className="muted">
                {session.companyName || session.tenantId.slice(0, 8)}
              </div>
              <button className="btn secondary" type="button" onClick={logout}>
                Cerrar sesión
              </button>
            </div>
          </aside>
          <main className="main">
            <SyncBanner />
            <Outlet />
          </main>
        </div>
      </SyncJobProvider>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/usage" element={<UsagePage />} />
        <Route path="/keys" element={<KeysPage />} />
        <Route path="/ingestion" element={<IngestionPage />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/chat" element={<ChatPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
