import { MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, platformApi, type Session } from "../api";
import { useAuth } from "../auth";
import { usePlatformAuth } from "../platformAuth";
import { visibleNavLeaves } from "../lib/nav";
import { platformNavLeaves } from "../lib/platformNav";

type PaletteMode = "tenant" | "platform";

export type Command = {
  id: string;
  label: string;
  group: string;
  to?: string;
};

let openListener: ((mode: PaletteMode) => void) | null = null;

/** Abre la paleta desde cualquier botón (Topbar / header del Control Center). */
export function openCommandPalette(mode: PaletteMode) {
  openListener?.(mode);
}

async function buildTenantCommands(session: Session): Promise<Command[]> {
  const token = session.token;
  const organizationId = session.organizationId;
  let entitlements: Record<string, boolean | number | null> = {};
  try {
    const out = await api<{ entitlements: Record<string, boolean | number | null> }>(
      "/api/v1/billing/entitlements",
      { token, organizationId }
    );
    entitlements = out.entitlements || {};
  } catch {
    entitlements = {};
  }

  const nav = visibleNavLeaves(session, entitlements).map((l) => ({
    id: `nav-${l.to}`,
    label: l.label,
    group: "Navegación",
    to: l.to,
  }));

  const [agents, sources, deployments] = await Promise.all([
    api<{ agents: { id: string; name: string }[] }>("/api/v1/agents", { token, organizationId }).catch(() => ({ agents: [] })),
    api<{ sources: { id: string; name: string }[] }>("/api/v1/sources", { token, organizationId }).catch(() => ({ sources: [] })),
    api<{ deployments: { id: string; slug: string }[] }>("/api/v1/deployments", { token, organizationId }).catch(() => ({ deployments: [] })),
  ]);

  return [
    ...nav,
    ...(agents.agents || []).map((a) => ({ id: `agent-${a.id}`, label: a.name, group: "Agentes", to: `/agents/${a.id}` })),
    ...(sources.sources || []).map((s) => ({ id: `source-${s.id}`, label: s.name, group: "Knowledge sources", to: "/knowledge/sources" })),
    ...(deployments.deployments || []).map((d) => ({ id: `deploy-${d.id}`, label: d.slug, group: "Deployments", to: "/deployments" })),
  ];
}

async function buildPlatformCommands(token: string): Promise<Command[]> {
  const nav = platformNavLeaves().map((l) => ({
    id: `nav-${l.to}`,
    label: l.label,
    group: "Navegación",
    to: l.to,
  }));
  const tenants = await platformApi<{ organizations: { id: string; name: string; company_name: string | null }[] }>(
    "/api/v1/platform/organizations",
    { token }
  ).catch(() => ({ organizations: [] as { id: string; name: string; company_name: string | null }[] }));
  return [
    ...nav,
    ...(tenants.organizations || []).map((t) => ({
      id: `tenant-${t.id}`,
      label: t.company_name || t.name,
      group: "Tenants",
      to: `/control-center/tenants/${t.id}`,
    })),
  ];
}

export function CommandPaletteRoot({ mode }: { mode: PaletteMode }) {
  const navigate = useNavigate();
  const { session } = useAuth();
  const { session: platformSession } = usePlatformAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [commands, setCommands] = useState<Command[]>([]);
  const [active, setActive] = useState(0);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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
    inputRef.current?.focus();
    setError("");
    setCommands([]);
    if (mode === "tenant" && session) {
      buildTenantCommands(session)
        .then(setCommands)
        .catch((e) => setError(e instanceof Error ? e.message : "Error"));
    } else if (mode === "platform" && platformSession) {
      buildPlatformCommands(platformSession.token)
        .then(setCommands)
        .catch((e) => setError(e instanceof Error ? e.message : "Error"));
    }
  }, [open, mode, session, platformSession]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q) || c.group.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  function close() {
    setOpen(false);
    setQuery("");
  }

  function run(cmd: Command) {
    close();
    if (cmd.to) navigate(cmd.to);
  }

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((a) => (filtered.length ? (a + 1) % filtered.length : 0));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((a) => (filtered.length ? (a - 1 + filtered.length) % filtered.length : 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const cmd = filtered[active];
        if (cmd) run(cmd);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, filtered, active]);

  if (!open) return null;

  const groups = filtered.reduce<Record<string, Command[]>>((acc, c) => {
    (acc[c.group] = acc[c.group] || []).push(c);
    return acc;
  }, {});

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh]">
      <div className="absolute inset-0 bg-black/60" onClick={close} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Búsqueda de comandos"
        className="relative w-[min(38rem,calc(100vw-2rem))] overflow-hidden rounded-md border border-border bg-surface shadow-pop"
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <MagnifyingGlass size={18} className="text-faint" aria-hidden />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={mode === "platform" ? "Buscar páginas, tenants…" : "Buscar páginas, agentes, fuentes…"}
            aria-label="Buscar"
            className="w-full bg-transparent text-sm text-text outline-none placeholder:text-faint"
          />
          <kbd className="rounded-xs border border-border bg-soft px-1.5 py-0.5 text-[10px] text-faint">ESC</kbd>
        </div>
        <div
          className="max-h-[46vh] overflow-y-auto p-2"
          aria-busy={commands.length === 0 && !error}
        >
          {error && <p className="px-3 py-2 text-xs text-danger" role="alert">{error}</p>}
          {!error && filtered.length === 0 && (
            <p className="px-3 py-4 text-sm text-muted" role="status">Sin coincidencias.</p>
          )}
          {Object.entries(groups).map(([group, items]) => (
            <div key={group} className="mb-1">
              <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-faint">{group}</p>
              <ul role="listbox" aria-label={group}>
                {items.map((cmd) => {
                  const globalIndex = filtered.indexOf(cmd);
                  return (
                    <li key={cmd.id} role="option" aria-selected={globalIndex === active}>
                      <button
                        type="button"
                        onMouseEnter={() => setActive(globalIndex)}
                        onClick={() => run(cmd)}
                        className={`flex w-full items-center justify-between gap-2 rounded-sm px-3 py-2 text-left text-sm ${
                          globalIndex === active ? "bg-accent-soft text-accent" : "text-text hover:bg-soft"
                        }`}
                      >
                        <span className="truncate">{cmd.label}</span>
                        {cmd.to && <span className="shrink-0 text-[11px] text-faint">{cmd.to}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}