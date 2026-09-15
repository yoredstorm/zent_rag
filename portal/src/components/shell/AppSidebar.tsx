import {
  MagnifyingGlass,
  SidebarSimple,
  SignOut,
} from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../auth";
import { useEntitlements } from "../../lib/entitlements";
import { NAV_GROUPS, canSeeNavItem, type NavGroup, type NavLeaf } from "../../lib/nav";
import { tourTargetForGroup, tourTargetForPath } from "../../lib/productTour";
import { Brand, IdentityTile } from "../Brand";
import { Kbd } from "../ui/code";
import { IconButton } from "../ui/Button";
import { ConfirmDialog } from "../ui/overlay";
import { Tooltip } from "../ui/overlay";
import { WorkspaceSelector } from "../WorkspaceSelector";
import { openCommandPalette } from "../CommandPalette";
import { cn } from "../ui/cn";

const COLLAPSED_GROUPS_KEY = "zent_nav_collapsed_groups";

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

function NavItem({
  item,
  collapsed,
  instanceId,
  onNavigate,
}: {
  item: NavLeaf;
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
      data-tour={tourTargetForPath(to)}
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
              layoutId={`${instanceId}-nav-rail`}
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

function SidebarNav({
  collapsed,
  instanceId,
  onNavigate,
}: {
  collapsed: boolean;
  instanceId: string;
  onNavigate?: () => void;
}) {
  const { session } = useAuth();
  const entitlements = useEntitlements();
  const { pathname } = useLocation();
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(readCollapsedGroups);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify(collapsedGroups));
    } catch {
      // sin persistencia
    }
  }, [collapsedGroups]);

  const groups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items?.filter((item) => canSeeNavItem(session, item.key, entitlements)),
        sections: group.sections
          ?.map((s) => ({
            heading: s.heading,
            items: s.items.filter((item) => canSeeNavItem(session, item.key, entitlements)),
          }))
          .filter((s) => s.items.length > 0),
      })).filter(
        (group) =>
          (group.items && group.items.length > 0) ||
          (group.sections && group.sections.length > 0)
      ) as NavGroup[],
    [session, entitlements]
  );

  // Un grupo colapsado que contiene la ruta activa se abre solo,
  // para que la navegación nunca oculte dónde estás.
  useEffect(() => {
    setCollapsedGroups((prev) => {
      const hiddenActive = groups
        .filter((g) => g.collapsible && prev.includes(g.label ?? ""))
        .filter((g) =>
          [...(g.items ?? [])].some(
            (item) => pathname === item.to || (item.to !== "/" && pathname.startsWith(`${item.to}/`))
          )
        )
        .map((g) => g.label ?? "");
      if (hiddenActive.length === 0) return prev;
      return prev.filter((label) => !hiddenActive.includes(label));
    });
  }, [pathname, groups]);

  function toggleGroup(label: string) {
    setCollapsedGroups((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
    );
  }

  return (
    <nav
      aria-label="Principal"
      className={cn("flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2.5 pb-3", collapsed && "px-2")}
    >
      {groups.map((group) => {
        const label = group.label ?? "General";
        const collapsedGroup = Boolean(group.collapsible) && collapsedGroups.includes(label);
        return (
          <div key={label} data-tour={tourTargetForGroup(group.label)}>
            {group.label && !collapsed && (
              <div className="mb-1 flex items-center justify-between px-2.5">
                <p className="eyebrow">{group.label}</p>
                {group.collapsible && (
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-xs text-ghost transition-colors duration-150 hover:bg-soft hover:text-muted"
                    aria-expanded={!collapsedGroup}
                    aria-label={`${collapsedGroup ? "Mostrar" : "Ocultar"} ${label}`}
                    onClick={() => toggleGroup(label)}
                  >
                    <span
                      className={cn("block transition-transform duration-200", collapsedGroup ? "" : "rotate-90")}
                      aria-hidden
                    >
                      ▸
                    </span>
                  </button>
                )}
              </div>
            )}
            {group.label && collapsed && <div className="mx-auto mb-1.5 h-px w-5 bg-border" aria-hidden />}
            {!collapsedGroup && (
              <div className="flex flex-col gap-0.5">
                {(group.items ?? []).map((item) => (
                  <NavItem
                    key={item.to}
                    item={item}
                    collapsed={collapsed}
                    instanceId={instanceId}
                    onNavigate={onNavigate}
                  />
                ))}
                {(group.sections ?? []).map((section) => (
                  <div key={section.heading} className="mt-2">
                    {!collapsed && (
                      <p className="mb-1 px-2.5 text-[10px] font-semibold tracking-[0.07em] text-ghost uppercase">
                        {section.heading}
                      </p>
                    )}
                    {section.items.map((item) => (
                      <NavItem
                        key={item.to}
                        item={item}
                        collapsed={collapsed}
                        instanceId={instanceId}
                        onNavigate={onNavigate}
                      />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

export function AppSidebar({
  collapsed,
  onToggleCollapsed,
  instanceId = "desktop",
  onNavigate,
  showCollapseToggle = true,
}: {
  collapsed: boolean;
  onToggleCollapsed?: () => void;
  instanceId?: string;
  onNavigate?: () => void;
  showCollapseToggle?: boolean;
}) {
  const { session, logout } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const identity = session?.email || session?.companyName || "";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className={cn("flex items-center gap-2 pt-4 pb-3", collapsed ? "px-2.5" : "px-4")}>
        {collapsed ? (
          <span className="mx-auto">
            <Brand compact />
          </span>
        ) : (
          <>
            <Brand />
            <span className="flex-1" />
            {showCollapseToggle && onToggleCollapsed && (
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

      <div className={cn("pb-3", collapsed ? "px-2" : "px-4")}>
        <WorkspaceSelector compact={collapsed} />
      </div>

      <div className={cn("pb-3", collapsed ? "px-2" : "px-3")}>
        <button
          type="button"
          data-tour="command-palette"
          onClick={() => openCommandPalette("tenant")}
          aria-label="Buscar (Ctrl+K)"
          className={cn(
            "flex w-full cursor-pointer items-center gap-2 rounded-sm border border-border bg-control text-muted transition-colors duration-200 hover:border-border-strong hover:text-text",
            collapsed ? "justify-center px-0 py-2" : "px-2.5 py-1.5"
          )}
        >
          <MagnifyingGlass size={15} className="shrink-0 text-faint" aria-hidden />
          {!collapsed && (
            <>
              <span className="flex-1 text-left text-[13px]">Buscar</span>
              <Kbd>Ctrl K</Kbd>
            </>
          )}
        </button>
      </div>

      <SidebarNav collapsed={collapsed} instanceId={instanceId} onNavigate={onNavigate} />

      <div className={cn("mt-2 border-t border-border py-3", collapsed ? "px-2" : "px-3")}>
        {!collapsed && identity && (
          <div className="mb-2 flex min-w-0 items-center gap-2.5 px-1">
            <IdentityTile label={identity} kind="account" size={26} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12.5px] font-medium text-text">{identity}</span>
              <span className="block truncate text-[11px] text-faint">
                {session?.companyName || "Organización"}
              </span>
            </span>
          </div>
        )}
        {collapsed ? (
          <div className="flex justify-center">
            <Tooltip label="Cerrar sesión" side="right">
              <button
                type="button"
                aria-label="Cerrar sesión"
                onClick={() => setConfirming(true)}
                className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-danger"
              >
                <SignOut size={17} aria-hidden />
              </button>
            </Tooltip>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn-ghost btn-sm w-full justify-start gap-2 px-2"
            onClick={() => setConfirming(true)}
          >
            <SignOut size={15} aria-hidden />
            Cerrar sesión
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="¿Cerrar sesión?"
        body="Vas a salir de este workspace. Podés volver a entrar con tu email y contraseña."
        confirmLabel="Cerrar sesión"
        tone="danger"
        onConfirm={() => {
          setConfirming(false);
          logout();
        }}
      />
    </div>
  );
}
