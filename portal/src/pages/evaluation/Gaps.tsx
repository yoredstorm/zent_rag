import { ListChecks } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtDateTime } from "../../lib/format";

type Gap = {
  id: string;
  gap_type: string;
  concept: string;
  question: string | null;
  occurrences: number;
  impact: Record<string, number>;
  status: string;
  evidence_hints: string[];
  last_seen_at: string;
};

export default function EvaluationGapsPage() {
  const { session } = useAuth();
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Gap[]>("/api/v1/learning/gaps?status=open")
      .then(setGaps)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const resolve = async (id: string) => {
    setBusy(id);
    try {
      await api(`/api/v1/learning/gaps/${id}/resolve`, { method: "POST", body: JSON.stringify({}) });
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <QualityLayout>
      <PageHeader
        title="Context Gaps"
        subtitle="Por qué Zent no pudo responder: gaps estructurados con impacto real."
      />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <SkeletonBlock rows={4} />
      ) : gaps.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="Sin gaps abiertos"
          body="Los gaps aparecen cuando una consulta no es contestable."
        />
      ) : (
        <div className="space-y-2">
          {gaps.map((g) => (
            <div key={g.id} className="card p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-600">
                      {g.gap_type}
                    </span>
                    <span className="font-medium">{g.concept}</span>
                    <span className="text-xs text-zinc-400">
                      {g.occurrences} consultas · {g.impact?.query_count_30d ?? 0}/30d
                    </span>
                  </div>
                  {g.question && <div className="mt-1 text-sm text-zinc-600">{g.question}</div>}
                  <div className="mt-1 text-xs text-zinc-400">Última vez: {fmtDateTime(g.last_seen_at)}</div>
                </div>
                <button className="btn btn-sm" disabled={busy === g.id} onClick={() => resolve(g.id)}>
                  Resolver
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </QualityLayout>
  );
}