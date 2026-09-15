import type { ReactNode } from "react";

/** Estilo compartido de los controles del panel (el portal no define `.input`). */
export const FIELD_INPUT_CLASS =
  "w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent";

/**
 * Campo del panel de ajustes: etiqueta visible + una línea que explica para qué
 * sirve. El control lo pasa quien lo usa, con `id` y `aria-describedby`
 * apuntando al hint (`<id>-hint`).
 */
export function AgentField({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label className={`block text-sm font-medium text-text ${hint ? "" : "mb-1"}`} htmlFor={id}>
        {label}
      </label>
      {hint && (
        <p id={`${id}-hint`} className="mt-0.5 mb-1.5 text-xs text-muted">
          {hint}
        </p>
      )}
      {children}
    </div>
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
        <h3 className="text-sm font-semibold text-text">{title}</h3>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/** Permiso del agente: nombre en claro, qué implica y el id de la tool. */
export function AgentToggleCard({
  id,
  label,
  hint,
  tech,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  tech: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label
      htmlFor={id}
      className="flex min-h-11 cursor-pointer items-start gap-3 rounded-md border border-border bg-soft p-3 hover:border-border-strong"
    >
      <input
        id={id}
        type="checkbox"
        className="mt-0.5"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-text">{label}</span>
        <span className="mt-0.5 block text-xs text-muted">{hint}</span>
        <span className="mt-0.5 block font-mono text-[11px] text-faint">{tech}</span>
      </span>
    </label>
  );
}
