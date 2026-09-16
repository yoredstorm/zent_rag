import {
  Bell,
  List,
  MagnifyingGlass,
  SidebarSimple,
  SignOut,
} from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import {
  PLATFORM_NAV,
  platformNavContextForPath,
  type PlatformNavItem,
} from "../../lib/platformNav";
import { CommandPaletteRoot, openCommandPalette } from "../../components/CommandPalette";
import { IdleSessionWarning } from "../../components/IdleSessionWarning";
import { StepUpModal } from "../../components/StepUpModal";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Brand, IdentityTile } from "../../components/Brand";
import {
  Badge,
  Breadcrumbs,
  Button,
  Drawer,
  IconButton,
  Input,
  Kbd,
  Menu,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  Popover,
  Tooltip,
  cn,
  menuItemClass,
  menuLabelClass,
  menuSeparatorClass,
} from "../../components/ui";

const IDLE_SESSION_MINUTES = 30;

const BASE = "/control-center";
const SIDEBAR_COLLAPSED_KEY = "zent_sidebar_collapsed";
const COLLAPSED_GROUPS_KEY = "zent_platform_nav_collapsed_groups";

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

function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function readCollapsedGroups(): string[] {
  try {
    const raw = window.localStorage.getItem(COLLAPSED_GROUPS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

/** Ítem de navegación: mismo lenguaje que el sidebar del workspace (rail + tooltip). */
function ControlNavItem({
  item,
  collapsed,
  instanceId,
  onNavigate,
}: {
  item: PlatformNavItem;
  collapsed: boolean;
  instanceId: string;
  onNavigate?: () => void;
}) {
  const reduce = useReducedMotion();
  const { to, label, icon: IconEl, end } = item;
  const link = (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      aria-label={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group relative flex min-h-8 items-center gap-2.5 rounded-sm text-[13px]",
          collapsed ? "justify-center px-0 py-1.5" : "px-2.5 py-1.5",
          isActive
            ? "bg-soft/70 font-medium text-text"
            : "text-muted hover:bg-soft/45 hover:text-text"
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span
              layoutId={`${instanceId}-platform-nav-rail`}
              className="absolute top-1 bottom-1 -left-1 w-[2px] rounded-full bg-accent"
              transition={
                reduce ? { duration: 0 } : { type: "spring", stiffness: 520, damping: 42, mass: 0.5 }
              }
              aria-hidden
            />
          )}
          <IconEl
            size={17}
            weight={isActive ? "fill" : "regular"}
            className={cn("shrink-0", isActive ? "text-accent" : "text-faint group-hover:text-muted")}
            aria-hidden
          />
          {!collapsed && <span className="truncate">{label}</span>}
        </>
      )}
    </NavLink>
  );

  if (!collapsed) return link;
  return (
    <Tooltip label={label} side="right">
      <span className="block">{link}</span>
    </Tooltip>
  );
}

