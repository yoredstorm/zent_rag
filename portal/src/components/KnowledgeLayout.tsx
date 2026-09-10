import { BookOpen, Database, MagnifyingGlass, PencilLine, Binoculars, Wrench, CaretDown, Sparkle, Graph } from "@phosphor-icons/react";
import { NavLink } from "react-router-dom";
import { useState, type ReactNode } from "react";

const DEFAULT_TABS: { to: string; label: string; icon: typeof Database; end?: boolean }[] = [
  { to: "/knowledge", label: "Resumen", icon: BookOpen, end: true },
  { to: "/knowledge/learning", label: "Aprendizaje", icon: Sparkle },
  { to: "/knowledge/map", label: "Mapa", icon: Graph },
  { to: "/knowledge/sources", label: "Fuentes", icon: Database },
  { to: "/knowledge/database", label: "Base", icon: Database },
  { to: "/knowledge/understanding", label: "Entendimiento", icon: BookOpen },
  { to: "/knowledge/glossary", label: "Términos", icon: PencilLine },
  { to: "/knowledge/improvements", label: "Mejoras", icon: Wrench },
];

const ADVANCED_TABS: { to: string; label: string; icon: typeof Database; end?: boolean }[] = [
  { to: "/knowledge/catalog", label: "Catálogo", icon: Binoculars },
  { to: "/knowledge/jobs", label: "Sincronización", icon: Database },
  { to: "/knowledge/review", label: "Relaciones", icon: PencilLine },
  { to: "/knowledge/sql", label: "SQL plataforma", icon: Database },
  { to: "/connectors", label: "Conectores", icon: Database },
  { to: "/knowledge/collections", label: "Colecciones", icon: Database },
  { to: "/knowledge/documents", label: "Documentos", icon: Database },
  { to: "/knowledge/playground", label: "Búsqueda", icon: MagnifyingGlass },
];

/** Hub de Conocimiento: tabs simples por defecto; avanzado en disclosure. */
export function KnowledgeLayout({ children }: { children: ReactNode }) {
  const [advanced, setAdvanced] = useState(false);
  return (
    <div>
      <nav className="tabs" aria-label="Secciones de conocimiento">
        {DEFAULT_TABS.map((tab) => (
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
        <button
          type="button"
          className="tab opacity-70 hover:opacity-100"
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
        >
          <CaretDown size={15} aria-hidden />
          Avanzado
        </button>
        {advanced &&
          ADVANCED_TABS.map((tab) => (
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
