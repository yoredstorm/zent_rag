import { Binoculars, CaretRight } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { fmtDateTime } from "../../lib/format";

type CatalogSource = {
  id: string;
  connector_id: string;
  engine: string;
  phase: string;
  last_scan_at: string | null;
  scan_error: string | null;
  content_signature: string | null;
};

type Readiness = {
  overall: number;
  schema_coverage: number;
  relationship_coverage: number;
  description_coverage: number;
  semantic_mapping_coverage: number;
  metric_coverage: number;
  glossary_coverage: number;
  freshness: number;
  data_quality: number;
  unknown_code_count: number;
  pending_review_count: number;
};

export default function KnowledgeCatalogPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [readiness, setReadiness] = useState<Record<string, Readiness>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<CatalogSource[]>("/api/v1/catalog/sources")
      .then(async (rows) => {
        setSources(rows);
        const ready: Record<string, Readiness> = {};
        await Promise.all(
          rows.map(async (s) => {
            try {
              ready[s.id] = await api<Readiness>(`/api/v1/catalog/sources/${s.id}/readiness`);
            } catch {
              /* sin readiness */
            }
          })
        );
        setReadiness(ready);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const startScan = async (sourceId: string) => {
    setScanning(sourceId);
    try {
      await api<{ job_id: string }>(`/api/v1/catalog/sources/${sourceId}/rescan`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setScanning("");
      load();
    } catch (e) {
      setError(String(e));
      setScanning("");
    }
  };

  return (
    <KnowledgeLayout>
      <PageHeader title="Catálogo" subtitle="Descubrimiento autónomo de metadata y catálogo semántico (FASE 24)." />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <SkeletonBlock rows={4} />
      ) : sources.length === 0 ? (
        <div className="text-sm text-zinc-500">
          Conectá un conector SQL y ejecutá{" "}
          <code className="rounded bg-zinc-100 px-1">POST /api/v1/catalog/discovery</code>{" "}
          para iniciar el primer scan.
        </div>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => {
            const r = readiness[s.id];
            return (
              <div key={s.id} className="card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Binoculars size={18} className="text-indigo-500" />
                    <span className="font-medium">{s.engine}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        s.phase === "COMPLETED" || s.phase === "WAITING_REVIEW"
                          ? "bg-emerald-100 text-emerald-700"
                          : s.phase === "FAILED" || s.phase === "PARTIAL"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-sky-100 text-sky-700"
                      }`}
                    >
                      {s.phase}
                    </span>
                  </div>
                  <button
                    className="btn btn-sm"
                    onClick={() => startScan(s.id)}
                    disabled={scanning === s.id}
                  >
                    {scanning === s.id ? <Spinner /> : <CaretRight size={14} />} Rescan
                  </button>
                </div>
                <div className="mt-2 text-xs text-zinc-500">
                  Último scan: {s.last_scan_at ? fmtDateTime(s.last_scan_at) : "nunca"}
                  {s.scan_error ? ` · error: ${s.scan_error}` : ""}
                </div>
                {r && (
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                    {[
                      ["Readiness", `${r.overall}%`],
                      ["Schema", `${r.schema_coverage}%`],
                      ["Relaciones", `${r.relationship_coverage}%`],
                      ["Semántico", `${r.semantic_mapping_coverage}%`],
                      ["Glosario", `${r.glossary_coverage}%`],
                      ["Métricas", `${r.metric_coverage}%`],
                      ["Códigos sin doc", String(r.unknown_code_count)],
                      ["En revisión", String(r.pending_review_count)],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded bg-zinc-50 px-2 py-1.5">
                        <div className="text-zinc-400">{label}</div>
                        <div className="font-semibold text-zinc-700">{value}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </KnowledgeLayout>
  );
}