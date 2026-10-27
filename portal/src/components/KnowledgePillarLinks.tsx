import { Link } from "react-router-dom";
import { loadSession } from "../api";
import { knowledgeTabs } from "../lib/knowledgeNav";

export function KnowledgePillarLinks({
  title = "Conocimiento",
  subtitle,
}: {
  title?: string;
  subtitle?: string;
}) {
  const simple = Boolean(loadSession()?.featureFlags?.knowledge_simple_ux);
  return (
    <nav
      className="mb-6 rounded-md border border-border bg-soft/60 px-4 py-3"
      aria-label="Pilares de conocimiento"
      data-testid="knowledge-pillar-links"
    >
      <p className="text-sm font-semibold text-text">{title}</p>
      {subtitle && <p className="mt-1 text-xs text-muted">{subtitle}</p>}
      <ul className="mt-2 flex flex-wrap gap-2">
        {knowledgeTabs(simple).map((pillar) => (
          <li key={pillar.to}>
            <Link to={pillar.to} className="btn btn-secondary min-h-9 px-3 text-xs">
              {pillar.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
