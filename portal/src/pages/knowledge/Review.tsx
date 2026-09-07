import { Check, Prohibit, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
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

export default function KnowledgeReviewPage() {
  const { session } = useAuth();
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Suggestion[]>("/api/v1/catalog/suggestions?status=pending")
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
      <PageHeader title="Cola de revisión" subtitle="Sugerencias semánticas (OBSERVED/INFERRED) que requieren aprobación humana. Nada se auto-aprueba." />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <SkeletonBlock rows={4} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Check}
          title="Sin sugerencias pendientes"
          body="Las inferencias del Discovery Engine aparecerán aquí para su revisión."
        />
      ) : (
        <div className="space-y-2">
          {items.map((s) => (
            <div key={s.id} className="card p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-600">
                      {s.type}
                    </span>
                    <span className="text-xs text-zinc-400">{s.confidence}</span>
                    <span className="text-xs text-zinc-400">
                      {fmtDateTime(s.created_at)}
                    </span>
                  </div>
                  <div className="mt-1 font-medium">{s.title}</div>
                  {s.description && (
                    <div className="mt-1 text-sm text-zinc-600">{s.description}</div>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={busy === s.id}
                    onClick={() => decide(s.id, "approve")}
                    title="Aprobar"
                  >
                    <Check size={14} /> Aprobar
                  </button>
                  <button
                    className="btn btn-sm"
                    disabled={busy === s.id}
                    onClick={() => decide(s.id, "reject")}
                    title="Rechazar"
                  >
                    <X size={14} /> Rechazar
                  </button>
                  <button
                    className="btn btn-sm"
                    disabled={busy === s.id}
                    onClick={() => decide(s.id, "defer")}
                    title="Diferir"
                  >
                    <Prohibit size={14} /> Diferir
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </KnowledgeLayout>
  );
}