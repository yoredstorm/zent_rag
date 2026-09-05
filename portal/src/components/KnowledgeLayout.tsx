import {
  Database,
  Files,
  FolderSimple,
  Gauge,
  List,
  MagnifyingGlass,
  Plugs,
  type Icon,
} from "@phosphor-icons/react";
import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const KNOWLEDGE_TABS: { to: string; label: string; icon: Icon; end?: boolean }[] = [
  { to: "/knowledge", label: "Resumen", icon: Gauge, end: true },
  { to: "/knowledge/sources", label: "Fuentes", icon: Database },
  { to: "/knowledge/collections", label: "Colecciones", icon: FolderSimple },
  { to: "/knowledge/documents", label: "Documentos", icon: Files },
  { to: "/knowledge/sql", label: "Bases de datos", icon: Database },
  { to: "/connectors", label: "Conectores", icon: Plugs },
  { to: "/knowledge/jobs", label: "Sincronización", icon: List },
  { to: "/knowledge/playground", label: "Búsqueda", icon: MagnifyingGlass },
];

/** Hub de Conocimiento: subnavegación compartida por todas las páginas del dominio. */
export function KnowledgeLayout({ children }: { children: ReactNode }) {
  return (
    <div>
      <nav className="tabs" aria-label="Secciones de conocimiento">
        {KNOWLEDGE_TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `tab ${isActive ? "" : "opacity-70 hover:opacity-100"}`
            }
          >
            <tab.icon size={15} aria-hidden />
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-4">{children}</div>
    </div>
  );
}