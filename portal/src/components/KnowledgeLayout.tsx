import {
  Brain,
  CaretDown,
  Database,
  Graph,
  Heartbeat,
  Pulse,
  type Icon,
} from "@phosphor-icons/react";
import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import {
  KNOWLEDGE_ADVANCED_TABS,
  KNOWLEDGE_PILLARS,
  knowledgePillarForPath,
  knowledgeTabIsActive,
  type KnowledgeTab,
} from "../lib/knowledgeNav";

const PILLAR_ICONS: Record<string, Icon> = {
  inicio: Brain,
  explorador: Graph,
  salud: Heartbeat,
  fuentes: Database,
  actividad: Pulse,
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

/** Knowledge OS: Resumen, Fuentes, Modelo, Calidad, Evaluación + Avanzado. */
export function KnowledgeLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const pillar = knowledgePillarForPath(pathname);
  const [advanced, setAdvanced] = useState(pillar === "avanzado");

  useEffect(() => {
    if (pillar === "avanzado") setAdvanced(true);
  }, [pillar]);

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
      <div className="mt-4">{children}</div>
    </div>
  );
}
