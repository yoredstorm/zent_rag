import {
  ArrowClockwise,
  CheckCircle,
  ListChecks,
  MagnifyingGlass,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  StatusBadge,
  ToolbarSpacer,
  Tooltip,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtDateTime, fmtNum } from "../../lib/format";

type Gap = {
  id: string;
  gap_type: string;
  concept: string;
  question: string | null;
  occurrences: number;
  impact: Record<string, number | string | null>;
  status: string;
  evidence_hints: string[];
  first_seen_at?: string;
  last_seen_at: string;
};

/** Tipos del engine → lenguaje de negocio. El código crudo queda en el title. */
const GAP_TYPE_LABELS: Record<string, string> = {
  MISSING_SOURCE: "Falta una fuente",
  MISSING_TABLE: "Falta una tabla",
  MISSING_FIELD: "Falta un campo",
  MISSING_RELATIONSHIP: "Falta una relación",
  MISSING_BUSINESS_TERM: "Falta definición de negocio",
  MISSING_METRIC: "Falta una métrica",
  UNDEFINED_ENUM: "Valor sin definir",
  AMBIGUOUS_TERM: "Término ambiguo",
  STALE_SOURCE: "Fuente desactualizada",
  LOW_DATA_QUALITY: "Calidad de datos baja",
  SOURCE_CONFLICT: "Fuentes en conflicto",
  PERMISSION_LIMITATION: "Limitación de permisos",
  UNSUPPORTED_OPERATION: "Operación no soportada",
};

const IMPACT_LABELS: Record<string, string> = {
  query_count_30d: "Consultas · 30 días",
  users: "Usuarios",
  agents: "Agentes",
};

function gapTypeLabel(type: string): string {
  return GAP_TYPE_LABELS[type] ?? type;
}

function impactLabel(key: string): string {
  return IMPACT_LABELS[key] ?? key.replace(/_/g, " ");
}

