import { useEffect, useState } from "react";
import { api } from "../../api";
import { Button, ErrorInline, SkeletonBlock } from "../ui";

export type SubflowDefinitionView = {
  name: string;
  version: number;
  status: string;
  capability_ref: string;
  durable: boolean;
  runnable_inline: boolean;
  output_ports: string[];
  node_config: Record<string, unknown>;
};

type Props = {
  loadLibrary?: () => Promise<SubflowDefinitionView[]>;
  onInsert: (subflow: SubflowDefinitionView) => void;
};

const DEFAULT_LOAD = async () => {
  const response = await api<{ subflows: SubflowDefinitionView[] }>(
    "/api/v1/workflows/subflows/library"
  );
  return response.subflows;
};

/** Biblioteca de subflujos publicados. Solo inserta un nodo con snapshot congelado. */
export function SubflowLibraryPanel({ loadLibrary = DEFAULT_LOAD, onInsert }: Props) {
  const [items, setItems] = useState<SubflowDefinitionView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void loadLibrary()
      .then((result) => {
        if (!cancelled) setItems(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "No se pudo cargar la biblioteca");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadLibrary]);

  return (
    <div className="space-y-3" data-testid="wf-subflow-library">
      {loading && <SkeletonBlock className="h-24" />}
      {error && <ErrorInline message={error} />}
      {!loading && items.length === 0 && (
        <p className="text-sm text-muted" data-testid="wf-subflow-empty">
          No hay subflujos publicados.
        </p>
      )}
      {items.map((item) => (
        <article
          key={`${item.name}-${item.version}`}
          className="rounded-md border border-border bg-soft/40 p-3"
          data-testid={`wf-subflow-${item.name}`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{item.name}</p>
              <p className="text-xs text-muted">
                v{item.version} · {item.status} · {item.capability_ref}
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onInsert(item)}
              data-testid={`wf-subflow-insert-${item.name}`}
            >
              Insertar
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            {item.durable
              ? "Contiene WAIT/LOOP/aprobación: se bloquea inline y debe vivir en el proceso padre."
              : "Se ejecuta inline sobre el snapshot congelado, sin runtime paralelo."}
          </p>
          <p className="mt-1 text-[11px] text-muted">
            Salidas: {item.output_ports.join(" · ")}
          </p>
        </article>
      ))}
    </div>
  );
}
