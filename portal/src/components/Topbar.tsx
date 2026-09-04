import {
  Bell,
  CaretDown,
  CircleNotch,
  Question,
  SignOut,
  GearSix,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

const ROUTE_TITLES: Record<string, string> = {
  "/": "Panel general",
  "/chat": "Playground",
  "/agents": "Agentes",
  "/agents/new": "Nuevo agente",
  "/knowledge/sources": "Conocimiento",
  "/knowledge/collections": "Colecciones",
  "/knowledge/documents": "Documentos",
  "/knowledge/sql": "Fuentes SQL",
  "/knowledge/jobs": "Trabajos de sync",
  "/knowledge/playground": "Búsqueda",
  "/data-sources": "Fuentes de datos",
  "/prompts": "Instrucciones",
  "/usage": "Analítica",
  "/ai-quality": "Calidad de IA",
  "/deployments": "Despliegues",
  "/keys": "API y Claves",
  "/webhooks": "Webhooks",
  "/developers": "Centro de desarrolladores",
  "/team": "Equipo y Acceso",
  "/billing": "Facturación",
  "/security": "Seguridad y Auditoría",
  "/settings": "Configuración",
  "/users": "Equipo y Acceso",
  "/audit": "Seguridad y Auditoría",
  "/evaluation": "Evaluación",
  "/projects": "Proyectos",
  "/connectors": "Conectores",
  "/workspaces": "Workspaces",
  "/notifications": "Notificaciones",
};

function routeTitle(pathname: string): string {
  if (pathname.startsWith("/agents/")) return "Agente";
  if (pathname.startsWith("/evaluation/")) return "Evaluación";
  if (pathname.startsWith("/knowledge/")) {
    const key = Object.keys(ROUTE_TITLES).find((k) => pathname.startsWith(k));
    return (key && ROUTE_TITLES[key]) || "Conocimiento";
  }
  if (pathname.startsWith("/developers")) return "Centro de desarrolladores";
  return ROUTE_TITLES[pathname] || "Zent";
}

export function Topbar() {
  const { session, logout } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [env, setEnv] = useState<string>("production");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [unread, setUnread] = useState<number>(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (!menuOpen) return;
    function onPointer(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const email = session?.email || "";
  const initial = (email.charAt(0) || "Z").toUpperCase();

  return (
    <header className="sticky top-0 z-20 hidden items-center justify-between gap-3 border-b border-border bg-bg/85 px-6 py-2.5 backdrop-blur-md lg:flex">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="text-sm font-medium text-muted">{routeTitle(pathname)}</span>
      </div>

      <div className="flex items-center gap-2.5">
        <span className="badge badge-muted">{env}</span>

        <span
          className="relative inline-flex items-center gap-1.5 text-xs text-muted"
          title={healthOk === null ? "Comprobando estado" : healthOk ? "Sistema operativo" : "Sistema degradado"}
        >
          <span
            className={`status-dot ${healthOk === null ? "bg-faint" : healthOk ? "bg-ok" : "bg-danger"}`}
            aria-hidden
          />
          {healthOk === null ? (
            <CircleNotch size={13} className="animate-spin" aria-hidden />
          ) : healthOk ? (
            "Saludable"
          ) : (
            "Degradado"
          )}
        </span>

        <span className="mx-1 h-5 w-px bg-border" aria-hidden />

        <Link
          to="/notifications"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
          aria-label={`Notificaciones${unread > 0 ? ` (${unread} sin leer)` : ""}`}
        >
          <Bell size={17} aria-hidden />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Link>

        <a
          href="/docs"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 w-9 items-center justify-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
          aria-label="Documentación de API"
        >
          <Question size={17} aria-hidden />
        </a>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-sm p-1 text-text transition-colors duration-150 hover:bg-soft"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-soft text-xs font-semibold text-muted">
              {initial}
            </span>
            <CaretDown size={13} className="text-faint" aria-hidden />
          </button>
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full z-50 mt-1.5 w-52 overflow-hidden rounded-md border border-border bg-raised shadow-pop"
            >
              <div className="border-b border-border px-3 py-2.5">
                <p className="truncate text-[13px] font-medium text-text">{email || "Cuenta"}</p>
                <p className="text-[11px] text-faint">Workspace de {session?.companyName || "tu organización"}</p>
              </div>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
                onClick={() => {
                  setMenuOpen(false);
                  navigate("/settings");
                }}
              >
                <GearSix size={15} aria-hidden />
                Configuración
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-left text-[13px] text-danger transition-colors duration-150 hover:bg-danger-soft"
                onClick={() => {
                  setMenuOpen(false);
                  logout();
                }}
              >
                <SignOut size={15} aria-hidden />
                Cerrar sesión
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}