export default function EvaluationGapsPage() {
  const { session } = useAuth();
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [pendingResolve, setPendingResolve] = useState<Gap | null>(null);

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Gap[]>("/api/v1/learning/gaps?status=open")
      .then((data) => {
        setGaps(Array.isArray(data) ? data : []);
        setError("");
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const resolve = async (id: string) => {
    setBusy(id);
    try {
      await api(`/api/v1/learning/gaps/${id}/resolve`, { method: "POST", body: JSON.stringify({}) });
      setPendingResolve(null);
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const types = useMemo(
    () => Array.from(new Set(gaps.map((gap) => gap.gap_type))).sort(),
    [gaps]
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return gaps.filter((gap) => {
      if (typeFilter && gap.gap_type !== typeFilter) return false;
      if (!needle) return true;
      return (
        gap.concept.toLowerCase().includes(needle) ||
        (gap.question || "").toLowerCase().includes(needle)
      );
    });
  }, [gaps, query, typeFilter]);

  const capped = gaps.length >= 100;

  return (
    <QualityLayout>
      <PageHeader
        title="Context Gaps"
        subtitle="Qué conocimiento falta, cuántas consultas afecta y cómo cerrarlo."
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0">
          <span className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button
              size="sm"
              variant="secondary"
              leadingIcon={ArrowClockwise}
              onClick={load}
            >
              Reintentar
            </Button>
          </span>
        </ErrorInline>

        {loading ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-[104px] rounded-lg" />
            ))}
          </div>
        ) : error && gaps.length === 0 ? null : gaps.length === 0 ? (
          <Panel>
            <EmptyState
              icon={ListChecks}
              title="Sin gaps abiertos"
              body="Los gaps aparecen cuando una consulta no es contestable con el conocimiento actual."
              hint="Cuando se detecten, vas a poder ver el concepto, las consultas afectadas y su evidencia."
            />
          </Panel>
        ) : (
          <Panel>
            <PanelHeader
              title="Gaps abiertos"
              description="Cada gap es accionable: resolvelo cuando el conocimiento ya lo cubra."
              actions={
                <ResultCount
                  shown={filtered.length}
                  total={gaps.length}
                  noun="gaps abiertos"
                />
              }
            />
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <div className="min-w-[200px] flex-1 sm:max-w-xs">
                <Input
                  icon={MagnifyingGlass}
                  value={query}
                  onChange={(ev) => setQuery(ev.target.value)}
                  placeholder="Buscar concepto o pregunta"
                  aria-label="Buscar gaps"
                />
              </div>
              <div className="min-w-[160px]">
                <Select
                  value={typeFilter}
                  onChange={(ev) => setTypeFilter(ev.target.value)}
                  placeholder="Todos los tipos"
                  aria-label="Filtrar por tipo de gap"
                >
                  {types.map((type) => (
                    <option key={type} value={type}>
                      {gapTypeLabel(type)}
                    </option>
                  ))}
                </Select>
              </div>
              <ToolbarSpacer />
              <Button
                size="sm"
                variant="ghost"
                leadingIcon={ArrowClockwise}
                onClick={load}
              >
                Actualizar
              </Button>
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                compact
                icon={MagnifyingGlass}
                title="Sin resultados"
                body="Ningún gap abierto coincide con la búsqueda o el tipo elegido."
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setQuery("");
                      setTypeFilter("");
                    }}
                  >
                    Limpiar filtros
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-border-soft">
                {filtered.map((gap) => {
                  // query_count_30d se muestra como chip propio a la derecha.
                  const impactEntries = Object.entries(gap.impact || {}).filter(
                    (entry): entry is [string, number] =>
                      typeof entry[1] === "number" && entry[0] !== "query_count_30d"
                  );
                  return (
                    <li
                      key={gap.id}
                      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between"
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={gap.status} />
                          <Badge tone="neutral" title={gap.gap_type}>
                            {gapTypeLabel(gap.gap_type)}
                          </Badge>
                          <span className="text-[13.5px] font-medium text-text">
                            {gap.concept}
                          </span>
                        </div>
                        {gap.question && (
                          <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
                            «{gap.question}»
                          </p>
                        )}
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
                          <span className="tabular-nums">
                            {fmtNum(gap.occurrences)} consultas afectadas
                          </span>
                          <span className="tabular-nums">
                            última vez {fmtDateTime(gap.last_seen_at)}
                          </span>
                        </div>
                        {impactEntries.length > 0 && (
                          <dl className="mt-2 flex flex-wrap gap-1.5">
                            {impactEntries.map(([key, value]) => (
                              <div key={key} className="chip" title={key}>
                                <dt className="text-[10px] text-ghost">{impactLabel(key)}</dt>
                                <dd className="mono text-xs text-muted tabular-nums">
                                  {fmtNum(value)}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        )}
                        {gap.evidence_hints.length > 0 && (
                          <div className="mt-2">
                            <p className="eyebrow mb-1">Evidencia</p>
                            <ul className="flex flex-wrap gap-1.5">
                              {gap.evidence_hints.slice(0, 4).map((hint, i) => (
                                <li key={i} className="chip mono max-w-full truncate" title={hint}>
                                  {hint}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {Number(gap.impact?.query_count_30d ?? 0) > 0 && (
                          <Tooltip label="Consultas de los últimos 30 días que pidieron este concepto">
                            <span className="chip tabular-nums">
                              <WarningCircle size={12} aria-hidden />
                              {fmtNum(Number(gap.impact.query_count_30d))}/30d
                            </span>
                          </Tooltip>
                        )}
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={busy === gap.id}
                          onClick={() => setPendingResolve(gap)}
                        >
                          Resolver
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            {capped && (
              <p className="border-t border-border px-4 py-3 text-xs text-faint">
                Se muestran los 100 gaps más recientes. Resolvé o filtrá para acotar la lista.
              </p>
            )}
          </Panel>
        )}

        {!loading && gaps.length > 0 && filtered.length > 0 && (
          <p className="text-xs text-faint">
            <CheckCircle size={12} aria-hidden className="mr-1.5 inline-block align-[-1px] text-ok" />
            Resolver un gap lo marca como cubierto y lo saca de esta lista. La acción no se puede
            deshacer desde acá.
          </p>
        )}
      </div>

      <ConfirmDialog
        open={pendingResolve !== null}
        onOpenChange={(open) => {
          if (!open) setPendingResolve(null);
        }}
        title="Resolver gap"
        body={
          pendingResolve
            ? `Marcar «${pendingResolve.concept}» como resuelto. Esta acción no se puede deshacer desde acá.`
            : undefined
        }
        confirmLabel="Resolver"
        tone="primary"
        loading={pendingResolve != null && busy === pendingResolve.id}
        onConfirm={() => {
          if (pendingResolve) void resolve(pendingResolve.id);
        }}
      />
    </QualityLayout>
  );
}
