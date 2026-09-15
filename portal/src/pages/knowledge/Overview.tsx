import { Database, Files, Lightning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { AttentionList } from "../../components/AttentionList";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
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
          <div className="flex flex-wrap gap-2">
            {resumeId && (
              <Link to={`/knowledge/add/${resumeId}`} className="btn btn-secondary">
                {COPY.continue}
              </Link>
            )}
            <Link to="/knowledge/add" className="btn btn-primary">
              {COPY.addSource}
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />

      {attention && (
        <div className="mb-4 rounded-md border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
          {attention.warning || "Zent tiene datos sin revisar de tu última fuente."}{" "}
          <Link className="text-accent underline" to={`/knowledge/add/${attention.id}`}>
            Revisar ahora
          </Link>
        </div>
      )}

      {loading && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="stat space-y-2">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      )}

      {!loading && !hasSources && (
        <div className="panel mb-4 p-6" data-testid="knowledge-empty">
          <p className="text-sm text-muted">{COPY.empty}</p>
          <Link to="/knowledge/add" className="btn btn-primary mt-3">
            {COPY.addSource}
          </Link>
        </div>
      )}

      {!loading && hasSources && (
        <>
          <div className="mb-4 rounded-md border border-border p-4" data-testid="knowledge-ready">
            <h2 className="font-semibold">{COPY.readyTitle}</h2>
            <p className="text-sm text-muted">{COPY.readyBody(sources.length, broken.length)}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Link to="/chat?target=knowledge" className="btn btn-primary">
                {COPY.playground}
              </Link>
              <Link to="/agents/new" className="btn btn-secondary">
                {COPY.createAgent}
              </Link>
              <Link to="/knowledge/sources" className="btn btn-secondary">
                {COPY.viewSources}
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <StatCard label="Fuentes" value={fmtNum(sources.length)} icon={Database} />
            <StatCard label="Documentos" value={fmtNum(documents)} icon={Files} />
            <StatCard
              label="Chunks indexados"
              value={vectorPoints != null ? fmtNum(vectorPoints) : "—"}
              icon={Lightning}
            />
          </div>

          <div className="mt-4">
            <AttentionList items={issues} emptyBody={COPY.attentionEmpty} />
          </div>
        </>
      )}
    </KnowledgeLayout>
  );
}
