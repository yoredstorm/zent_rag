import { Files } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  ResultCount,
  StatusBadge,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type SourceRow = { id: string; name: string };
type DocRow = {
  id: number;
  external_id: string;
  status: string;
  last_seen_at: string | null;
  source_name: string;
};

const PAGE_SIZE = 25;

const columns: Column<DocRow>[] = [
  {
    key: "source_name",
    header: "Fuente",
    sortable: true,
    render: (d) => <span className="text-text">{d.source_name}</span>,
  },
  {
    key: "external_id",
    header: "External ID",
    sortable: true,
    render: (d) => (
      <span className="mono block max-w-[320px] truncate text-xs text-muted" title={d.external_id}>
        {d.external_id}
      </span>
    ),
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (d) => <StatusBadge status={d.status} />,
  },
  {
    key: "last_seen_at",
    header: "Visto",
    hideBelow: "md",
    sortable: true,
    render: (d) => (
      <span className="text-xs text-muted">{d.last_seen_at ? fmtDateTime(d.last_seen_at) : "—"}</span>
    ),
  },
];

export default function KnowledgeDocumentsPage() {
  const { session } = useAuth();
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);

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

  const rows = useMemo(() => {
    if (!sort) return docs;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...docs].sort((a, b) => {
      const left = a[sort.key as keyof DocRow];
      const right = b[sort.key as keyof DocRow];
      return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
    });
  }, [docs, sort]);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = rows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const sourceCount = new Set(docs.map((d) => d.source_name)).size;

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.documents}
        subtitle="Registro de documentos indexados por fuente (solo tu organización)."
      />

      <DataTable
        columns={columns}
        rows={pageRows}
        rowKey={(d) => `${d.source_name}-${d.id}`}
        caption="Documentos indexados"
        loading={loading}
        error={error || null}
        sort={sort}
        onSortChange={(next) => {
          setSort(next);
          setPage(1);
        }}
        empty={
          <EmptyState
            icon={Files}
            title="Sin documentos indexados"
            body="Cuando sincronices fuentes, los documentos aparecerán aquí."
          />
        }
        footer={
          docs.length > 0 ? (
            <>
              {docs.length > PAGE_SIZE ? (
                <Pagination
                  page={safePage}
                  pageSize={PAGE_SIZE}
                  total={rows.length}
                  onPageChange={setPage}
                />
              ) : (
                <ResultCount shown={docs.length} total={docs.length} noun="documentos" />
              )}
              <span className="text-xs text-faint tabular-nums">
                {sourceCount === 1 ? "1 fuente" : `${sourceCount} fuentes`}
              </span>
            </>
          ) : undefined
        }
      />
    </KnowledgeLayout>
  );
}
