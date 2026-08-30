import { Bell, Buildings, Cards, ChartLineUp, Coins, SignOut } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Outlet } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";

type Notice = {
  id: string;
  type: string;
  organization_id: string | null;
  organization_name: string | null;
  title: string;
  body: string | null;
  created_at: string | null;
  read_at: string | null;
};

export default function AdminLayout() {
  const { session, logout } = usePlatformAuth();
  const [open, setOpen] = useState(false);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);

  const loadNotices = useCallback(async () => {
    if (!session) return;
    try {
      const data = await platformApi<{ notifications: Notice[]; unread_count: number }>(
        "/api/v1/platform/notifications",
        { token: session.token }
      );
      setNotices(data.notifications || []);
      setUnread(data.unread_count || 0);
    } catch {
      // Keep last known inbox if poll/login race fails.
    }
  }, [session]);

  useEffect(() => {
    if (!session) return;
    void loadNotices();
    const id = window.setInterval(() => void loadNotices(), 30000);
    return () => window.clearInterval(id);
  }, [session, loadNotices]);

  if (!session) return <Navigate to="/admin/login" replace />;

  async function markRead(id: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/notifications/${id}/read`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      await loadNotices();
    } catch {
      // Leave the item unread; next poll will refresh.
    }
  }

  return (
    <div className="flex min-h-[100dvh]">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="border-b border-border px-4 py-4">
          <p className="text-xs font-medium uppercase tracking-wider text-faint">
            Control Center
          </p>
          <p className="mt-1 text-sm font-semibold text-text">Zent plataforma</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Administración">
          <NavLink
            to="/admin"
            end
            className={({ isActive }) =>
              `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-accent-soft text-text" : "text-muted hover:bg-soft hover:text-text"
              }`
            }
          >
            <ChartLineUp size={18} aria-hidden />
            Dashboard
          </NavLink>
          <NavLink
            to="/admin/customers"
            className={({ isActive }) =>
              `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-accent-soft text-text" : "text-muted hover:bg-soft hover:text-text"
              }`
            }
          >
            <Buildings size={18} aria-hidden />
            Clientes
          </NavLink>
          <NavLink
            to="/admin/plans"
            className={({ isActive }) =>
              `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-accent-soft text-text" : "text-muted hover:bg-soft hover:text-text"
              }`
            }
          >
            <Cards size={18} aria-hidden />
            Planes
          </NavLink>
          <NavLink
            to="/admin/usage"
            className={({ isActive }) =>
              `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm ${
                isActive ? "bg-accent-soft text-text" : "text-muted hover:bg-soft hover:text-text"
              }`
            }
          >
            <Coins size={18} aria-hidden />
            FinOps
          </NavLink>
        </nav>
        <div className="border-t border-border p-4">
          <p className="mb-2 truncate text-xs text-faint" title={session.email}>
            {session.email}
          </p>
          <button
            type="button"
            className="btn btn-ghost w-full justify-start gap-2 px-2 py-1.5 text-[13px]"
            onClick={logout}
          >
            <SignOut size={16} aria-hidden />
            Cerrar sesión
          </button>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <span className="text-sm font-semibold lg:hidden">Control Center</span>
          <span className="hidden text-sm text-muted lg:inline">Inbox de plataforma</span>
          <div className="relative flex items-center gap-2">
            <button
              type="button"
              className="btn btn-ghost relative min-h-11 min-w-11"
              aria-label="Notificaciones"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              <Bell size={18} aria-hidden />
              {unread > 0 && (
                <span className="absolute right-1 top-1 inline-flex min-w-5 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </button>
            <button type="button" className="btn btn-ghost min-h-11 text-sm lg:hidden" onClick={logout}>
              Salir
            </button>
            {open && (
              <div
                className="absolute right-0 top-12 z-20 w-[min(100vw-2rem,22rem)] rounded-md border border-border bg-surface p-2 shadow-lg"
                role="dialog"
                aria-label="Notificaciones"
              >
                {notices.length === 0 && (
                  <p className="px-3 py-4 text-sm text-muted">Sin avisos.</p>
                )}
                <ul className="max-h-80 overflow-y-auto">
                  {notices.map((n) => (
                    <li key={n.id} className="border-b border-border last:border-0">
                      <div className="px-3 py-2">
                        <p className="text-sm font-medium text-text">{n.title}</p>
                        {n.body && <p className="mt-0.5 text-xs text-muted">{n.body}</p>}
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                          {n.organization_id && (
                            <Link
                              className="text-accent hover:underline"
                              to={`/admin/customers/${n.organization_id}`}
                              onClick={() => setOpen(false)}
                            >
                              {n.organization_name || "Ver cliente"}
                            </Link>
                          )}
                          <span className="text-faint">
                            {n.created_at
                              ? new Date(n.created_at).toLocaleString("es-CL")
                              : ""}
                          </span>
                          {!n.read_at && (
                            <button
                              type="button"
                              className="text-accent hover:underline"
                              onClick={() => void markRead(n.id)}
                            >
                              Marcar leída
                            </button>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
