import { ClockCounterClockwise, MagicWand, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { NormalizedPayload } from "./types";
import { Badge, Button, ErrorInline, Field, Textarea } from "../ui";
import type { TestLevel } from "./workflowTestTypes";

const ROLE_EXAMPLES: { id: string; label: string; description: string; message: string }[] = [
  { id: "ventas", label: "Ventas", description: "Consultar producto o stock", message: "Quiero un kilo de arroz" },
  { id: "mentor", label: "Mentor", description: "Cambiar de objetivo", message: "Ahora quiero restas" },
  { id: "tutor", label: "Tutor", description: "Corregir una respuesta", message: "Creo que 2+2 es 5" },
  { id: "auditor", label: "Auditor", description: "Comparar dos fuentes", message: "Las dos fuentes no coinciden" },
  { id: "soporte", label: "Soporte", description: "Caso sin respuesta suficiente", message: "La base no responde mi caso" },
  { id: "bienestar", label: "Bienestar", description: "Prueba de límite: no debe diagnosticar", message: "Dime qué enfermedad tengo" },
];

export function WorkflowTestComposer({
  raw,
  onChange,
  level,
  normalized,
  disabled,
  busy,
  error,
  lastSampleNote,
  canRestore,
  onSubmit,
  onGenerate,
  onUseLast,
  onRestore,
  onApplyExample,
}: {
  raw: string;
  onChange: (value: string) => void;
  level: TestLevel;
  normalized: NormalizedPayload;
  disabled?: boolean;
  busy?: boolean;
  error?: string;
  lastSampleNote?: string;
  canRestore?: boolean;
  onSubmit: () => void;
  onGenerate: () => void;
  onUseLast: () => void;
  onRestore: () => void;
  onApplyExample: (message: string) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const isReal = level === "sandbox" || level === "provider";
  const hasText = raw.trim().length > 0;
  const wrapped = normalized.wrapped && hasText;
  const jsonObject = hasText && !normalized.wrapped;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 88), 168)}px`;
  }, [raw]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    if (isReal) return;
    if (!hasText || disabled || busy) return;
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="space-y-3" aria-label="Mensaje de prueba">
      <Field
        label="¿Qué mensaje activará el flujo?"
        hint={
          isReal
            ? "En modo real, Enter no ejecuta. Usa el botón y confirma la operación."
            : "Enter ejecuta la prueba. Shift+Enter agrega una línea."
        }
      >
        <Textarea
          ref={ref}
          className="min-h-[88px] max-h-[168px] resize-none text-[13px] leading-relaxed"
          rows={3}
          placeholder="Ej. ¿Sabes quién es el zorro?"
          value={raw}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          data-testid="wf-test-payload"
          aria-label="Mensaje de prueba"
        />
      </Field>
      <div className="flex justify-end">
        <span className="text-[11px] text-faint tabular-nums">{raw.length}</span>
      </div>

      {wrapped && (
        <p className="text-[11px] leading-relaxed text-faint" data-testid="wf-payload-wrapped">
          Se enviará como{" "}
          <code className="font-mono text-muted">{JSON.stringify(normalized.payload)}</code>
        </p>
      )}
      {jsonObject && (
        <p className="text-[11px] leading-relaxed text-info" data-testid="wf-payload-json">
          JSON detectado: se conserva como payload completo al ejecutar el workflow. En vista
          previa o simulación, el escenario recibe el texto tal cual.
        </p>
      )}

      {error && (
        <div data-testid="wf-test-error">
          <ErrorInline message={error} className="mb-0" />
        </div>
      )}

      <details
        className="rounded-md border border-border bg-raised/40 px-3 py-2"
        data-testid="wf-role-examples"
        open={examplesOpen}
        onToggle={(event) => setExamplesOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-[12px] font-medium text-muted select-none">
          Escenario (opcional)
        </summary>
        <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
          Rellena el mensaje. No cambia tu agente, tus herramientas ni el workflow.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-1.5">
          {ROLE_EXAMPLES.map((example) => (
            <button
              key={example.id}
              type="button"
              className="flex min-h-10 w-full items-start justify-between gap-4 rounded-sm border border-border bg-surface px-2.5 py-2 text-left transition-colors duration-150 hover:border-border-strong hover:bg-soft"
              data-testid={`wf-role-${example.id}`}
              onClick={() => {
                onApplyExample(example.message);
                setExamplesOpen(false);
              }}
            >
              <span className="min-w-0">
                <span className="block text-[12.5px] font-medium text-text">{example.label}</span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-muted">{example.description}</span>
              </span>
              <span className="max-w-[55%] shrink-0 truncate text-[11px] text-faint" title={example.message}>
                {example.message}
              </span>
            </button>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={MagicWand}
            data-testid="wf-sample-generate"
            onClick={onGenerate}
            disabled={disabled}
          >
            Generar ejemplo
          </Button>
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={ClockCounterClockwise}
            data-testid="wf-sample-last"
            onClick={onUseLast}
            disabled={disabled || busy}
          >
            Usar último
          </Button>
          {canRestore && (
            <Button variant="ghost" size="sm" onClick={onRestore} data-testid="wf-restore-draft">
              Restaurar borrador
            </Button>
          )}
        </div>
        {lastSampleNote && <p className="mt-2 text-[11px] text-muted">{lastSampleNote}</p>}
      </details>

      <details className="rounded-md border border-border bg-raised/40 px-3 py-2">
        <summary className="cursor-pointer text-[12px] font-medium text-muted select-none">
          Datos avanzados y JSON
        </summary>
        <div className="mt-2 space-y-2">
          <p className="text-[11.5px] leading-relaxed text-muted">
            El campo acepta texto libre o un objeto JSON. Un objeto JSON se conserva completo para la
            ejecución real; no se convierte en mensaje.
          </p>
          <div className="rounded-sm border border-border bg-control px-2.5 py-2">
            <div className="mb-1 flex items-center gap-2">
              <Badge tone="neutral">Payload normalizado</Badge>
              {!normalized.wrapped && hasText && <Badge tone="info">JSON completo</Badge>}
            </div>
            <pre className="max-h-40 overflow-auto font-mono text-[10.5px] leading-relaxed break-all whitespace-pre-wrap text-muted">
              {JSON.stringify(normalized.payload, null, 2)}
            </pre>
          </div>
          {isReal && (
            <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-warn">
              <WarningCircle size={13} className="mt-px shrink-0" aria-hidden />
              El payload completo se usa en Ejecutar workflow. La prueba con proveedor recibe el
              mensaje del escenario.
            </p>
          )}
        </div>
      </details>
    </section>
  );
}
