import { Link } from "react-router-dom";
import { KNOWLEDGE_PILLARS } from "../lib/knowledgeNav";

export function KnowledgePillarLinks({
  title = "Conocimiento",
  subtitle,
}: {
  title?: string;
  subtitle?: string;
}) {
  return (
    <nav
      className="mb-6 rounded-md border border-border bg-soft/60 px-4 py-3"
      aria-label="Pilares de conocimiento"
      data-testid="knowledge-pillar-links"
    >
      <p className="text-sm font-semibold text-text">{title}</p>
      {subtitle && <p className="mt-1 text-xs text-muted">{subtitle}</p>}
      <ul className="mt-2 flex flex-wrap gap-2">
        {KNOWLEDGE_PILLARS.map((pillar) => (
          <li key={pillar.id}>
            <Link to={pillar.to} className="btn btn-secondary min-h-9 px-3 text-xs">
              {pillar.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
