import { ArrowsLeftRight, DownloadSimple } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Migration = { id: string; kind: string; direction: string; status: string; filename: string | null; rows_total: number; rows_valid: number; rows_applied: number; rows_failed: number; created_at: string };
type Preview = { migration_id: string; status: string; rows_total: number; rows_valid: number; rows_failed: number; preview: Record<string, string>[]; errors: { index: number; errors: string[] }[] };

export default function MigrationsPage() {
  const { session } = useAuth();
  const [migrations, setMigrations] = useState<Migration[]>([]);
  const [kind, setKind] = useState("kb");
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const m = await api<{ migrations: Migration[] }>("/api/v1/migrations", { token: session.token, organizationId: session.organizationId });
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
    try {
      const r = await api<{ status: string; rows_applied: number; rows_failed: number }>("/api/v1/migrations/import/apply", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ migration_id: preview.migration_id }),
      });
      setError(`Aplicado: ${r.rows_applied} ok · ${r.rows_failed} fallaron`);
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
    try {
      const e = await api<{ migration_id: string }>("/api/v1/migrations/export", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ kind }),
      });
      setError(`Export listo: ${e.migration_id.slice(0, 8)}…`);
      await load();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const CSV_SAMPLE = `name,description,embedding_model
Migración KB 1,Base importada,text-embedding-3-small
KB Duplicada,ya existente,text-embedding-3-small`;

  return (
    <div>
      <PageHeader title="Migraciones de datos" subtitle="Importa KBs y agentes desde CSV/JSON con validación y dry-run, o exporta con manifest." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="panel p-4">
            <h2 className="mb-2 text-sm font-semibold text-text">Importar (CSV/JSON)</h2>
            <div className="grid grid-cols-1 gap-2">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
                {["kb", "agents", "full"].map((k) => (<option key={k} value={k}>{k}</option>))}
              </select>
              <textarea
                className="h-40 rounded-md border border-border bg-soft p-3 font-mono text-xs"
                placeholder={CSV_SAMPLE}
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
              <div className="flex gap-2">
                <button type="button" className="btn btn-primary min-h-9 flex-1 text-xs" disabled={!!busy} onClick={() => void previewImport()}>
                  Preview (dry-run)
                </button>
                <button type="button" className="btn btn-secondary min-h-9 flex-1 text-xs" disabled={!!busy} onClick={() => void exportKind()}>
                  <DownloadSimple size={13} /> Exportar {kind}
                </button>
              </div>
            </div>

            {preview && (
              <div className="mt-3 rounded-md bg-soft p-3 text-xs">
                <p className="text-text">
                  {preview.rows_valid} válidas · {preview.rows_failed} inválidas de {preview.rows_total}
                </p>
                {preview.preview.length > 0 && (
                  <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-[10px] text-faint">
                    {JSON.stringify(preview.preview, null, 1)}
                  </pre>
                )}
                {preview.errors.length > 0 && (
                  <p className="mt-2 text-red-400">
                    {preview.errors.map((e) => `fila ${e.index}: ${e.errors.join(", ")}`).join(" · ")}
                  </p>
                )}
                <button type="button" className="btn btn-primary mt-2 min-h-8 text-xs" disabled={!!busy} onClick={() => void applyImport()}>
                  Aplicar import
                </button>
              </div>
            )}
          </section>

          <section className="panel p-4">
            <h2 className="mb-2 text-sm font-semibold text-text">Historial</h2>
            <div className="space-y-1">
              {migrations.map((m) => (
                <div key={m.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1.5 text-[11px]">
                  <ArrowsLeftRight size={12} className="text-faint" />
                  <span className="text-text">{m.direction} · {m.kind}</span>
                  <span className={`badge ${m.status === "applied" || m.status === "exported" ? "badge-ok" : m.status === "failed" ? "badge-danger" : "badge-warning"}`}>{m.status}</span>
                  <span className="text-faint">{m.rows_valid} válidas · {m.rows_applied} aplicadas · {m.rows_failed} fail</span>
                  <span className="flex-1" />
                  {m.direction === "export" && m.filename && (
                    <button
                      type="button"
                      className="btn btn-ghost min-h-7 px-2 text-[11px]"
                      onClick={() => session && window.open(`/api/v1/migrations/export/${m.id}/download?token=${encodeURIComponent(session.token)}&organizationId=${encodeURIComponent(session.organizationId)}`, "_blank")}
                    >
                      Descargar
                    </button>
                  )}
                </div>
              ))}
              {migrations.length === 0 && <p className="text-xs text-faint">Sin migraciones.</p>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}