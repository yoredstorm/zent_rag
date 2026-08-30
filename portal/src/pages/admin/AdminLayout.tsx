import { Buildings, Cards, ChartLineUp, Coins, SignOut } from "@phosphor-icons/react";
import { NavLink, Navigate, Outlet } from "react-router-dom";
import { usePlatformAuth } from "../../platformAuth";

export default function AdminLayout() {
  const { session, logout } = usePlatformAuth();
  if (!session) return <Navigate to="/admin/login" replace />;

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
        <header className="flex items-center justify-between border-b border-border px-4 py-3 lg:hidden">
          <span className="text-sm font-semibold">Control Center</span>
          <button type="button" className="btn btn-ghost min-h-11 text-sm" onClick={logout}>
            Salir
          </button>
        </header>
        <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
