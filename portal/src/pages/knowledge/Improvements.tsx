import { Wrench } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
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

const PRIORITY_TONE: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-amber-100 text-amber-700",
  medium: "bg-sky-100 text-sky-700",
  low: "bg-zinc-100 text-zinc-600",
};

const STATUSES = ["OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "BLOCKED"];

export default function KnowledgeImprovementsPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Improvement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

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

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.improvements}
        subtitle="Backlog priorizado de mejoras del ciclo gobernado (gaps, clusters, métricas sugeridas)."
      />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <SkeletonBlock rows={4} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="Sin mejoras pendientes"
          body="Los gaps de contexto se convertirán aquí en acciones priorizadas."
        />
      ) : (
        <div className="space-y-2">
          {items.map((i) => (
            <div key={i.id} className="card p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${PRIORITY_TONE[i.priority] ?? ""}`}
                    >
                      {i.priority}
                    </span>
                    <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-600">
                      {i.gap_type}
                    </span>
                    <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs">{i.status}</span>
                    <span className="text-xs text-zinc-400">{fmtDateTime(i.created_at)}</span>
                  </div>
                  <div className="mt-1 font-medium">{i.title}</div>
                  {i.recommended_action && (
                    <div className="mt-1 text-sm text-zinc-600">→ {i.recommended_action}</div>
                  )}
                  <div className="mt-1 text-xs text-zinc-400">
                    {i.affected_queries} consultas · {i.affected_users} usuarios ·{" "}
                    {i.affected_agents} agentes
                    {i.owner ? ` · owner: ${i.owner}` : ""}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  {STATUSES.filter((s) => s !== i.status).slice(0, 3).map((s) => (
                    <button
                      key={s}
                      className="btn btn-sm"
                      disabled={busy === i.id}
                      onClick={() => setStatus(i.id, s)}
                    >
                      {s.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </KnowledgeLayout>
  );
}