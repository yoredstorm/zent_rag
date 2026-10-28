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
import { useEffect, useRef, useState, type ReactNode } from "react";
import { loadSession } from "../api";
import {
  knowledgeAdvancedTabs,
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

function TabLink({ tab, pathname }: { tab: KnowledgeTab; pathname: string }) {
  const active = knowledgeTabIsActive(pathname, tab);
  return (
    <NavLink
      to={tab.to}
      end={tab.end}
      aria-current={active ? "page" : undefined}
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
  const advancedTabs = knowledgeAdvancedTabs(simple);
  const legacyPillar = simple ? null : knowledgePillarForPath(pathname);
  const simpleSection = simple ? knowledgeSimpleSectionForPath(pathname) : null;
  const activeId = simple ? simpleSection : legacyPillar;
  const [advanced, setAdvanced] = useState(false);
  const advancedRef = useRef<HTMLDivElement>(null);

  // La navegación principal permanece compacta incluso en rutas avanzadas.
  useEffect(() => {
    setAdvanced(false);
  }, [pathname]);

  useEffect(() => {
    if (!advanced) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!advancedRef.current?.contains(event.target as Node)) setAdvanced(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAdvanced(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [advanced]);

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
            type="button"
            className={`tab ${activeId === "avanzado" ? "text-text" : "opacity-70 hover:opacity-100"}`}
            onClick={() => setAdvanced((value) => !value)}
            aria-expanded={advanced}
            aria-controls="knowledge-advanced-tools"
            title="Herramientas especializadas. No son necesarias para empezar."
          >
            {simple ? <Wrench size={15} aria-hidden /> : <CaretDown size={15} aria-hidden />}
            Herramientas avanzadas
          </button>
          {advanced && (
            <div
              id="knowledge-advanced-tools"
              role="group"
              aria-label="Herramientas avanzadas de conocimiento"
              className="absolute right-0 top-full z-50 mt-2 w-[min(90vw,410px)] rounded-lg border border-border bg-surface p-3 shadow-xl"
            >
              <p className="px-2 pb-2 text-xs text-faint">
                Para administración, diagnóstico o configuración especializada.
              </p>
              <div className="grid max-h-[min(65vh,450px)] grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
                {advancedTabs.map((tab) => (
                  <div key={tab.to} onClick={() => setAdvanced(false)}>
                    <TabLink tab={tab} pathname={pathname} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </nav>
      <div className="mt-4">{children}</div>
    </div>
  );
}
