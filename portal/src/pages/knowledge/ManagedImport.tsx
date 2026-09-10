import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { PageHeader } from "../../components/ui";

export default function ManagedImportPage() {
  const { session } = useAuth();
  const [headers, setHeaders] = useState("codigo,descripcion,precio,stock");
  const [rowsText, setRowsText] = useState("A1,Ibuprofeno,12.5,4");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState("");

  function parsed() {
    const cols = headers.split(",").map((h) => h.trim());
    const rows = rowsText
      .split("\n")
      .map((line) => line.split(",").map((cell) => cell.trim()))
      .filter((row) => row.some(Boolean));
    return { cols, rows };
  }

  async function run() {
    if (!session) return;
    const { cols, rows } = parsed();
    const data = await api<Record<string, unknown>>("/api/v1/managed-db/import/preview", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({
        headers: cols,
        rows,
        table_name: "Products",
      }),
    });
    setPreview(data);
  }

  async function apply() {
    if (!session) return;
    const { cols, rows } = parsed();
    await api("/api/v1/managed-db/import/apply", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({
        headers: cols,
        rows,
        table_name: "Products",
        mode: "create",
      }),
    });
    setMsg("Imported into managed database.");
  }

  return (
    <KnowledgeLayout>
      <PageHeader title={KNOWLEDGE_HEADINGS.importCsv} />
      <ol className="mb-4 list-decimal pl-5 text-sm text-muted">
        <li>Upload File</li>
        <li>Detect Columns</li>
        <li>Infer Types</li>
        <li>Preview</li>
        <li>Create New Table or Import Into Existing</li>
        <li>Semantic Mapping</li>
        <li>Import</li>
      </ol>
      <textarea className="input min-h-16" value={headers} onChange={(e) => setHeaders(e.target.value)} />
      <textarea className="input mt-2 min-h-24" value={rowsText} onChange={(e) => setRowsText(e.target.value)} />
      <div className="mt-2 flex gap-2">
        <button type="button" className="btn btn-primary" onClick={() => void run()}>
          Detect Columns
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => void apply()}>
          Import Into New Table
        </button>
      </div>
      {msg && <p className="mt-2 text-sm text-ok">{msg}</p>}
      {preview && <pre className="mt-4 overflow-auto text-xs">{JSON.stringify(preview, null, 2)}</pre>}
    </KnowledgeLayout>
  );
}
