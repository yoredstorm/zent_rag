import {
  Bell,
  CircleNotch,
  Code,
  GearSix,
  GraduationCap,
  MagnifyingGlass,
  Question,
  SignOut,
  SidebarSimple,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { openCommandPalette } from "./CommandPalette";
import { ThemeToggle } from "./ThemeToggle";
import { KNOWLEDGE_ROUTE_TITLES } from "../lib/knowledgeNav";
import { navContextForPath } from "../lib/nav";
import { requestProductTourStart } from "../lib/productTour";
import { IdentityTile } from "./Brand";
import { Menu, MenuItem, MenuLabel, MenuSeparator } from "./ui/overlay";
import { Kbd } from "./ui/code";
import { StatusDot, type Tone } from "./ui/Badge";
import { Tooltip } from "./ui/overlay";
import { cn } from "./ui/cn";

const ROUTE_TITLES: Record<string, string> = {
  "/": "Panel general",
  "/chat": "Playground",
  "/agents": "Agentes",
  "/agents/new": "Nuevo agente",
  "/assistants": "Asistentes",
  ...KNOWLEDGE_ROUTE_TITLES,
  "/workflows": "Workflows",
  "/data-sources": "Fuentes de datos",
  "/prompts": "Instrucciones",
  "/usage": "Analítica",
  "/ai-quality": "Calidad de IA",
  "/deployments": "Despliegues",
  "/keys": "API y Claves",
  "/webhooks": "Webhooks",
  "/developers": "Centro de desarrolladores",
  "/developers/mcp": "MCP",
  "/team": "Equipo y Acceso",
  "/billing": "Facturación",
  "/security": "Seguridad y Auditoría",
  "/settings": "Configuración",
  "/evaluation": "Evaluación",
  "/projects": "Proyectos",
  "/connectors": "Conectores",
  "/workspaces": "Workspaces",
  "/notifications": "Notificaciones",
};

function routeTitle(pathname: string): string {
  const exact = ROUTE_TITLES[pathname];
  if (exact) return exact;
  if (pathname.startsWith("/agents/")) return "Agente";
  if (pathname.startsWith("/assistants/")) return "Asistente";
  if (pathname.startsWith("/evaluation/")) return "Evaluación";
  if (pathname === "/knowledge" || pathname.startsWith("/knowledge/")) {
    const key = Object.keys(ROUTE_TITLES)
      .filter((k) => pathname === k || pathname.startsWith(`${k}/`))
      .sort((a, b) => b.length - a.length)[0];
    return (key && ROUTE_TITLES[key]) || "Conocimiento";
  }
  if (pathname.startsWith("/developers")) return "Centro de desarrolladores";
  return "Zent";
}

/**
 * Topbar del workspace: dónde estás, buscador, estado del sistema y cuenta.
 * Todo lo operativo vive acá; el sidebar es navegación, no estado.
 */
export function Topbar({
  sidebarCollapsed = false,
  onExpandSidebar,
}: {
  sidebarCollapsed?: boolean;
  onExpandSidebar?: () => void;
} = {}) {
  const { session, logout } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [env, setEnv] = useState<string>("production");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [unread, setUnread] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    async function pollHealth() {
      try {
        const res = await fetch("/health");
        const data = await res.json();
        if (!cancelled) {
          setHealthOk(res.ok && data.status === "healthy");
          if (typeof data.environment === "string") setEnv(data.environment);
        }
      } catch {
        if (!cancelled) setHealthOk(false);
      }
    }
    void pollHealth();
    const t = window.setInterval(pollHealth, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    api<{ count: number }>("/api/v1/notifications/unread-count", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        if (!cancelled) setUnread(typeof data.count === "number" ? data.count : 0);
      })
      .catch(() => {
        if (!cancelled) setUnread(0);
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  const email = session?.email || "";
  const context = navContextForPath(pathname);
  const sectionLabel = context?.group.label ?? null;
  const title = context?.leaf.label ?? routeTitle(pathname);
  const healthTone: Tone = healthOk === null ? "neutral" : healthOk ? "ok" : "danger";
  const healthLabel = healthOk === null ? "Comprobando" : healthOk ? "Saludable" : "Degradado";

  return (
    <header className="sticky top-0 z-20 hidden items-center justify-between gap-4 border-b border-border bg-bg/85 px-5 py-2 backdrop-blur-md lg:flex">
      <div className="flex min-w-0 items-baseline gap-2.5">
        {sidebarCollapsed && onExpandSidebar && (
          <button
            type="button"
            onClick={onExpandSidebar}
            aria-label="Mostrar menú"
            className="-ml-1 mr-0.5 inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center self-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
          >
            <SidebarSimple size={16} aria-hidden />
          </button>
        )}
        {sectionLabel && (
          <span className="text-[11px] font-semibold tracking-[0.07em] text-faint uppercase">
            {sectionLabel}
          </span>
        )}
        <span className="truncate text-[15px] font-medium text-text" data-page-title>
          {title}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          className="mr-1 inline-flex h-9 min-w-[13rem] cursor-pointer items-center gap-2 rounded-sm border border-border bg-control px-2.5 text-[13px] text-faint transition-colors duration-200 hover:border-border-strong hover:text-muted"
          onClick={() => openCommandPalette("tenant")}
          aria-label="Buscar (Ctrl+K)"
          data-tour="command-palette"
        >
          <MagnifyingGlass size={14} aria-hidden />
          <span className="flex-1 text-left">Buscar o ir a…</span>
          <Kbd>Ctrl K</Kbd>
        </button>

        <Tooltip
          label={`Entorno ${env} · sistema ${healthLabel.toLowerCase()}`}
          side="bottom"
        >
          <span className="inline-flex h-9 items-center gap-2 rounded-sm px-2 text-xs text-muted">
            <span className="hidden xl:inline">{env}</span>
            {healthOk === null ? (
              <CircleNotch size={13} className="animate-spin text-faint" aria-hidden />
            ) : (
              <StatusDot tone={healthTone} />
            )}
            <span className="sr-only">
              Entorno {env}. Sistema {healthLabel}.
            </span>
          </span>
        </Tooltip>

        <ThemeToggle compact />

        <Tooltip label={unread > 0 ? `${unread} sin leer` : "Notificaciones"} side="bottom">
          <Link
            to="/notifications"
            className="relative inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
            aria-label={`Notificaciones${unread > 0 ? ` (${unread} sin leer)` : ""}`}
          >
            <Bell size={17} aria-hidden />
            {unread > 0 && (
              <span className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg tabular-nums">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </Link>
        </Tooltip>

        <Tooltip label="Documentación de API" side="bottom">
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
            aria-label="Documentación de API"
          >
            <Question size={17} aria-hidden />
          </a>
        </Tooltip>

        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />

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
              <IdentityTile label={email || "Z"} kind="account" size={28} />
            </button>
          }
        >
          <div className="border-b border-border px-2.5 pt-1.5 pb-2.5">
            <p className="truncate text-[13px] font-medium text-text">{email || "Cuenta"}</p>
            <p className="truncate text-[11px] text-faint">
              {session?.companyName || "Tu organización"}
            </p>
          </div>
          <MenuLabel>Ayuda y ajustes</MenuLabel>
          <MenuItem
            className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-muted outline-none select-none data-[highlighted]:bg-soft data-[highlighted]:text-text"
            onSelect={() => requestProductTourStart()}
          >
            <GraduationCap size={15} aria-hidden />
            Ver tutorial
          </MenuItem>
          <MenuItem
            className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-muted outline-none select-none data-[highlighted]:bg-soft data-[highlighted]:text-text"
            onSelect={() => navigate("/settings")}
          >
            <GearSix size={15} aria-hidden />
            Configuración
          </MenuItem>
          <MenuItem
            className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-muted outline-none select-none data-[highlighted]:bg-soft data-[highlighted]:text-text"
            onSelect={() => openCommandPalette("tenant")}
          >
            <Code size={15} aria-hidden />
            Buscar
          </MenuItem>
          <MenuSeparator className="my-1 h-px bg-border" />
          <MenuItem
            className={cn(
              "flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-[13px] text-danger outline-none select-none",
              "data-[highlighted]:bg-danger-soft"
            )}
            onSelect={() => logout()}
          >
            <SignOut size={15} aria-hidden />
            Cerrar sesión
          </MenuItem>
        </Menu>
      </div>
    </header>
  );
}
