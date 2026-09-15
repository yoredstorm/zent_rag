import { ArrowsClockwise } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  Progress,
  ResultCount,
  Select,
  statusLabel,
  type Column,
  type SortState,
} from "../../components/ui";
import { StatusBadge } from "../../components/ui/Badge";
import { fmtDateTime, fmtNum, formatErrorSummary } from "../../lib/format";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type Job = {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  records_processed: number;
  records_failed: number;
  error_summary: string | { error?: unknown; message?: unknown } | null;
  created_at: string;
};

const FAILED = new Set(["failed", "dead"]);
const PAGE_SIZE = 20;

/** La API expone `dead` para jobs sin intentos restantes: no está en el vocabulario compartido. */
function jobLabel(status: string): string | undefined {
  return status === "dead" ? "Descartado" : undefined;
}

const columns: Column<Job>[] = [
  {
    key: "job_type",
    header: "Tipo",
    sortable: true,
    render: (j) => (
      <div className="min-w-0">
        <span className="mono text-xs text-text">{j.job_type}</span>
        {FAILED.has(j.status) && j.error_summary ? (
          <p className="mt-1 max-w-[52ch] text-xs leading-relaxed text-danger">
            {formatErrorSummary(j.error_summary)}
          </p>
        ) : null}
      </div>
    ),
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (j) => <StatusBadge status={j.status} label={jobLabel(j.status)} />,
  },
  {
    key: "progress",
    header: "Progreso",
    sortable: true,
    width: "180px",
    render: (j) => (
      <Progress
        value={j.progress}
        tone={FAILED.has(j.status) ? "danger" : j.status === "completed" ? "ok" : "accent"}
        showValue
        className="max-w-[160px]"
      />
    ),
  },
  {
    key: "records_processed",
    header: "Procesados",
    align: "right",
    hideBelow: "md",
    sortable: true,
    render: (j) => <span className="mono text-xs text-muted">{fmtNum(j.records_processed)}</span>,
  },
  {
    key: "records_failed",
    header: "Fallidos",
    align: "right",
    hideBelow: "md",
    sortable: true,
    render: (j) => (
      <span className={j.records_failed > 0 ? "mono text-xs text-danger" : "mono text-xs text-faint"}>
        {fmtNum(j.records_failed)}
      </span>
    ),
  },
  {
    key: "created_at",
    header: "Creado",
    hideBelow: "lg",
    sortable: true,
    render: (j) => <span className="text-xs text-muted">{fmtDateTime(j.created_at)}</span>,
  },
];

export default function KnowledgeJobsPage() {
  const { session } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<{ jobs: Job[] }>("/api/v1/jobs?limit=50", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setJobs(data.jobs || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const statuses = useMemo(
    () => Array.from(new Set(jobs.map((j) => j.status))).sort(),
    [jobs],
  );

  const filtered = useMemo(
    () => (statusFilter ? jobs.filter((j) => j.status === statusFilter) : jobs),
    [jobs, statusFilter],
  );

  const rows = useMemo(() => {
    if (!sort) return filtered;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const left = a[sort.key as keyof Job];
      const right = b[sort.key as keyof Job];
      if (typeof left === "number" && typeof right === "number") return (left - right) * dir;
      return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
    });
  }, [filtered, sort]);

  const visible = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const failedCount = jobs.filter((j) => FAILED.has(j.status)).length;

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.jobs}
        subtitle="Jobs de ingestión de tu organización. La API legacy de ingestión sigue disponible."
        actions={
          failedCount > 0 ? (
            <Badge tone="danger">
              {fmtNum(failedCount)} {failedCount === 1 ? "job con error" : "jobs con error"}
            </Badge>
          ) : undefined
        }
      />

      <DataTable
        columns={columns}
        rows={visible}
        rowKey={(j) => j.id}
        caption="Trabajos de ingestión"
        loading={loading}
        error={error || null}
        sort={sort}
        onSortChange={setSort}
        toolbar={
          statuses.length > 1 ? (
            <Select
              className="w-full sm:w-52"
              aria-label="Filtrar por estado"
              placeholder="Todos los estados"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
            >
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </Select>
          ) : undefined
        }
        empty={
          <EmptyState
            icon={ArrowsClockwise}
            title="Sin trabajos todavía"
            body="Cuando sincronices una fuente, el progreso se listará aquí."
          />
        }
        footer={
          rows.length > 0 ? (
            <>
              <ResultCount shown={visible.length} total={rows.length} noun="trabajos" />
              {rows.length > PAGE_SIZE && (
                <Pagination
                  page={page}
                  pageSize={PAGE_SIZE}
                  total={rows.length}
                  onPageChange={setPage}
                />
              )}
            </>
          ) : undefined
        }
      />
    </KnowledgeLayout>
  );
}