function ControlNav({
  collapsed,
  instanceId,
  onNavigate,
}: {
  collapsed: boolean;
  instanceId: string;
  onNavigate?: () => void;
}) {
  const { pathname } = useLocation();
  const [query, setQuery] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(readCollapsedGroups);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify(collapsedGroups));
    } catch {
      // sin persistencia
    }
  }, [collapsedGroups]);

  // Un grupo colapsado que contiene la ruta activa se abre solo.
  useEffect(() => {
    setCollapsedGroups((prev) => {
      const hiddenActive = PLATFORM_NAV.filter((g) => prev.includes(g.label))
        .filter((g) =>
          g.items.some(
            (item) =>
              pathname === item.to || (item.to !== BASE && pathname.startsWith(`${item.to}/`))
          )
        )
        .map((g) => g.label);
      if (hiddenActive.length === 0) return prev;
      return prev.filter((label) => !hiddenActive.includes(label));
    });
  }, [pathname]);

  const q = query.trim().toLowerCase();
  const flat = q
    ? PLATFORM_NAV.flatMap((g) => g.items).filter((item) =>
        item.label.toLowerCase().includes(q)
      )
    : [];

  function toggleGroup(label: string) {
    setCollapsedGroups((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
    );
  }

  return (
    <>
      {!collapsed && (
        <div className="px-3 pb-3">
          <Input
            type="search"
            icon={MagnifyingGlass}
            aria-label="Buscar sección"
            placeholder="Buscar: costs, operations…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}
      <nav
        aria-label="Control Center"
        className={cn(
          "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2.5 pb-3",
          collapsed && "px-2"
        )}
      >
        {q ? (
          flat.length === 0 ? (
            <p className="px-2.5 py-2 text-xs text-muted">Sin coincidencias.</p>
          ) : (
            <div className="flex flex-col gap-0.5">
              {flat.map((item) => (
                <ControlNavItem
                  key={item.to}
                  item={item}
                  collapsed={collapsed}
                  instanceId={instanceId}
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          )
        ) : (
          PLATFORM_NAV.map((group) => {
            const groupCollapsed = collapsedGroups.includes(group.label);
            return (
              <div key={group.label}>
                {!collapsed && (
                  <div className="mb-1 flex items-center justify-between px-2.5">
                    <p className="eyebrow">{group.label}</p>
                    <button
                      type="button"
                      className="inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-xs text-ghost transition-colors duration-150 hover:bg-soft hover:text-muted"
                      aria-expanded={!groupCollapsed}
                      aria-label={`${groupCollapsed ? "Mostrar" : "Ocultar"} ${group.label}`}
                      onClick={() => toggleGroup(group.label)}
                    >
                      <span
                        className={cn(
                          "block transition-transform duration-200",
                          groupCollapsed ? "" : "rotate-90"
                        )}
                        aria-hidden
                      >
                        ▸
                      </span>
                    </button>
                  </div>
                )}
                {collapsed && <div className="mx-auto mb-1.5 h-px w-5 bg-border" aria-hidden />}
                {!groupCollapsed && (
                  <div className="flex flex-col gap-0.5">
                    {group.items.map((item) => (
                      <ControlNavItem
                        key={item.to}
                        item={item}
                        collapsed={collapsed}
                        instanceId={instanceId}
                        onNavigate={onNavigate}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </nav>
    </>
  );
}

function AdminSidebar({
  collapsed,
  onToggleCollapsed,
  instanceId,
  onNavigate,
  showHeader = true,
}: {
  collapsed: boolean;
  onToggleCollapsed?: () => void;
  instanceId: string;
  onNavigate?: () => void;
  showHeader?: boolean;
}) {
  const { session, logout } = usePlatformAuth();
  const identity = session?.email || "";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      {showHeader && (
        <>
          <div className={cn("flex items-center gap-2 pt-4 pb-2", collapsed ? "px-2.5" : "px-4")}>
            {collapsed ? (
              <span className="mx-auto">
                <Brand compact />
              </span>
            ) : (
              <>
                <Brand />
                <span className="flex-1" />
                {onToggleCollapsed && (
                  <IconButton
                    label="Ocultar menú"
                    icon={SidebarSimple}
                    iconSize={16}
                    onClick={onToggleCollapsed}
                    className="h-8 w-8 min-h-0"
                  />
                )}
              </>
            )}
          </div>
          {!collapsed && <p className="eyebrow px-4 pb-3">Control Center</p>}
        </>
      )}

      <ControlNav collapsed={collapsed} instanceId={instanceId} onNavigate={onNavigate} />

      <div className={cn("mt-2 border-t border-border py-3", collapsed ? "px-2" : "px-3")}>
        {!collapsed && identity && (
          <div className="mb-2 flex min-w-0 items-center gap-2.5 px-1">
            <IdentityTile label={identity} kind="account" size={26} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12.5px] font-medium text-text">{identity}</span>
              <span className="block truncate text-[11px] text-faint">Plataforma Zent</span>
            </span>
          </div>
        )}
        {collapsed ? (
          <div className="flex justify-center">
            <Tooltip label="Cerrar sesión" side="right">
              <button
                type="button"
                aria-label="Cerrar sesión"
                onClick={logout}
                className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-danger"
              >
                <SignOut size={17} aria-hidden />
              </button>
            </Tooltip>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={SignOut}
            className="w-full justify-start gap-2 px-2"
            onClick={logout}
          >
            Cerrar sesión
          </Button>
        )}
      </div>
    </div>
  );
}

export default function AdminLayout() {
  const { session, logout } = usePlatformAuth();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-sidebar", collapsed ? "collapsed" : "expanded");
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // sin persistencia
    }
  }, [collapsed]);

  useEffect(() => {
    setDrawer(false);
  }, [location.pathname]);

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

  const context = platformNavContextForPath(location.pathname);
  const pageTitle = context?.item.label ?? "Overview";
  const crumbs = [
    { label: "Control Center", to: BASE },
    ...(context ? [{ label: context.group.label }] : []),
    { label: pageTitle },
  ];

  return (
    <div className="min-h-[100dvh]">
      <a href="#plataforma-contenido" className="skip-link">
        Saltar al contenido
      </a>
      <aside className="app-sidebar fixed inset-y-0 left-0 z-30 hidden border-r border-border bg-surface lg:block">
        <AdminSidebar
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((v) => !v)}
          instanceId="desktop"
        />
      </aside>

      <Drawer
        open={drawer}
        onOpenChange={setDrawer}
        title="Control Center"
        description="Navegación de plataforma"
        side="left"
        width={290}
        closeLabel="Cerrar menú"
        overlayClassName="lg:hidden"
        className="lg:hidden"
      >
        <AdminSidebar
          collapsed={false}
          instanceId="mobile"
          showHeader={false}
          onNavigate={() => setDrawer(false)}
        />
      </Drawer>

      <div className="app-main flex min-h-[100dvh] min-w-0 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border bg-bg/85 px-4 py-2 backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-2.5">
            <IconButton
              label="Abrir menú"
              icon={List}
              iconSize={18}
              aria-expanded={drawer}
              onClick={() => setDrawer(true)}
              className="h-8 w-8 min-h-0 self-center lg:hidden"
            />
            {collapsed && (
              <button
                type="button"
                onClick={() => setCollapsed(false)}
                aria-label="Mostrar menú"
                className="-ml-1 mr-0.5 hidden h-8 w-8 shrink-0 cursor-pointer items-center justify-center self-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text lg:inline-flex"
              >
                <SidebarSimple size={16} aria-hidden />
              </button>
            )}
            <Breadcrumbs items={crumbs} className="hidden min-w-0 sm:flex" />
            <span className="truncate text-[15px] font-medium text-text sm:hidden" data-page-title>
              {pageTitle}
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              className="mr-1 hidden h-9 min-w-[13rem] cursor-pointer items-center gap-2 rounded-sm border border-border bg-control px-2.5 text-[13px] text-faint transition-colors duration-200 hover:border-border-strong hover:text-muted sm:flex"
              onClick={() => openCommandPalette("platform")}
              aria-label="Buscar (Ctrl+K)"
            >
              <MagnifyingGlass size={14} aria-hidden />
              <span className="flex-1 text-left">Buscar sección…</span>
              <Kbd>Ctrl K</Kbd>
            </button>

            <Popover
              align="end"
              width={360}
              trigger={
                <button
                  type="button"
                  className="relative inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
                  aria-label={`Notificaciones${unread > 0 ? ` (${unread} sin leer)` : ""}`}
                >
                  <Bell size={17} aria-hidden />
                  {unread > 0 && (
                    <span className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg tabular-nums">
                      {unread > 99 ? "99+" : unread}
                    </span>
                  )}
                </button>
              }
            >
              <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
                <p className="eyebrow">Notificaciones</p>
                {unread > 0 && (
                  <span className="text-[11px] text-faint tabular-nums">{unread} sin leer</span>
                )}
              </div>
              {notices.length === 0 ? (
                <p className="px-1 py-3 text-[13px] text-muted">Sin avisos.</p>
              ) : (
                <ul className="max-h-80 divide-y divide-border-soft overflow-y-auto">
                  {notices.map((n) => (
                    <li key={n.id}>
                      <div className="py-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-[13px] font-medium text-text">{n.title}</p>
                          {!n.read_at && <Badge tone="accent">nuevo</Badge>}
                        </div>
                        {n.body && (
                          <p className="mt-0.5 text-xs leading-relaxed text-muted">{n.body}</p>
                        )}
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                          {n.organization_id && (
                            <Link
                              className="text-accent hover:underline"
                              to={`${BASE}/tenants/${n.organization_id}`}
                            >
                              {n.organization_name || "Ver tenant"}
                            </Link>
                          )}
                          <span className="text-faint">
                            {n.created_at ? new Date(n.created_at).toLocaleString("es-PE") : ""}
                          </span>
                        </div>
                        {!n.read_at && (
                          <button
                            type="button"
                            className="mt-1 cursor-pointer text-xs font-medium text-accent hover:underline"
                            onClick={() => void markRead(n.id)}
                          >
                            Marcar leído
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Popover>

            <ThemeToggle compact />

            <span className="mx-0.5 hidden h-5 w-px bg-border sm:block" aria-hidden />

            <Menu
              label="Cuenta"
              align="end"
              className="min-w-[15rem]"
              trigger={
                <button
                  type="button"
                  className="flex cursor-pointer items-center gap-2 rounded-sm p-1 transition-colors duration-150 hover:bg-soft"
                  aria-label="Cuenta"
                >
                  <IdentityTile label={session.email || "Z"} kind="account" size={28} />
                </button>
              }
            >
              <div className="border-b border-border px-2.5 pt-1.5 pb-2.5">
                <p className="truncate text-[13px] font-medium text-text">
                  {session.email || "Cuenta"}
                </p>
                <p className="truncate text-[11px] text-faint">Plataforma Zent</p>
              </div>
              <MenuLabel className={menuLabelClass}>Sesión</MenuLabel>
              <MenuItem
                className={menuItemClass}
                onSelect={() => openCommandPalette("platform")}
              >
                <MagnifyingGlass size={15} aria-hidden />
                Buscar sección
              </MenuItem>
              <MenuSeparator className={menuSeparatorClass} />
              <MenuItem
                className={cn(menuItemClass, "text-danger data-[highlighted]:bg-danger-soft")}
                onSelect={() => logout()}
              >
                <SignOut size={15} aria-hidden />
                Cerrar sesión
              </MenuItem>
            </Menu>
          </div>
        </header>

        <main
          id="plataforma-contenido"
          className="mx-auto w-full max-w-[1360px] flex-1 px-4 py-5 sm:px-6 lg:px-8"
          tabIndex={-1}
        >
          <CommandPaletteRoot mode="platform" />
          <IdleSessionWarning minutes={IDLE_SESSION_MINUTES} onLogout={logout} />
          <StepUpModal />
          <Outlet />
        </main>
      </div>
    </div>
  );
}
