import {
  ArrowCounterClockwise,
  ChartBar,
  Flask,
  Gauge,
  type Icon,
} from "@phosphor-icons/react";
import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const QUALITY_TABS: { to: string; label: string; icon: Icon; end?: boolean }[] = [
  { to: "/ai-quality", label: "Resumen", icon: Gauge, end: true },
  { to: "/evaluation/datasets", label: "Datasets", icon: Flask },
  { to: "/evaluation/runs", label: "Runs", icon: ChartBar },
  { to: "/evaluation/compare", label: "Regresiones", icon: ArrowCounterClockwise },
];

/** Hub de Calidad: subnavegación compartida entre Calidad de IA y Evaluación. */
export function QualityLayout({ children }: { children: ReactNode }) {
  return (
    <div>
      <nav className="tabs" aria-label="Secciones de calidad">
        {QUALITY_TABS.map((tab) => (
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