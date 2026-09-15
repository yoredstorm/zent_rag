import {
  Archive,
  BookOpen,
  CheckCircle,
  Clock,
  Eye,
  Plus,
  Sparkle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  SectionHeader,
  Textarea,
  type Column,
  type Tone,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { isApiError } from "../../lib/errors";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type GlossaryTerm = {
  id: string;
  concept: string;
  definition: string;
  synonyms: string[];
  owner: string | null;
  status: string;
  version: number;
  provenance: string;
};

const STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  approved: { label: "Aprobado", tone: "ok", icon: CheckCircle },
  draft: { label: "Borrador", tone: "warn", icon: Clock },
  deprecated: { label: "Obsoleto", tone: "neutral", icon: Archive },
};

const PROVENANCE_META: Record<string, { label: string; icon: Icon }> = {
  APPROVED: { label: "Aprobado por una persona", icon: CheckCircle },
  OBSERVED: { label: "Observado en los datos", icon: Eye },
  INFERRED: { label: "Inferido por Zent", icon: Sparkle },
  REJECTED: { label: "Rechazado", icon: XCircle },
  DEPRECATED: { label: "Obsoleto", icon: Archive },
};

function StatusCell({ term }: { term: GlossaryTerm }) {
  const meta = STATUS_META[term.status];
  return (
    <span className="flex flex-wrap items-center gap-2">
      {meta ? (
        <Badge tone={meta.tone} icon={meta.icon}>
          {meta.label}
        </Badge>
      ) : (
        <Badge tone="neutral">{term.status}</Badge>
      )}
      <span className="mono text-[11px] text-faint">v{term.version}</span>
    </span>
  );
}

function ProvenanceCell({ provenance }: { provenance: string }) {
  const meta = PROVENANCE_META[provenance];
  if (!meta) return <span className="text-xs text-faint">{provenance}</span>;
  const IconEl = meta.icon;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <IconEl size={13} aria-hidden />
      {meta.label}
    </span>
  );
}

export default function KnowledgeGlossaryPage() {
  const { session } = useAuth();
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [concept, setConcept] = useState("");
  const [definition, setDefinition] = useState("");
  const [synonyms, setSynonyms] = useState("");
  const [saving, setSaving] = useState(false);
  const inflight = useRef(false);

  const load = useCallback(() => {
    if (!session || inflight.current) return;
    inflight.current = true;
    setLoading(true);
    api<GlossaryTerm[]>("/api/v1/catalog/glossary", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setTerms)
      .catch((e) => {
        if (isApiError(e)) {
          setError(
            e.status === 401 || e.status === 403
              ? "Sin permiso para el glosario de catálogo (catalog:read). Habla con el admin de tu organización."
              : e.message,
          );
        } else {
          setError(String(e));
        }
      })
      .finally(() => {
        inflight.current = false;
        setLoading(false);
      });
  }, [session]);

  // Dep estable (session puede ser un objeto nuevo en cada render → evita loop)
  useEffect(() => load(), [load]);

  const save = async () => {
    if (!session || !concept.trim() || !definition.trim()) return;
    setSaving(true);
    try {
      await api("/api/v1/catalog/glossary", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          concept,
          definition,
          synonyms: synonyms.split(",").map((s) => s.trim()).filter(Boolean),
          status: "draft",
        }),
      });
      setConcept("");
      setDefinition("");
      setSynonyms("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const canSave = Boolean(concept.trim() && definition.trim()) && !saving;

  const columns: Column<GlossaryTerm>[] = [
    {
      key: "concept",
      header: "Término",
      render: (t) => <span className="font-medium text-text">{t.concept}</span>,
    },
    {
      key: "definition",
      header: "Definición",
      className: "max-w-[48ch] text-muted",
      render: (t) => <span className="text-[13px] leading-relaxed">{t.definition}</span>,
    },
    {
      key: "synonyms",
      header: "Sinónimos",
      hideBelow: "md",
      render: (t) =>
        t.synonyms.length > 0 ? (
          <span className="flex flex-wrap gap-1">
            {t.synonyms.map((s) => (
              <span key={s} className="chip">
                {s}
              </span>
            ))}
          </span>
        ) : (
          <span className="text-xs text-faint">—</span>
        ),
    },
    {
      key: "status",
      header: "Estado",
      render: (t) => <StatusCell term={t} />,
    },
    {
      key: "provenance",
      header: "Origen",
      hideBelow: "lg",
      render: (t) => <ProvenanceCell provenance={t.provenance} />,
    },
    {
      key: "owner",
      header: "Owner",
      hideBelow: "xl",
      render: (t) =>
        t.owner ? (
          <span className="text-[13px] text-muted">{t.owner}</span>
        ) : (
          <span className="text-xs text-faint">sin owner</span>
        ),
    },
  ];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.glossary}
        subtitle="Términos de negocio con sinónimos, owner y versionado. Solo lo aprobado alimenta las respuestas."
      />

      {error && <ErrorInline message={error} />}

      <Panel className="mb-6">
        <PanelHeader
          title="Nuevo término"
          description="Se guarda como borrador y queda versionado; no alimenta respuestas hasta aprobarlo."
        />
        <form
          className="p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Concepto" required hint="Por ejemplo: cliente activo.">
              <Input
                value={concept}
                onChange={(e) => setConcept(e.target.value)}
                placeholder="cliente activo"
                autoComplete="off"
              />
            </Field>
            <Field
              label="Sinónimos"
              hint="Separados por coma. Opcional."
            >
              <Input
                value={synonyms}
                onChange={(e) => setSynonyms(e.target.value)}
                placeholder="cliente vigente, cliente con actividad"
                autoComplete="off"
              />
            </Field>
            <Field
              label="Definición"
              required
              className="sm:col-span-2"
              hint="Cómo se calcula o qué incluye, en una frase que pueda usar cualquiera."
            >
              <Textarea
                value={definition}
                onChange={(e) => setDefinition(e.target.value)}
                rows={3}
                placeholder="Cliente con al menos una compra en los últimos 12 meses."
              />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-faint">
              Estado inicial: borrador · versión 1 si el término es nuevo.
            </p>
            <Button
              type="submit"
              variant="primary"
              leadingIcon={Plus}
              loading={saving}
              disabled={!canSave}
            >
              Guardar borrador
            </Button>
          </div>
        </form>
      </Panel>

      <SectionHeader
        title="Términos"
        description="El vocabulario que Zent usa para interpretar preguntas y mapear campos."
        actions={!loading && terms.length > 0 ? <ResultCount shown={terms.length} total={terms.length} noun="términos" /> : undefined}
      />

      <div className="mt-4">
        <DataTable
          columns={columns}
          rows={terms}
          rowKey={(t) => t.id}
          caption="Términos del glosario de negocio"
          loading={loading}
          empty={
            <EmptyState
              icon={BookOpen}
              title="Sin términos aún"
              body="Creá el primer término arriba para fijar el vocabulario con el que Zent interpreta tus datos."
              hint="Los términos en borrador se pueden aprobar después; nada se publica solo."
            />
          }
        />
      </div>
    </KnowledgeLayout>
  );
}
