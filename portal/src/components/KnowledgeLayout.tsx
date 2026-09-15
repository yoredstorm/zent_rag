import {
  BookOpen,
  Database,
  PencilLine,
  Binoculars,
  CaretDown,
  Sparkle,
  Graph,
  type Icon,
} from "@phosphor-icons/react";
import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import {
  KNOWLEDGE_ADVANCED_TABS,
  KNOWLEDGE_PILLARS,
  KNOWLEDGE_SUBNAVS,
  knowledgePillarForPath,
  knowledgeTabIsActive,
  type KnowledgeTab,
} from "../lib/knowledgeNav";

const PILLAR_ICONS: Record<(typeof KNOWLEDGE_PILLARS)[number]["id"], Icon> = {
  resumen: BookOpen,
  fuentes: Database,
  mejora: Sparkle,
};

const TAB_ICONS: Record<string, Icon> = {
  "/knowledge/sources": Database,
  "/knowledge/glossary": PencilLine,
  "/knowledge/catalog": Binoculars,
  "/knowledge/learning": Sparkle,
  "/knowledge/map": Graph,
  "/knowledge/jobs": Database,
  "/connectors": Database,
};

function TabLink({ tab, pathname }: { tab: KnowledgeTab; pathname: string }) {
  const IconCmp = TAB_ICONS[tab.to];
  const active = knowledgeTabIsActive(pathname, tab);
  return (
    <NavLink
      to={tab.to}
      end={tab.end}
      aria-current={active ? "page" : undefined}
      className={`tab ${active ? "" : "opacity-70 hover:opacity-100"}`}
    >
      {IconCmp && <IconCmp size={15} aria-hidden />}
      {tab.label}
    </NavLink>
  );
}

/** Hub de Conocimiento: Resumen, Fuentes, Aprendizaje + Avanzado. */
export function KnowledgeLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const pillar = knowledgePillarForPath(pathname);
  const [advanced, setAdvanced] = useState(pillar === "avanzado");

  useEffect(() => {
    if (pillar === "avanzado") setAdvanced(true);
  }, [pillar]);

  const subnav = pillar === "mejora" ? KNOWLEDGE_SUBNAVS.mejora : null;

  return (
    <div>
      <nav className="tabs" aria-label="Secciones de conocimiento">
        {KNOWLEDGE_PILLARS.map((tab) => {
          const IconCmp = PILLAR_ICONS[tab.id];
          const active = pillar === tab.id;
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              aria-current={active ? "page" : undefined}
              className={`tab ${active ? "" : "opacity-70 hover:opacity-100"}`}
            >
              <IconCmp size={15} aria-hidden />
              {tab.label}
            </NavLink>
          );
        })}
        <button
          type="button"
          className={`tab ${advanced || pillar === "avanzado" ? "" : "opacity-70 hover:opacity-100"}`}
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
        >
          <CaretDown size={15} aria-hidden />
          Avanzado
        </button>
        {advanced &&
          KNOWLEDGE_ADVANCED_TABS.map((tab) => (
            <TabLink key={tab.to} tab={tab} pathname={pathname} />
          ))}
      </nav>
      {subnav && (
        <nav className="tabs mt-1" aria-label="Subsecciones de Aprendizaje">
          {subnav.map((tab) => (
            <TabLink key={tab.to} tab={tab} pathname={pathname} />
          ))}
        </nav>
      )}
      <div className="mt-4">{children}</div>
    </div>
  );
}
