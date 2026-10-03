// =============================================================================
// Búsqueda universal de conocimiento — conceptos, entidades, reglas, fuentes
// =============================================================================
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { Badge, EmptyState, ErrorInline, Spinner } from "../ui";
import {
  fetchKnowledgeSearch,
  objectTypeLabel,
  type KnowledgeObject,
} from "../../lib/knowledgeModel";
import { KnowledgeConfidenceBadge } from "../knowledgeLearning/KnowledgeConfidenceBadge";

const TYPE_ORDER = [
  "concept",
  "entity",
  "business_rule",
  "metric",
  "process",
  "term",
  "attribute",
  "relationship",
  "table",
  "column",
  "source",
  "document",
  "domain",
];

export function KnowledgeSearch({
  initialQuery = "",
  autoFocus = false,
  onQueryChange,
}: {
  initialQuery?: string;
  autoFocus?: boolean;
  onQueryChange?: (query: string) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [items, setItems] = useState<KnowledgeObject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    const value = query.trim();
    if (value.length < 2) {
      setItems([]);
      setSearched("");
      setError("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    const handle = window.setTimeout(() => {
      void fetchKnowledgeSearch(value, 20)
        .then((result) => {
          if (cancelled) return;
          setItems(result.items);
          setSearched(value);
          setError("");
        })
        .catch((err) => {
          if (cancelled) return;
          setItems([]);
          setError(err instanceof Error ? err.message : "La búsqueda falló.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 280);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [query]);

  const groups = useMemo(() => {
    const byType = new Map<string, KnowledgeObject[]>();
    for (const item of items) {
      const list = byType.get(item.type) ?? [];
      list.push(item);
      byType.set(item.type, list);
    }
    return [...byType.entries()].sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a[0]);
      const ib = TYPE_ORDER.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }, [items]);

  return (
    <div className="flex flex-col gap-4" data-testid="knowledge-search">
      <div className="relative">
        <MagnifyingGlass
          size={16}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          aria-hidden
        />
        <input
          ref={inputRef}
          className="input h-11 pl-9 pr-10 text-[15px]"
          placeholder="Buscar conceptos, entidades, reglas, fuentes…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            onQueryChange?.(event.target.value);
          }}
          aria-label="Buscar en el conocimiento"
          autoComplete="off"
        />
        {query && (
          <button
            type="button"
            className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-sm text-faint hover:bg-soft hover:text-text"
            onClick={() => {
              setQuery("");
              onQueryChange?.("");
              inputRef.current?.focus();
            }}
            aria-label="Limpiar búsqueda"
          >
            <X size={14} aria-hidden />
          </button>
        )}
        {loading && (
          <span className="absolute right-10 top-1/2 -translate-y-1/2">
            <Spinner size={14} />
          </span>
        )}
      </div>

      {error && <ErrorInline message={error} className="mb-0" />}

      {!loading && !error && query.trim().length >= 2 && items.length === 0 && searched && (
        <EmptyState
          icon={MagnifyingGlass}
          title={`Sin resultados para “${searched}”`}
          body="Prueba con otro nombre, un término del negocio o el nombre de una fuente."
        />
      )}

      {groups.length > 0 && (
        <div className="flex flex-col gap-5">
          {groups.map(([type, groupItems]) => (
            <section key={type}>
              <div className="mb-2 flex items-center gap-2">
                <h2 className="eyebrow">{objectTypeLabel(type)}</h2>
                <span className="text-[11px] text-faint">{groupItems.length}</span>
              </div>
              <ul className="panel divide-y divide-border-soft overflow-hidden">
                {groupItems.map((item) => (
                  <li key={item.id}>
                    <Link
                      to={`/knowledge/objects/${item.id}`}
                      className="flex items-center gap-3 px-4 py-3 transition-colors duration-150 hover:bg-soft/50"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-text">
                          {item.display_name || item.name}
                        </span>
                        {item.description && (
                          <span className="mt-0.5 line-clamp-1 block text-xs text-muted">
                            {item.description}
                          </span>
                        )}
                      </span>
                      {item.domain && (
                        <span className="hidden shrink-0 text-[11px] text-faint sm:inline">
                          {item.domain}
                        </span>
                      )}
                      <Badge tone="neutral" className="shrink-0">
                        {item.status}
                      </Badge>
                      {item.confidence != null && (
                        <KnowledgeConfidenceBadge confidence={item.confidence} compact />
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      {query.trim().length < 2 && (
        <p className="text-sm text-muted">
          Escribe al menos dos caracteres. La búsqueda recorre el conocimiento
          canónico completo: conceptos, entidades, reglas, métricas, términos,
          fuentes y documentos.
        </p>
      )}
    </div>
  );
}
