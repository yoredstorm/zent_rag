import {
  ArrowDown,
  ArrowUp,
  CheckCircle,
  Circle,
  Clock,
  Minus,
  Prohibit,
  WarningCircle,
  Wrench,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonTable,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Tone,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtDateTime } from "../../lib/format";

type Improvement = {
  id: string;
  priority: string;
  gap_type: string;
  title: string;
  recommended_action: string | null;
  affected_queries: number;
  affected_users: number;
  affected_agents: number;
  status: string;
  owner: string | null;
  suggested_concept: string | null;
  created_at: string;
};

const PRIORITY_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  critical: { label: "Crítica", tone: "danger", icon: WarningCircle },
  high: { label: "Alta", tone: "warn", icon: ArrowUp },
  medium: { label: "Media", tone: "info", icon: Minus },
  low: { label: "Baja", tone: "neutral", icon: ArrowDown },
};

const STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  OPEN: { label: "Abierta", tone: "info", icon: Circle },
  IN_REVIEW: { label: "En revisión", tone: "warn", icon: Clock },
  RESOLVED: { label: "Resuelta", tone: "ok", icon: CheckCircle },
  DISMISSED: { label: "Descartada", tone: "neutral", icon: Prohibit },
  BLOCKED: { label: "Bloqueada", tone: "danger", icon: XCircle },
};

const STATUS_LABELS: Record<string, string> = {
  OPEN: "Abiertas",
  IN_REVIEW: "En revisión",
  RESOLVED: "Resueltas",
  DISMISSED: "Descartadas",
  BLOCKED: "Bloqueadas",
};

const ACTION_LABELS: Record<string, string> = {
  OPEN: "Reabrir",
  IN_REVIEW: "En revisión",
  RESOLVED: "Resolver",
  DISMISSED: "Descartar",
  BLOCKED: "Bloquear",
};

const GAP_LABELS: Record<string, string> = {
  MISSING_SOURCE: "Falta fuente",
  MISSING_TABLE: "Falta tabla",
  MISSING_FIELD: "Falta campo",
  MISSING_RELATIONSHIP: "Falta relación",
  MISSING_BUSINESS_TERM: "Falta término de negocio",
  MISSING_METRIC: "Falta métrica",
  UNDEFINED_ENUM: "Enum sin definir",
  AMBIGUOUS_TERM: "Término ambiguo",
  STALE_SOURCE: "Fuente desactualizada",
  LOW_DATA_QUALITY: "Calidad de datos baja",
  SOURCE_CONFLICT: "Conflicto entre fuentes",
  PERMISSION_LIMITATION: "Limitación de permisos",
  UNSUPPORTED_OPERATION: "Operación no soportada",
};

const STATUSES = ["OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "BLOCKED"];

function PriorityBadge({ priority }: { priority: string }) {
  const meta = PRIORITY_META[priority];
  if (!meta) return <Badge tone="neutral">{priority}</Badge>;
  const IconEl = meta.icon;
  return (
    <Badge tone={meta.tone} icon={IconEl}>
      {meta.label}
    </Badge>
  );
}

function StatusBadgeCell({ status }: { status: string }) {
  const meta = STATUS_META[status];
  if (!meta) return <Badge tone="neutral">{status}</Badge>;
  const IconEl = meta.icon;
  return (
    <Badge tone={meta.tone} icon={IconEl}>
      {meta.label}
    </Badge>
  );
}

export default function KnowledgeImprovementsPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Improvement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState("all");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Improvement[]>("/api/v1/learning/improvements", {
      token: session?.token,
      organizationId: session?.organizationId,
    })
      .then(setItems)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const setStatus = async (id: string, status: string) => {
    setBusy(id);
    try {
      await api(`/api/v1/learning/improvements/${id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const visible = filter === "all" ? items : items.filter((i) => i.status === filter);
  const openish = items.filter((i) => i.status === "OPEN" || i.status === "IN_REVIEW").length;

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.improvements}
        subtitle="Backlog priorizado de gaps de contexto: qué falta, a quién afecta y qué acción lo cierra."
      />

      {error && <ErrorInline message={error} />}

      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={5} cols={4} />
        </Panel>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="Sin mejoras pendientes"
          body="Los gaps de contexto se convertirán aquí en acciones priorizadas."
          hint="Cuando una pregunta no se puede responder, Zent registra el gap y propone cómo cerrarlo."
        />
      ) : (
        <>
          <Tabs value={filter} onValueChange={setFilter} variant="pill">
            <TabsList>
              <TabsTrigger value="all">
                Todas <span className="mono text-faint">{items.length}</span>
              </TabsTrigger>
              {STATUSES.map((status) => {
                const count = items.filter((i) => i.status === status).length;
                return (
                  <TabsTrigger key={status} value={status} disabled={count === 0}>
                    {STATUS_LABELS[status]}{" "}
                    <span className="mono text-faint">{count}</span>
                  </TabsTrigger>
                );
              })}
            </TabsList>
            <TabsContent value={filter}>
              <Panel>
                <PanelHeader
                  title="Backlog"
                  description={`${openish} de ${items.length} mejoras siguen abiertas o en revisión.`}
                />
                {visible.length === 0 ? (
                  <EmptyState
                    compact
                    title="Nada en este estado"
                    body="Probá con otro filtro para ver el resto del backlog."
                    action={
                      <Button variant="ghost" size="sm" onClick={() => setFilter("all")}>
                        Ver todas
                      </Button>
                    }
                  />
                ) : (
              <ul className="divide-y divide-border-soft">
                {visible.map((i) => {
                  const transitions = STATUSES.filter((s) => s !== i.status).slice(0, 3);
                  const gapSuffix = i.gap_type ? ` (${i.gap_type})` : "";
                  const title =
                    gapSuffix && i.title.endsWith(gapSuffix)
                      ? i.title.slice(0, -gapSuffix.length)
                      : i.title;
                  return (
                    <li key={i.id} className="p-4 transition-colors duration-120 hover:bg-soft/40">
                      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <PriorityBadge priority={i.priority} />
                            <Badge tone="neutral">{GAP_LABELS[i.gap_type] ?? i.gap_type}</Badge>
                            <StatusBadgeCell status={i.status} />
                            <span className="text-xs text-faint tabular-nums">
                              {fmtDateTime(i.created_at)}
                            </span>
                          </div>
                          <p className="mt-2 text-sm font-medium text-text">{title}</p>
                          {i.recommended_action && (
                            <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
                              {i.recommended_action}
                            </p>
                          )}
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint tabular-nums">
                            <span>{i.affected_queries} consultas</span>
                            <span>{i.affected_users} usuarios</span>
                            <span>{i.affected_agents} agentes</span>
                            {i.owner && <span>owner: {i.owner}</span>}
                          </div>
                          {i.suggested_concept && (
                            <p className="mt-1.5 text-xs text-muted">
                              Concepto sugerido:{" "}
                              <span className="font-medium text-text">{i.suggested_concept}</span>
                            </p>
                          )}
                        </div>

                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          {transitions.map((s) => (
                            <Button
                              key={s}
                              size="sm"
                              variant="secondary"
                              disabled={busy === i.id}
                              loading={busy === i.id && s === transitions[0]}
                              onClick={() => setStatus(i.id, s)}
                            >
                              {ACTION_LABELS[s] ?? s.replace("_", " ")}
                            </Button>
                          ))}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
                )}
              </Panel>
            </TabsContent>
          </Tabs>
        </>
      )}
    </KnowledgeLayout>
  );
}
