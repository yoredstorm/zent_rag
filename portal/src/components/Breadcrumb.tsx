import { Link } from "react-router-dom";

export type BreadcrumbItem = { label: string; to?: string };

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Miga de pan" className="mb-4 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
      {items.map((item, i) => {
        const last = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`} className="flex items-center gap-1.5">
            {i > 0 && <span aria-hidden className="text-faint">/</span>}
            {item.to && !last ? (
              <Link to={item.to} className="rounded-sm transition-colors hover:text-accent">
                {item.label}
              </Link>
            ) : (
              <span className={last ? "font-medium text-text" : ""}>{item.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}