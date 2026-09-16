/**
 * WorkflowPatchPanel — edición del workflow con lenguaje natural (misión §21).
 * Muestra el diff semántico antes de aplicar; nunca regenera el flujo completo
 * ni publica: al aplicar solo persiste el grafo editado.
 */
import { ArrowRight, Check, MagicWand, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Button, ErrorInline, Textarea } from "../ui";

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
    <div className="space-y-4" data-testid="wf-patch-panel">
      <div className="flex items-start gap-2.5">
        <MagicWand size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <p className="text-[13px] leading-relaxed text-muted">
          Pide el cambio como se lo dirías a una persona. Zent te muestra el diff y tú confirmas.
        </p>
      </div>

      <Textarea
        rows={3}
        placeholder="Cambia 10 por 5…"
        value={prompt}
        data-testid="wf-patch-prompt"
        onChange={(e) => setPrompt(e.target.value)}
        aria-label="Qué quieres cambiar"
      />
      <div className="flex flex-wrap gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="chip max-w-full cursor-pointer truncate transition-colors duration-150 hover:bg-raised hover:text-text"
            onClick={() => setPrompt(example)}
          >
            {example}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          leadingIcon={ArrowRight}
          loading={busy}
          disabled={prompt.trim().length < 4}
          data-testid="wf-patch-preview"
          onClick={() => void ask()}
        >
          Ver cambios
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cerrar
        </Button>
      </div>

      <ErrorInline message={error} className="mb-0" />

      {preview && preview.diff.length > 0 && (
        <div className="space-y-3 rounded-lg border border-accent-line bg-accent-soft/40 p-3" data-testid="wf-patch-diff">
          <p className="text-[13px] font-medium text-text">{preview.summary || "Cambios propuestos"}</p>
          <ul className="space-y-1.5">
            {preview.diff.map((entry, index) => (
              <li key={`${entry.op}-${index}`} className="rounded-md border border-border-soft bg-surface px-2.5 py-2 text-[12px]">
                <p className="text-faint">
                  {entry.node_label || entry.node_id} · {entry.label}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-danger line-through">{renderValue(entry.before)}</span>
                  <ArrowRight size={11} className="shrink-0 text-faint" aria-hidden />
                  <span className="font-mono font-medium text-ok">{renderValue(entry.after)}</span>
                </p>
              </li>
            ))}
          </ul>
          {(errors.length > 0 || warnings.length > 0) && (
            <ul className="space-y-1.5">
              {[...errors, ...warnings].map((issue) => (
                <li
                  key={`${issue.code}-${issue.message}`}
                  className={`flex items-start gap-1.5 text-[12px] leading-relaxed ${
                    issue.severity === "error" ? "text-danger" : "text-warn"
                  }`}
                >
                  <WarningCircle size={12} className="mt-0.5 shrink-0" aria-hidden />
                  {issue.message}
                </li>
              ))}
            </ul>
          )}
          <Button
            variant="primary"
            leadingIcon={Check}
            loading={applying}
            disabled={errors.length > 0}
            data-testid="wf-patch-apply"
            onClick={() => void apply()}
          >
            Aplicar cambios
          </Button>
        </div>
      )}

      {preview && preview.diff.length === 0 && !error && (
        <p
          className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5 text-[12px] leading-relaxed text-muted"
          data-testid="wf-patch-empty"
        >
          No detecté un cambio aplicable. Prueba con algo como «Cambia el asunto a …».
        </p>
      )}

      {preview?.questions && preview.questions.length > 0 && (
        <ul className="list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-muted">
          {preview.questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
