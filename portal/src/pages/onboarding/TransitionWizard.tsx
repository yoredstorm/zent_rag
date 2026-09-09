import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { PageHeader } from "../../components/ui";

const IMPACT = [
  "documentos de demo",
  "vectores de demo",
  "catálogo de demo",
  "mapeos semánticos de demo",
  "glosario de demo",
  "consultas verificadas de demo",
  "agentes de demo",
  "entidades de demo",
  "relaciones de demo",
  "grafo de contexto de demo",
  "registros de fuentes de demo",
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
          name: "Mi negocio",
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
        <h1 className="text-2xl font-semibold">Bienvenido a tu espacio de negocio.</h1>
        <p className="text-muted">¿Cómo quieres empezar?</p>
        <div className="grid gap-2">
          <Link className="btn btn-primary" to="/knowledge/add">
            Conectar base de datos
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Subir archivos
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Importar hoja de cálculo
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Conectar Google Drive
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Conectar sitio web
          </Link>
          <Link className="btn btn-secondary" to="/knowledge/add">
            Conectar API
          </Link>
          <Link className="btn btn-primary" to="/knowledge/database">
            Crear una base de datos con Zent
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-4 p-6">
      <PageHeader title="Empezar con mis datos" />
      <p className="text-sm text-muted">Elige cómo pasar a tus datos</p>
      <label className="flex gap-2 rounded-md border border-border p-3">
        <input
          type="radio"
          checked={mode === "new_workspace"}
          onChange={() => setMode("new_workspace")}
        />
        <span>
          <strong>Crear un espacio de negocio vacío</strong>
          <span className="block text-xs text-muted">Recomendado. El demo queda para consulta.</span>
        </span>
      </label>
      <label className="flex gap-2 rounded-md border border-border p-3">
        <input
          type="radio"
          checked={mode === "purge"}
          onChange={() => setMode("purge")}
        />
        <span>Reemplazar el demo por completo</span>
      </label>
      {mode === "purge" && (
        <div className="space-y-2 text-sm">
          <p>Se eliminará:</p>
          <ul className="list-disc pl-5 text-muted">
            {IMPACT.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p>Escribe DELETE DEMO para confirmar.</p>
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
        Continuar
      </button>
    </div>
  );
}
