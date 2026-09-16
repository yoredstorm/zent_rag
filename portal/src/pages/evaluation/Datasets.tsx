import {
  ArrowsClockwise,
  FloppyDisk,
  Stack,
  UploadSimple,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Modal,
  PageHeader,
  Pagination,
  ResultCount,
  SuccessInline,
  Textarea,
  ToolbarSpacer,
  type Column,
  type SortState,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtDateTime, fmtNum } from "../../lib/format";

type Dataset = {
  id: string;
  name: string;
  case_count?: number;
  schema_version?: number;
  created_at?: string;
};

const PAGE_SIZE = 10;

function sortDatasets(rows: Dataset[], sort: SortState): Dataset[] {
  if (!sort) return rows;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[sort.key as keyof Dataset];
    const bv = b[sort.key as keyof Dataset];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "es") * dir;
  });
}

export default function EvaluationDatasetsPage() {
  const { session } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [name, setName] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);

  const reload = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    try {
      const out = await api<{ datasets: Dataset[] }>("/api/v1/eval/datasets", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setDatasets(out.datasets || []);
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Error cargando datasets");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      setJsonText(String(reader.result || ""));
      if (!name.trim()) setName(file.name.replace(/\.json$/i, ""));
    };
    reader.readAsText(file);
  }

  function closeImport() {
    if (busy) return;
    setImportOpen(false);
    setError("");
  }

  async function onImport(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const parsed = JSON.parse(jsonText) as unknown;
      const cases = Array.isArray(parsed)
        ? parsed
        : (parsed as { cases?: unknown }).cases;
      if (!Array.isArray(cases) || cases.length === 0) {
        throw new Error("El JSON debe ser un array de casos o { cases: [...] }");
      }
      await api("/api/v1/eval/datasets/import", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), cases }),
      });
      setMsg("Dataset importado.");
      setJsonText("");
      setName("");
      setImportOpen(false);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Importación fallida");
    } finally {
      setBusy(false);
    }
  }

  const sorted = sortDatasets(datasets, sort);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const columns: Column<Dataset>[] = [
    {
      key: "name",
      header: "Dataset",
      sortable: true,
      render: (ds) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] font-medium text-text" title={ds.name}>
            {ds.name}
          </p>
          <p className="mt-0.5 text-xs text-faint tabular-nums">
            schema v{ds.schema_version ?? 2}
            {ds.created_at ? ` · creado ${fmtDateTime(ds.created_at)}` : ""}
          </p>
        </div>
      ),
    },
    {
      key: "case_count",
      header: "Casos",
      align: "right",
      sortable: true,
      render: (ds) => <span className="mono text-[13px]">{fmtNum(ds.case_count ?? 0)}</span>,
    },
    {
      key: "created_at",
      header: "Creado",
      sortable: true,
      hideBelow: "md",
      render: (ds) => (
        <span className="text-xs text-muted tabular-nums">{fmtDateTime(ds.created_at)}</span>
      ),
    },
  ];

  return (
    <QualityLayout>
      <PageHeader
        title="Datasets de evaluación"
        subtitle="Golden set schema v2: question, expected_answer (opcional), expected_sources."
      />

      <div className="flex flex-col gap-4">
        <SuccessInline message={msg} className="mb-0" />

        <DataTable
          columns={columns}
          rows={pageRows}
          rowKey={(ds) => ds.id}
          caption="Datasets de evaluación"
          loading={loading}
          error={loadError}
          stickyHeader
          sort={sort}
          onSortChange={(next) => {
            setSort(next);
            setPage(1);
          }}
          rowActions={(ds) => (
            <ButtonLink
              to={`/evaluation/runs?dataset=${ds.id}`}
              size="sm"
              variant="secondary"
            >
              Lanzar run
            </ButtonLink>
          )}
          empty={
            <EmptyState
              icon={Stack}
              title="Sin datasets"
              body="Importá un golden set schema v2 (question, expected_answer opcional, expected_sources) para lanzar un run."
              hint="También podés partir de un JSON exportado desde otra evaluación."
              action={
                <Button
                  variant="primary"
                  leadingIcon={UploadSimple}
                  onClick={() => setImportOpen(true)}
                >
                  Importar JSON
                </Button>
              }
            />
          }
          toolbar={
            <>
              <ResultCount shown={pageRows.length} total={datasets.length} noun="datasets" />
              <ToolbarSpacer />
              <Button
                size="sm"
                variant="ghost"
                leadingIcon={ArrowsClockwise}
                onClick={() => void reload()}
                disabled={loading}
              >
                Actualizar
              </Button>
              <Button
                size="sm"
                variant="primary"
                leadingIcon={UploadSimple}
                onClick={() => setImportOpen(true)}
              >
                Importar JSON
              </Button>
            </>
          }
          footer={
            sorted.length > PAGE_SIZE ? (
              <Pagination
                page={safePage}
                pageSize={PAGE_SIZE}
                total={sorted.length}
                onPageChange={setPage}
              />
            ) : undefined
          }
        />
      </div>

      <Modal
        open={importOpen}
        onOpenChange={(open) => (open ? setImportOpen(true) : closeImport())}
        title="Importar dataset"
        description="Golden set schema v2: question, expected_answer (opcional), expected_sources."
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={closeImport} disabled={busy}>
              Cancelar
            </Button>
            <Button
              type="submit"
              form="dataset-import-form"
              variant="primary"
              loading={busy}
              leadingIcon={FloppyDisk}
            >
              Importar
            </Button>
          </>
        }
      >
        <form id="dataset-import-form" className="flex flex-col gap-4" onSubmit={onImport}>
          <ErrorInline message={error} className="mb-0" />
          <Field label="Nombre" required>
            <Input
              value={name}
              onChange={(ev) => setName(ev.target.value)}
              required
              autoComplete="off"
            />
          </Field>
          <Field
            label="Archivo"
            hint="Opcional: cargá un .json para completar el nombre y el contenido."
          >
            <input
              type="file"
              accept="application/json,.json"
              className="block w-full cursor-pointer text-[13px] text-muted file:mr-3 file:cursor-pointer file:rounded-sm file:border file:border-border file:bg-raised file:px-3 file:py-1.5 file:text-[13px] file:font-medium file:text-text"
              onChange={(ev) => {
                const file = ev.target.files?.[0];
                if (file) onFile(file);
              }}
            />
          </Field>
          <Field label="JSON" required hint="Array de casos o { cases: [...] }.">
            <Textarea
              className="min-h-[200px] font-mono text-xs"
              value={jsonText}
              onChange={(ev) => setJsonText(ev.target.value)}
              required
              spellCheck={false}
            />
          </Field>
        </form>
      </Modal>
    </QualityLayout>
  );
}
