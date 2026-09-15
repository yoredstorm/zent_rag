import {
  BookOpen,
  ChartLineUp,
  Check,
  CheckCircle,
  Cube,
  FileText,
  GitBranch,
  ListBullets,
  Prohibit,
  Question,
  Scales,
  Table,
  Tag,
  WarningCircle,
  X,
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
  type Tone,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtDateTime } from "../../lib/format";

type Suggestion = {
  id: string;
  type: string;
  title: string;
  description: string | null;
  confidence: string;
  evidence: string[];
  status: string;
  created_at: string;
};

const TYPE_META: Record<string, { label: string; icon: Icon }> = {
  entity_identification: { label: "Entidad", icon: Cube },
  table_identification: { label: "Tabla", icon: Table },
  relationship_candidate: { label: "Relación", icon: GitBranch },
  enum_definition: { label: "Valores de enum", icon: ListBullets },
  field_mapping: { label: "Campo", icon: Tag },
  metric_proposal: { label: "Métrica", icon: ChartLineUp },
  glossary_term: { label: "Término", icon: BookOpen },
  document_fact: { label: "Documento", icon: FileText },
  business_rule: { label: "Regla de negocio", icon: Scales },
};

const CONFIDENCE_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  high: { label: "Confianza alta", tone: "ok", icon: CheckCircle },
  medium: { label: "Confianza media", tone: "warn", icon: WarningCircle },
  low: { label: "Confianza baja", tone: "neutral", icon: Question },
};

function TypeBadge({ type }: { type: string }) {
  const meta = TYPE_META[type];
  if (!meta) return <Badge tone="neutral">{type.replace(/_/g, " ")}</Badge>;
  const IconEl = meta.icon;
  return (
    <Badge tone="neutral" icon={IconEl}>
      {meta.label}
    </Badge>
  );
}

function ConfidenceBadge({ value }: { value: string }) {
  const meta = CONFIDENCE_META[value?.toLowerCase?.() ?? ""];
  if (!meta) return value ? <Badge tone="neutral">Confianza {value}</Badge> : null;
  const IconEl = meta.icon;
  return (
    <Badge tone={meta.tone} icon={IconEl}>
      {meta.label}
    </Badge>
  );
}

export default function KnowledgeReviewPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Suggestion[]>("/api/v1/catalog/suggestions?status=pending", {
      token: session?.token,
      organizationId: session?.organizationId,
    })
      .then(setItems)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const decide = async (id: string, action: "approve" | "reject" | "defer") => {
    setBusy(id);
    try {
      await api(`/api/v1/catalog/suggestions/${id}/${action}`, {
        method: action === "approve" ? "POST" : "POST",
        body: JSON.stringify({}),
      });
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.review}
        subtitle="Sugerencias semánticas observadas o inferidas que necesitan aprobación humana. Nada se auto-aprueba."
      />

      {error && <ErrorInline message={error} />}

      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={5} cols={4} />
        </Panel>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Check}
          title="Sin sugerencias pendientes"
          body="Las inferencias del Discovery Engine aparecerán aquí para su revisión."
          hint="Aprobar una sugerencia la convierte en conocimiento con trazabilidad; rechazarla o diferirla queda auditado."
        />
      ) : (
        <Panel>
          <PanelHeader
            title="Pendientes"
            description="Cada decisión queda auditada y materializa conocimiento con provenance aprobado."
            actions={<Badge tone="warn">{items.length} por revisar</Badge>}
          />
          <ul className="divide-y divide-border-soft">
            {items.map((s) => (
              <li key={s.id} className="p-4 transition-colors duration-120 hover:bg-soft/40">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <TypeBadge type={s.type} />
                      <ConfidenceBadge value={s.confidence} />
                      <span className="text-xs text-faint tabular-nums">
                        {fmtDateTime(s.created_at)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-text">{s.title}</p>
                    {s.description && (
                      <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
                        {s.description}
                      </p>
                    )}
                    {s.evidence.length > 0 && (
                      <div className="mt-2.5">
                        <p className="eyebrow">Evidencia</p>
                        <ul className="mt-1 space-y-0.5">
                          {s.evidence.slice(0, 3).map((item, i) => (
                            <li key={i} className="text-xs leading-relaxed text-faint">
                              {item}
                            </li>
                          ))}
                        </ul>
                        {s.evidence.length > 3 && (
                          <p className="mt-1 text-xs text-faint">
                            +{s.evidence.length - 3} más
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      leadingIcon={Check}
                      loading={busy === s.id}
                      onClick={() => decide(s.id, "approve")}
                    >
                      Aprobar
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      leadingIcon={X}
                      disabled={busy === s.id}
                      onClick={() => decide(s.id, "reject")}
                    >
                      Rechazar
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      leadingIcon={Prohibit}
                      disabled={busy === s.id}
                      onClick={() => decide(s.id, "defer")}
                    >
                      Diferir
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </KnowledgeLayout>
  );
}
