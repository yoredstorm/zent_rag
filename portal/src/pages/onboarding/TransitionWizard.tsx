import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { PageHeader } from "../../components/ui";

const IMPACT = [
  "demo documents",
  "demo vectors",
  "demo catalog",
  "demo semantic mappings",
  "demo glossary",
  "demo verified queries",
  "demo agents",
  "demo entities",
  "demo relationships",
  "demo context graph",
  "demo source records",
];

export default function TransitionWizardPage() {
  const { session, applySession } = useAuth();
  const [mode, setMode] = useState<"new_workspace" | "purge">("new_workspace");
  const [confirm, setConfirm] = useState("");
  const [welcome, setWelcome] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<{
        welcome?: string;
        workspace?: { id: string; kind: string };
      }>("/api/v1/demo-transition/start-with-my-data", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          mode,
          confirmation: mode === "purge" ? confirm : undefined,
          name: "My Business",
        }),
      });
      if (data.workspace?.id) {
        applySession({
          ...session,
          workspaceId: data.workspace.id,
          workspaceKind: data.workspace.kind,
        });
      } else {
        applySession({ ...session, workspaceKind: "business" });
      }
      setWelcome(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  if (welcome) {
    return (
      <div className="mx-auto max-w-xl space-y-4 p-6">
        <h1 className="text-2xl font-semibold">Welcome to your business workspace.</h1>
        <p className="text-muted">How would you like to begin?</p>
        <div className="grid gap-2">
          <Link className="btn btn-primary" to="/knowledge/add">
            Connect Database
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Upload Files
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Import Spreadsheet
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Connect Google Drive
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Connect Website
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Connect API
          </Link>
          <Link className="btn btn-primary" to="/knowledge/database">
            Create a database with Zent
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-4 p-6">
      <PageHeader title="Start with My Data" />
      <p className="text-sm text-muted">Choose transition mode</p>
      <label className="flex gap-2 rounded-md border border-border p-3">
        <input
          type="radio"
          checked={mode === "new_workspace"}
          onChange={() => setMode("new_workspace")}
        />
        <span>
          <strong>Create a clean business workspace</strong>
          <span className="block text-xs text-muted">Recommended. Demo stays for reference.</span>
        </span>
      </label>
      <label className="flex gap-2 rounded-md border border-border p-3">
        <input
          type="radio"
          checked={mode === "purge"}
          onChange={() => setMode("purge")}
        />
        <span>Replace demo completely</span>
      </label>
      {mode === "purge" && (
        <div className="space-y-2 text-sm">
          <p>Will remove:</p>
          <ul className="list-disc pl-5 text-muted">
            {IMPACT.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p>Type DELETE DEMO to confirm.</p>
          <input
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy || (mode === "purge" && confirm !== "DELETE DEMO")}
        onClick={() => void submit()}
      >
        Continue
      </button>
    </div>
  );
}
