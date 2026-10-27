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
import { useEffect, useState, type ReactNode } from "react";
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
      className={`tab ${active ? "" : "opacity-70 hover:opacity-100"}`}
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
  const [advanced, setAdvanced] = useState(activeId === "avanzado");

  useEffect(() => {
    if (activeId === "avanzado") setAdvanced(true);
  }, [activeId]);

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
        <button
          type="button"
          className={`tab ${advanced || activeId === "avanzado" ? "" : "opacity-70 hover:opacity-100"}`}
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
        >
          {simple ? <Wrench size={15} aria-hidden /> : <CaretDown size={15} aria-hidden />}
          Avanzado
        </button>
        {advanced &&
          advancedTabs.map((tab) => (
            <TabLink key={tab.to} tab={tab} pathname={pathname} />
          ))}
      </nav>
      <div className="mt-4">{children}</div>
    </div>
  );
}
