import { ArrowsClockwise, Copy } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, SuccessInline } from "../ui";
import { hookCurl, hookFetch } from "./types";

type Props = {
  workflowId: string;
  status: string;
  triggerType: string;
  /** Ruta relativa devuelta por el backend (`/api/v1/public/workflows/:id/hook`). */
  hookPath: string;
  hasHookSecret: boolean;
  /** Secret en claro conocido en esta sesión (creación o rotación). */
  secret: string;
  onSecret: (secret: string) => void;
};

const SECRET_PLACEHOLDER = "<TU_SECRET>";

const ANDROID_PAYLOAD = `{
  "event": "workflow.run",
  "title": "Stock bajo",
  "body": "Quedan 3 unidades",
  "sku": "ABC",
  "stock": 3,
  "workflow_id": "…",
  "run_id": "…"
}`;

export function WorkflowApiPanel({
  workflowId,
  status,
  triggerType,
  hookPath,
  hasHookSecret,
  secret,
  onSecret,
}: Props) {
  const { session } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const hookUrl = `${origin}${hookPath}`;
  const shown = secret || SECRET_PLACEHOLDER;

  async function rotate() {
    if (!session) return;
    if (
      hasHookSecret &&
      !window.confirm(
        "Rotar el secret invalida el actual de inmediato. Los sistemas que ya llaman al hook " +
          "fallarán con 401 hasta que uses el nuevo. ¿Continuar?",
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const out = await api<{ hook_secret: string }>(
        `/api/v1/workflows/${workflowId}/hook-secret/rotate`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      onSecret(out.hook_secret);
      setMsg("Secret nuevo emitido. Cópialo ahora: no se vuelve a mostrar.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  function copy(value: string, label: string) {
    void navigator.clipboard.writeText(value);
    setMsg(`${label} copiado.`);
  }

  return (
    <div className="space-y-4" data-testid="wf-api-panel">
      <section className="panel space-y-3 p-4">
        <div>
          <h2 className="text-sm font-semibold text-text">API del workflow</h2>
          <p className="mt-0.5 text-xs text-muted">
            Cualquier sistema puede disparar este workflow con un POST autenticado por secret.
          </p>
        </div>

        {status !== "active" && (
          <div
            className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-text"
            role="status"
            data-testid="wf-api-inactive"
          >
            El workflow está en <span className="font-medium">{status}</span>. El hook público
            responde <code className="font-mono">409 Workflow is not active</code> hasta que lo
            actives. Las pruebas desde el estudio funcionan igual.
          </div>
        )}

        <dl className="space-y-2 text-xs">
          <div>
            <dt className="text-faint">Endpoint</dt>
            <dd className="mt-0.5 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-soft px-2 py-1 font-mono text-[11px] text-text">
                POST {hookUrl}
              </code>
              <button
                type="button"
                className="btn btn-ghost min-h-8 px-2 text-[10px]"
                onClick={() => copy(hookUrl, "Endpoint")}
              >
                <Copy size={12} aria-hidden /> Copiar
              </button>
            </dd>
          </div>
          <div>
            <dt className="text-faint">Header de autenticación</dt>
            <dd className="mt-0.5 font-mono text-[11px] text-text">X-Zent-Workflow-Secret</dd>
            <p className="mt-1 text-[10px] text-muted">
              En Bruno/Postman: pestaña <span className="font-medium text-text">Headers</span>, no
              Params. El secret en la URL da 401 y queda en logs.
            </p>
          </div>
          <div>
            <dt className="text-faint">Trigger</dt>
            <dd className="mt-0.5 text-text">{triggerType}</dd>
          </div>
        </dl>

        <div className="rounded-md border border-border p-3">
          <p className="text-xs font-semibold text-text">Secret</p>
          {secret ? (
            <>
              <p className="mt-1 break-all font-mono text-[11px] text-text" data-testid="wf-hook-secret">
                {secret}
              </p>
              <p className="mt-1 text-[10px] text-muted">
                Visible solo en esta sesión. Guárdalo en tu gestor de secretos.
              </p>
            </>
          ) : (
            <p className="mt-1 text-[11px] text-muted">
              {hasHookSecret
                ? "Ya existe un secret, pero solo se muestra una vez. Rota para emitir uno nuevo."
                : "Este workflow no tiene secret inbound. Rota para emitir uno."}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {secret && (
              <button
                type="button"
                className="btn btn-ghost min-h-8 px-2 text-[10px]"
                onClick={() => copy(secret, "Secret")}
              >
                <Copy size={12} aria-hidden /> Copiar secret
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary min-h-8 px-2 text-[10px]"
              disabled={busy}
              onClick={() => void rotate()}
              data-testid="wf-rotate-secret"
            >
              <ArrowsClockwise size={12} aria-hidden />
              {hasHookSecret ? "Rotar secret" : "Emitir secret"}
            </button>
          </div>
        </div>

        <ErrorInline message={error} />
        <SuccessInline message={msg} />
      </section>

      <section className="panel space-y-3 p-4">
        <h3 className="text-sm font-semibold text-text">Llamarlo desde tu código</h3>
        <Snippet
          label="curl"
          code={hookCurl(hookUrl, shown)}
          onCopy={() => copy(hookCurl(hookUrl, shown), "curl")}
        />
        <Snippet
          label="fetch (JS)"
          code={hookFetch(hookUrl, shown)}
          onCopy={() => copy(hookFetch(hookUrl, shown), "fetch")}
        />
        <p className="text-[11px] text-muted">
          El body entero llega como payload del trigger (o el campo <code className="font-mono">payload</code>{" "}
          si lo envías). Referencia los campos con{" "}
          <code className="font-mono text-text">{"{{trigger.message}}"}</code>.
        </p>
      </section>

      <section className="panel space-y-2 p-4" data-testid="wf-android-contract">
        <h3 className="text-sm font-semibold text-text">Contrato Android / webhook saliente</h3>
        <p className="text-xs text-muted">
          Suscríbete en Webhooks al evento <code className="font-mono text-text">workflow.run</code>{" "}
          (firma <code className="font-mono text-text">X-Zent-Signature</code>). Payload de ejemplo:
        </p>
        <pre className="overflow-x-auto rounded-md bg-soft p-2 font-mono text-[10px] text-text">
          {ANDROID_PAYLOAD}
        </pre>
        <button
          type="button"
          className="btn btn-ghost min-h-8 px-2 text-[10px]"
          onClick={() => copy(ANDROID_PAYLOAD, "Payload Android")}
        >
          <Copy size={12} aria-hidden /> Copiar payload
        </button>
      </section>
    </div>
  );
}

function Snippet({ label, code, onCopy }: { label: string; code: string; onCopy: () => void }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <p className="flex-1 text-[11px] font-medium text-muted">{label}</p>
        <button type="button" className="btn btn-ghost min-h-7 px-2 text-[10px]" onClick={onCopy}>
          <Copy size={12} aria-hidden /> Copiar
        </button>
      </div>
      <pre className="mt-1 overflow-x-auto rounded-md bg-soft p-2 font-mono text-[10px] text-text">
        {code}
      </pre>
    </div>
  );
}
