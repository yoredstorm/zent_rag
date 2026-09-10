import {
  Database,
  Files,
  FolderSimple,
  Heartbeat,
  Lightning,
  List,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { AttentionList } from "../../components/AttentionList";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
  StatusBadge,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtDateTime, fmtNum, timeAgo } from "../../lib/format";

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
  progress: number;
  records_processed: number;
  records_failed: number;
  error_summary: string | null;
  created_at: string;
};

type KB = { id: string; name: string; status: string };

type SqlOverview = { total_sources: number; synced_sources: number };

const BROKEN = new Set(["error", "failed"]);

export default function KnowledgeOverviewPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [kbs, setKbs] = useState<KB[]>([]);
  const [vectorPoints, setVectorPoints] = useState<number | null>(null);
  const [sql, setSql] = useState<SqlOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hasRealData, setHasRealData] = useState(true);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [attention, setAttention] = useState<{ id: string; warning?: string | null } | null>(null);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [s, j, kb, st, ing, gate, attentionData] = await Promise.all([
          api<{ sources: Source[] }>("/api/v1/sources", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ jobs: Job[] }>("/api/v1/jobs?limit=20", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ vector_points: number }>("/api/v1/billing/usage/storage", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => null),
          api<SqlOverview>("/api/v1/ingestion/sources", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => null),
          api<{ has_real_data: boolean; resume_session_id: string | null }>(
            "/api/v1/data-onboarding/gate",
            { token: session.token, organizationId: session.organizationId }
          ).catch(() => ({ has_real_data: false, resume_session_id: null })),
          api<{ sessions: Array<{ id: string; warning?: string | null }> }>(
            "/api/v1/data-onboarding/sessions?status=NEEDS_ATTENTION",
            { token: session.token, organizationId: session.organizationId }
          ).catch(() => ({ sessions: [] })),
        ]);
        setSources(s.sources || []);
        setJobs(j.jobs || []);
        setKbs(kb.knowledge_bases || []);
        setVectorPoints(st?.vector_points ?? null);
        setSql(ing);
        setHasRealData(
          Boolean(gate.has_real_data) ||
            (s.sources || []).some((src) => src.type !== "sql")
        );
        setResumeId(gate.resume_session_id);
        setAttention(attentionData.sessions?.[0] || null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando conocimiento");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const healthy = sources.filter((s) => !BROKEN.has(s.status)).length;
  const broken = sources.filter((s) => BROKEN.has(s.status));
  const documents = sources.reduce((acc, s) => acc + (s.document_count || 0), 0);
  const failedJobs = jobs.filter((j) => j.status === "failed" || j.status === "dead");
  const recentJobs = jobs.slice(0, 8);
  const lastSync = sources
    .map((s) => s.last_sync)
    .filter(Boolean)
    .sort()
    .reverse()[0];

  const issues: { id: string; label: string; to: string }[] = [
    ...broken.slice(0, 5).map((s) => ({
      id: `src-${s.id}`,
      label: `La fuente «${s.name}» no se sincronizó correctamente.`,
      to: "/knowledge/sources",
    })),
    ...failedJobs.slice(0, 5).map((j) => ({
      id: `job-${j.id}`,
      label: `El job de ${j.job_type} falló.${j.error_summary ? ` ${j.error_summary.slice(0, 120)}` : ""}`,
      to: "/knowledge/jobs",
    })),
  ];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.overview}
        subtitle="Comprende, aprueba y mide el conocimiento que tu IA puede utilizar."
        actions={
          <div className="flex flex-wrap gap-2">
            {resumeId && (
              <Link to={`/knowledge/add/${resumeId}`} className="btn btn-secondary">
                Continuar
              </Link>
            )}
            <Link to="/knowledge/add" className="btn btn-primary">
              Añade conocimiento a Zent
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />
      <section className="mb-6 grid gap-3 md:grid-cols-3" aria-label="Viaje de conocimiento">
        <Link
          to="/knowledge/glossary"
          className="panel block p-4 transition-colors hover:border-accent/40"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">1. Comprende</p>
          <h2 className="mt-1 font-semibold text-text">Semántica</h2>
          <p className="mt-1 text-sm text-muted">Términos, catálogo y entendimiento de tus datos.</p>
        </Link>
        <Link
          to="/knowledge/review"
          className="panel block p-4 transition-colors hover:border-accent/40"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">2. Aprueba</p>
          <h2 className="mt-1 font-semibold text-text">Revisión</h2>
          <p className="mt-1 text-sm text-muted">Nada se auto-aprueba: confirma sugerencias y términos.</p>
        </Link>
        <Link
          to="/knowledge/learning"
          className="panel block p-4 transition-colors hover:border-accent/40"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">3. Mide</p>
          <h2 className="mt-1 font-semibold text-text">Aprendizaje</h2>
          <p className="mt-1 text-sm text-muted">Readiness, mapa y mejoras del conocimiento aprendido.</p>
        </Link>
      </section>
      {hasRealData && (
        <div className="mb-4 rounded-md border border-border p-4">
          <h2 className="font-semibold">Tu conocimiento está listo.</h2>
          <p className="text-sm text-muted">
            Conectado: {sources.length} fuentes. Pendientes de revisión: {broken.length} items.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Link to="/chat" className="btn btn-primary">Pregúntale a Zent</Link>
            <Link to="/agents/new" className="btn btn-secondary">Crear agente</Link>
            <Link to="/knowledge/improvements" className="btn btn-secondary">Revisar mejoras</Link>
          </div>
        </div>
      )}
      {attention && (
        <div className="mb-4 rounded-md border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
          {attention.warning ||
            "Zent tiene datos sin revisar de tu última fuente."}{" "}
          <Link className="text-accent underline" to={`/knowledge/add/${attention.id}`}>
            Revisar ahora
          </Link>
        </div>
      )}
      {!loading && !hasRealData && (
        <div className="panel mb-4 p-6">
          <p className="text-sm text-muted">
            Aún no hay datos de negocio. Empieza con el asistente guiado.
          </p>
          <Link to="/knowledge/add" className="btn btn-primary mt-3">
            Añade conocimiento a Zent
          </Link>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="stat space-y-2">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatCard label="Fuentes conectadas" value={fmtNum(sources.length)} icon={Database} />
            <StatCard
              label="Fuentes saludables"
              value={fmtNum(healthy)}
              icon={Heartbeat}
              tone={broken.length > 0 ? "warn" : "ok"}
              hint={broken.length > 0 ? `${broken.length} con error` : "todo en orden"}
            />
            <StatCard label="Documentos" value={fmtNum(documents)} icon={Files} />
            <StatCard
              label="Chunks indexados"
              value={vectorPoints != null ? fmtNum(vectorPoints) : "—"}
              icon={Lightning}
            />
            <StatCard label="Bases de datos SQL" value={fmtNum(sql?.total_sources ?? 0)} icon={Database} />
            <StatCard label="Colecciones" value={fmtNum(kbs.length)} icon={FolderSimple} />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <AttentionList
                items={issues}
                emptyBody="No se detectaron problemas en tus fuentes ni trabajos de sincronización."
              />
            </div>

            <div className="panel">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Última sincronización</h2>
              </div>
              <div className="p-4">
                {lastSync ? (
                  <div className="flex items-center gap-2 text-sm text-text">
                    <Lightning size={15} className="text-accent" aria-hidden />
                    {fmtDateTime(lastSync)}
                  </div>
                ) : (
                  <p className="text-sm text-muted">Sin sincronizaciones aún.</p>
                )}
                <p className="mt-2 text-xs text-faint">
                  {fmtNum(sql?.synced_sources ?? 0)} de {fmtNum(sql?.total_sources ?? 0)} tablas SQL sincronizadas.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel overflow-x-auto xl:col-span-2">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Trabajos recientes</h2>
                <Link to="/knowledge/jobs" className="text-xs text-accent hover:underline">
                  Ver todos
                </Link>
              </div>
              {recentJobs.length === 0 ? (
                <EmptyState
                  icon={List}
                  title="Sin trabajos"
                  body="Cuando sincronices fuentes, los jobs quedarán registrados aquí."
                />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Estado</th>
                      <th>Progreso</th>
                      <th>Procesados</th>
                      <th>Fallidos</th>
                      <th>Creado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentJobs.map((j) => (
                      <tr key={j.id}>
                        <td className="text-sm">{j.job_type}</td>
                        <td>
                          <StatusBadge status={j.status} />
                        </td>
                        <td className="mono text-xs text-muted">{j.progress}%</td>
                        <td className="mono text-xs text-muted">{fmtNum(j.records_processed)}</td>
                        <td className="mono text-xs text-muted">{fmtNum(j.records_failed)}</td>
                        <td className="text-xs text-muted">{timeAgo(j.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="panel">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Atajos</h2>
              </div>
              <div className="flex flex-col gap-2 p-4">
                <Link
                  to="/knowledge/add"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Añade conocimiento a Zent
                  <span className="text-faint transition-transform group-hover:translate-x-0.5">→</span>
                </Link>
                <Link
                  to="/knowledge/sources"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Ver fuentes
                  <span className="text-faint transition-transform group-hover:translate-x-0.5">→</span>
                </Link>
                <Link
                  to="/connectors"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Administrar conectores
                  <span className="text-faint transition-transform group-hover:translate-x-0.5">→</span>
                </Link>
                <Link
                  to="/knowledge/playground"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Probar la búsqueda
                  <span className="text-faint transition-transform group-hover:translate-x-0.5">→</span>
                </Link>
              </div>
            </div>
          </div>
        </>
      )}
    </KnowledgeLayout>
  );
}