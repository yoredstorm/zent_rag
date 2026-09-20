import { CaretDown } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Checkbox, Field, Panel, cn } from "../ui";

const LABEL_CLASS = "text-[13px] font-medium text-text";

/**
 * Campo del panel de ajustes. Envuelve la primitiva `Field`: label real siempre
 * visible, hint y error conectados por `aria-describedby`, control con el id del
 * campo (los inputs del panel usan las primitivas Input/Textarea/Select).
 */
export function AgentField({
  id,
  label,
  hint,
  error,
  required,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Field
      id={id}
      label={<span className={LABEL_CLASS}>{label}</span>}
      hint={hint}
      error={error}
      required={required}
      className={className}
    >
      {children}
    </Field>
  );
}

/** Bloque con título y explicación para agrupar varios campos. */
export function AgentFieldGroup({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-3">
      <div>
        <h3 className="text-h3">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-relaxed text-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/**
 * Permiso del agente: nombre en claro, qué implica y el id de la tool.
 * El toggle es la primitiva Checkbox (foco visible y estado por `aria-checked`).
 */
export function AgentToggleCard({
  id,
  label,
  hint,
  tech,
  checked,
  onChange,
  disabled = false,
  disabledHint,
}: {
  id: string;
  label: string;
  hint: string;
  tech: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  disabledHint?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-raised p-3 transition-colors duration-150",
        disabled
          ? "border-border opacity-70"
          : checked
            ? "border-accent-line bg-accent-soft/40"
            : "border-border hover:border-border-strong",
      )}
    >
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        label={<span className="font-medium">{label}</span>}
        hint={hint}
        disabled={disabled}
      />
      <p className="mt-1 pl-[26px] font-mono text-[11px] text-faint">{tech}</p>
      {disabled && disabledHint ? (
        <p className="mt-1 pl-[26px] text-[11px] leading-relaxed text-faint">{disabledHint}</p>
      ) : null}
    </div>
  );
}

/**
 * Progressive disclosure del estudio: el título resume y el detalle aparece
 * solo cuando se pide. Sin `<details>` para mantener el control desde la URL.
 */
export function AgentDisclosure({
  id,
  title,
  hint,
  open,
  onToggle,
  children,
  className,
}: {
  id: string;
  title: string;
  hint?: ReactNode;
  open: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={className}>
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-4 py-3 text-left"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => onToggle(!open)}
      >
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-h3">{title}</span>
          {hint && <span className="text-xs text-muted">{hint}</span>}
        </span>
        <CaretDown
          size={15}
          aria-hidden
          className={cn(
            "shrink-0 text-faint transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div id={id} className="animate-rise border-t border-border p-4">
          {children}
        </div>
      )}
    </Panel>
  );
}
