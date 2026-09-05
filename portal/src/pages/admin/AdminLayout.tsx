import {
  Bell,
  List,
  MagnifyingGlass,
  SignOut,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useId, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { PLATFORM_NAV, type PlatformNavItem, type PlatformNavGroup } from "../../lib/platformNav";
import { CommandPaletteRoot, openCommandPalette } from "../../components/CommandPalette";
import { ThemeToggle } from "../../components/ThemeToggle";

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

const BASE = "/control-center";

const NAV = PLATFORM_NAV;

function ControlNav({
  groups,
  query,
  onQuery,
  onNavigate,
}: {
  groups: PlatformNavGroup[];
  query: string;
  onQuery: (value: string) => void;
  onNavigate?: () => void;
}) {
  const searchId = useId();
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groups.map((g) => [g.label, true]))
  );

  const q = query.trim().toLowerCase();
  const flat = q
    ? groups.flatMap((g) => g.items).filter((item) => item.label.toLowerCase().includes(q))
    : [];

  function renderItem({ to, label, icon: Icon, end }: PlatformNavItem) {
    return (
      <NavLink
        key={to}
        to={to}
        end={end}
        onClick={onNavigate}
        className={({ isActive }) =>
          `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm ${
            isActive
              ? "bg-accent-soft text-text"
              : "text-muted hover:bg-soft hover:text-text"
          }`
        }
      >
        <Icon size={18} aria-hidden />
        {label}
      </NavLink>
    );
  }

  return (
    <>
      <div className="border-b border-border px-3 py-3">
        <label className="sr-only" htmlFor={searchId}>
          Buscar sección
        </label>
        <div className="relative">
          <MagnifyingGlass
            size={16}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint"
            aria-hidden
          />
          <input
            id={searchId}
            type="search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Buscar: costs, operations…"
            className="w-full rounded-md border border-border bg-soft py-2 pl-8 pr-2 text-sm text-text"
          />
        </div>
      </div>
      <nav className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3" aria-label="Control Center">
        {q ? (
          <>
            {flat.length === 0 && <p className="px-2 py-3 text-xs text-muted">Sin coincidencias.</p>}
            {flat.map(renderItem)}
          </>
        ) : (
          groups.map((group) => {
            const expanded = open[group.label] ?? true;
            return (
              <div key={group.label}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-xs px-2 py-1 text-[10px] font-semibold tracking-wider text-faint uppercase transition-colors duration-150 hover:text-muted"
                  aria-expanded={expanded}
                  onClick={() => setOpen((v) => ({ ...v, [group.label]: !(v[group.label] ?? true) }))}
                >
                  {group.label}
                  <span className={`transition-transform duration-150 ${expanded ? "rotate-90" : ""}`} aria-hidden>
                    ▸
                  </span>
                </button>
                {expanded && (
                  <div className="flex flex-col gap-1">{group.items.map(renderItem)}</div>
                )}
              </div>
            );
          })
        )}
      </nav>
    </>
  );
}

export default function AdminLayout() {
  const { session, logout } = usePlatformAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [query, setQuery] = useState("");
  const [notices, setNotices] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

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

  if (!session) {
    return (
      <Navigate
        to="/control-center/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

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
    <div className="flex h-dvh max-h-dvh overflow-hidden">
      <aside className="hidden h-full w-60 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="border-b border-border px-4 py-4">
          <p className="text-xs font-medium uppercase tracking-wider text-faint">
            Control Center
          </p>
          <p className="mt-1 text-sm font-semibold text-text">Zent plataforma</p>
        </div>
        <ControlNav groups={NAV} query={query} onQuery={setQuery} />
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
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setDrawer(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-border bg-surface shadow-pop">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <p className="text-sm font-semibold text-text">Control Center</p>
              <button
                type="button"
                className="btn btn-ghost min-h-11 min-w-11"
                aria-label="Cerrar menú"
                onClick={() => setDrawer(false)}
              >
                <X size={18} aria-hidden />
              </button>
            </div>
            <ControlNav
              groups={NAV}
              query={query}
              onQuery={setQuery}
              onNavigate={() => setDrawer(false)}
            />
          </div>
        </div>
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-ghost min-h-11 min-w-11 lg:hidden"
              aria-label="Abrir menú"
              aria-expanded={drawer}
              onClick={() => setDrawer(true)}
            >
              <List size={18} aria-hidden />
            </button>
            <span className="text-sm font-semibold lg:hidden">Control Center</span>
            <span className="hidden text-sm text-muted lg:inline">Inbox de plataforma</span>
          </div>
          <div className="relative flex items-center gap-2">
            <button
              type="button"
              className="btn btn-ghost hidden min-h-11 items-center gap-2 px-2 text-xs text-muted sm:flex"
              onClick={() => openCommandPalette("platform")}
              aria-label="Buscar (Ctrl+K)"
            >
              <MagnifyingGlass size={16} aria-hidden />
              Buscar
              <kbd className="rounded-xs border border-border bg-bg px-1 font-mono text-[10px] text-faint">Ctrl K</kbd>
            </button>
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
            <ThemeToggle compact />
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
                              to={`${BASE}/tenants/${n.organization_id}`}
                              onClick={() => setOpen(false)}
                            >
                              {n.organization_name || "Ver tenant"}
                            </Link>
                          )}
                          <span className="text-faint">
                            {n.created_at
                              ? new Date(n.created_at).toLocaleString("es-PE")
                              : ""}
                          </span>
                        </div>
                        {!n.read_at && (
                          <button
                            type="button"
                            className="mt-1 text-xs text-accent hover:underline"
                            onClick={() => void markRead(n.id)}
                          >
                            Marcar leído
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
          <CommandPaletteRoot mode="platform" />
          <Outlet />
        </main>
      </div>
    </div>
  );
}