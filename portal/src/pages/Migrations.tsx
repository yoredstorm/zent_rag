import { ArrowsLeftRight, DownloadSimple, FileArrowUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  StatusBadge,
  SuccessInline,
  Textarea,
  type Column,
} from "../components/ui";
import { fmtDateTime, fmtNum } from "../lib/format";

type Migration = {
  id: string;
  kind: string;
  direction: string;
  status: string;
  filename: string | null;
  rows_total: number;
  rows_valid: number;
  rows_applied: number;
  rows_failed: number;
  created_at: string;
};
type Preview = {
  migration_id: string;
  status: string;
  rows_total: number;
  rows_valid: number;
  rows_failed: number;
  preview: Record<string, string>[];
  errors: { index: number; errors: string[] }[];
};

const KINDS = [
  { value: "kb", label: "Knowledge bases" },
  { value: "agents", label: "Agentes" },
  { value: "full", label: "Migración completa" },
];

const CSV_SAMPLE = `name,description,embedding_model
Migración KB 1,Base importada,text-embedding-3-small
KB Duplicada,ya existente,text-embedding-3-small`;

export default function MigrationsPage() {
  const { session } = useAuth();
  const [migrations, setMigrations] = useState<Migration[]>([]);
  const [kind, setKind] = useState("kb");
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Migration | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const m = await api<{ migrations: Migration[] }>("/api/v1/migrations", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setMigrations(m.migrations || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function previewImport() {
    if (!session) return;
    setBusy("preview");
    setError("");
    setMsg("");
    try {
      const p = await api<Preview>("/api/v1/migrations/import/preview", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ kind, content, filename: "import.csv" }),
      });
      setPreview(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function applyImport() {
    if (!session || !preview) return;
    setBusy("apply");
    setError("");
    setMsg("");
    try {
      const r = await api<{ status: string; rows_applied: number; rows_failed: number }>(
        "/api/v1/migrations/import/apply",
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ migration_id: preview.migration_id }),
        },
      );
      setMsg(`Aplicado: ${r.rows_applied} ok · ${r.rows_failed} fallaron`);
      setPreview(null);
      setContent("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function exportKind() {
    if (!session) return;
    setBusy("export");
    setError("");
    setMsg("");
    try {
      const e = await api<{ migration_id: string }>("/api/v1/migrations/export", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ kind }),
      });
      setMsg(`Export listo: ${e.migration_id.slice(0, 8)}…`);
      await load();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const previewColumns: Column<Record<string, string>>[] = Object.keys(
    preview?.preview[0] ?? {},
  ).map((key) => ({
    key,
    header: key,
    render: (row) => <span className="mono text-[11px] text-muted">{row[key] ?? "—"}</span>,
  }));

  function openDownload(migration: Migration) {
    if (!session) return;
    window.open(
      `/api/v1/migrations/export/${migration.id}/download?token=${encodeURIComponent(session.token || "")}&organizationId=${encodeURIComponent(session.organizationId)}`,
      "_blank",
    );
  }

  const columns: Column<Migration>[] = [
    {
      key: "direction",
      header: "Movimiento",
      render: (m) => (
        <div className="min-w-0">
          <span className="flex items-center gap-2">
            <Badge tone={m.direction === "export" ? "info" : "neutral"}>{m.direction}</Badge>
            <span className="text-[13px] text-text">{m.kind}</span>
          </span>
          {m.filename && (
            <p className="mono mt-1 truncate text-[11px] text-faint">{m.filename}</p>
          )}
        </div>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (m) => <StatusBadge status={m.status} />,
    },
    {
      key: "rows",
      header: "Filas",
      align: "right",
      hideBelow: "md",
      render: (m) => (
        <span className="mono text-xs text-muted">
          {fmtNum(m.rows_valid)} válidas · {fmtNum(m.rows_applied)} aplicadas ·{" "}
          <span className={m.rows_failed > 0 ? "text-danger" : undefined}>
            {fmtNum(m.rows_failed)} con error
          </span>
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Creado",
      hideBelow: "lg",
      render: (m) => <span className="text-xs text-muted">{fmtDateTime(m.created_at)}</span>,
    },
    {
      key: "download",
      header: "",
      align: "right",
      render: (m) =>
        m.direction === "export" && m.filename ? (
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={DownloadSimple}
            onClick={() => openDownload(m)}
          >
            Descargar
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Migraciones de datos"
        subtitle="Importá KBs y agentes desde CSV/JSON con validación y dry-run, o exportá con manifest."
      />
      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
          <Panel>
            <PanelHeader
              title="Importar"
              description="El dry-run valida filas antes de aplicar. Nada se escribe hasta que confirmes."
            />
            <div className="panel-body flex flex-col gap-4">
              <Field label="Tipo">
                <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                  {KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Contenido CSV / JSON" hint="Pegá el contenido o usá el ejemplo como referencia.">
                <Textarea
                  className="min-h-40 font-mono text-xs"
                  placeholder={CSV_SAMPLE}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  leadingIcon={FileArrowUp}
                  loading={busy === "preview"}
                  disabled={!!busy}
                  onClick={() => void previewImport()}
                >
                  Preview (dry-run)
                </Button>
                <Button
                  variant="secondary"
                  leadingIcon={DownloadSimple}
                  loading={busy === "export"}
                  disabled={!!busy}
                  onClick={() => void exportKind()}
                >
                  Exportar {kind}
                </Button>
              </div>

              {preview && (
                <div className="rounded-md border border-border bg-control p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="ok">{fmtNum(preview.rows_valid)} válidas</Badge>
                    <Badge tone={preview.rows_failed > 0 ? "danger" : "neutral"}>
                      {fmtNum(preview.rows_failed)} inválidas
                    </Badge>
                    <Badge tone="neutral">{fmtNum(preview.rows_total)} totales</Badge>
                  </div>
                  {previewColumns.length > 0 && (
                    <div className="mt-3">
                      <DataTable
                        columns={previewColumns}
                        rows={preview.preview}
                        rowKey={(row) => preview.preview.indexOf(row).toString()}
                        caption="Vista previa de filas"
                      />
                    </div>
                  )}
                  {preview.errors.length > 0 && (
                    <ErrorInline className="mt-3 mb-0" message={null}>
                      <ul className="list-disc pl-4">
                        {preview.errors.map((e) => (
                          <li key={e.index}>
                            Fila {e.index}: {e.errors.join(", ")}
                          </li>
                        ))}
                      </ul>
                    </ErrorInline>
                  )}
                  <Button
                    variant="primary"
                    className="mt-3"
                    loading={busy === "apply"}
                    disabled={!!busy}
                    onClick={() => void applyImport()}
                  >
                    Aplicar import
                  </Button>
                </div>
              )}
            </div>
          </Panel>

          <Panel>
            <PanelHeader
              title="Historial"
              description="Importaciones y exportaciones recientes de la organización."
            />
            <DataTable
              columns={columns}
              rows={migrations}
              rowKey={(m) => m.id}
              caption="Migraciones"
              loading={loading}
              empty={
                <EmptyState
                  icon={ArrowsLeftRight}
                  title="Sin migraciones"
                  body="Cuando importes o exportes datos, el historial aparece acá."
                />
              }
              onRowClick={(m) => setSelected(m)}
              isRowSelected={(m) => selected?.id === m.id}
              rowActions={(m) => (
                <Button variant="ghost" size="sm" onClick={() => setSelected(m)}>
                  Detalle
                </Button>
              )}
            />
          </Panel>
        </div>
      </div>

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected ? `${selected.direction} · ${selected.kind}` : "Migración"}
        description={selected?.filename ?? undefined}
        width={460}
        footer={
          selected?.direction === "export" && selected.filename ? (
            <Button
              variant="secondary"
              leadingIcon={DownloadSimple}
              onClick={() => openDownload(selected)}
            >
              Descargar export
            </Button>
          ) : undefined
        }
      >
        {selected && (
          <div className="space-y-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Movimiento", value: selected.direction },
                { key: "Tipo", value: selected.kind },
                { key: "Estado", value: <StatusBadge status={selected.status} /> },
                { key: "Archivo", value: selected.filename || "—", mono: true },
                { key: "Filas totales", value: fmtNum(selected.rows_total), mono: true },
                { key: "Filas válidas", value: fmtNum(selected.rows_valid), mono: true },
                { key: "Filas aplicadas", value: fmtNum(selected.rows_applied), mono: true },
                { key: "Filas con error", value: fmtNum(selected.rows_failed), mono: true },
                { key: "Creada", value: fmtDateTime(selected.created_at) },
                { key: "ID", value: selected.id, mono: true },
              ]}
            />
          </div>
        )}
      </Drawer>
    </div>
  );
}
