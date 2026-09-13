/**
 * WorkflowPatchPanel — edición del workflow con lenguaje natural (misión §21).
 * Muestra el diff semántico antes de aplicar; nunca regenera el flujo completo
 * ni publica: al aplicar solo persiste el grafo editado.
 */
import { ArrowRight, MagicWand, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, Spinner } from "../ui";

type DiffEntry = {
  op: string;
  node_id: string | null;
  node_label?: string;
  label: string;
  before: unknown;
  after: unknown;
  description?: string;
};

type Issue = { code: string; severity: "error" | "warning" | "info"; message: string; hint?: string | null };

type Preview = {
  patch: Record<string, unknown> | null;
  diff: DiffEntry[];
  issues: Issue[];
  base_graph_hash: string;
  summary: string | null;
  questions: string[];
  confidence?: number;
};

type Props = {
  workflowId: string;
  onApplied: () => void;
  onClose: () => void;
};

const EXAMPLES = [
  "Cambia el asunto a Stock crítico",
  "Avisa también al gerente",
  "En vez de in-app usa correo",
  "Ejecútalo solo de lunes a viernes a las 9am",
];

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function WorkflowPatchPanel({ workflowId, onApplied, onClose }: Props) {
  const { session } = useAuth();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  async function ask() {
    if (!session || prompt.trim().length < 4) return;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await api<Preview>(`/api/v1/workflows/${workflowId}/patch/preview`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      setPreview(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!session || !preview?.patch) return;
    setApplying(true);
    setError("");
    try {
      await api(`/api/v1/workflows/${workflowId}/patch/apply`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          patch: preview.patch,
          base_graph_hash: preview.base_graph_hash,
        }),
      });
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setApplying(false);
    }
  }

  const errors = preview?.issues.filter((i) => i.severity === "error") ?? [];
  const warnings = preview?.issues.filter((i) => i.severity !== "error") ?? [];

  return (
    <div className="space-y-3" data-testid="wf-patch-panel">
      <div className="flex items-start gap-2">
        <MagicWand size={16} className="mt-0.5 text-accent" aria-hidden />
        <p className="text-xs text-muted">
          Pide el cambio como se lo dirías a una persona. Zent te muestra el diff y tú confirmas.
        </p>
      </div>

      <textarea
        className="w-full resize-y rounded-md border border-border bg-soft px-2.5 py-2 text-xs"
        rows={3}
        placeholder="Cambia 10 por 5…"
        value={prompt}
        data-testid="wf-patch-prompt"
        onChange={(e) => setPrompt(e.target.value)}
      />
      <div className="flex flex-wrap gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted hover:border-accent/40 hover:text-text"
            onClick={() => setPrompt(example)}
          >
            {example}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-primary min-h-9 gap-1.5 px-3 text-xs"
          disabled={busy || prompt.trim().length < 4}
          data-testid="wf-patch-preview"
          onClick={() => void ask()}
        >
          {busy ? <Spinner size={13} /> : <ArrowRight size={14} aria-hidden />}
          Ver cambios
        </button>
        <button type="button" className="btn btn-ghost min-h-9 px-3 text-xs" onClick={onClose}>
          Cerrar
        </button>
      </div>

      <ErrorInline message={error} />

      {preview && preview.diff.length > 0 && (
        <div className="space-y-2 rounded-md border border-accent/30 bg-accent/5 p-3" data-testid="wf-patch-diff">
          <p className="text-[11px] font-medium text-text">{preview.summary || "Cambios propuestos"}</p>
          <ul className="space-y-1.5">
            {preview.diff.map((entry, index) => (
              <li key={`${entry.op}-${index}`} className="rounded-md bg-surface/70 px-2 py-1.5 text-[10px]">
                <p className="text-faint">
                  {entry.node_label || entry.node_id} · {entry.label}
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-danger line-through">{renderValue(entry.before)}</span>
                  <ArrowRight size={10} className="text-faint" aria-hidden />
                  <span className="font-medium text-ok">{renderValue(entry.after)}</span>
                </p>
              </li>
            ))}
          </ul>
          {(errors.length > 0 || warnings.length > 0) && (
            <ul className="space-y-1">
              {[...errors, ...warnings].map((issue) => (
                <li
                  key={`${issue.code}-${issue.message}`}
                  className={`flex items-start gap-1 text-[10px] ${issue.severity === "error" ? "text-danger" : "text-warn"}`}
                >
                  <WarningCircle size={11} className="mt-0.5 shrink-0" aria-hidden />
                  {issue.message}
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            className="btn btn-primary min-h-9 gap-1.5 px-3 text-xs"
            disabled={applying || errors.length > 0}
            data-testid="wf-patch-apply"
            onClick={() => void apply()}
          >
            {applying ? <Spinner size={13} /> : null}
            Aplicar cambios
          </button>
        </div>
      )}

      {preview && preview.diff.length === 0 && !error && (
        <p className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-[11px] text-muted" data-testid="wf-patch-empty">
          No detecté un cambio aplicable. Prueba con algo como «Cambia el asunto a …».
        </p>
      )}

      {preview?.questions && preview.questions.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[10px] text-muted">
          {preview.questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
