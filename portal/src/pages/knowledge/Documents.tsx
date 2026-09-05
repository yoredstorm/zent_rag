import { Files } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";

type SourceRow = { id: string; name: string };
type DocRow = {
  id: number;
  external_id: string;
  status: string;
  last_seen_at: string | null;
  source_name: string;
};

export default function KnowledgeDocumentsPage() {
  const { session } = useAuth();
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const listing = await api<{ sources: SourceRow[] }>("/api/v1/sources", {
          token: session.token,
          organizationId: session.organizationId,
        });
        const rows: DocRow[] = [];
        for (const source of listing.sources || []) {
          const data = await api<{
            documents: Omit<DocRow, "source_name">[];
          }>(`/api/v1/sources/${source.id}/documents?limit=50`, {
            token: session.token,
            organizationId: session.organizationId,
          });
          for (const doc of data.documents || []) {
            rows.push({ ...doc, source_name: source.name });
          }
        }
        setDocs(rows);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <KnowledgeLayout>
      <PageHeader
        title="Documentos"
        subtitle="Registry de documentos indexados por fuente (solo tu organización)."
      />
      <ErrorInline message={error} />
      <div className="panel">
        {loading ? (
          <div className="p-5">
            <SkeletonBlock rows={5} />
          </div>
        ) : docs.length === 0 ? (
          <EmptyState
            icon={Files}
            title="Sin documentos indexados"
            body="Cuando sincronices fuentes, los documentos aparecerán aquí."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[640px]">
              <thead>
                <tr>
                  <th>Fuente</th>
                  <th>External ID</th>
                  <th>Estado</th>
                  <th>Visto</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={`${d.source_name}-${d.id}`}>
                    <td className="text-text">{d.source_name}</td>
                    <td className="mono max-w-[280px] truncate text-xs" title={d.external_id}>
                      {d.external_id}
                    </td>
                    <td>
                      <span className="badge badge-ok">{d.status}</span>
                    </td>
                    <td className="text-muted">
                      {d.last_seen_at ? fmtDateTime(d.last_seen_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </KnowledgeLayout>
  );
}
