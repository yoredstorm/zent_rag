// =============================================================================
// ActivityFeed — el aprendizaje contado como historia, no como log
// =============================================================================
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Brain,
  FileText,
  Gear,
  MagnifyingGlass,
  SealCheck,
  Stack,
  type Icon,
} from "@phosphor-icons/react";
import { Button, Panel, Skeleton, cn } from "../ui";
import type { KnowledgeFeedItem } from "../../lib/knowledgeActivity";
import { timeAgo } from "../../lib/format";

const CATEGORY_ICONS: Record<string, Icon> = {
  discovery: MagnifyingGlass,
  ai: Brain,
  validation: SealCheck,
  indexing: Stack,
  system: Gear,
  compilation: FileText,
  object: Brain,
  knowledge: Brain,
};

const SEVERITY_TONE: Record<KnowledgeFeedItem["severity"], string> = {
  info: "text-info",
  success: "text-ok",
  warning: "text-warn",
  error: "text-danger",
};

function FeedRow({ item }: { item: KnowledgeFeedItem }) {
  const IconCmp = CATEGORY_ICONS[item.category] ?? CATEGORY_ICONS[item.kind] ?? Brain;
  const body = (
    <>
      <span className="kh-feed-icon">
        <IconCmp
          size={13}
          className={cn(SEVERITY_TONE[item.severity])}
          weight="regular"
          aria-hidden
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-text">{item.title}</span>
        {item.detail && (
          <span className="mt-0.5 block truncate text-[11px] text-muted">
            {item.detail}
          </span>
        )}
      </span>
      {item.repeat > 1 && (
        <span className="badge badge-muted shrink-0" title={`${item.repeat} veces`}>
          ×{item.repeat}
        </span>
      )}
      <time className="shrink-0 text-[11px] text-faint" dateTime={item.at ?? undefined}>
        {timeAgo(item.at)}
      </time>
    </>
  );
  if (item.href) {
    return (
      <Link to={item.href} className="kh-feed-row">
        {body}
      </Link>
    );
  }
  return <div className="kh-feed-row">{body}</div>;
}

export function ActivityFeed({
  items,
  loading = false,
  initialLimit = 8,
  expandable = true,
  title = "Aprendizaje reciente",
  description = "Lo último que ZENT descubrió, comprendió y conectó.",
  actions,
  bare = false,
}: {
  items: KnowledgeFeedItem[];
  loading?: boolean;
  initialLimit?: number;
  expandable?: boolean;
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  /** Sin panel ni cabecera: para incrustar en una vista que ya es un panel. */
  bare?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = useMemo(
    () => (expanded ? items : items.slice(0, initialLimit)),
    [items, expanded, initialLimit]
  );

  const content = (
    <>
      {loading && (
        <div className="flex flex-col gap-3" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-9 rounded-sm" />
          ))}
        </div>
      )}
      {!loading && items.length === 0 && (
        <p className="text-sm text-muted">
          Sin actividad todavía. Cuando ZENT aprenda de una fuente, cada
          descubrimiento aparecerá aquí.
        </p>
      )}
      {!loading && visible.length > 0 && (
        <>
          <ul className="flex flex-col">
            {visible.map((item) => (
              <li key={item.id}>
                <FeedRow item={item} />
              </li>
            ))}
          </ul>
          {expandable && items.length > initialLimit && (
            <Button
              className="mt-3"
              size="sm"
              variant="ghost"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Ver menos" : `Ver ${items.length - initialLimit} eventos más`}
            </Button>
          )}
        </>
      )}
    </>
  );

  if (bare) {
    return (
      <div data-testid="knowledge-activity-feed" data-bare="true">
        {content}
      </div>
    );
  }

  return (
    <Panel className="overflow-hidden" data-testid="knowledge-activity-feed">
      <div className="panel-header">
        <div className="min-w-0">
          <h2 className="text-h3">{title}</h2>
          <p className="mt-0.5 text-xs text-muted">{description}</p>
        </div>
        {actions}
      </div>
      <div className="panel-body">{content}</div>
    </Panel>
  );
}
