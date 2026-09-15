import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Clock, MagnifyingGlass, SquaresFour, type Icon } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, platformApi, type Session } from "../api";
import { useAuth } from "../auth";
import { usePlatformAuth } from "../platformAuth";
import { visibleNavLeaves } from "../lib/nav";
import { platformNavLeaves } from "../lib/platformNav";
import { useEntitlements } from "../lib/entitlements";
import { Kbd } from "./ui/code";
import { Skeleton } from "./ui/states";
import { cn } from "./ui/cn";

type PaletteMode = "tenant" | "platform";

export type Command = {
  id: string;
  label: string;
  group: string;
  to?: string;
  icon?: Icon;
  /** Palabras extra para buscar (sinónimos, rutas). */
  keywords?: string;
};

const RECENT_KEY = "zent_palette_recent";
const MAX_RECENT = 5;

let openListener: ((mode: PaletteMode) => void) | null = null;

/** Abre la paleta desde cualquier botón (Topbar / header del Control Center). */
export function openCommandPalette(mode: PaletteMode) {
  openListener?.(mode);
}

function readRecent(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function pushRecent(id: string) {
  try {
    const next = [id, ...readRecent().filter((v) => v !== id)].slice(0, MAX_RECENT);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // sin persistencia
  }
}

async function buildTenantCommands(session: Session, entitlements: Record<string, boolean | number | null>): Promise<Command[]> {
  const token = session.token;
  const organizationId = session.organizationId;

  const nav = visibleNavLeaves(session, entitlements).map((l) => ({
    id: `nav-${l.to}`,
    label: l.label,
    group: "Navegación",
    to: l.to,
    icon: l.icon,
    keywords: l.to,
  }));

  const [agents, sources, deployments] = await Promise.all([
    api<{ agents: { id: string; name: string }[] }>("/api/v1/agents", { token, organizationId }).catch(() => ({ agents: [] })),
    api<{ sources: { id: string; name: string }[] }>("/api/v1/sources", { token, organizationId }).catch(() => ({ sources: [] })),
    api<{ deployments: { id: string; slug: string }[] }>("/api/v1/deployments", { token, organizationId }).catch(() => ({ deployments: [] })),
  ]);

  return [
    ...nav,
    ...(agents.agents || []).map((a) => ({
      id: `agent-${a.id}`,
      label: a.name,
      group: "Agentes",
      to: `/agents/${a.id}`,
      icon: SquaresFour,
    })),
    ...(sources.sources || []).map((s) => ({
      id: `source-${s.id}`,
      label: s.name,
      group: "Fuentes de conocimiento",
      to: "/knowledge/sources",
      icon: SquaresFour,
    })),
    ...(deployments.deployments || []).map((d) => ({
      id: `deploy-${d.id}`,
      label: d.slug,
      group: "Despliegues",
      to: "/deployments",
      icon: SquaresFour,
    })),
  ];
}

async function buildPlatformCommands(token: string): Promise<Command[]> {
  const nav = platformNavLeaves().map((l) => ({
    id: `nav-${l.to}`,
    label: l.label,
    group: "Navegación",
    to: l.to,
    icon: l.icon,
    keywords: l.to,
  }));
  const tenants = await platformApi<{
    organizations: { id: string; name: string; company_name: string | null }[];
  }>("/api/v1/platform/organizations", { token }).catch(
    () => ({ organizations: [] as { id: string; name: string; company_name: string | null }[] })
  );
  return [
    ...nav,
    ...(tenants.organizations || []).map((t) => ({
      id: `tenant-${t.id}`,
      label: t.company_name || t.name,
      group: "Tenants",
      to: `/control-center/tenants/${t.id}`,
      icon: SquaresFour,
    })),
  ];
}

/** Ranking: prefijo > inicio de palabra > substring. Estable dentro de cada nivel. */
function score(command: Command, query: string): number {
  const label = command.label.toLowerCase();
  const q = query.toLowerCase();
  if (label === q) return 0;
  if (label.startsWith(q)) return 1;
  if (label.split(/[\s/·-]+/).some((word) => word.startsWith(q))) return 2;
  if (label.includes(q)) return 3;
  if (command.group.toLowerCase().includes(q)) return 4;
  if (command.keywords?.toLowerCase().includes(q)) return 5;
  return -1;
}

export function CommandPaletteRoot({ mode }: { mode: PaletteMode }) {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { session: platformSession } = usePlatformAuth();
  const entitlements = useEntitlements();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [commands, setCommands] = useState<Command[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    openListener = (m) => {
      if (m === mode) {
        setOpen(true);
        setQuery("");
        setActive(0);
      }
    };
    return () => {
      openListener = null;
    };
  }, [mode]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
        setQuery("");
        setActive(0);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    setError("");
    setCommands([]);
    setLoading(true);
    const request =
      mode === "tenant" && session
        ? buildTenantCommands(session, entitlements)
        : mode === "platform" && platformSession
          ? buildPlatformCommands(platformSession.token)
          : Promise.resolve([]);
    request
      .then(setCommands)
      .catch((e) => setError(e instanceof Error ? e.message : "No pudimos cargar los comandos."))
      .finally(() => setLoading(false));
  }, [open, mode, session, platformSession, entitlements]);

  const recent = useMemo(() => {
    if (!open) return [];
    const ids = readRecent();
    return ids
      .map((id) => commands.find((c) => c.id === id))
      .filter((c): c is Command => Boolean(c));
  }, [open, commands]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands
      .map((c) => ({ c, s: score(c, q) }))
      .filter((row) => row.s >= 0)
      .sort((a, b) => a.s - b.s)
      .map((row) => row.c);
  }, [commands, query]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  function close() {
    setOpen(false);
    setQuery("");
  }

  function run(cmd: Command) {
    pushRecent(cmd.id);
    close();
    if (cmd.to) navigate(cmd.to);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((a) => (filtered.length ? (a + 1) % filtered.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((a) => (filtered.length ? (a - 1 + filtered.length) % filtered.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const cmd = filtered[active];
      if (cmd) run(cmd);
    } else if (event.key === "Home") {
      setActive(0);
    } else if (event.key === "End") {
      setActive(Math.max(0, filtered.length - 1));
    }
  }

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const showRecent = !query.trim() && recent.length > 0;
  const groups = useMemo(() => {
    const source = query.trim() ? filtered : filtered.filter((c) => !recent.some((r) => r.id === c.id));
    return source.reduce<Record<string, Command[]>>((acc, c) => {
      (acc[c.group] = acc[c.group] || []).push(c);
      return acc;
    }, {});
  }, [filtered, query, recent]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[var(--z-palette)] animate-fade-in bg-scrim backdrop-blur-[2px] data-[state=closed]:animate-fade-out" />
        <DialogPrimitive.Content
          aria-label="Búsqueda de comandos"
          onKeyDown={onKeyDown}
          className="fixed top-[12vh] left-1/2 z-[var(--z-palette)] flex max-h-[min(70dvh,640px)] w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 flex-col animate-pop-in overflow-hidden rounded-xl border border-border bg-overlay shadow-pop outline-none data-[state=closed]:animate-pop-out"
        >
          <DialogPrimitive.Title className="sr-only">Búsqueda de comandos</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Buscá páginas, agentes, fuentes y despliegues. Usá las flechas para navegar y Enter para abrir.
          </DialogPrimitive.Description>

          <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
            <MagnifyingGlass size={17} className="shrink-0 text-ghost" aria-hidden />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                mode === "platform" ? "Buscar páginas, tenants…" : "Buscar páginas, agentes, fuentes…"
              }
              aria-label="Buscar"
              className="w-full bg-transparent text-sm text-text outline-none placeholder:text-ghost"
            />
            <Kbd>esc</Kbd>
          </div>

          <div
            ref={listRef}
            className="min-h-0 flex-1 overflow-y-auto p-2"
            aria-busy={loading}
            role="listbox"
            aria-label="Resultados"
          >
            {loading && (
              <div className="flex flex-col gap-1.5 p-1" aria-hidden>
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-9" />
                ))}
              </div>
            )}

            {!loading && error && (
              <p className="px-3 py-3 text-[13px] text-danger" role="alert">
                {error}
              </p>
            )}

            {!loading && !error && showRecent && (
              <div className="mb-1">
                <p className="eyebrow flex items-center gap-1.5 px-3 py-1.5">
                  <Clock size={11} aria-hidden />
                  Recientes
                </p>
                <ul>
                  {recent.map((cmd) => {
                    const index = filtered.indexOf(cmd);
                    return (
                      <CommandRow
                        key={`recent-${cmd.id}`}
                        command={cmd}
                        active={index === active}
                        onHover={() => setActive(index)}
                        onSelect={() => run(cmd)}
                      />
                    );
                  })}
                </ul>
              </div>
            )}

            {!loading && !error && filtered.length === 0 && (
              <div className="px-3 py-6 text-center">
                <p className="text-sm text-text">Sin coincidencias</p>
                <p className="mt-1 text-xs text-muted">
                  Probá con el nombre de una página, un agente o una fuente.
                </p>
              </div>
            )}

            {!loading &&
              !error &&
              Object.entries(groups).map(([group, items]) => (
                <div key={group} className="mb-1">
                  <p className="eyebrow px-3 py-1.5">{group}</p>
                  <ul>
                    {items.map((cmd) => {
                      const index = filtered.indexOf(cmd);
                      return (
                        <CommandRow
                          key={cmd.id}
                          command={cmd}
                          active={index === active}
                          onHover={() => setActive(index)}
                          onSelect={() => run(cmd)}
                        />
                      );
                    })}
                  </ul>
                </div>
              ))}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 text-[11px] text-faint">
            <span className="flex items-center gap-3">
              <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> navegar
              </span>
              <span className="flex items-center gap-1.5">
                <Kbd>↵</Kbd> abrir
              </span>
            </span>
            <span className="tabular-nums">{filtered.length > 0 ? `${filtered.length} resultados` : ""}</span>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function CommandRow({
  command,
  active,
  onHover,
  onSelect,
}: {
  command: Command;
  active: boolean;
  onHover: () => void;
  onSelect: () => void;
}) {
  const IconEl = command.icon ?? SquaresFour;
  return (
    <li role="option" aria-selected={active} data-active={active || undefined}>
      <button
        type="button"
        onMouseEnter={onHover}
        onClick={onSelect}
        className={cn(
          "flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-3 py-2 text-left text-[13px] transition-colors duration-100",
          active ? "bg-soft text-text" : "text-muted hover:bg-soft/60 hover:text-text"
        )}
      >
        <IconEl
          size={15}
          weight={active ? "fill" : "regular"}
          className={cn("shrink-0", active ? "text-accent" : "text-faint")}
          aria-hidden
        />
        <span className="min-w-0 flex-1 truncate">{command.label}</span>
        {active && <Kbd>↵</Kbd>}
      </button>
    </li>
  );
}
