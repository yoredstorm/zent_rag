import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { PageHeader } from "../../components/ui";

type Field = { name: string; type: string; required?: boolean; unique?: boolean };

const FRIENDLY = [
  "Text",
  "Long Text",
  "Number",
  "Money",
  "Integer",
  "Boolean",
  "Date",
  "Date & Time",
  "Identifier",
  "Relation",
  "JSON",
  "Email",
  "Phone",
];

export default function DatabaseBuilderPage() {
  const { session } = useAuth();
  const [db, setDb] = useState<Record<string, unknown> | null>(null);
  const [prompt, setPrompt] = useState("");
  const [proposal, setProposal] = useState<Record<string, unknown> | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState("");
  const [tableName, setTableName] = useState("Products");
  const [fields, setFields] = useState<Field[]>([
    { name: "Name", type: "Text", required: true },
    { name: "Price", type: "Money" },
  ]);
  const [relFrom, setRelFrom] = useState("Sales");
  const [relTo, setRelTo] = useState("Customers");

  useEffect(() => {
    if (!session) return;
    api<Record<string, unknown>>("/api/v1/managed-db", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setDb)
      .catch(() => setDb(null));
  }, [session]);

  async function createDb() {
    if (!session) return;
    setError("");
    try {
      const created = await api<Record<string, unknown>>("/api/v1/managed-db", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setDb(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }

  async function askAi() {
    if (!session) return;
    const data = await api<{ proposal: Record<string, unknown>; id: string; ddl_preview?: string }>(
      "/api/v1/managed-db/proposals",
      {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ prompt }),
      }
    );
    setProposal(data);
  }

  async function saveManual() {
    if (!session) return;
    const data = await api<Record<string, unknown>>("/api/v1/managed-db/proposals", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({
        status: "DRAFT",
        proposal: {
          tables: [{ name: tableName, fields }],
          relationships: [{ from_table: relFrom, to_table: relTo, from_column: "id", to_column: "id" }],
        },
      }),
    });
    setProposal(data);
  }

  async function approve() {
    if (!session || !proposal?.id) return;
    await api(`/api/v1/managed-db/proposals/${proposal.id}/apply`, {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
    });
  }

  return (
    <KnowledgeLayout>
      <PageHeader title="Database Builder" />
      {error && <p className="text-sm text-danger">{error}</p>}
      {!db ? (
        <button type="button" className="btn btn-primary" onClick={() => void createDb()}>
          Create a database with Zent
        </button>
      ) : (
        <p className="text-sm text-muted">
          Backup: {(db as { backup?: { restore_ready?: boolean } }).backup?.restore_ready
            ? "listo"
            : "pendiente"}
        </p>
      )}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section className="space-y-2 rounded-md border border-border p-4">
          <h2 className="font-medium">Create Table</h2>
          <label className="text-sm">
            Table Name
            <input className="input" value={tableName} onChange={(e) => setTableName(e.target.value)} />
          </label>
          {fields.map((field, idx) => (
            <div key={idx} className="grid grid-cols-2 gap-2">
              <input
                className="input"
                value={field.name}
                onChange={(e) => {
                  const next = [...fields];
                  next[idx] = { ...field, name: e.target.value };
                  setFields(next);
                }}
              />
              <select
                className="input"
                value={field.type}
                onChange={(e) => {
                  const next = [...fields];
                  next[idx] = { ...field, type: e.target.value };
                  setFields(next);
                }}
              >
                {FRIENDLY.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setFields((current) => [...current, { name: "New Field", type: "Text" }])}
          >
            Add Field
          </button>
          <div className="flex gap-2">
            <input className="input" value={relFrom} onChange={(e) => setRelFrom(e.target.value)} />
            <input className="input" value={relTo} onChange={(e) => setRelTo(e.target.value)} />
          </div>
          <p className="text-xs text-muted">Each {relFrom} belongs to one {relTo}</p>
          <button type="button" className="btn btn-secondary" onClick={() => void saveManual()}>
            Save draft
          </button>
        </section>
        <section className="space-y-2 rounded-md border border-border p-4">
          <h2 className="font-medium">Ask AI to Design</h2>
          <textarea
            className="input min-h-28"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="I run a pharmacy and need products, customers, sales and inventory."
          />
          <button type="button" className="btn btn-secondary" onClick={() => void askAi()}>
            Propose schema
          </button>
        </section>
      </div>
      {proposal && (
        <section className="mt-4 space-y-2 rounded-md border border-border p-4">
          <h2 className="font-medium">Preview</h2>
          <pre className="overflow-auto text-xs">{JSON.stringify(proposal.proposal || proposal, null, 2)}</pre>
          {advanced && Boolean(proposal.ddl_preview) && (
            <pre className="overflow-auto text-xs">{String(proposal.ddl_preview)}</pre>
          )}
          <button type="button" className="btn btn-secondary text-xs" onClick={() => setAdvanced((v) => !v)}>
            Advanced
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void approve()}>
            Approve Schema
          </button>
        </section>
      )}
      <Link to="/knowledge/database/import" className="btn btn-secondary mt-4 inline-flex">
        Import Data
      </Link>
    </KnowledgeLayout>
  );
}
