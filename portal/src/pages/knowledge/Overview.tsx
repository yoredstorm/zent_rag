import {
  CheckCircle,
  Database,
  Files,
  Lightning,
  Plus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { AttentionList } from "../../components/AttentionList";
import {
  ButtonLink,
  cn,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Skeleton,
  WarningInline,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtNum, formatErrorSummary } from "../../lib/format";
import { COPY } from "./knowledgeCopy";

type Source = {
  id: string;
  name: string;
  type: string;
  status: string;
  last_sync: string | null;
  last_error: string | null;
  document_count: number;
  error_count: number;
};

type Job = {
  id: string;
  job_type: string;
  status: string;
  error_summary: string | { error?: unknown; message?: unknown } | null;
};

const BROKEN = new Set(["error", "failed"]);

export default function KnowledgeOverviewPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [vectorPoints, setVectorPoints] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [attention, setAttention] = useState<{ id: string; warning?: string | null } | null>(null);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [s, j, st, gate, attentionData] = await Promise.all([
          api<{ sources: Source[] }>("/api/v1/sources", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ jobs: Job[] }>("/api/v1/jobs?limit=20", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ jobs: [] as Job[] })),
          api<{ vector_points: number }>("/api/v1/billing/usage/storage", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => null),
          api<{ has_real_data: boolean; resume_session_id: string | null }>(
            "/api/v1/data-onboarding/gate",
            { token: session.token, organizationId: session.organizationId },
          ).catch(() => ({ has_real_data: false, resume_session_id: null })),
          api<{ sessions: Array<{ id: string; warning?: string | null }> }>(
            "/api/v1/data-onboarding/sessions?status=NEEDS_ATTENTION",
            { token: session.token, organizationId: session.organizationId },
          ).catch(() => ({ sessions: [] })),
        ]);
        setSources(s.sources || []);
        setJobs(j.jobs || []);
        setVectorPoints(st?.vector_points ?? null);
        setResumeId(gate.resume_session_id);
        setAttention(attentionData.sessions?.[0] || null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando conocimiento");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const broken = sources.filter((s) => BROKEN.has(s.status));
  const documents = sources.reduce((acc, s) => acc + (s.document_count || 0), 0);
  const failedJobs = jobs.filter((j) => j.status === "failed" || j.status === "dead");
  const hasSources = sources.length > 0;
  const hasIssues = broken.length > 0;

  const issues: { id: string; label: string; to: string }[] = [
    ...broken.slice(0, 5).map((s) => ({
      id: `src-${s.id}`,
      label: `La fuente «${s.name}» no se sincronizó correctamente.`,
      to: "/knowledge/sources",
    })),
    ...failedJobs.slice(0, 5).map((j) => ({
      id: `job-${j.id}`,
      label: `El job de ${j.job_type} falló.${j.error_summary ? ` ${formatErrorSummary(j.error_summary).slice(0, 120)}` : ""}`,
      to: "/knowledge/jobs",
    })),
  ];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.overview}
        subtitle={COPY.subtitle}
        actions={
          <>
            {resumeId && (
              <ButtonLink to={`/knowledge/add/${resumeId}`} variant="secondary">
                {COPY.continue}
              </ButtonLink>
            )}
            <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
              {COPY.addSource}
            </ButtonLink>
          </>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />

        {attention && (
          <WarningInline
            className="mb-0"
            message={
              <>
                {attention.warning || "Zent tiene datos sin revisar de tu última fuente."}{" "}
                <Link
                  to={`/knowledge/add/${attention.id}`}
                  className="font-medium underline underline-offset-2"
                >
                  Revisar ahora
                </Link>
              </>
            }
          />
        )}

        {loading && (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-[124px] rounded-lg" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-[86px] rounded-lg" />
              ))}
            </div>
          </div>
        )}

        {!loading && !hasSources && (
          <div data-testid="knowledge-empty">
            <Panel>
              <EmptyState
                icon={Database}
                title="Todavía no hay fuentes"
                body={COPY.empty}
                action={
                  <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
                    {COPY.addSource}
                  </ButtonLink>
                }
                secondaryAction={
                  <ButtonLink to="/knowledge/sources" variant="secondary">
                    {COPY.viewSources}
                  </ButtonLink>
                }
              />
            </Panel>
          </div>
        )}

        {!loading && hasSources && (
          <>
            <div data-testid="knowledge-ready">
              <Panel>
                <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 gap-3">
                    <span
                      className={cn(
                        "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border",
                        hasIssues
                          ? "border-warn/25 bg-warn-soft text-warn"
                          : "border-ok/25 bg-ok-soft text-ok",
                      )}
                      aria-hidden
                    >
                      {hasIssues ? <WarningCircle size={20} /> : <CheckCircle size={20} />}
                    </span>
                    <div className="min-w-0">
                      <h2 className="text-h2">{COPY.readyTitle}</h2>
                      <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
                        {COPY.readyBody(sources.length, broken.length)}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <ButtonLink to="/chat?target=knowledge" variant="primary">
                      {COPY.playground}
                    </ButtonLink>
                    <ButtonLink to="/agents/new" variant="secondary">
                      {COPY.createAgent}
                    </ButtonLink>
                    <ButtonLink to="/knowledge/sources" variant="secondary">
                      {COPY.viewSources}
                    </ButtonLink>
                  </div>
                </div>
              </Panel>
            </div>

            <MetricGrid cols={3}>
              <Metric
                label="Fuentes"
                value={fmtNum(sources.length)}
                icon={Database}
                hint={hasIssues ? `${fmtNum(broken.length)} con incidencias` : "sin incidencias"}
              />
              <Metric label="Documentos" value={fmtNum(documents)} icon={Files} />
              <Metric
                label="Chunks indexados"
                value={vectorPoints != null ? fmtNum(vectorPoints) : "—"}
                icon={Lightning}
                hint={vectorPoints == null ? "sin dato de uso" : undefined}
              />
            </MetricGrid>

            <AttentionList items={issues} emptyBody={COPY.attentionEmpty} />
          </>
        )}
      </div>
    </KnowledgeLayout>
  );
}
