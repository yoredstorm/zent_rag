import { NavLink, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { COMPANY_TABS, companyTabIsActive } from "../lib/companyNav";

/** Hub de Company Intelligence Studio: una pestaña por sección (§1). */
export function CompanyIntelligenceLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <div>
      <nav className="tabs flex-wrap" aria-label="Secciones de Company Intelligence">
        {COMPANY_TABS.map((tab) => {
          const active = companyTabIsActive(pathname, tab);
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              aria-current={active ? "page" : undefined}
              className={`tab ${active ? "" : "opacity-70 hover:opacity-100"}`}
            >
              {tab.label}
            </NavLink>
          );
        })}
      </nav>
      <div className="mt-4">{children}</div>
    </div>
  );
}
