// =============================================================================
// DiscoveryFeed — "Descubrimientos": lo que ZENT encontró mientras aprendía
// =============================================================================
// No expone eventos crudos: los agrupa y los cuenta con lenguaje humano.
// "ZENT reconoció 84 carriers" con detalle expandible.
// =============================================================================
import { useMemo, useState } from "react";
import {
  CalendarBlank,
  CaretDown,
  CheckCircle,
  CopySimple,
  Cube,
  GraphIcon,
  Lightning,
  LinkSimple,
  ShieldCheck,
  Sparkle,
  Table,
  TreeStructure,
  WarningCircle,
} from "@phosphor-icons/react";

import { timeAgo } from "../../lib/format";
import type { Discovery, SessionSource } from "../../lib/knowledgeSessions";

function EventIcon({ type, severity }: { type: string; severity: string }) {
  if (severity === "error") {
    return <WarningCircle size={15} weight="fill" className="text-danger" />;
  }
  if (severity === "warning") {
    return <WarningCircle size={15} weight="fill" className="text-warn" />;
  }
  switch (type) {
    case "ENTITY_DISCOVERED":
      return <Sparkle size={15} weight="fill" className="text-accent" />;
    case "ENTITY_MATCHED":
      return <LinkSimple size={15} weight="bold" className="text-info" />;
    case "ENTITY_MERGED":
      return <GraphIcon size={15} weight="bold" className="text-info" />;
    case "FACT_DISCOVERED":
    case "FACT_REINFORCED":
      return <Lightning size={15} weight="fill" className="text-accent" />;
    case "RELATIONSHIP_DISCOVERED":
      return <GraphIcon size={15} weight="bold" className="text-accent" />;
    case "RULE_DISCOVERED":
      return <ShieldCheck size={15} weight="fill" className="text-info" />;
    case "TEMPORAL_RANGE_DISCOVERED":
      return <CalendarBlank size={15} weight="fill" className="text-info" />;
    case "DUPLICATE_DETECTED":
      return <CopySimple size={15} weight="bold" className="text-faint" />;
    case "TABLE_DETECTED":
      return <Table size={15} weight="bold" className="text-muted" />;
    case "STRUCTURE_DISCOVERED":
      return <TreeStructure size={15} weight="bold" className="text-muted" />;
    case "KNOWLEDGE_OBJECT_CREATED":
      return <Cube size={15} weight="fill" className="text-accent" />;
    case "KNOWLEDGE_READY":
    case "SOURCE_AVAILABLE":
      return <CheckCircle size={15} weight="fill" className="text-ok" />;
    default:
      return <Sparkle size={15} weight="fill" className="text-muted" />;
  }
}

const CONFLICT_LABEL: Record<string, string> = {
  VERSION_CHANGE: "posible nueva versión",
  TEMPORAL_CHANGE: "cambio de vigencia",
  SCOPE_DIFFERENCE: "diferencia de alcance",
  EXCEPTION: "excepción",
  SOURCE_CONFLICT: "contradicción entre fuentes",
  POSSIBLE_DUPLICATE: "posible duplicado",
  UNRESOLVED: "sin clasificar",
};

function detailRows(item: Discovery): Array<[string, string]> {
  const payload = (item.items[0] ?? {}) as Record<string, unknown>;
  const nested = (Array.isArray(payload.items) ? payload.items[0] : {}) as Record<
    string,
    unknown
  >;
  const rows: Array<[string, string]> = [];
  const push = (label: string, value: unknown) => {
    if (value === undefined || value === null || value === "") return;
    rows.push([label, String(value)]);
  };
  const read = (key: string) => payload[key] ?? nested[key];
  push("Nombre", read("name"));
  push("Tipo", read("entity_type"));
  push("Sujeto", read("subject"));
  push("Predicado", read("predicate"));
  push("Objeto", read("object") ?? read("object_value"));
  push("Regla", read("statement"));
  const conflictType = read("conflict_type");
  if (conflictType) {
    rows.push([
      "Conflicto",
      CONFLICT_LABEL[String(conflictType)] ?? String(conflictType),
    ]);
  }
  push("Valor A", read("value_a"));
  push("Valor B", read("value_b"));
  push("Páginas", read("pages"));
  push("Tablas", read("tables"));
  push("Filas", read("rows"));
  push("Columnas", read("columns"));
  push("Hojas", read("sheets"));
  return rows;
}

export function DiscoveryFeed({
  discoveries,
  sources,
}: {
  discoveries: Discovery[];
  sources: SessionSource[];
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const sourceNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const source of sources) {
      if (source.source_id) names[source.source_id] = source.name;
    }
    return names;
  }, [sources]);

  if (discoveries.length === 0) {
    return (
      <p className="text-[13px] text-faint" data-testid="discovery-feed-empty">
        Todavía no hay descubrimientos. Los eventos aparecen a medida que ZENT
        interpreta tus fuentes.
      </p>
    );
  }

  return (
    <ul className="ks-feed" data-testid="discovery-feed">
      {discoveries.map((item) => {
        const rows = detailRows(item);
        const expandable = rows.length > 0 || item.count > 1;
        const isOpen = expanded === item.seq;
        const sourceName = item.source_id ? sourceNames[item.source_id] : null;
        return (
          <li
            key={`${item.seq}-${item.event_type}`}
            className="ks-feed-item"
            data-severity={item.severity}
          >
            <button
              type="button"
              className="ks-feed-button"
              onClick={() => expandable && setExpanded(isOpen ? null : item.seq)}
              aria-expanded={expandable ? isOpen : undefined}
              disabled={!expandable}
            >
              <span className="ks-feed-icon">
                <EventIcon type={item.event_type} severity={item.severity} />
              </span>
              <span className="min-w-0 flex-1 text-left">
                <span className="ks-feed-message">{item.message}</span>
                <span className="ks-feed-meta">
                  {item.count > 1 && (
                    <span className="badge badge-muted">×{item.count}</span>
                  )}
                  {sourceName && <span className="truncate">{sourceName}</span>}
                  <span className="text-faint">{timeAgo(item.at)}</span>
                </span>
              </span>
              {expandable && (
                <CaretDown
                  size={13}
                  className={`ks-feed-caret ${isOpen ? "is-open" : ""}`}
                  aria-hidden
                />
              )}
            </button>
            {isOpen && (
              <div className="ks-feed-detail">
                {rows.map(([label, value]) => (
                  <div key={label} className="ks-feed-row">
                    <span className="text-faint">{label}</span>
                    <span className="text-muted break-words">{value}</span>
                  </div>
                ))}
                {item.items.length > 1 && (
                  <p className="text-[11px] text-faint">
                    +{item.items.length - 1} muestras más en el detalle técnico
                    de la sesión.
                  </p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default DiscoveryFeed;
