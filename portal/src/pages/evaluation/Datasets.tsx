import { FloppyDisk, Plus, Stack } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../../components/ui";

type Dataset = {
  id: string;
  name: string;
  case_count?: number;
  schema_version?: number;
  created_at?: string;
};

export default function EvaluationDatasetsPage() {
  const { session } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [name, setName] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    if (!session) return;
    setLoading(true);
    try {
      const out = await api<{ datasets: Dataset[] }>("/api/v1/eval/datasets", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setDatasets(out.datasets || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando datasets");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [session]);

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      setJsonText(String(reader.result || ""));
      if (!name.trim()) setName(file.name.replace(/\.json$/i, ""));
    };
    reader.readAsText(file);
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
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Importación fallida");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Datasets de evaluación"
        subtitle="Golden set schema v2: question, expected_answer (opcional), expected_sources."
        actions={
          <Link to="/evaluation/runs" className="btn btn-secondary min-h-11">
            Ver runs
          </Link>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />
      <form className="panel mb-6 p-5" onSubmit={onImport}>
        <h2 className="mb-3 text-sm font-semibold text-text">Importar JSON</h2>
        <label className="mb-1 block text-sm text-text" htmlFor="ds-name">
          Nombre
        </label>
        <input
          id="ds-name"
          className="mb-3 w-full max-w-md rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
          value={name}
          onChange={(ev) => setName(ev.target.value)}
          required
        />
        <label className="mb-1 block text-sm text-text" htmlFor="ds-file">
          Archivo
        </label>
        <input
          id="ds-file"
          type="file"
          accept="application/json,.json"
          className="mb-3 block text-sm"
          onChange={(ev) => {
            const file = ev.target.files?.[0];
            if (file) onFile(file);
          }}
        />
        <label className="mb-1 block text-sm text-text" htmlFor="ds-json">
          JSON
        </label>
        <textarea
          id="ds-json"
          className="min-h-[140px] w-full rounded-md border border-border bg-soft px-3 py-2.5 font-mono text-xs"
          value={jsonText}
          onChange={(ev) => setJsonText(ev.target.value)}
          required
        />
        <button type="submit" className="btn btn-primary mt-3 min-h-11" disabled={busy}>
          {busy ? <Spinner size={14} /> : <FloppyDisk size={16} aria-hidden />}
          Importar
        </button>
      </form>
      {loading && <SkeletonBlock />}
      {!loading && datasets.length === 0 && (
        <EmptyState
          icon={Stack}
          title="Sin datasets"
          body="Importa un golden set para lanzar un run."
          action={
            <span className="inline-flex items-center gap-1 text-sm text-muted">
              <Plus size={14} aria-hidden /> Schema v2
            </span>
          }
        />
      )}
      {datasets.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {datasets.map((ds) => (
            <li key={ds.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-text">{ds.name}</p>
                <p className="text-xs text-muted">
                  {ds.case_count ?? "—"} casos
                  {ds.schema_version ? ` · v${ds.schema_version}` : ""}
                </p>
              </div>
              <Link
                to={`/evaluation/runs?dataset=${ds.id}`}
                className="btn btn-secondary min-h-11 text-sm"
              >
                Lanzar run
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
