import {
  Brain,
  CaretDown,
  ChatCircleDots,
  Database,
  Graph,
  Heartbeat,
  Pulse,
  Wrench,
  type Icon,
} from "@phosphor-icons/react";
import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadSession } from "../api";
import {
  knowledgeAdvancedGroups,
  knowledgePillarForPath,
  knowledgeSimpleSectionForPath,
  knowledgeTabIsActive,
  knowledgeTabs,
  type KnowledgeSimpleSection,
  type KnowledgeTab,
} from "../lib/knowledgeNav";

const PILLAR_ICONS: Record<string, Icon> = {
  inicio: Brain,
  explorador: Graph,
  salud: Heartbeat,
  fuentes: Database,
  actividad: Pulse,
  resumen: Brain,
  preguntar: ChatCircleDots,
  mejorar: Heartbeat,
};

const SIMPLE_TAB_SECTIONS: Record<string, KnowledgeSimpleSection> = {
  "/knowledge": "resumen",
  "/knowledge/sources": "fuentes",
  "/knowledge/ask": "preguntar",
  "/knowledge/improve": "mejorar",
};

function TabLink({
  tab,
  pathname,
  onSelect,
}: {
  tab: KnowledgeTab;
  pathname: string;
  onSelect?: () => void;
}) {
  const active = knowledgeTabIsActive(pathname, tab);
  return (
    <NavLink
      to={tab.to}
      end={tab.end}
      aria-current={active ? "page" : undefined}
      onClick={onSelect}
      className={`block rounded-md px-3 py-2 text-[13px] transition-colors hover:bg-soft hover:text-text focus-visible:outline-2 focus-visible:outline-accent ${active ? "bg-soft font-semibold text-text" : "text-muted"}`}
    >
      {tab.label}
    </NavLink>
  );
}

/** Knowledge OS: cuatro experiencias simples + herramientas avanzadas. */
export function KnowledgeLayout({
  children,
  simpleNavigation,
}: {
  children: ReactNode;
  simpleNavigation?: boolean;
}) {
  const { pathname } = useLocation();
  const simple =
    simpleNavigation ?? Boolean(loadSession()?.featureFlags?.knowledge_simple_ux);
  const tabs = knowledgeTabs(simple);
  const advancedGroups = knowledgeAdvancedGroups(simple);
  const legacyPillar = simple ? null : knowledgePillarForPath(pathname);
  const simpleSection = simple ? knowledgeSimpleSectionForPath(pathname) : null;
  const activeId = simple ? simpleSection : legacyPillar;
  const [advanced, setAdvanced] = useState(false);
  const [query, setQuery] = useState("");
  const advancedRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // La navegación principal permanece compacta incluso en rutas avanzadas.
  useEffect(() => {
    setAdvanced(false);
    setQuery("");
  }, [pathname]);

  useEffect(() => {
    if (!advanced) return;
    setQuery("");
    const focusTimer = window.setTimeout(() => {
      panelRef.current
        ?.querySelector<HTMLElement>(
          'a, button, input, [tabindex]:not([tabindex="-1"])',
        )
        ?.focus();
    }, 0);
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!advancedRef.current?.contains(event.target as Node)) setAdvanced(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAdvanced(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [advanced]);

  const filteredGroups = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return advancedGroups;
    return advancedGroups
      .map((group) => ({
        ...group,
        tabs: group.tabs.filter((tab) =>
          `${group.label} ${tab.label}`.toLowerCase().includes(term),
        ),
      }))
      .filter((group) => group.tabs.length > 0);
  }, [advancedGroups, query]);

  return (
    <div>
      <nav className="tabs" aria-label="Secciones de conocimiento">
        {tabs.map((tab) => {
          const active = simple
            ? SIMPLE_TAB_SECTIONS[tab.to] === simpleSection
            : legacyPillar === (tab as { id?: string }).id;
          const iconKey = simple
            ? SIMPLE_TAB_SECTIONS[tab.to]
            : (tab as { id?: string }).id;
          const IconCmp = iconKey ? PILLAR_ICONS[iconKey] : undefined;
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              aria-current={active ? "page" : undefined}
              className={`tab ${active ? "" : "opacity-70 hover:opacity-100"}`}
            >
              {IconCmp && <IconCmp size={15} aria-hidden />}
              {tab.label}
            </NavLink>
          );
        })}
        <div ref={advancedRef} className="relative">
          <button
            ref={triggerRef}
            type="button"
            className={`tab ${activeId === "avanzado" ? "text-text" : "opacity-70 hover:opacity-100"}`}
            onClick={() => setAdvanced((value) => !value)}
            aria-expanded={advanced}
            aria-controls="knowledge-advanced-tools"
            aria-haspopup="dialog"
            aria-label="Herramientas avanzadas"
            title="Herramientas especializadas. No son necesarias para empezar."
          >
            {simple ? <Wrench size={15} aria-hidden /> : <CaretDown size={15} aria-hidden />}
            <span className="hidden sm:inline">Herramientas avanzadas</span>
            <span className="sm:hidden">Avanzado</span>
          </button>
          {advanced && (
            <div
              ref={panelRef}
              id="knowledge-advanced-tools"
              role="dialog"
              aria-modal="false"
              aria-labelledby="knowledge-advanced-tools-title"
              className="absolute right-0 top-full z-50 mt-2 w-[min(92vw,470px)] rounded-lg border border-border bg-surface p-3 shadow-xl"
            >
              <div className="flex items-start justify-between gap-3 px-2 pb-2">
                <div>
                  <p id="knowledge-advanced-tools-title" className="text-sm font-semibold text-text">
                    Herramientas avanzadas
                  </p>
                  <p className="mt-0.5 text-xs text-faint">
                    Para administración, diagnóstico o configuración especializada.
                  </p>
                </div>
                <Wrench size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden />
              </div>
              <label className="sr-only" htmlFor="knowledge-advanced-search">
                Buscar herramienta avanzada
              </label>
              <input
                id="knowledge-advanced-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar herramienta"
                className="input mb-2 h-9 text-xs"
              />
              <div className="max-h-[min(65vh,460px)] overflow-y-auto pr-1">
                {filteredGroups.length === 0 ? (
                  <p className="px-2 py-3 text-xs text-muted">
                    Ninguna herramienta coincide.
                  </p>
                ) : (
                  filteredGroups.map((group) => (
                    <section key={group.id} className="mb-2 last:mb-0">
                      <p className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
                        {group.label}
                      </p>
                      <p className="px-2 pb-1 text-[11px] text-faint">
                        {group.description}
                      </p>
                      <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
                        {group.tabs.map((tab) => (
                          <TabLink
                            key={tab.to}
                            tab={tab}
                            pathname={pathname}
                            onSelect={() => setAdvanced(false)}
                          />
                        ))}
                      </div>
                    </section>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </nav>
      <div className="mt-4">{children}</div>
    </div>
  );
}
