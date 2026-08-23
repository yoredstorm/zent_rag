import { Copy, Key as KeyIcon, X } from "@phosphor-icons/react";
import { useState } from "react";
import { useToast } from "../Toast";

export function ApiKeyCreatedModal({
  apiKey,
  onClose,
}: {
  apiKey: string;
  onClose: () => void;
}) {
  const { pushToast } = useToast();
  const [revealed, setRevealed] = useState(true);
  const snippet = `from zent import Zent

client = Zent(api_key="${apiKey}")
print(client.chat("What is our refund policy?").answer)`;

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      pushToast("success", `${label} copiada`, "Ya está en tu portapapeles.");
    } catch {
      pushToast("error", "No se pudo copiar", "Copia el texto manualmente.");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div className="absolute inset-0 bg-black/60" aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="api-key-modal-title"
        className="relative m-4 w-full max-w-lg rounded-lg border border-accent/30 bg-surface p-5 shadow-pop"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <KeyIcon size={18} className="text-accent" aria-hidden />
            <h2 id="api-key-modal-title" className="text-base font-semibold text-text">
              Tu API key
            </h2>
          </div>
          <button
            type="button"
            className="btn btn-ghost px-2 py-1"
            aria-label="Cerrar"
            onClick={onClose}
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        <p className="mb-3 text-sm text-muted">
          Guárdala ahora. No se vuelve a mostrar. Con ella puedes hacer{" "}
          <code className="mono text-xs">client.chat()</code> en menos de 5 minutos.
        </p>
        <label className="sr-only" htmlFor="signup-api-key">
          API key
        </label>
        <input
          id="signup-api-key"
          className="mb-3 w-full rounded-md border border-border bg-soft px-3 py-2.5 font-mono text-sm text-text"
          readOnly
          value={revealed ? apiKey : "•".repeat(48)}
        />
        <div className="mb-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-secondary min-h-11"
            onClick={() => setRevealed((v) => !v)}
          >
            {revealed ? "Ocultar" : "Mostrar"}
          </button>
          <button
            type="button"
            className="btn btn-primary min-h-11"
            onClick={() => void copy(apiKey, "API key")}
          >
            <Copy size={15} aria-hidden />
            Copiar key
          </button>
        </div>
        <pre className="mb-3 overflow-x-auto rounded-md border border-border bg-soft p-3 text-xs text-text">
          {snippet}
        </pre>
        <button
          type="button"
          className="btn btn-secondary min-h-11 w-full"
          onClick={() => void copy(snippet, "Snippet")}
        >
          Copiar snippet
        </button>
        <button
          type="button"
          className="btn btn-primary mt-3 min-h-11 w-full"
          onClick={onClose}
        >
          Ya la guardé
        </button>
      </div>
    </div>
  );
}
